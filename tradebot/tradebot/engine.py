"""The bot loop: once per candle, read the market, decide, check the risk limits and trade."""
from __future__ import annotations

import logging
import math
import threading
import time

import pandas as pd

from .broker import PaperBroker, TradeSkipped
from .config import Config, home_dir
from .data import MarketData, interval_seconds
from .notify import Notifier
from .risk import RiskManager, RiskState
from .store import Store
from .strategy import compute_signals

log = logging.getLogger(__name__)


class Bot:
    def __init__(self, cfg: Config, broker, market: MarketData, store: Store, notifier: Notifier):
        self.cfg = cfg
        self.broker = broker
        self.market = market
        self.store = store
        self.notifier = notifier
        self.risk = RiskManager(cfg.risk)
        self.mode = "paper" if isinstance(broker, PaperBroker) else "live"
        self._acted_on_halt = False
        self.next_check: float | None = None  # unix time of the next scheduled check, for the app's countdown
        self._poke = threading.Event()

    def poke(self) -> None:
        """Wakes a waiting run_forever at once, e.g. to act on an emergency stop without the 10 s poll."""
        self._poke.set()

    def _wait(self, seconds: float) -> None:
        self._poke.wait(seconds)
        self._poke.clear()

    def signal(self) -> tuple[pd.Series, pd.Timestamp]:
        m = self.cfg.market
        df = self.market.recent(m.signal_symbol, m.interval, m.history_bars)
        step = pd.Timedelta(seconds=interval_seconds(m.interval))
        closed_at = df.index[-1] + step
        age = pd.Timestamp.now(tz="UTC") - closed_at
        if age > step * self.cfg.risk.stale_bars:
            raise TradeSkipped(f"Market data is stale (last candle closed {age} ago); not trading on it")
        return compute_signals(df, self.cfg.strategy, m.interval).iloc[-1], closed_at

    def tick(self) -> str:
        sig, closed_at = self.signal()
        price = float(sig["close"])
        saved = self.store.load()
        resumes = saved.get("resumes", 0)
        section = saved.get(self.mode, {})  # paper and live keep separate peaks and counters
        state = RiskState.from_dict(section.get("risk", {}))
        halt = self.store.halt_reason()
        state.halted, state.halt_reason = halt is not None, halt or ""

        port = self.broker.portfolio(price)
        for event in self.risk.update(state, port, pd.Timestamp.now(tz="UTC")):
            self.store.halt(event)
            self.notifier.send(f"🛑 {event}. Selling to stablecoin. Run `tradebot resume` once you've checked why.")

        decision = self.risk.plan(float(sig["target"]), port, state)
        note = decision.note
        if decision.order:
            try:
                fill = self.broker.execute(decision.order, price)
            except TradeSkipped as e:
                note = f"trade skipped: {e}"
                self.notifier.send(f"⚠️ {note}")
            else:
                state.trades_today += 1
                port = self.broker.portfolio(price)
                self.store.log_trade(self.mode, fill, decision.order.reason, port.equity)
                verb = "Bought" if fill.side == "buy" else "Sold"
                self.notifier.send(f"{verb} {fill.asset_amount:.6f} at ${fill.price:,.2f} for ${fill.quote_amount:,.2f} "
                                   f"via {fill.route} ({decision.order.reason}). Account ${port.equity:,.2f}"
                                   + (f". tx {fill.tx_hash}" if fill.tx_hash else ""))
        self._acted_on_halt = state.halted

        section.update({"risk": state.to_dict(), "last_tick": pd.Timestamp.now(tz="UTC").isoformat(),
                        "last_signal": {k: (None if pd.isna(v) else round(float(v), 4)) for k, v in sig.items()},
                        "last_equity": port.equity, "last_target": decision.target, "last_exposure": port.exposure})
        if isinstance(self.broker, PaperBroker):
            section["balances"] = {"quote": self.broker.quote, "asset": self.broker.asset}
        saved = self.store.load()  # re-read, so a `resume` made during this check isn't lost
        if saved.get("resumes", 0) != resumes:
            section["risk"]["peak_equity"] = port.equity
        saved[self.mode] = section
        self.store.save(saved)
        self.store.log_equity(self.mode, price, port.equity, port.exposure, decision.target)
        return (f"[{self.mode}] candle {closed_at:%Y-%m-%d %H:%M} price ${price:,.2f} | trend {sig['trend']:+.2f} "
                f"target {decision.target:.0%} holding {port.exposure:.0%} | account ${port.equity:,.2f} "
                f"(peak ${state.peak_equity:,.2f}) | {note}")

    def run_forever(self, stop: threading.Event | None = None) -> None:
        """Checks the market once per candle until `stop` is set (or forever). Call poke() after setting `stop`
        to end the wait at once; otherwise it's noticed within 10 seconds."""
        stop = stop or threading.Event()
        step = interval_seconds(self.cfg.market.interval)
        failures = 0
        while not stop.is_set():
            try:
                log.info(self.tick())
                failures = 0
            except TradeSkipped as e:
                log.warning(str(e))
            except Exception as e:  # keep running through network hiccups; report persistent trouble
                failures += 1
                log.exception("Check failed (%s in a row)", failures)
                if failures in (1, 5) or failures % 20 == 0:
                    self.notifier.send(f"⚠️ Error ({failures} in a row): {type(e).__name__}: {e}")
                retry = time.time() + min(60 * failures, 600)
                self.next_check = retry
                while time.time() < retry and not stop.is_set():  # back off; a halt can't act while checks fail
                    self._wait(min(10, max(retry - time.time(), 0)))
                continue
            # Wake 20 s after the next candle closes. Check the halt flag every 10 s so `tradebot stop` acts fast.
            wake = self.next_check = (math.floor(time.time() / step) + 1) * step + 20
            while time.time() < wake and not stop.is_set():
                if self.store.halt_reason() and not self._acted_on_halt:
                    log.info("Halt requested: %s", self.store.halt_reason())
                    break
                self._wait(min(10, max(wake - time.time(), 0)))
        self.next_check = None


def load_live(cfg: Config, password: str):
    """Unlocks the bot wallet and connects to BNB Chain."""
    from .dex import Chain, LiveBroker
    from .wallet import load_account

    chain = Chain(cfg, load_account(home_dir() / "keystore.json", password))
    return chain, LiveBroker(chain, cfg)


def build_bot(cfg: Config, password: str | None = None, market: MarketData | None = None):
    """A bot for the configured mode. Live mode needs the wallet password. Returns (bot, chain or None)."""
    store = Store(home_dir())
    chain = None
    if cfg.mode == "live":
        if not password:
            raise ValueError("Live mode needs the bot wallet's password.")
        chain, broker = load_live(cfg, password)
    else:
        saved = store.load().get("paper", {}).get("balances", {})
        p = cfg.paper
        broker = PaperBroker(saved.get("quote", p.starting_cash), saved.get("asset", 0.0), p.fee_bps, p.slippage_bps,
                             p.gas_usd)
    market = market or MarketData(cfg.market.data_url, home_dir() / "data")
    return Bot(cfg, broker, market, store, Notifier(cfg.notify)), chain

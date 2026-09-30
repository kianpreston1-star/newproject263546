"""The bot loop: once per candle, read the market, decide, check the risk limits and trade."""
from __future__ import annotations

import logging
import math
import time

import pandas as pd

from .broker import PaperBroker, TradeSkipped
from .config import Config
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
        state = RiskState.from_dict(saved.get("risk", {}))
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

        saved.update({"risk": state.to_dict(), "last_tick": pd.Timestamp.now(tz="UTC").isoformat(),
                      "last_signal": {k: (None if pd.isna(v) else round(float(v), 4)) for k, v in sig.items()},
                      "last_equity": port.equity, "last_target": decision.target})
        if isinstance(self.broker, PaperBroker):
            saved["paper"] = {"quote": self.broker.quote, "asset": self.broker.asset}
        self.store.save(saved)
        return (f"[{self.mode}] candle {closed_at:%Y-%m-%d %H:%M} price ${price:,.2f} | trend {sig['trend']:+.2f} "
                f"target {decision.target:.0%} holding {port.exposure:.0%} | account ${port.equity:,.2f} "
                f"(peak ${state.peak_equity:,.2f}) | {note}")

    def run_forever(self) -> None:
        step = interval_seconds(self.cfg.market.interval)
        failures = 0
        while True:
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
                time.sleep(min(60 * failures, 600))
                continue
            # Wake 20 s after the next candle closes. Check the halt flag every 10 s so `tradebot stop` acts fast.
            wake = (math.floor(time.time() / step) + 1) * step + 20
            while time.time() < wake:
                if self.store.halt_reason() and not self._acted_on_halt:
                    log.info("Halt requested: %s", self.store.halt_reason())
                    break
                time.sleep(min(10, max(wake - time.time(), 0)))

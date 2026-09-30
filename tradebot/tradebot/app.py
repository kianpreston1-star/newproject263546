"""The desktop app's engine room: runs the bot in a background thread and carries out what the window asks."""
from __future__ import annotations

import collections
import copy
import logging
import math
import threading
import time
from pathlib import Path

import numpy as np
import pandas as pd
from web3 import Web3

from .config import BTCB, ETH_BEP20, WBNB, Config, home_dir, load_config, save_config
from .data import MarketData
from .engine import build_bot, load_live
from .store import Store
from .wallet import create_wallet, wallet_address

log = logging.getLogger(__name__)

COINS = {
    "BNB": {"signal_symbol": "BNBUSDT", "asset_token": WBNB},
    "BTC": {"signal_symbol": "BTCUSDT", "asset_token": BTCB},
    "ETH": {"signal_symbol": "ETHUSDT", "asset_token": ETH_BEP20},
}


def coin_of(cfg: Config) -> str:
    for name, c in COINS.items():
        if c["signal_symbol"] == cfg.market.signal_symbol and c["asset_token"].lower() == cfg.chain.asset_token.lower():
            return name
    return cfg.market.signal_symbol.removesuffix("USDT")


def jsonable(obj):
    """Makes results safe for JSON: numpy numbers become floats, NaN and infinity become null."""
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        return None if not math.isfinite(obj) else float(obj)
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    return obj


def series_points(s: pd.Series, max_points: int = 600) -> list:
    """[[unix ms, value], ...], thinned out for drawing."""
    step = max(1, len(s) // max_points)
    thin = s.iloc[::step]
    if thin.index[-1] != s.index[-1]:
        thin = pd.concat([thin, s.iloc[-1:]])
    return [[int(t.value // 10**6), float(v)] for t, v in thin.items()]


class RingLog(logging.Handler):
    """Keeps the latest log lines for the window's activity panel."""

    def __init__(self, size: int = 300):
        super().__init__(logging.INFO)
        self.lines: collections.deque = collections.deque(maxlen=size)

    def emit(self, record: logging.LogRecord) -> None:
        text = record.getMessage()
        if record.exc_info and record.exc_info[1] is not None:
            text += f": {type(record.exc_info[1]).__name__}: {record.exc_info[1]}"
        self.lines.append({"time": record.created, "level": record.levelname, "text": text})


class BotService:
    def __init__(self, config_path: str | Path | None = None, market=None):
        self.config_path = Path(config_path) if config_path else home_dir() / "config.toml"
        self.store = Store(home_dir())
        self.market = market  # tests pass a stand-in for the live price feed
        self.log = RingLog()
        self.error = ""
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop: threading.Event | None = None
        self._bot = None
        self._job: dict = {"state": "idle"}
        self._chain_cache: tuple = (None, None)
        self._balances_cache: tuple = (0.0, None)

    def config(self) -> Config:
        return load_config(self.config_path)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def keystore(self) -> Path:
        return home_dir() / "keystore.json"

    # ---- the bot ---------------------------------------------------------------------------------

    def start(self, password: str | None = None, confirm_live: bool = False) -> dict:
        with self._lock:
            if self.running:
                raise ValueError("The bot is already running.")
            cfg = self.config()
            if cfg.mode == "live":
                if not self.keystore.exists():
                    raise ValueError("Create the bot's wallet first (Wallet tab).")
                if not confirm_live:
                    raise ValueError("Tick the box to confirm you want to trade real money.")
            bot, _ = build_bot(cfg, password, self.market)
            self.store.acquire_lock()
            self._bot, self._stop, self.error = bot, threading.Event(), ""
            self._thread = threading.Thread(target=self._run, name="bot", daemon=True)
            self._thread.start()
        bot.notifier.send(f"Started in {cfg.mode} mode")
        return {"message": f"Started in {cfg.mode} mode."}

    def _run(self) -> None:
        try:
            self._bot.run_forever(self._stop)
        except Exception as e:  # run_forever handles its own errors; this is a last resort
            self.error = f"The bot stopped unexpectedly: {type(e).__name__}: {e}"
            log.exception("The bot stopped unexpectedly")
        finally:
            self.store.release_lock()
            self._bot = None  # drops the unlocked wallet from memory
            log.info("Bot stopped.")

    def pause(self) -> dict:
        bot = self._bot
        if not self.running or bot is None:
            return {"message": "The bot isn't running."}
        self._stop.set()
        bot.poke()
        return {"message": "Stopping after the current check. Your coins stay where they are."}

    def emergency_stop(self) -> dict:
        self.store.halt("Emergency stop from the app")
        bot = self._bot
        if self.running and bot is not None:
            bot.poke()
            return {"message": "Selling everything to USDT now. The bot will then stay out of the market."}
        return {"message": "Halted. Press Start: the bot will sell everything to USDT first, then stay out of the market."}

    def resume(self) -> dict:
        self.store.resume()
        return {"message": "Resumed. The bot will trade again on its next check."}

    def shutdown(self, timeout: float = 60) -> None:
        bot = self._bot
        if self.running and bot is not None:
            self._stop.set()
            bot.poke()
            self._thread.join(timeout)

    # ---- what the window shows -------------------------------------------------------------------

    def status(self) -> dict:
        try:
            cfg = self.config()
            config_error = ""
        except (ValueError, OSError) as e:
            cfg, config_error = Config(), str(e)
        bot = self._bot if self.running else None
        mode = bot.mode if bot else cfg.mode
        section = self.store.load().get(mode, {})
        equity_rows = self.store.read_equity(mode, limit=100_000)
        start_equity = float(equity_rows[0]["equity"]) if equity_rows else None
        if mode == "paper" and not equity_rows:
            start_equity = cfg.paper.starting_cash
        risk = section.get("risk", {})
        return jsonable({
            "mode": mode,
            "configured_mode": cfg.mode,
            "running": bot is not None,
            "stopping": bot is not None and self._stop.is_set(),
            "halted": self.store.halt_reason(),
            "coin": coin_of(cfg),
            "symbol": cfg.market.signal_symbol,
            "last_tick": section.get("last_tick"),
            "next_check": bot.next_check if bot else None,
            "signal": section.get("last_signal"),
            "target": section.get("last_target"),
            "exposure": section.get("last_exposure"),
            "equity": section.get("last_equity"),
            "start_equity": start_equity,
            "peak": risk.get("peak_equity"),
            "trades_today": risk.get("trades_today", 0),
            "max_exposure": cfg.risk.max_exposure,
            "kill_switch": cfg.risk.max_drawdown,
            "wallet": wallet_address(self.keystore) if self.keystore.exists() else None,
            "error": self.error or config_error,
            "log": list(self.log.lines)[-80:],
        })

    def history(self) -> dict:
        bot = self._bot if self.running else None
        mode = bot.mode if bot else self.config().mode
        return {"mode": mode, "equity": self.store.read_equity(mode), "trades": self.store.read_trades(mode, 50)[::-1]}

    # ---- backtests (in the background, so the window stays responsive) ---------------------------

    def start_backtest(self, coin: str, days: int, kind: str) -> dict:
        if coin not in COINS or kind not in ("backtest", "walkforward") or not 90 <= int(days) <= 3000:
            raise ValueError("Pick a coin, a period and a test type.")
        with self._lock:
            if self._job.get("state") == "running":
                raise ValueError("A test is already running.")
            self._job = {"state": "running", "coin": coin, "days": int(days), "kind": kind, "started": time.time()}
        threading.Thread(target=self._backtest, args=(coin, int(days), kind), name="backtest", daemon=True).start()
        return {"message": "Test started."}

    def _backtest(self, coin: str, days: int, kind: str) -> None:
        from .backtest import run_backtest, walk_forward
        from .data import interval_seconds

        job = dict(self._job)
        try:
            cfg = self.config()
            cfg.market.signal_symbol = COINS[coin]["signal_symbol"]
            md = MarketData(cfg.market.data_url, home_dir() / "data")
            df = md.history(cfg.market.signal_symbol, cfg.market.interval, days)
            if kind == "walkforward":
                per_day = 86400 // interval_seconds(cfg.market.interval)
                wf = walk_forward(df, cfg, 365 * per_day, 90 * per_day)
                result = {"metrics": wf.metrics, "benchmark": wf.benchmark, "bot": series_points(wf.equity),
                          "hold": series_points(wf.benchmark_equity), "start": wf.equity.index[0],
                          "folds": [{"from": f["from"], "to": f["to"], "bot": f["test_return"], "hold": f["hold_return"]}
                                    for f in wf.folds]}
            else:
                r = run_backtest(df, cfg)
                hold = df["close"].loc[r.equity.index] / df["close"].loc[r.equity.index[0]] * cfg.paper.starting_cash
                result = {"metrics": r.metrics, "benchmark": r.benchmark, "bot": series_points(r.equity),
                          "hold": series_points(hold), "start": r.equity.index[0], "halted_at": r.halted_at,
                          "halt_reason": r.halt_reason, "trades": r.metrics["trades"]}
            result["starting_cash"] = cfg.paper.starting_cash
            job.update(state="done", result=jsonable(result), finished=time.time())
        except Exception as e:
            log.exception("Test failed")
            job.update(state="error", error=str(e) or type(e).__name__)
        self._job = job

    def backtest_job(self) -> dict:
        return jsonable(self._job)

    # ---- wallet ----------------------------------------------------------------------------------

    def _chain(self, cfg: Config):
        from .dex import Chain

        key = (cfg.chain.rpc_url, cfg.chain.quote_token, cfg.chain.asset_token)
        if self._chain_cache[0] != key:
            self._chain_cache = (key, Chain(cfg))
        return self._chain_cache[1]

    def balances(self, refresh: bool = False) -> dict:
        if not self.keystore.exists():
            return {}
        cached_at, cached = self._balances_cache
        if cached and not refresh and time.time() - cached_at < 30:
            return cached
        cfg = self.config()
        chain = self._chain(cfg)
        address = wallet_address(self.keystore)
        result = {"quote": chain.quote.to_float(chain.quote.balance(address)), "quote_symbol": chain.quote.symbol,
                  "asset": chain.asset.to_float(chain.asset.balance(address)), "asset_symbol": chain.asset.symbol,
                  "bnb": chain.native_balance(address)}
        self._balances_cache = (time.time(), result)
        return result

    def wallet(self, refresh: bool = False) -> dict:
        if not self.keystore.exists():
            return {"exists": False}
        import segno

        address = wallet_address(self.keystore)
        info = {"exists": True, "address": address, "path": str(self.keystore),
                "qr": segno.make(address, error="m").svg_inline(omitsize=True, border=2, dark="#111", light="#fff")}
        try:
            info["balances"] = self.balances(refresh)
        except Exception as e:
            info["balance_error"] = f"Couldn't read balances from BNB Chain: {e}"
        return info

    def create_wallet(self, password: str, password2: str) -> dict:
        if password != password2:
            raise ValueError("The two passwords don't match.")
        address = create_wallet(self.keystore, password)
        return {"message": "Wallet created.", "address": address}

    def withdraw(self, to: str, password: str, confirm: str) -> dict:
        if self.running:
            raise ValueError("Stop the bot first (Pause on the Dashboard).")
        if not Web3.is_address(to or ""):
            raise ValueError("That isn't a valid BNB Smart Chain address.")
        to = Web3.to_checksum_address(to)
        if (confirm or "").strip().lower() != to[-4:].lower():
            raise ValueError("Type the last 4 characters of the address to confirm.")
        self.store.acquire_lock()
        try:
            chain, _ = load_live(self.config(), password)
            if to == chain.address:
                raise ValueError("That's the bot's own address. Use your Trust Wallet's BNB Smart Chain address.")
            self.store.halt("Funds withdrawn")
            sent = chain.withdraw_all(to)
        finally:
            self.store.release_lock()
        self._balances_cache = (0.0, None)
        return {"message": "Sent everything back." if sent else "The bot wallet was already empty.", "sent": sent}

    # ---- settings --------------------------------------------------------------------------------

    def settings(self) -> dict:
        cfg = self.config()
        return jsonable({
            "mode": cfg.mode, "coin": coin_of(cfg), "coins": list(COINS),
            "starting_cash": cfg.paper.starting_cash, "max_exposure": cfg.risk.max_exposure,
            "max_drawdown": cfg.risk.max_drawdown, "daily_loss_limit": cfg.risk.daily_loss_limit,
            "min_trade_usd": cfg.risk.min_trade_usd, "telegram_bot_token": cfg.notify.telegram_bot_token,
            "telegram_chat_id": cfg.notify.telegram_chat_id, "has_wallet": self.keystore.exists(),
            "config_path": str(self.config_path), "running": self.running,
        })

    def save_settings(self, data: dict) -> dict:
        if self.running:
            raise ValueError("Pause the bot before changing settings.")
        cfg = self.config()
        new = copy.deepcopy(cfg)
        new.mode = data.get("mode", cfg.mode)
        if new.mode == "live" and not self.keystore.exists():
            raise ValueError("Create the bot's wallet (Wallet tab) before switching to live trading.")
        notes = []
        coin = data.get("coin", coin_of(cfg))
        if coin not in COINS:
            raise ValueError(f"Unknown coin {coin}.")
        if coin != coin_of(cfg):
            if self.keystore.exists():
                held = self.balances(refresh=True)
                if held["asset"] > 0 and (cfg.mode == "live" or new.mode == "live"):
                    raise ValueError(f"The bot wallet still holds {held['asset']:.6f} {held['asset_symbol']}. "
                                     "Sell it first (Emergency sell on the Dashboard), then switch coins.")
            new.market.signal_symbol = COINS[coin]["signal_symbol"]
            new.chain.asset_token = COINS[coin]["asset_token"]
            self._reset_paper()
            notes.append("the paper account was reset, since it held the old coin")
        try:
            new.paper.starting_cash = float(data.get("starting_cash", cfg.paper.starting_cash))
            for name in ("max_exposure", "max_drawdown", "daily_loss_limit", "min_trade_usd"):
                setattr(new.risk, name, float(data.get(name, getattr(cfg.risk, name))))
        except (TypeError, ValueError):
            raise ValueError("Please enter numbers in the number fields.") from None
        if new.paper.starting_cash < 10:
            raise ValueError("The paper account needs at least $10.")
        new.notify.telegram_bot_token = str(data.get("telegram_bot_token", "")).strip()
        new.notify.telegram_chat_id = str(data.get("telegram_chat_id", "")).strip()
        save_config(new, self.config_path)
        self._balances_cache = (0.0, None)
        if new.paper.starting_cash != cfg.paper.starting_cash and not notes:
            notes.append("the new paper balance applies after you reset the paper account")
        return {"message": "Saved" + (": " + "; ".join(notes) if notes else ".")}

    def _reset_paper(self) -> None:
        saved = self.store.load()
        saved.pop("paper", None)
        self.store.save(saved)
        self.store.clear_mode("paper")

    def reset_paper(self) -> dict:
        bot = self._bot if self.running else None
        if bot and bot.mode == "paper":
            raise ValueError("Pause the bot first.")
        self._reset_paper()
        return {"message": f"Paper account reset to ${self.config().paper.starting_cash:,.2f}."}

"""The bot's state on disk: counters, pretend balances, the halt flag and the trade log."""
from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .broker import Fill


class Store:
    def __init__(self, home: Path):
        self.home = home
        self.state_path = home / "state.json"
        self.halt_path = home / "HALT"
        self.trades_path = home / "trades.csv"
        self.equity_path = home / "equity.csv"

    def load(self) -> dict:
        if not self.state_path.exists():
            return {}
        with open(self.state_path) as f:
            return json.load(f)

    def save(self, state: dict) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, self.state_path)  # atomic: a crash mid-write can't corrupt the state

    # The halt flag is a file, so `tradebot stop` in another terminal reaches a running bot.
    def halt(self, reason: str) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        self.halt_path.write_text(reason + "\n")

    def halt_reason(self) -> str | None:
        if not self.halt_path.exists():
            return None
        return self.halt_path.read_text().strip() or "halted"

    def clear_halt(self) -> None:
        self.halt_path.unlink(missing_ok=True)

    def resume(self) -> None:
        """Clears a halt and measures future drawdowns from the current balance, in every mode."""
        self.clear_halt()
        saved = self.load()
        for mode in ("paper", "live"):
            risk = saved.get(mode, {}).get("risk")
            if risk:
                risk.update(peak_equity=0.0, halted=False, halt_reason="")
        saved["resumes"] = saved.get("resumes", 0) + 1
        self.save(saved)

    # A PID lock, so two copies of the bot never trade the same wallet at once.
    def running_pid(self) -> int | None:
        lock = self.home / "bot.pid"
        try:
            pid = int(lock.read_text())
            os.kill(pid, 0)
            return pid
        except (FileNotFoundError, ValueError, ProcessLookupError):
            return None
        except PermissionError:  # alive, but owned by another user
            return pid

    def acquire_lock(self) -> None:
        pid = self.running_pid()
        if pid and pid != os.getpid():
            raise RuntimeError(f"The bot is already running (process {pid}). Stop it first with Ctrl+C in its window.")
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "bot.pid").write_text(str(os.getpid()))

    def release_lock(self) -> None:
        if self.running_pid() == os.getpid():
            (self.home / "bot.pid").unlink(missing_ok=True)

    def log_trade(self, mode: str, fill: Fill, reason: str, equity: float) -> None:
        new = not self.trades_path.exists()
        with open(self.trades_path, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["time", "mode", "side", "units", "usd", "price", "cost_usd", "route", "tx", "equity", "reason"])
            w.writerow([datetime.now(timezone.utc).isoformat(timespec="seconds"), mode, fill.side,
                        f"{fill.asset_amount:.8f}", f"{fill.quote_amount:.2f}", f"{fill.price:.4f}", f"{fill.cost_usd:.4f}",
                        fill.route, fill.tx_hash, f"{equity:.2f}", reason])

    def log_equity(self, mode: str, price: float, equity: float, exposure: float, target: float) -> None:
        new = not self.equity_path.exists()
        with open(self.equity_path, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["time", "mode", "price", "equity", "exposure", "target"])
            w.writerow([datetime.now(timezone.utc).isoformat(timespec="seconds"), mode, f"{price:.6f}",
                        f"{equity:.4f}", f"{exposure:.4f}", f"{target:.4f}"])

    @staticmethod
    def _read_csv(path: Path, mode: str | None, limit: int) -> list[dict]:
        if not path.exists():
            return []
        with open(path, newline="") as f:
            rows = [r for r in csv.DictReader(f) if r.get("time") and (mode is None or r.get("mode") == mode)]
        return rows[-limit:]

    def read_trades(self, mode: str | None = None, limit: int = 200) -> list[dict]:
        return self._read_csv(self.trades_path, mode, limit)

    def read_equity(self, mode: str | None = None, limit: int = 5000) -> list[dict]:
        return self._read_csv(self.equity_path, mode, limit)

    def clear_mode(self, mode: str) -> None:
        """Deletes one mode's rows from the trade and equity logs (used when resetting the paper account)."""
        for path in (self.trades_path, self.equity_path):
            if not path.exists():
                continue
            with open(path, newline="") as f:
                rows = list(csv.reader(f))
            keep = [rows[0]] + [r for r in rows[1:] if len(r) > 1 and r[1] != mode] if rows else []
            tmp = path.with_suffix(".tmp")
            with open(tmp, "w", newline="") as f:
                csv.writer(f).writerows(keep)
            os.replace(tmp, path)

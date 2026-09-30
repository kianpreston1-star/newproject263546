"""Candles from Binance's free public market-data API (no account or key needed)."""
from __future__ import annotations

import logging
import time
from pathlib import Path

import pandas as pd
import requests

log = logging.getLogger(__name__)

INTERVAL_SECONDS = {
    "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200,
    "4h": 14400, "6h": 21600, "12h": 43200, "1d": 86400,
}
COLUMNS = ["open", "high", "low", "close", "volume"]


def interval_seconds(interval: str) -> int:
    try:
        return INTERVAL_SECONDS[interval]
    except KeyError:
        raise ValueError(f"Unsupported interval '{interval}'. Use one of: {', '.join(INTERVAL_SECONDS)}") from None


def periods_per_year(interval: str) -> float:
    return 365 * 86400 / interval_seconds(interval)  # crypto trades around the clock


class MarketData:
    def __init__(self, base_url: str, cache_dir: Path | None = None, session: requests.Session | None = None):
        self.base_url = base_url.rstrip("/")
        self.cache_dir = cache_dir
        self.session = session or requests.Session()

    def _get_klines(self, symbol: str, interval: str, start_ms: int | None, limit: int = 1000) -> list:
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        if start_ms is not None:
            params["startTime"] = start_ms
        for attempt in range(5):
            try:
                r = self.session.get(f"{self.base_url}/api/v3/klines", params=params, timeout=20)
                if r.status_code == 429 or r.status_code >= 500:
                    raise requests.HTTPError(f"HTTP {r.status_code}")
                r.raise_for_status()
                return r.json()
            except (requests.RequestException, ValueError) as e:
                if attempt == 4:
                    raise RuntimeError(f"Couldn't load {symbol} candles: {e}") from e
                time.sleep(2**attempt)
        return []

    @staticmethod
    def _frame(rows: list, now_ms: int) -> pd.DataFrame:
        if not rows:
            return pd.DataFrame(columns=COLUMNS, index=pd.DatetimeIndex([], tz="UTC", name="time"), dtype=float)
        df = pd.DataFrame(rows).iloc[:, :7]
        df.columns = ["time", *COLUMNS, "close_time"]
        df = df[df["close_time"] < now_ms]  # only finished candles, so a signal never uses a half-formed bar
        df.index = pd.to_datetime(df["time"], unit="ms", utc=True)
        df.index.name = "time"
        return df[COLUMNS].astype(float)

    def recent(self, symbol: str, interval: str, bars: int) -> pd.DataFrame:
        """The latest `bars` finished candles."""
        step_ms = interval_seconds(interval) * 1000
        now_ms = int(time.time() * 1000)
        start = now_ms - (bars + 1) * step_ms
        rows: list = []
        while True:
            chunk = self._get_klines(symbol, interval, start)
            rows += chunk
            if len(chunk) < 1000:
                break
            start = chunk[-1][0] + step_ms
        df = self._frame(rows, now_ms)
        return df[~df.index.duplicated()].iloc[-bars:]

    def history(self, symbol: str, interval: str, days: float) -> pd.DataFrame:
        """Finished candles for the last `days` days, cached on disk so repeat backtests are fast."""
        step_ms = interval_seconds(interval) * 1000
        now_ms = int(time.time() * 1000)
        start_ms = now_ms - int(days * 86400 * 1000)
        cache = self.cache_dir / f"{symbol}_{interval}.csv" if self.cache_dir else None
        df = None
        if cache and cache.exists():
            df = pd.read_csv(cache, index_col="time", parse_dates=["time"])
            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC")
            if df.empty or df.index[0].value // 10**6 > start_ms + step_ms:
                df = None  # the cache doesn't reach back far enough
        fetch_from = start_ms if df is None else int(df.index[-1].value // 10**6) + step_ms
        rows: list = []
        while fetch_from < now_ms - step_ms:
            chunk = self._get_klines(symbol, interval, fetch_from)
            if not chunk:
                break
            rows += chunk
            fetch_from = chunk[-1][0] + step_ms
            log.debug("Loaded %s candles up to %s", len(rows), pd.to_datetime(chunk[-1][0], unit="ms"))
        new = self._frame(rows, now_ms)
        df = new if df is None or df.empty else pd.concat([df, new]) if len(new) else df
        df = df[~df.index.duplicated(keep="last")].sort_index().astype(float)
        if cache:
            cache.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(cache)
        return df[df.index >= pd.Timestamp(start_ms, unit="ms", tz="UTC")]

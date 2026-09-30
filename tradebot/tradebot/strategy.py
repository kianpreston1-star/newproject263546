"""The trading strategy: turns candles into a target share of the account to hold in the coin.

Core: time-series momentum (trend following). The trend is scored over four horizons, from one week to
two months, each adjusted for volatility, and the bot holds more of the coin the stronger and more
consistent the uptrend is. When the trend turns down it moves to the stablecoin. Crypto trends have
tended to persist, and sidestepping the long bear markets is where this earns its keep: in testing it
roughly halved the worst loss compared with just holding.

Overlay: in a long-term uptrend, sharp dips below the recent average add a little extra exposure.

Sizing: volatility targeting shrinks the position when the market gets wild, and the target is smoothed
so the bot doesn't pay fees to chase every wiggle. The strategy is long-only, since a DEX spot wallet
can't short.

Faster, hourly versions of these ideas made money before fees but lost it all to trading costs; see the
README for the numbers. Everything here is causal, so the backtest and the live bot compute exactly the
same numbers from the same candles.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import indicators as ind
from .config import StrategyConfig
from .data import periods_per_year


def warmup_bars(p: StrategyConfig) -> int:
    return max(*p.momentum_lookbacks, p.long_filter_ema, p.mr_window) + p.vol_window


def compute_signals(df: pd.DataFrame, p: StrategyConfig, interval: str) -> pd.DataFrame:
    close = df["close"]
    ann_vol = np.log(close).diff().rolling(p.vol_window).std() * np.sqrt(periods_per_year(interval))

    # Trend: -1 (strong, steady downtrend) .. +1 (strong, steady uptrend).
    trend = ind.momentum_score(close, p.momentum_lookbacks, p.vol_window)
    exposure = (trend / p.trend_full).clip(0, 1)

    # Dip-buying overlay, only while the long-term trend is up.
    uptrend = close > ind.ema(close, p.long_filter_ema)
    dip = (-ind.zscore(close, p.mr_window) / p.mr_z).clip(0, 1).where(uptrend, 0.0)
    exposure = (exposure + p.dip_weight * dip).clip(0, 1)

    vol_scale = (p.target_vol / ann_vol).clip(0, 1)
    target = (exposure * vol_scale).ewm(span=p.smoothing, adjust=False).mean().fillna(0.0)
    target.iloc[: warmup_bars(p)] = 0.0

    return pd.DataFrame({
        "close": close, "trend": trend, "dip": dip, "volatility": ann_vol, "vol_scale": vol_scale,
        "target": target,
    })

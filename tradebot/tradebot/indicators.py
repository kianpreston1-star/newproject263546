"""Technical indicators. Every one is causal: the value at a bar only uses that bar and earlier ones."""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def zscore(s: pd.Series, n: int) -> pd.Series:
    """How many standard deviations the price is above (+) or below (-) its n-bar average."""
    m = s.rolling(n).mean()
    sd = s.rolling(n).std()
    return (s - m) / sd.replace(0, np.nan)


def momentum_score(close: pd.Series, lookbacks, vol_window: int) -> pd.Series:
    """Average over several horizons of the volatility-adjusted return, squashed into -1..1.

    For each horizon h the h-bar log return is divided by the volatility expected over h bars, which makes
    it a t-statistic-like "how unusual is this move" number; tanh keeps a single huge move from dominating.
    """
    vol = np.log(close).diff().rolling(vol_window).std()
    parts = [np.tanh(np.log(close / close.shift(h)) / (vol * np.sqrt(h))) for h in lookbacks]
    return pd.concat(parts, axis=1).mean(axis=1, skipna=False)

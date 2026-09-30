import numpy as np
import pandas as pd
import pytest


def make_candles(returns: np.ndarray, start_price: float = 100.0, seed: int = 0) -> pd.DataFrame:
    """Hourly candles following the given per-bar log returns, with a little intrabar noise."""
    rng = np.random.default_rng(seed)
    close = start_price * np.exp(np.cumsum(returns))
    open_ = np.concatenate([[start_price], close[:-1]])
    wiggle = np.abs(rng.normal(0, 0.002, len(close)))
    idx = pd.date_range("2022-01-01", periods=len(close), freq="h", tz="UTC", name="time")
    return pd.DataFrame({"open": open_, "high": np.maximum(open_, close) * (1 + wiggle),
                         "low": np.minimum(open_, close) * (1 - wiggle), "close": close,
                         "volume": 1.0}, index=idx)


@pytest.fixture
def random_walk():
    rng = np.random.default_rng(42)
    return make_candles(rng.normal(0, 0.01, 6000))


@pytest.fixture
def uptrend():
    rng = np.random.default_rng(1)
    return make_candles(rng.normal(0.0008, 0.005, 5000))


@pytest.fixture
def downtrend():
    rng = np.random.default_rng(2)
    return make_candles(rng.normal(-0.0008, 0.005, 5000))

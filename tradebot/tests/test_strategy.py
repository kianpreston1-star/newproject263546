import numpy as np
import pandas as pd
import pytest

from tradebot import indicators as ind
from tradebot.config import StrategyConfig
from tradebot.strategy import compute_signals, warmup_bars


def test_signals_never_look_ahead(random_walk):
    """Adding future candles must not change any past signal. This is what keeps the backtest honest."""
    p = StrategyConfig()
    full = compute_signals(random_walk, p, "1h")
    cut = len(random_walk) - 700
    partial = compute_signals(random_walk.iloc[:cut], p, "1h")
    pd.testing.assert_frame_equal(full.iloc[:cut], partial)


def test_target_is_a_valid_exposure(random_walk):
    target = compute_signals(random_walk, StrategyConfig(), "1h")["target"]
    assert target.notna().all()
    assert (target >= 0).all() and (target <= 1).all()
    assert (target.iloc[: warmup_bars(StrategyConfig())] == 0).all()


def test_invests_in_uptrends_and_exits_downtrends(uptrend, downtrend):
    p = StrategyConfig()
    up = compute_signals(uptrend, p, "1h")["target"].iloc[warmup_bars(p):]
    down = compute_signals(downtrend, p, "1h")["target"].iloc[warmup_bars(p):]
    assert up.mean() > 0.6
    assert down.mean() < 0.05


def test_volatility_targeting_shrinks_positions():
    from conftest import make_candles

    rng = np.random.default_rng(3)
    calm = make_candles(rng.normal(0.0008, 0.005, 5000))
    wild = make_candles(rng.normal(0.0008 * 4, 0.02, 5000))  # same trend strength, 4x the volatility
    p = StrategyConfig()
    w = warmup_bars(p)
    assert compute_signals(wild, p, "1h")["target"].iloc[w:].mean() < compute_signals(calm, p, "1h")["target"].iloc[w:].mean()


def test_indicators():
    s = pd.Series([1.0, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    assert ind.ema(s, 3).iloc[-1] == pytest.approx(9.0, abs=0.01)
    assert ind.zscore(s, 5).iloc[-1] == pytest.approx((10 - 8) / s.iloc[-5:].std())
    trend = pd.Series(np.exp(np.linspace(0, 1, 400)))
    noisy = trend * (1 + 0.001 * np.sin(np.arange(400)))
    assert ind.momentum_score(noisy, [24, 48], 48).iloc[-1] > 0.9
    assert ind.momentum_score(1 / noisy, [24, 48], 48).iloc[-1] < -0.9

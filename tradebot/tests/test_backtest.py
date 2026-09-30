import numpy as np
import pytest

from tradebot.backtest import metrics, run_backtest, walk_forward
from tradebot.config import Config
from tradebot.risk import CAP_TOLERANCE
from tradebot.strategy import warmup_bars


def test_backtest_runs_and_reports(uptrend):
    r = run_backtest(uptrend, Config())
    m = r.metrics
    assert m["trades"] > 0
    assert m["total_return"] > 0
    assert 0.5 < m["avg_exposure"] <= Config().risk.max_exposure + CAP_TOLERANCE
    assert r.exposure.max() <= Config().risk.max_exposure + CAP_TOLERANCE + 0.02  # one candle of drift
    assert len(r.equity) == len(uptrend) - warmup_bars(Config().strategy)
    assert r.benchmark["total_return"] > 0


def test_backtest_is_deterministic(random_walk):
    a = run_backtest(random_walk, Config())
    b = run_backtest(random_walk, Config())
    assert a.metrics == b.metrics


def test_stays_out_of_downtrends(downtrend):
    r = run_backtest(downtrend, Config())
    assert r.metrics["total_return"] > r.benchmark["total_return"] + 0.3


def test_trades_fill_at_the_next_open(uptrend):
    """A decision made with a candle's close is filled at the following candle's open, never the same close."""
    r = run_backtest(uptrend, Config())
    first = r.trades.iloc[0]
    fill_bar = uptrend.index.get_loc(first["time"])
    assert first["price"] > uptrend["open"].iloc[fill_bar]  # the open plus costs
    assert first["price"] == pytest.approx(uptrend["open"].iloc[fill_bar] * 1.001, rel=1e-3)


def test_costs_reduce_returns(random_walk):
    cheap, pricey = Config(), Config()
    pricey.paper.fee_bps = 50
    assert run_backtest(random_walk, pricey).metrics["final_equity"] < run_backtest(random_walk, cheap).metrics["final_equity"]


def test_metrics_on_a_known_curve():
    import pandas as pd

    idx = pd.date_range("2024-01-01", periods=8761, freq="h", tz="UTC")
    eq = pd.Series(np.linspace(100, 200, len(idx)), index=idx)
    eq.iloc[4000] = 50  # one-hour 50%+ crash
    m = metrics(eq, "1h")
    assert m["total_return"] == pytest.approx(1.0)
    assert m["cagr"] == pytest.approx(1.0, rel=0.01)
    assert m["max_drawdown"] == pytest.approx(50 / (100 + 100 * 3999 / 8760) - 1, rel=1e-6)


def test_walk_forward_uses_only_past_data(random_walk):
    cfg = Config()
    grid = {"strategy.trend_full": [0.25, 0.5], "risk.rebalance_threshold": [0.1, 0.2]}
    wf = walk_forward(random_walk, cfg, train_bars=1000, test_bars=500, grid=grid)
    assert wf.folds
    for fold in wf.folds:
        assert fold["params"]["strategy.trend_full"] in (0.25, 0.5)
    first_test = wf.folds[0]["from"]
    assert first_test == random_walk.index[warmup_bars(cfg.strategy) + 1000]
    assert wf.equity.index[0] == first_test

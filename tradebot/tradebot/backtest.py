"""Backtesting and walk-forward testing.

The backtest replays history candle by candle through the same strategy, risk manager and cost model the
live bot uses. A decision made at a candle's close is filled at the next candle's open, so it never
trades on information it wouldn't have had.

Walk-forward testing guards against the classic trap of tuning a strategy until it fits the past
perfectly and then fails live: it picks settings using only data *before* each test window, then scores
them on the window that follows, and stitches those unseen windows together.
"""
from __future__ import annotations

import copy
import itertools
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .broker import PaperBroker
from .config import Config
from .data import periods_per_year
from .risk import RiskManager, RiskState
from .strategy import compute_signals, warmup_bars


@dataclass
class BacktestResult:
    equity: pd.Series
    exposure: pd.Series
    trades: pd.DataFrame
    metrics: dict
    benchmark: dict
    halted_at: pd.Timestamp | None = None
    halt_reason: str = ""


def metrics(equity: pd.Series, interval: str) -> dict:
    ppy = periods_per_year(interval)
    rets = equity.pct_change().dropna()
    years = len(rets) / ppy
    total = equity.iloc[-1] / equity.iloc[0] - 1
    vol = rets.std() * np.sqrt(ppy)
    downside = rets[rets < 0].std() * np.sqrt(ppy)
    dd = equity / equity.cummax() - 1
    cagr = (1 + total) ** (1 / years) - 1 if years > 0 and total > -1 else float("nan")
    monthly = equity.resample("ME").last().pct_change().dropna()
    return {
        "total_return": total,
        "cagr": cagr,
        "volatility": vol,
        "sharpe": rets.mean() * ppy / vol if vol > 0 else 0.0,
        "sortino": rets.mean() * ppy / downside if downside > 0 else 0.0,
        "max_drawdown": dd.min(),
        "calmar": cagr / -dd.min() if dd.min() < 0 else float("nan"),
        "positive_months": (monthly > 0).mean() if len(monthly) else float("nan"),
    }


def run_backtest(df: pd.DataFrame, cfg: Config, start: int | None = None, end: int | None = None,
                 signals: pd.DataFrame | None = None, kill_switch: bool = True) -> BacktestResult:
    """Simulates trading on df.iloc[start:end]. Signals come from the whole df (they are causal), so the
    strategy is already warmed up when the window starts."""
    if signals is None:
        signals = compute_signals(df, cfg.strategy, cfg.market.interval)
    start = warmup_bars(cfg.strategy) if start is None else max(start, 1)
    end = len(df) if end is None else end
    if end - start < 2:
        raise ValueError("Not enough candles to backtest. Load more history.")

    risk_cfg = copy.copy(cfg.risk)
    if not kill_switch:
        risk_cfg.max_drawdown = 1.0
    risk = RiskManager(risk_cfg)
    p = cfg.paper
    broker = PaperBroker(p.starting_cash, 0.0, p.fee_bps, p.slippage_bps, p.gas_usd)
    state = RiskState()

    opens, closes = df["open"].to_numpy(), df["close"].to_numpy()
    targets = signals["target"].to_numpy()
    times = df.index
    equity = np.empty(end - start)
    exposure = np.empty(end - start)
    trades = []
    halted_at = None

    equity[0] = broker.portfolio(closes[start]).equity
    exposure[0] = 0.0
    for i in range(start, end - 1):
        port = broker.portfolio(closes[i])
        for event in risk.update(state, port, times[i]):
            halted_at = times[i]
        decision = risk.plan(targets[i], port, state)
        if decision.order:
            fill = broker.execute(decision.order, opens[i + 1])
            state.trades_today += 1
            trades.append({"time": times[i + 1], "side": fill.side, "units": fill.asset_amount,
                           "usd": fill.quote_amount, "price": fill.price, "cost": fill.cost_usd,
                           "reason": decision.order.reason})
        after = broker.portfolio(closes[i + 1])
        equity[i + 1 - start] = after.equity
        exposure[i + 1 - start] = after.exposure

    index = times[start:end]
    eq = pd.Series(equity, index=index, name="equity")
    hold = pd.Series(closes[start:end] / closes[start] * p.starting_cash, index=index, name="buy_and_hold")
    trade_df = pd.DataFrame(trades, columns=["time", "side", "units", "usd", "price", "cost", "reason"])
    m = metrics(eq, cfg.market.interval)
    m.update({
        "trades": len(trade_df),
        "costs_paid": float(trade_df["cost"].sum()) if len(trade_df) else 0.0,
        "avg_exposure": float(np.mean(exposure)),
        "final_equity": float(eq.iloc[-1]),
    })
    bench = metrics(hold, cfg.market.interval)
    bench["final_equity"] = float(hold.iloc[-1])
    return BacktestResult(eq, pd.Series(exposure, index=index, name="exposure"), trade_df, m, bench,
                          halted_at, state.halt_reason)


# The settings walk-forward testing chooses between. Kept small on purpose: the more knobs you search,
# the easier it is to find settings that only look good by luck.
DEFAULT_GRID = {
    "strategy.momentum_lookbacks": [(72, 168, 336, 720), (168, 336, 720, 1440), (336, 720, 1440, 2160)],
    "strategy.trend_full": [0.25, 0.5],
    "risk.rebalance_threshold": [0.1, 0.2],
}


def _with(cfg: Config, params: dict) -> Config:
    new = copy.deepcopy(cfg)
    for key, value in params.items():
        section, name = key.split(".")
        setattr(getattr(new, section), name, value)
    return new


@dataclass
class WalkForwardResult:
    equity: pd.Series
    benchmark_equity: pd.Series
    metrics: dict
    benchmark: dict
    folds: list = field(default_factory=list)


def walk_forward(df: pd.DataFrame, cfg: Config, train_bars: int, test_bars: int,
                 grid: dict | None = None) -> WalkForwardResult:
    grid = grid or DEFAULT_GRID
    combos = [dict(zip(grid, values)) for values in itertools.product(*grid.values())]
    cfgs = [_with(cfg, c) for c in combos]
    signals = [compute_signals(df, c.strategy, c.market.interval) for c in cfgs]
    warm = max(warmup_bars(c.strategy) for c in cfgs)

    oos_returns = []
    folds = []
    start = warm + train_bars
    while start + test_bars // 4 < len(df):
        end = min(start + test_bars, len(df))
        scores = []
        for c, sig in zip(cfgs, signals):
            r = run_backtest(df, c, start - train_bars, start, sig, kill_switch=False)
            scores.append(r.metrics["sharpe"])
        best = int(np.nanargmax(scores))
        test = run_backtest(df, cfgs[best], start, end, signals[best], kill_switch=False)
        oos_returns.append(test.equity.pct_change().fillna(0.0))
        folds.append({"from": df.index[start], "to": df.index[end - 1], "params": combos[best],
                      "train_sharpe": scores[best], "test_return": test.metrics["total_return"],
                      "hold_return": test.benchmark["total_return"]})
        start = end

    if not oos_returns:
        raise ValueError("Not enough history for walk-forward testing. Use more days or shorter windows.")
    rets = pd.concat(oos_returns)
    equity = (1 + rets).cumprod() * cfg.paper.starting_cash
    closes = df["close"].loc[equity.index]
    hold = closes / closes.iloc[0] * cfg.paper.starting_cash
    return WalkForwardResult(equity, hold, metrics(equity, cfg.market.interval),
                             metrics(hold, cfg.market.interval), folds)

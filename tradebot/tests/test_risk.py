import pandas as pd
import pytest

from tradebot.broker import PaperBroker
from tradebot.config import RiskConfig
from tradebot.risk import Order, Portfolio, RiskManager, RiskState

NOW = pd.Timestamp("2025-01-01 12:00", tz="UTC")


def fresh(p: Portfolio, rm: RiskManager) -> RiskState:
    state = RiskState()
    rm.update(state, p, NOW)
    return state


def test_buys_toward_target_capped_by_trade_size():
    rm = RiskManager(RiskConfig(max_trade_fraction=0.5))
    p = Portfolio(quote=1000, asset=0, price=10)
    d = rm.plan(0.8, p, fresh(p, rm))
    assert d.order.side == "buy"
    assert d.order.quote_amount == pytest.approx(500)  # 80% wanted, one trade is capped at 50%


def test_caps_exposure():
    rm = RiskManager(RiskConfig(max_exposure=0.6, max_trade_fraction=1.0))
    p = Portfolio(quote=1000, asset=0, price=10)
    d = rm.plan(1.0, p, fresh(p, rm))
    assert d.order.quote_amount == pytest.approx(600)


def test_trims_when_gains_push_past_the_cap():
    rm = RiskManager(RiskConfig(max_exposure=0.8, rebalance_threshold=0.15))
    drifted = Portfolio(quote=100, asset=90, price=10)  # 90% invested after a rally
    d = rm.plan(1.0, drifted, fresh(drifted, rm))
    assert d.order.side == "sell"
    assert d.order.asset_amount == pytest.approx(10)  # back to 80%
    near = Portfolio(quote=160, asset=84, price=10)  # 84%: within the tolerance
    assert rm.plan(1.0, near, fresh(near, rm)).order is None


def test_small_changes_are_ignored():
    rm = RiskManager(RiskConfig(rebalance_threshold=0.15))
    p = Portfolio(quote=500, asset=50, price=10)  # 50% invested
    assert rm.plan(0.6, p, fresh(p, rm)).order is None
    assert rm.plan(0.7, p, fresh(p, rm)).order is not None


def test_target_zero_sells_everything():
    rm = RiskManager(RiskConfig())
    p = Portfolio(quote=900, asset=5, price=10)  # only 5% invested, below the rebalance threshold
    d = rm.plan(0.0, p, fresh(p, rm))
    assert d.order.side == "sell" and d.order.asset_amount == 5


def test_tiny_trades_are_skipped():
    rm = RiskManager(RiskConfig(min_trade_usd=10))
    p = Portfolio(quote=30, asset=0, price=10)
    assert rm.plan(0.2, p, fresh(p, rm)).order is None  # $6 buy


def test_daily_loss_limit_blocks_buys_but_allows_sells():
    rm = RiskManager(RiskConfig(daily_loss_limit=0.05, max_trade_fraction=1.0))
    state = fresh(Portfolio(quote=500, asset=50, price=10), rm)  # $1000 at the start of the day
    down = Portfolio(quote=500, asset=50, price=8.8)  # now $940, a 6% loss
    rm.update(state, down, NOW)
    assert rm.plan(0.9, down, state).order is None
    assert rm.plan(0.0, down, state).order.side == "sell"


def test_daily_counters_reset_next_day():
    rm = RiskManager(RiskConfig())
    p = Portfolio(quote=1000, asset=0, price=10)
    state = fresh(p, rm)
    state.trades_today = 99
    rm.update(state, p, NOW + pd.Timedelta(days=1))
    assert state.trades_today == 0


def test_trade_limit_per_day():
    rm = RiskManager(RiskConfig(max_trades_per_day=3))
    p = Portfolio(quote=1000, asset=0, price=10)
    state = fresh(p, rm)
    state.trades_today = 3
    assert rm.plan(0.9, p, state).order is None


def test_kill_switch_halts_and_liquidates():
    rm = RiskManager(RiskConfig(max_drawdown=0.25, max_trade_fraction=0.1))
    state = fresh(Portfolio(quote=0, asset=100, price=10), rm)
    crashed = Portfolio(quote=0, asset=100, price=7.4)
    events = rm.update(state, crashed, NOW)
    assert state.halted and events
    d = rm.plan(1.0, crashed, state)
    assert d.order.side == "sell" and d.order.asset_amount == 100  # all of it, ignoring the per-trade cap
    state.trades_today = 1000
    assert rm.plan(1.0, crashed, state).order is not None  # the trade limit never blocks getting out


def test_paper_broker_charges_costs():
    b = PaperBroker(1000, fee_bps=5, slippage_bps=5, gas_usd=0.02)
    fill = b.execute(Order("buy", quote_amount=500), price=10)
    assert b.quote == 500
    assert fill.asset_amount == pytest.approx((500 - 0.02) * 0.999 / 10)
    b.execute(Order("sell", asset_amount=b.asset), price=10)
    assert b.asset == 0
    assert 998.9 < b.quote < 999.0  # about 0.2% in round-trip costs plus gas


def test_paper_broker_cannot_overspend():
    b = PaperBroker(100)
    b.execute(Order("buy", quote_amount=1000), price=10)
    assert b.quote == 0
    b.execute(Order("sell", asset_amount=1000), price=10)
    assert b.asset == 0

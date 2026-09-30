"""Risk management: decides whether and how much to trade, and trips the kill switch.

Shared by the backtester, paper trading and live trading, so all three behave the same way.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from .config import RiskConfig

CAP_TOLERANCE = 0.05  # how far rising prices may push the position past max_exposure before it's trimmed


@dataclass
class Portfolio:
    quote: float  # stablecoin balance, in dollars
    asset: float  # units of the traded coin
    price: float  # dollars per unit of the coin

    @property
    def asset_value(self) -> float:
        return self.asset * self.price

    @property
    def equity(self) -> float:
        return self.quote + self.asset_value

    @property
    def exposure(self) -> float:
        return self.asset_value / self.equity if self.equity > 0 else 0.0


@dataclass
class RiskState:
    peak_equity: float = 0.0
    day: str = ""
    day_start_equity: float = 0.0
    trades_today: int = 0
    halted: bool = False
    halt_reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RiskState":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Order:
    side: str  # "buy" or "sell"
    quote_amount: float = 0.0  # dollars to spend, for a buy
    asset_amount: float = 0.0  # units to sell, for a sell
    reason: str = ""


@dataclass
class Decision:
    target: float  # exposure after risk limits
    order: Order | None
    note: str


class RiskManager:
    def __init__(self, cfg: RiskConfig):
        self.cfg = cfg

    def update(self, state: RiskState, p: Portfolio, now: pd.Timestamp) -> list[str]:
        """Rolls the daily counters, tracks the equity peak and trips the kill switch. Returns events to report."""
        events = []
        day = now.strftime("%Y-%m-%d")
        if state.day != day:
            state.day, state.day_start_equity, state.trades_today = day, p.equity, 0
        if p.equity > state.peak_equity:
            state.peak_equity = p.equity
        drawdown = self.drawdown(state, p)
        if not state.halted and drawdown >= self.cfg.max_drawdown:
            state.halted = True
            state.halt_reason = f"Kill switch: account fell {drawdown:.1%} from its peak of ${state.peak_equity:,.2f}"
            events.append(state.halt_reason)
        return events

    @staticmethod
    def drawdown(state: RiskState, p: Portfolio) -> float:
        return 1 - p.equity / state.peak_equity if state.peak_equity > 0 else 0.0

    def plan(self, signal_target: float, p: Portfolio, state: RiskState) -> Decision:
        c = self.cfg
        target = min(max(signal_target, 0.0), c.max_exposure)
        exposure = p.exposure
        notes = []

        if state.halted:
            target = 0.0
            notes.append("halted: moving to stablecoin")
        elif state.day_start_equity > 0 and p.equity <= state.day_start_equity * (1 - c.daily_loss_limit):
            if target > exposure:
                target = exposure
                notes.append("daily loss limit hit: no new buys today")

        if state.trades_today >= c.max_trades_per_day and not state.halted:
            return Decision(target, None, "daily trade limit reached")

        delta = target - exposure
        full_exit = target == 0.0 and p.asset_value >= c.min_trade_usd
        over_cap = exposure > c.max_exposure + CAP_TOLERANCE  # price gains pushed the position past the cap
        if abs(delta) < c.rebalance_threshold and not full_exit and not over_cap:
            return Decision(target, None, "; ".join(notes) or f"holding (target {target:.0%}, now {exposure:.0%})")

        value = delta * p.equity
        if not state.halted and not full_exit:
            cap = c.max_trade_fraction * p.equity
            value = max(-cap, min(cap, value))

        if value > 0:
            spend = min(value, p.quote)
            if spend < c.min_trade_usd:
                return Decision(target, None, "; ".join(notes) or "buy too small")
            order = Order("buy", quote_amount=spend, reason=f"target {target:.0%}, now {exposure:.0%}")
        else:
            units = p.asset if target == 0.0 else min(-value / p.price, p.asset)
            if units * p.price < c.min_trade_usd:
                return Decision(target, None, "; ".join(notes) or "sell too small")
            order = Order("sell", asset_amount=units, reason=f"target {target:.0%}, now {exposure:.0%}")
        if notes:
            order.reason = "; ".join([order.reason, *notes])
        return Decision(target, order, order.reason)

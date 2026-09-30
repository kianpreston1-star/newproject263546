"""Order execution. PaperBroker simulates fills; the live broker lives in dex.py."""
from __future__ import annotations

from dataclasses import dataclass

from .risk import Order, Portfolio


class TradeSkipped(Exception):
    """A safety check refused a trade. Nothing was sent; the bot tries again next candle."""


@dataclass
class Fill:
    side: str
    asset_amount: float
    quote_amount: float
    price: float
    cost_usd: float  # fees, price impact and gas
    tx_hash: str = ""
    route: str = "paper"


class PaperBroker:
    """Fills every order at the given price minus a realistic cost, with pretend money."""

    def __init__(self, quote: float, asset: float = 0.0, fee_bps: float = 5.0, slippage_bps: float = 5.0,
                 gas_usd: float = 0.0):
        self.quote = quote
        self.asset = asset
        self.cost = (fee_bps + slippage_bps) / 10_000
        self.gas_usd = gas_usd

    def portfolio(self, price: float) -> Portfolio:
        return Portfolio(self.quote, self.asset, price)

    def execute(self, order: Order, price: float) -> Fill:
        if order.side == "buy":
            spend = min(order.quote_amount, self.quote)
            gas = min(self.gas_usd, spend)
            units = (spend - gas) * (1 - self.cost) / price
            self.quote -= spend
            self.asset += units
            return Fill("buy", units, spend, spend / units if units else price, spend - units * price)
        units = min(order.asset_amount, self.asset)
        proceeds = units * price * (1 - self.cost) - self.gas_usd
        self.asset -= units
        self.quote += proceeds
        return Fill("sell", units, proceeds, proceeds / units if units else price, units * price - proceeds)

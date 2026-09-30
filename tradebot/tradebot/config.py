"""Settings. Every value has a safe default here; ~/.tradebot/config.toml overrides any of them."""
from __future__ import annotations

import os
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

# BNB Chain (BSC) mainnet contracts, each checked on-chain.
USDT = "0x55d398326f99059fF775485246999027B3197955"
WBNB = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
PANCAKE_V2_ROUTER = "0x10ED43C718714eb63d5aA57B78B54704E256024E"
PANCAKE_V3_ROUTER = "0x13f4EA83D0bd40E75C8222255bc855a974568Dd4"  # SmartRouter
PANCAKE_V3_QUOTER = "0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997"  # QuoterV2


def home_dir() -> Path:
    """Where the bot keeps its config, encrypted wallet, state and logs. Never inside the repository."""
    return Path(os.environ.get("TRADEBOT_HOME") or Path.home() / ".tradebot").expanduser()


@dataclass
class MarketConfig:
    signal_symbol: str = "BNBUSDT"  # Binance pair whose candles drive the signals
    interval: str = "1h"
    history_bars: int = 2600  # candles loaded on every live check; must cover the strategy's warm-up
    data_url: str = "https://data-api.binance.vision"


@dataclass
class StrategyConfig:
    momentum_lookbacks: tuple = (168, 336, 720, 1440)  # bars; with 1h candles: 1 week, 2 weeks, 1 and 2 months
    vol_window: int = 720
    trend_full: float = 0.5  # trend score at which the bot is fully invested (0-1; lower = more all-or-nothing)
    dip_weight: float = 0.3  # extra exposure for a deep dip during a long-term uptrend
    mr_window: int = 48
    mr_z: float = 2.0  # how stretched (in standard deviations) a dip must be to count in full
    long_filter_ema: int = 1440
    target_vol: float = 0.6  # annualised volatility the position is sized for
    smoothing: int = 24  # bars; smooths the target so small wiggles don't cost fees


@dataclass
class RiskConfig:
    max_exposure: float = 0.9  # never hold more than this share of the account in the traded coin
    rebalance_threshold: float = 0.15  # ignore target changes smaller than this (saves fees)
    max_trade_fraction: float = 0.5  # largest single trade, as a share of the account
    min_trade_usd: float = 10.0
    max_slippage_bps: float = 50.0  # a swap reverts on-chain if it would fill worse than this
    max_price_deviation: float = 0.02  # skip a trade if the DEX price is this far from the market price
    daily_loss_limit: float = 0.05  # after losing this much in a UTC day, only reduce the position
    max_drawdown: float = 0.40  # kill switch: sell everything and halt at this loss from the peak (worst in testing: ~35%)
    max_trades_per_day: int = 12
    stale_bars: int = 2  # refuse to trade on market data older than this many candles


@dataclass
class ChainConfig:
    rpc_url: str = "https://bsc-dataseed.bnbchain.org"
    send_rpc_url: str = ""  # optional separate (e.g. MEV-protected) RPC used only to send transactions
    chain_id: int = 56
    quote_token: str = USDT
    asset_token: str = WBNB
    v2_router: str = PANCAKE_V2_ROUTER
    v3_router: str = PANCAKE_V3_ROUTER
    v3_quoter: str = PANCAKE_V3_QUOTER
    v3_fee_tiers: tuple = (100, 500, 2500)
    use_v2: bool = True
    max_gas_gwei: float = 3.0
    min_gas_bnb: float = 0.002  # keep at least this much BNB for fees
    tx_timeout: int = 180


@dataclass
class PaperConfig:
    starting_cash: float = 1000.0
    fee_bps: float = 5.0  # pool fee plus price impact; the 0.01% and 0.05% PancakeSwap v3 pools cost less
    slippage_bps: float = 5.0
    gas_usd: float = 0.02


@dataclass
class NotifyConfig:
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""


@dataclass
class Config:
    mode: str = "paper"  # "paper": real prices, pretend money. "live": real trades.
    market: MarketConfig = field(default_factory=MarketConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    chain: ChainConfig = field(default_factory=ChainConfig)
    paper: PaperConfig = field(default_factory=PaperConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)

    def validate(self) -> None:
        if self.mode not in ("paper", "live"):
            raise ValueError(f'mode must be "paper" or "live", not "{self.mode}"')
        r = self.risk
        for name in ("max_exposure", "rebalance_threshold", "max_trade_fraction", "daily_loss_limit", "max_drawdown"):
            value = getattr(r, name)
            if not 0 < value <= 1:
                raise ValueError(f"risk.{name} must be between 0 and 1, not {value}")
        if not 0 < r.max_slippage_bps <= 500:
            raise ValueError("risk.max_slippage_bps must be between 0 and 500")
        if not 0 < r.max_price_deviation <= 0.2:
            raise ValueError("risk.max_price_deviation must be between 0 and 0.2")
        if r.max_trades_per_day < 1:
            raise ValueError("risk.max_trades_per_day must be at least 1")
        s = self.strategy
        if not s.momentum_lookbacks or min(s.momentum_lookbacks) < 2:
            raise ValueError("strategy.momentum_lookbacks needs at least one value of 2 or more")
        if not 0 < s.trend_full <= 1:
            raise ValueError("strategy.trend_full must be between 0 and 1")
        if s.target_vol <= 0 or s.smoothing < 1 or s.dip_weight < 0:
            raise ValueError("strategy.target_vol and strategy.smoothing must be positive, dip_weight not negative")
        from .strategy import warmup_bars

        if self.market.history_bars < warmup_bars(s) + 50:
            raise ValueError(f"market.history_bars must be at least {warmup_bars(s) + 50} for these strategy settings")


def _merge(obj, data: dict, where: str) -> None:
    known = {f.name for f in fields(obj)}
    for key, value in data.items():
        if key not in known:
            raise ValueError(f"Unknown setting '{where}{key}' in the config file")
        current = getattr(obj, key)
        if is_dataclass(current):
            if not isinstance(value, dict):
                raise ValueError(f"'{where}{key}' must be a [{where}{key}] section")
            _merge(current, value, f"{where}{key}.")
            continue
        if isinstance(current, tuple):
            value = tuple(value)
        elif isinstance(current, bool):
            if not isinstance(value, bool):
                raise ValueError(f"'{where}{key}' must be true or false")
        elif isinstance(current, float) and isinstance(value, int):
            value = float(value)
        elif type(current) is not type(value):
            raise ValueError(f"'{where}{key}' should be a {type(current).__name__}, got {value!r}")
        setattr(obj, key, value)


def load_config(path: str | Path | None = None) -> Config:
    cfg = Config()
    path = Path(path) if path else home_dir() / "config.toml"
    if path.exists():
        with open(path, "rb") as f:
            _merge(cfg, tomllib.load(f), "")
    cfg.notify.telegram_bot_token = os.environ.get("TRADEBOT_TELEGRAM_TOKEN", cfg.notify.telegram_bot_token)
    cfg.notify.telegram_chat_id = os.environ.get("TRADEBOT_TELEGRAM_CHAT", cfg.notify.telegram_chat_id)
    cfg.validate()
    return cfg

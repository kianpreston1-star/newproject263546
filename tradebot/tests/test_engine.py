import numpy as np
import pandas as pd
import pytest

from conftest import make_candles
from tradebot.broker import PaperBroker, TradeSkipped
from tradebot.config import Config
from tradebot.engine import Bot
from tradebot.notify import Notifier
from tradebot.store import Store


class FakeMarket:
    """Serves candles whose last one closed a moment ago, like the live feed."""

    def __init__(self, df: pd.DataFrame, age_hours: float = 0.1):
        end = pd.Timestamp.now(tz="UTC").floor("h") - pd.Timedelta(hours=1) - pd.Timedelta(hours=age_hours).floor("h")
        self.df = df.set_axis(pd.date_range(end=end, periods=len(df), freq="h", tz="UTC", name="time"))

    def recent(self, symbol, interval, bars):
        return self.df.iloc[-bars:]


def make_bot(tmp_path, df, **kw) -> Bot:
    cfg = Config()
    return Bot(cfg, PaperBroker(1000.0), FakeMarket(df, **kw), Store(tmp_path), Notifier(cfg.notify))


@pytest.fixture
def rally():
    return make_candles(np.random.default_rng(1).normal(0.0008, 0.005, 3000))


def test_tick_trades_and_saves_state(tmp_path, rally):
    bot = make_bot(tmp_path, rally)
    line = bot.tick()
    assert "[paper]" in line
    saved = Store(tmp_path).load()
    assert saved["paper"]["asset"] > 0  # bought into the uptrend
    assert saved["risk"]["trades_today"] == 1
    assert saved["risk"]["peak_equity"] == pytest.approx(1000.0)
    assert (tmp_path / "trades.csv").read_text().count("\n") == 2

    # A restarted bot picks up where it left off.
    again = make_bot(tmp_path, rally)
    again.broker = PaperBroker(saved["paper"]["quote"], saved["paper"]["asset"])
    again.tick()
    assert Store(tmp_path).load()["risk"]["trades_today"] == 2


def test_stop_liquidates_and_stays_out(tmp_path, rally):
    bot = make_bot(tmp_path, rally)
    bot.tick()
    assert bot.broker.asset > 0
    Store(tmp_path).halt("test stop")
    assert "halted" in bot.tick()
    assert bot.broker.asset == 0
    bot.tick()
    assert bot.broker.asset == 0  # doesn't buy back in while halted


def test_kill_switch_trips_on_drawdown(tmp_path, rally):
    bot = make_bot(tmp_path, rally)
    bot.tick()
    store = Store(tmp_path)
    saved = store.load()
    saved["risk"]["peak_equity"] = 5000.0  # pretend the account used to be worth far more
    store.save(saved)
    bot.tick()
    assert store.halt_reason().startswith("Kill switch")
    assert bot.broker.asset == 0


def test_refuses_stale_data(tmp_path, rally):
    bot = make_bot(tmp_path, rally, age_hours=5)
    with pytest.raises(TradeSkipped, match="stale"):
        bot.tick()
    assert bot.broker.asset == 0

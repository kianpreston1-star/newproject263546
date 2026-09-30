import numpy as np
import pandas as pd
import pytest

from conftest import FakeMarket, make_candles
from tradebot.broker import PaperBroker, TradeSkipped
from tradebot.config import Config
from tradebot.engine import Bot
from tradebot.notify import Notifier
from tradebot.store import Store


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
    saved = Store(tmp_path).load()["paper"]
    assert saved["balances"]["asset"] > 0  # bought into the uptrend
    assert saved["risk"]["trades_today"] == 1
    assert saved["risk"]["peak_equity"] == pytest.approx(1000.0)
    assert (tmp_path / "trades.csv").read_text().count("\n") == 2
    assert len(Store(tmp_path).read_equity("paper")) == 1

    # A restarted bot picks up where it left off.
    again = make_bot(tmp_path, rally)
    again.broker = PaperBroker(saved["balances"]["quote"], saved["balances"]["asset"])
    again.tick()
    assert Store(tmp_path).load()["paper"]["risk"]["trades_today"] == 2


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
    saved["paper"]["risk"]["peak_equity"] = 5000.0  # pretend the account used to be worth far more
    store.save(saved)
    bot.tick()
    assert store.halt_reason().startswith("Kill switch")
    assert bot.broker.asset == 0


def test_refuses_stale_data(tmp_path, rally):
    bot = make_bot(tmp_path, rally, age_hours=5)
    with pytest.raises(TradeSkipped, match="stale"):
        bot.tick()
    assert bot.broker.asset == 0


def test_paper_and_live_keep_separate_peaks(tmp_path, rally):
    """A $1,000 paper account followed by a $200 live wallet must not look like an 80% loss."""
    store = Store(tmp_path)
    store.save({"paper": {"risk": {"peak_equity": 1000.0}}})
    bot = make_bot(tmp_path, rally)
    bot.broker = PaperBroker(200.0)
    bot.mode = "live"  # stand-in for a live wallet holding $200
    bot.tick()
    assert store.halt_reason() is None
    assert store.load()["live"]["risk"]["peak_equity"] == pytest.approx(200.0)
    assert store.load()["paper"]["risk"]["peak_equity"] == 1000.0


def test_resume_resets_the_peak(tmp_path, rally):
    bot = make_bot(tmp_path, rally)
    bot.tick()
    store = Store(tmp_path)
    saved = store.load()
    saved["paper"]["risk"]["peak_equity"] = 5000.0
    store.save(saved)
    bot.tick()
    assert store.halt_reason()
    store.resume()
    assert store.halt_reason() is None
    bot.tick()
    assert store.halt_reason() is None
    assert store.load()["paper"]["risk"]["peak_equity"] < 1100


def test_run_forever_stops_when_asked(tmp_path, rally):
    import threading

    bot = make_bot(tmp_path, rally)
    stop = threading.Event()
    t = threading.Thread(target=bot.run_forever, args=(stop,))
    t.start()
    for _ in range(100):
        if bot.next_check:
            break
        t.join(0.05)
    assert bot.next_check  # one check done, now waiting for the next candle
    stop.set()
    bot.poke()
    t.join(5)
    assert not t.is_alive()
    assert bot.next_check is None

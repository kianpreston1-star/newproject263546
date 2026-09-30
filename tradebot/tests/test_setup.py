"""Config, wallet, state and the pure pieces of the live broker."""
import json
import os
import stat
from pathlib import Path

import pytest

from tradebot.config import Config, load_config
from tradebot.dex import Route, best_route, min_out, price_deviation
from tradebot.store import Store
from tradebot.wallet import create_wallet, load_account, wallet_address


def test_config_overrides_and_validation(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('mode = "live"\n[risk]\nmax_drawdown = 0.3\nmin_trade_usd = 20\n'
                    '[strategy]\nmomentum_lookbacks = [168, 720]\n')
    cfg = load_config(path)
    assert cfg.mode == "live"
    assert cfg.risk.max_drawdown == 0.3
    assert cfg.risk.min_trade_usd == 20.0 and isinstance(cfg.risk.min_trade_usd, float)
    assert cfg.strategy.momentum_lookbacks == (168, 720)
    assert cfg.risk.daily_loss_limit == Config().risk.daily_loss_limit


@pytest.mark.parametrize("text", [
    'mode = "yolo"',
    "[risk]\nmax_drawdown = 2",
    "[risk]\nmax_drawdonw = 0.3",  # typo
    '[risk]\nmax_drawdown = "0.3"',
    "[market]\nhistory_bars = 100",  # not enough for the strategy's warm-up
])
def test_config_rejects_mistakes(tmp_path, text):
    path = tmp_path / "config.toml"
    path.write_text(text)
    with pytest.raises(ValueError):
        load_config(path)


def test_example_config_loads(tmp_path):
    import tradebot.cli

    path = tmp_path / "config.toml"
    path.write_text((Path(tradebot.cli.__file__).parent / "config.example.toml").read_text())
    assert load_config(path).mode == "paper"


def test_wallet_round_trip(tmp_path):
    path = tmp_path / "home" / "keystore.json"
    address = create_wallet(path, "correct horse battery")
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert "privateKey" not in path.read_text() and "crypto" in json.loads(path.read_text())
    assert wallet_address(path).lower() == address.lower()
    assert load_account(path, "correct horse battery").address == address
    with pytest.raises(ValueError, match="Wrong wallet password"):
        load_account(path, "wrong password!!")


def test_wallet_is_never_overwritten(tmp_path):
    path = tmp_path / "keystore.json"
    create_wallet(path, "correct horse battery")
    before = path.read_text()
    with pytest.raises(FileExistsError):
        create_wallet(path, "another password")
    assert path.read_text() == before


def test_wallet_needs_a_real_password(tmp_path):
    with pytest.raises(ValueError):
        create_wallet(tmp_path / "keystore.json", "short")


def test_store_halt_and_state(tmp_path):
    store = Store(tmp_path)
    assert store.halt_reason() is None
    store.halt("because")
    assert store.halt_reason() == "because"
    store.clear_halt()
    assert store.halt_reason() is None
    store.save({"a": 1})
    assert store.load() == {"a": 1}


def test_store_lock(tmp_path):
    store = Store(tmp_path)
    store.acquire_lock()
    assert store.running_pid() == os.getpid()
    store.acquire_lock()  # the same process may re-acquire
    (tmp_path / "bot.pid").write_text("1")  # pid 1 is always alive: another bot
    with pytest.raises(RuntimeError, match="already running"):
        store.acquire_lock()
    (tmp_path / "bot.pid").write_text("999999999")  # stale lock from a crashed bot
    store.acquire_lock()
    store.release_lock()
    assert not (tmp_path / "bot.pid").exists()


def test_route_selection_and_slippage():
    routes = [Route("v2", 990, path=("a", "b")), Route("v3", 1000, fee=100), Route("v3", 995, fee=500)]
    assert best_route(routes).fee == 100
    assert best_route([]) is None
    assert Route("v3", 1, fee=100).describe() == "PancakeSwap v3 0.01% pool"
    assert Route("v3", 1, fee=2500).describe() == "PancakeSwap v3 0.25% pool"
    assert min_out(10_000, 50) == 9_950
    assert min_out(10**18, 50) == 995 * 10**15
    assert price_deviation(102, 100) == pytest.approx(0.02)

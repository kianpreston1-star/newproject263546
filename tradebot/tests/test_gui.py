"""The desktop app's server: security checks and every button's back end, in paper mode."""
import json
import threading
import time
import urllib.error
import urllib.request

import numpy as np
import pytest

from conftest import FakeMarket, make_candles
from tradebot.app import BotService
from tradebot.config import load_config
from tradebot.gui import Server


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEBOT_HOME", str(tmp_path))
    (tmp_path / "config.toml").write_text('mode = "paper"\n[chain]\nrpc_url = "http://127.0.0.1:9"\n')
    rally = make_candles(np.random.default_rng(1).normal(0.0008, 0.005, 3000))
    service = BotService(market=FakeMarket(rally))
    server = Server(service, "secret-token", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    service.shutdown(5)
    server.shutdown()


def call(server, path, body=None, token="secret-token", host=None):
    url = f"http://127.0.0.1:{server.port}{path}"
    headers = {"X-Tradebot-Token": token, "Content-Type": "application/json"}
    if host:
        headers["Host"] = host
    data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
    req = urllib.request.Request(url, data=data, headers=headers, method="GET" if body is None else "POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=10) as r:
            return r.status, json.loads(r.read()) if r.headers["Content-Type"] == "application/json" else r.headers
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def wait_for(fn, seconds=10):
    end = time.time() + seconds
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.05)
    return False


def test_page_is_served_with_a_strict_policy(app):
    code, headers = call(app, "/", token="")
    assert code == 200
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert headers["X-Frame-Options"] == "DENY"


def test_api_needs_the_token(app):
    assert call(app, "/api/status", token="")[0] == 403
    assert call(app, "/api/status", token="wrong")[0] == 403
    assert call(app, "/api/start", {}, token="wrong")[0] == 403
    assert call(app, "/api/status")[0] == 200


def test_rejects_other_hosts(app):
    """Blocks DNS rebinding: a web page whose domain points at 127.0.0.1 still sends its own Host."""
    assert call(app, "/api/status", host="evil.example:80")[0] == 403
    assert call(app, "/", token="", host="evil.example")[0] == 403


def test_bad_requests(app):
    assert call(app, "/api/start", b"not json")[0] == 400
    assert call(app, "/api/nope")[0] == 404
    code, body = call(app, "/api/backtest", {"coin": "DOGE", "days": 365, "kind": "backtest"})
    assert code == 400 and "Pick a coin" in body["error"]


def test_start_pause_and_emergency(app):
    code, st = call(app, "/api/status")
    assert st["mode"] == "paper" and not st["running"] and st["start_equity"] == 1000.0

    assert call(app, "/api/start", {})[0] == 200
    assert wait_for(lambda: call(app, "/api/status")[1]["last_tick"])
    st = call(app, "/api/status")[1]
    assert st["running"] and st["exposure"] > 0.3 and st["equity"] == pytest.approx(1000, abs=5)
    assert call(app, "/api/start", {})[0] == 400  # already running

    hist = call(app, "/api/history")[1]
    assert hist["trades"][0]["side"] == "buy" and len(hist["equity"]) == 1

    assert call(app, "/api/emergency", {})[0] == 200
    assert wait_for(lambda: call(app, "/api/status")[1]["exposure"] == 0)
    assert call(app, "/api/status")[1]["halted"]
    assert call(app, "/api/resume", {})[0] == 200
    assert call(app, "/api/status")[1]["halted"] is None

    assert call(app, "/api/pause", {})[0] == 200
    assert wait_for(lambda: not call(app, "/api/status")[1]["running"])


def test_settings(app, tmp_path):
    st = call(app, "/api/settings")[1]
    assert st["mode"] == "paper" and st["coin"] == "BNB" and not st["has_wallet"]

    code, body = call(app, "/api/settings", {**st, "max_drawdown": 0.3, "telegram_chat_id": "42"})
    assert code == 200, body
    cfg = load_config(tmp_path / "config.toml")
    assert cfg.risk.max_drawdown == 0.3 and cfg.notify.telegram_chat_id == "42"
    assert cfg.chain.rpc_url == "http://127.0.0.1:9"  # settings the app doesn't show are kept

    assert call(app, "/api/settings", {**st, "max_drawdown": 2})[0] == 400
    code, body = call(app, "/api/settings", {**st, "mode": "live"})
    assert code == 400 and "wallet" in body["error"]

    code, body = call(app, "/api/settings", {**st, "coin": "ETH"})
    assert code == 200 and "reset" in body["message"]
    cfg = load_config(tmp_path / "config.toml")
    assert cfg.market.signal_symbol == "ETHUSDT" and cfg.chain.asset_token.startswith("0x2170")


def test_settings_locked_while_running(app):
    call(app, "/api/start", {})
    code, body = call(app, "/api/settings", call(app, "/api/settings")[1])
    assert code == 400 and "Pause" in body["error"]


def test_wallet(app, tmp_path):
    assert call(app, "/api/wallet")[1] == {"exists": False}
    code, body = call(app, "/api/wallet/create", {"password": "long enough pw", "password2": "different pw!!"})
    assert code == 400 and "match" in body["error"]
    code, body = call(app, "/api/wallet/create", {"password": "long enough pw", "password2": "long enough pw"})
    assert code == 200 and body["address"].startswith("0x")
    w = call(app, "/api/wallet")[1]
    assert w["exists"] and w["address"] == body["address"] and w["qr"].startswith("<svg")
    assert "balance_error" in w  # the test config points at an RPC that isn't there
    assert call(app, "/api/wallet/create", {"password": "long enough pw", "password2": "long enough pw"})[0] == 400

    code, body = call(app, "/api/withdraw", {"to": "0x" + "11" * 20, "password": "x", "confirm": "nope"})
    assert code == 400 and "last 4" in body["error"]


def test_paper_reset(app, tmp_path):
    call(app, "/api/start", {})
    wait_for(lambda: call(app, "/api/status")[1]["last_tick"])
    assert call(app, "/api/paper/reset", {})[0] == 400  # not while paper trading
    call(app, "/api/pause", {})
    wait_for(lambda: not call(app, "/api/status")[1]["running"])
    assert call(app, "/api/paper/reset", {})[0] == 200
    st = call(app, "/api/status")[1]
    assert st["equity"] is None and st["start_equity"] == 1000.0
    assert call(app, "/api/history")[1]["trades"] == []


def test_quit_stops_the_server(app):
    call(app, "/api/start", {})
    assert call(app, "/api/quit", {})[0] == 200
    assert wait_for(lambda: not app.service.running)


@pytest.mark.parametrize("installed, running, expected", [
    ({"google-chrome", "firefox", "pgrep"}, set(), ["google-chrome", "--app=URL"]),
    ({"chromium", "firefox", "pgrep"}, {"firefox"}, ["firefox", "--new-window", "URL"]),  # reuse the open Firefox
    ({"chromium", "firefox", "pgrep"}, {"firefox", "chromium"}, ["chromium", "--app=URL"]),
    ({"firefox", "pgrep"}, set(), ["firefox", "--new-window", "URL"]),
])
def test_window_opens_like_cloud_ai(monkeypatch, installed, running, expected):
    import subprocess
    from tradebot import gui

    monkeypatch.setattr(gui.shutil, "which", lambda name: name if name in installed else None)
    launched = []

    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0 if cmd[-1] in running else 1)

    monkeypatch.setattr(gui.subprocess, "run", fake_run)
    monkeypatch.setattr(gui.subprocess, "Popen", lambda cmd, **kw: launched.append(cmd))
    gui.open_window("URL")
    assert launched[0][: len(expected)] == expected

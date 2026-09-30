"""The desktop app: a small web server that only this computer can reach, shown in its own window.

`tradebot gui` starts the server in the background if it isn't already running, then opens the window.
The bot keeps running in the background when the window is closed; the window's Quit button stops it.

Security: the server listens on 127.0.0.1 only, rejects requests whose Host header isn't its own
(DNS rebinding), and every API call must carry a random token that only the window knows. Web pages
open in your browser can't read that token, so they can't press the app's buttons.
"""
from __future__ import annotations

import hmac
import json
import logging
import logging.handlers
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .app import BotService
from .broker import TradeSkipped
from .config import home_dir

log = logging.getLogger(__name__)

UI_DIR = Path(__file__).parent / "ui"
PREFERRED_PORT = 8764
STATIC = {"/": ("index.html", "text/html; charset=utf-8"), "/index.html": ("index.html", "text/html; charset=utf-8"),
          "/icon.svg": ("icon.svg", "image/svg+xml")}
CSP = ("default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


ROUTES = {
    ("GET", "/api/ping"): lambda svc, q: {"ok": True, "pid": os.getpid()},
    ("GET", "/api/status"): lambda svc, q: svc.status(),
    ("GET", "/api/history"): lambda svc, q: svc.history(),
    ("GET", "/api/wallet"): lambda svc, q: svc.wallet(refresh=q.get("refresh") == "1"),
    ("GET", "/api/settings"): lambda svc, q: svc.settings(),
    ("GET", "/api/backtest"): lambda svc, q: svc.backtest_job(),
    ("POST", "/api/start"): lambda svc, d: svc.start(d.get("password"), bool(d.get("confirm_live"))),
    ("POST", "/api/pause"): lambda svc, d: svc.pause(),
    ("POST", "/api/emergency"): lambda svc, d: svc.emergency_stop(),
    ("POST", "/api/resume"): lambda svc, d: svc.resume(),
    ("POST", "/api/backtest"): lambda svc, d: svc.start_backtest(d.get("coin", ""), int(d.get("days", 0)), d.get("kind", "")),
    ("POST", "/api/wallet/create"): lambda svc, d: svc.create_wallet(d.get("password", ""), d.get("password2", "")),
    ("POST", "/api/withdraw"): lambda svc, d: svc.withdraw(d.get("to", ""), d.get("password", ""), d.get("confirm", "")),
    ("POST", "/api/settings"): lambda svc, d: svc.save_settings(d),
    ("POST", "/api/paper/reset"): lambda svc, d: svc.reset_paper(),
}


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, service: BotService, token: str, port: int):
        try:
            super().__init__(("127.0.0.1", port), Handler)
        except OSError:
            super().__init__(("127.0.0.1", 0), Handler)  # preferred port taken: let the system pick one
        self.service = service
        self.token = token
        self.port = self.server_address[1]
        self.hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}

    def quit_soon(self) -> None:
        def stop():
            self.service.shutdown()
            self.shutdown()
        threading.Thread(target=stop, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    server: Server
    server_version = "tradebot"
    sys_version = ""

    def log_message(self, fmt, *args):
        log.debug("%s " + fmt, self.address_string(), *args)

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        if ctype.startswith("text/html"):
            self.send_header("Content-Security-Policy", CSP)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj, allow_nan=False).encode(), "application/json")

    def _checked(self) -> bool:
        if self.headers.get("Host", "") not in self.server.hosts:
            self._json(403, {"error": "Wrong host"})
            return False
        return True

    def do_GET(self) -> None:
        if not self._checked():
            return
        url = urlsplit(self.path)
        if url.path in STATIC:
            name, ctype = STATIC[url.path]
            return self._send(200, (UI_DIR / name).read_bytes(), ctype)
        if url.path.startswith("/api/"):
            return self._api("GET", url.path, {k: v[-1] for k, v in parse_qs(url.query).items()})
        self._json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        if not self._checked():
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length > 65536:
            return self._json(413, {"error": "Request too large"})
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(data, dict):
                raise ValueError
        except ValueError:
            return self._json(400, {"error": "Bad request"})
        self._api("POST", urlsplit(self.path).path, data)

    def _api(self, method: str, path: str, data: dict) -> None:
        if not hmac.compare_digest(self.headers.get("X-Tradebot-Token", ""), self.server.token):
            return self._json(403, {"error": "Not authorized. Open tradebot from its icon."})
        if (method, path) == ("POST", "/api/quit"):
            self._json(200, {"message": "tradebot is shutting down."})
            return self.server.quit_soon()
        route = ROUTES.get((method, path))
        if route is None:
            return self._json(404, {"error": "Not found"})
        try:
            self._json(200, route(self.server.service, data) or {})
        except (ValueError, FileNotFoundError, FileExistsError, RuntimeError, TradeSkipped) as e:
            self._json(400, {"error": str(e)})
        except Exception as e:
            log.exception("%s %s failed", method, path)
            self._json(500, {"error": f"{type(e).__name__}: {e}"})


# ---- running the server ----------------------------------------------------------------------------

def info_path() -> Path:
    return home_dir() / "gui.json"


def read_info() -> dict | None:
    try:
        return json.loads(info_path().read_text())
    except (OSError, ValueError):
        return None


def ping(info: dict | None) -> bool:
    if not info:
        return False
    req = urllib.request.Request(f"http://127.0.0.1:{info['port']}/api/ping", headers={"X-Tradebot-Token": info["token"]})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never send this through a proxy
    try:
        with opener.open(req, timeout=2) as r:
            return json.loads(r.read()).get("ok") is True
    except (OSError, ValueError):
        return False


def serve(config_path: str | None = None, port: int = PREFERRED_PORT) -> None:
    """Runs the app server in the foreground until Quit is pressed."""
    home = home_dir()
    home.mkdir(parents=True, exist_ok=True)
    service = BotService(config_path)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    file_handler = logging.handlers.RotatingFileHandler(home / "bot.log", maxBytes=5_000_000, backupCount=3)
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
    root.addHandler(file_handler)
    root.addHandler(service.log)
    for noisy in ("urllib3", "web3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    server = Server(service, secrets.token_urlsafe(32), port)
    fd = os.open(info_path(), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"port": server.port, "token": server.token, "pid": os.getpid()}, f)
    log.info("tradebot app ready on http://127.0.0.1:%s", server.port)
    try:
        server.serve_forever()
    finally:
        service.shutdown()
        if (read_info() or {}).get("pid") == os.getpid():
            info_path().unlink(missing_ok=True)
        log.info("tradebot app closed.")


def ensure_server(config_path: str | None = None) -> dict:
    """Starts the background server if needed and returns its connection details."""
    info = read_info()
    if ping(info):
        return info
    home_dir().mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "tradebot"] + (["--config", config_path] if config_path else []) + ["gui", "--serve"]
    with open(home_dir() / "app.log", "ab") as out:
        subprocess.Popen(cmd, cwd=home_dir(), stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                         start_new_session=True)
    for _ in range(80):
        time.sleep(0.25)
        info = read_info()
        if ping(info):
            return info
    raise RuntimeError(f"tradebot's app server didn't start. Details are in {home_dir() / 'app.log'}")


def open_window(url: str) -> None:
    """Opens the app in its own window: a Chrome-family browser's app mode if there is one, else a browser tab.
    Like Cloud AI, it reuses Firefox when that's the browser already open, to save memory."""
    chrome = next((b for b in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                               "brave-browser", "microsoft-edge") if shutil.which(b)), None)

    def running(name):
        return shutil.which("pgrep") and subprocess.run(["pgrep", "-x", name], capture_output=True).returncode == 0

    chrome_open = any(running(n) for n in ("chrome", "chromium", "brave", "msedge"))
    if chrome and (chrome_open or not running("firefox")):
        cmd = [chrome, f"--app={url}", "--window-size=1320,900"]
    elif shutil.which("firefox"):
        cmd = ["firefox", "--new-window", url]
    else:
        webbrowser.open(url)
        return
    subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def notify_error(message: str) -> None:
    print(message, file=sys.stderr)
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", "tradebot", message], check=False)


def main(args) -> None:
    if args.serve:
        serve(args.config)
        return
    if args.stop:
        info = read_info()
        if not ping(info):
            print("The tradebot app isn't running.")
            return
        req = urllib.request.Request(f"http://127.0.0.1:{info['port']}/api/quit", data=b"{}", method="POST",
                                     headers={"X-Tradebot-Token": info["token"], "Content-Type": "application/json"})
        urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=5).read()
        print("The tradebot app is shutting down (the bot stops after its current check).")
        return
    if hasattr(os, "geteuid") and os.geteuid() == 0 and not os.environ.get("TRADEBOT_ALLOW_ROOT"):
        notify_error("tradebot can't open as root (browsers refuse to run as root). Open it as your normal user.")
        sys.exit(1)
    try:
        info = ensure_server(args.config)
    except RuntimeError as e:
        notify_error(str(e))
        sys.exit(1)
    url = f"http://127.0.0.1:{info['port']}/#t={info['token']}"
    if args.check:
        print(f"✔ tradebot's app server is running at http://127.0.0.1:{info['port']}/")
        return
    open_window(url)

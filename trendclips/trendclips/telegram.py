"""Your phone is the control panel: each new video arrives in Telegram with ✅ Post / ❌ Skip buttons, and you can
type /make, /trends or /stats to the bot. Only your own chat is listened to."""
from __future__ import annotations

import html
import logging
import threading
import time
from pathlib import Path

import requests

log = logging.getLogger(__name__)

HELP = """Commands:
/make – make a video about what's trending now
/make <topic> – make a video about a topic you choose
/trends – what's trending right now
/stats – how your videos are doing
/help – this list"""


class TelegramError(RuntimeError):
    pass


def keyboard(*rows: list[tuple[str, str]]) -> dict:
    return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in rows]}


class Telegram:
    def __init__(self, token: str, chat_id: str = "", session: requests.Session | None = None):
        self.token = token.strip()
        self.chat_id = str(chat_id).strip()
        self.http = session or requests.Session()

    @property
    def ready(self) -> bool:
        return bool(self.token and self.chat_id)

    def call(self, method: str, files: dict | None = None, http_timeout: float = 30, **params):
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        try:
            if files:
                r = self.http.post(url, data={k: v for k, v in params.items() if v is not None}, files=files,
                                   timeout=http_timeout)
            else:
                r = self.http.post(url, json={k: v for k, v in params.items() if v is not None},
                                   timeout=http_timeout)
        except requests.RequestException as e:  # the URL holds the bot token, so it's never logged
            raise TelegramError(f"couldn't reach Telegram ({type(e).__name__})") from None
        try:
            data = r.json()
        except ValueError:
            raise TelegramError(f"Telegram answered HTTP {r.status_code}") from None
        if not data.get("ok"):
            raise TelegramError(data.get("description", f"HTTP {r.status_code}"))
        return data["result"]

    def me(self) -> dict:
        return self.call("getMe")

    def send(self, text: str, buttons: dict | None = None, html_mode: bool = False) -> dict:
        return self.call("sendMessage", chat_id=self.chat_id, text=text[:4096], reply_markup=buttons,
                         parse_mode="HTML" if html_mode else None, disable_web_page_preview=True)

    def send_video(self, path: Path, caption: str, buttons: dict | None = None) -> dict:
        import json

        with open(path, "rb") as f:
            return self.call("sendVideo", files={"video": (Path(path).name, f, "video/mp4")}, http_timeout=600,
                             chat_id=self.chat_id, caption=caption[:1024], supports_streaming="true",
                             width=1080, height=1920, reply_markup=json.dumps(buttons) if buttons else None)

    def answer(self, callback_id: str, text: str = "") -> None:
        try:
            self.call("answerCallbackQuery", callback_query_id=callback_id, text=text[:200])
        except TelegramError:
            pass  # too late to answer; harmless

    def set_buttons(self, message_id: int, buttons: dict | None) -> None:
        try:
            self.call("editMessageReplyMarkup", chat_id=self.chat_id, message_id=message_id,
                      reply_markup=buttons or {"inline_keyboard": []})
        except TelegramError:
            pass

    def updates(self, offset: int, wait: int = 50) -> list[dict]:
        """Long polling: Telegram holds the request open until something arrives or `wait` seconds pass."""
        return self.call("getUpdates", http_timeout=wait + 15, offset=offset, timeout=wait,
                         allowed_updates=["message", "callback_query"])


def find_chat_id(token: str, wait: float = 180, say=print) -> tuple[str, str] | None:
    """Waits for you to message the bot, then returns (your chat id, your first name)."""
    tg = Telegram(token)
    deadline = time.time() + wait
    offset = 0
    while time.time() < deadline:
        try:
            for u in tg.call("getUpdates", http_timeout=35, offset=offset, timeout=20, allowed_updates=["message"]):
                offset = u["update_id"] + 1
                msg = u.get("message") or {}
                chat = msg.get("chat", {})
                if chat.get("type") == "private":
                    tg.call("getUpdates", offset=offset, timeout=0)  # mark it read
                    return str(chat["id"]), chat.get("first_name", "")
        except TelegramError as e:
            say(f"  (waiting… {e})")
            time.sleep(3)
    return None


def approval_caption(video: dict) -> str:
    meta = video["meta"]
    script = meta.get("script", {})
    hosts = []
    for s in meta.get("sources", []):
        host = s.split("/")[2].removeprefix("www.") if s.count("/") >= 2 else s
        if host not in hosts:
            hosts.append(host)
    trend_from = ", ".join(meta.get("trend_sources") or []) or "you"
    lines = [
        f"🎬 {video['title']}",
        "",
        f"🔥 Trending on: {trend_from}",
        f"🗂 {video['category']} · ⏱ {meta.get('duration', 0):.0f}s · 🎞 {meta.get('stock_shots', 0)}/"
        f"{meta.get('shots', 0)} stock shots · ✍️ {meta.get('writer', '?')}",
    ]
    if hosts:
        lines.append(f"📰 Facts from: {', '.join(hosts[:4])}")
    if script.get("hook_text"):
        lines.append(f"🪝 Hook: {script['hook_text']}")
    lines += ["", "Watch it and check the facts, then:"]
    return "\n".join(lines)


def send_for_approval(tg: Telegram, store, video: dict) -> None:
    msg = tg.send_video(Path(video["path"]), approval_caption(video),
                        keyboard([("✅ Post it", f"post:{video['id']}"), ("❌ Skip", f"skip:{video['id']}")]))
    store.update_video(video["id"], status="sent", telegram_message_id=msg["message_id"])


def caption_for_posting(video: dict) -> str:
    from .pipeline import post_text
    from .writer import Script

    return post_text(Script.from_dict(video["meta"]["script"]))


class Bot:
    """Listens for your button taps and commands. Runs in the background (a systemd user service)."""

    def __init__(self, cfg, store, paths, tg: Telegram | None = None):
        self.cfg, self.store, self.paths = cfg, store, paths
        self.tg = tg or Telegram(cfg.telegram.bot_token, cfg.telegram.chat_id)
        self.job: threading.Thread | None = None

    def run_forever(self) -> None:
        offset = int(self.store.get("telegram_offset", "0"))
        backoff = 5
        log.info("Telegram bot listening")
        while True:
            try:
                updates = self.tg.updates(offset)
                backoff = 5
            except TelegramError as e:
                log.warning("Telegram: %s; retrying in %ss", e, backoff)
                time.sleep(backoff)
                backoff = min(backoff * 2, 120)
                continue
            for u in updates:
                offset = u["update_id"] + 1
                self.store.set("telegram_offset", offset)
                try:
                    self.handle(u)
                except Exception:
                    log.exception("Couldn't handle a Telegram update")

    def handle(self, update: dict) -> None:
        if "callback_query" in update:
            cb = update["callback_query"]
            chat = str(cb.get("message", {}).get("chat", {}).get("id", ""))
            if chat != self.tg.chat_id:
                return
            action, _, vid = (cb.get("data") or "").partition(":")
            if action in ("post", "skip") and vid.isdigit():
                getattr(self, f"on_{action}")(int(vid), cb)
            else:
                self.tg.answer(cb["id"])
        elif "message" in update:
            msg = update["message"]
            if str(msg.get("chat", {}).get("id", "")) != self.tg.chat_id:
                return
            self.on_text((msg.get("text") or "").strip())

    def on_post(self, vid: int, cb: dict) -> None:
        video = self.store.video(vid)
        if not video or video["status"] in ("posted", "approved", "skipped"):
            self.tg.answer(cb["id"], "Already done")
            return
        self.tg.answer(cb["id"], "On it…")
        self.tg.set_buttons(cb["message"]["message_id"], keyboard([("✅ Approved", "noop")]))
        status, lines = "approved", []
        if self.cfg.youtube.upload:
            from . import youtube

            try:
                yt_id, note = youtube.upload_video(self.paths.home, self.cfg, video)
                self.store.update_video(vid, youtube_id=yt_id)
                status = "posted"
                lines.append(f"▶️ On YouTube: https://youtube.com/shorts/{yt_id}")
                if note:
                    lines.append(note)
            except Exception as e:
                lines.append(f"⚠️ YouTube upload failed: {e}\nYou can upload the video above by hand instead.")
        caption = caption_for_posting(video)
        lines += [
            "",
            "📲 To post on TikTok, Instagram Reels" + ("" if status == "posted" else " and YouTube Shorts") + ":",
            "1. Tap the video above, then ⋮ → Save to Gallery.",
            "2. Upload it in the app (on TikTok, adding a trending sound at very low volume helps reach).",
            "3. Tap the caption below to copy it, and paste it in.",
        ]
        self.store.update_video(vid, status=status, posted=time.time())
        self.tg.send("\n".join(lines))
        self.tg.send(f"<code>{html.escape(caption)}</code>", html_mode=True)

    def on_skip(self, vid: int, cb: dict) -> None:
        video = self.store.video(vid)
        if video and video["status"] not in ("posted", "approved"):
            self.store.update_video(vid, status="skipped")
        self.tg.answer(cb["id"], "Skipped")
        self.tg.set_buttons(cb["message"]["message_id"], keyboard([("❌ Skipped", "noop")]))

    def on_text(self, text: str) -> None:
        cmd, _, arg = text.partition(" ")
        cmd = cmd.split("@")[0].lower()
        if cmd == "/make":
            self.start_make(arg.strip())
        elif cmd == "/trends":
            self.tg.send(self.trends_text())
        elif cmd == "/stats":
            self.tg.send(stats_text(self.store))
        elif cmd in ("/start", "/help"):
            self.tg.send("👋 Trend Clips is connected.\n\n" + HELP)
        else:
            self.tg.send("I didn't catch that.\n\n" + HELP)

    def start_make(self, topic: str) -> None:
        if self.job and self.job.is_alive():
            self.tg.send("⏳ Already making a video; it'll arrive here when it's done.")
            return
        self.tg.send(f"🎬 Making a video about {topic or 'what is trending'}. It takes about 5 to 15 minutes "
                     "on the laptop; it'll arrive here for approval.")

        def work():
            from .pipeline import Busy, make_videos
            from .store import Store

            store = Store(self.paths.db)  # SQLite connections can't be shared between threads

            def progress(line: str):
                log.info(line)
                if "failed" in line or "not enough" in line or line.startswith("Picked") or "worth a video" in line:
                    try:
                        self.tg.send(line)
                    except TelegramError:
                        pass

            try:
                made = make_videos(self.cfg, store, self.paths, 1, topic=topic, send=True, progress=progress)
                if not made:
                    self.tg.send("😕 No video this time. Try /make <topic> to choose one yourself.")
            except Busy as e:
                self.tg.send(f"⏳ {e}")
            except Exception as e:
                log.exception("/make failed")
                self.tg.send(f"⚠️ Making the video failed: {e}")
            finally:
                store.close()

        self.job = threading.Thread(target=work, daemon=True)
        self.job.start()

    def trends_text(self) -> str:
        from .trends import TrendScanner

        trends, skipped = TrendScanner(self.cfg).scan(self.store.recent_topic_keys(self.cfg.trends.repeat_after_days))
        lines = ["🔥 Trending now (best first):"]
        lines += [f"{i}. {t.title} ({', '.join(t.sources)})" for i, t in enumerate(trends[:12], 1)]
        if skipped:
            lines += ["", f"Skipped {len(skipped)}: " + "; ".join(f"{t.title} ({r})" for t, r in skipped[:6])]
        lines += ["", "Reply /make to make one now, or /make <topic>."]
        return "\n".join(lines)


def stats_text(store) -> str:
    videos = store.videos(limit=500)
    if not videos:
        return "No videos yet. Send /make to make the first one."
    counts: dict[str, int] = {}
    for v in videos:
        counts[v["status"]] = counts.get(v["status"], 0) + 1
    lines = ["📊 Videos: " + ", ".join(f"{n} {s}" for s, n in sorted(counts.items()))]
    with_views = [v for v in videos if v.get("views") is not None]
    if with_views:
        lines.append(f"👀 YouTube views: {sum(v['views'] for v in with_views):,} across {len(with_views)} videos")
        best = max(with_views, key=lambda v: v["views"])
        lines.append(f"🏆 Best: {best['title']} ({best['views']:,} views)")
        perf = store.category_performance()
        if perf:
            lines.append("By topic: " + ", ".join(f"{c} {p['avg_views']:,} avg" for c, p in perf.items()))
    else:
        lines.append("YouTube view counts appear here once youtube.api_key and youtube.channel_id are set.")
    return "\n".join(lines)

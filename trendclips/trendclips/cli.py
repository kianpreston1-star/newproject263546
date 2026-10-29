"""Command line: `trendclips <command>`. Run `trendclips --help` for the list."""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import shutil
import subprocess
import sys
import time
import warnings
from pathlib import Path

from .config import Config, home_dir, load_config, save_config

UNIT_DIR = Path.home() / ".config" / "systemd" / "user"


def setup_logging(verbose: bool = False) -> None:
    home_dir().mkdir(parents=True, exist_ok=True)
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if verbose else logging.WARNING)
    logfile = logging.handlers.RotatingFileHandler(home_dir() / "trendclips.log", maxBytes=5_000_000, backupCount=3)
    logfile.setLevel(logging.INFO)
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, handlers=[console, logfile],
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    for noisy in ("urllib3", "httpx", "huggingface_hub", "phonemizer", "faster_whisper", "fastembed", "PIL",
                  "kokoro_onnx", "google_auth_oauthlib"):
        logging.getLogger(noisy).setLevel(logging.ERROR)
    # Model downloads only happen during setup; keep their chatter (not their progress bars) out of the way.
    os.environ.setdefault("HF_HUB_VERBOSITY", "error")
    os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    warnings.filterwarnings("ignore", module="huggingface_hub")


def say(msg: str = "") -> None:
    print(msg, flush=True)


def _objects():
    from .pipeline import Paths
    from .store import Store

    cfg = load_config()
    paths = Paths()
    return cfg, Store(paths.db), paths


def _ensure_config() -> None:
    path = home_dir() / "config.toml"
    if not path.exists():
        save_config(Config(), path)


# setup ----------------------------------------------------------------------------------------------------------
def _ask(question: str, current: str = "", secret: bool = True) -> str:
    if current:
        shown = f"…{current[-4:]}" if secret and len(current) > 8 else current
        question += f"\n    (already set: {shown}; press Enter to keep it)"
    try:
        answer = input(f"  {question}\n  > ").strip()
    except EOFError:
        answer = ""
    return answer or current


def _check_gemini(cfg: Config) -> str | None:
    from .llm import LLM, LLMError

    one = Config().ai
    one.providers, one.gemini_api_key, one.gemini_model = ("gemini",), cfg.ai.gemini_api_key, cfg.ai.gemini_model
    try:
        LLM(one).json("Reply with JSON.", 'Reply with exactly {"ok": true}', temperature=0)
        return None
    except LLMError as e:
        return str(e)


def _check_get(url: str, **kw) -> str | None:
    import requests

    try:
        r = requests.get(url, timeout=20, **kw)
        return None if r.ok else f"HTTP {r.status_code} (is the key right?)"
    except requests.RequestException as e:
        return type(e).__name__


def cmd_setup(args) -> None:
    from . import assets
    from .pipeline import Paths

    _ensure_config()
    paths = Paths()
    say("Trend Clips setup. Everything here is free. Press Enter to skip any question; run `trendclips setup` "
        "again any time to change an answer.\n")
    say("1. Downloading fonts and AI models (about 900 MB the first time)…")
    problems = assets.ensure_all(paths, say)
    if problems:
        say("   Some downloads failed. Check your internet connection and run `trendclips setup` again.")
    if args.downloads_only:
        return
    cfg = load_config()

    say("\n2. The AI scriptwriter.")
    say("   Recommended: a free Google Gemini key. Open https://aistudio.google.com/apikey, sign in with a Google")
    say("   account, click 'Create API key' and paste it here. (Free; no card needed.)")
    cfg.ai.gemini_api_key = _ask("Gemini API key:", cfg.ai.gemini_api_key)
    if cfg.ai.gemini_api_key:
        err = _check_gemini(cfg)
        say("   ✔ Gemini works" if not err else f"   ✘ Gemini didn't work: {err}")
    from .llm import LLM

    if "ollama" in LLM(cfg.ai).available():
        say(f"   ✔ Ollama is running on this laptop; it's the backup writer ({cfg.ai.ollama_model}).")
    else:
        say("   Optional backup that works offline: install Ollama (see the README), then run "
            f"`ollama pull {cfg.ai.ollama_model}`.")

    say("\n3. Stock footage (the videos look far better with it).")
    say("   Pexels: sign up free at https://www.pexels.com/api/ and copy 'Your API Key'.")
    cfg.footage.pexels_api_key = _ask("Pexels API key:", cfg.footage.pexels_api_key)
    if cfg.footage.pexels_api_key:
        err = _check_get("https://api.pexels.com/videos/search", params={"query": "ocean", "per_page": 1},
                         headers={"Authorization": cfg.footage.pexels_api_key})
        say("   ✔ Pexels works" if not err else f"   ✘ Pexels didn't work: {err}")
    say("   Pixabay (more choice): sign up free at https://pixabay.com, then open https://pixabay.com/api/docs/")
    say("   and copy the key shown under 'Parameters'.")
    cfg.footage.pixabay_api_key = _ask("Pixabay API key:", cfg.footage.pixabay_api_key)
    if cfg.footage.pixabay_api_key:
        err = _check_get("https://pixabay.com/api/videos/",
                         params={"key": cfg.footage.pixabay_api_key, "q": "ocean", "per_page": 3})
        say("   ✔ Pixabay works" if not err else f"   ✘ Pixabay didn't work: {err}")

    say("\n4. Telegram, to approve videos from your phone.")
    say("   In Telegram, search for @BotFather, send /newbot and follow the steps. It gives you a token")
    say("   like 123456:ABC-DEF…; paste it here.")
    token = _ask("Bot token:", cfg.telegram.bot_token)
    if token:
        from .telegram import Telegram, TelegramError, find_chat_id

        try:
            me = Telegram(token).me()
            say(f"   ✔ Found your bot @{me.get('username')}")
            new_bot = token != cfg.telegram.bot_token
            cfg.telegram.bot_token = token
            if not cfg.telegram.chat_id or new_bot or args.relink:
                say(f"   Now open https://t.me/{me.get('username')} on your phone and press Start (or send 'hi').")
                say("   Waiting up to 3 minutes…")
                found = find_chat_id(token, 180, say)
                if found:
                    cfg.telegram.chat_id, name = found
                    Telegram(token, cfg.telegram.chat_id).send(f"✅ Hi {name}! Trend Clips is connected. New "
                                                               "videos will arrive here for your approval.")
                    say(f"   ✔ Connected to {name}'s chat")
                else:
                    say("   ✘ No message arrived. Run `trendclips setup --relink` to try again.")
        except TelegramError as e:
            say(f"   ✘ That token didn't work: {e}")

    say("\n5. YouTube (optional): trending videos as an extra trend source, and view counts for /stats.")
    say("   The README's YouTube section shows how to get a free API key; your channel ID starts with UC and is")
    say("   shown at https://www.youtube.com/account_advanced.")
    cfg.youtube.api_key = _ask("YouTube API key:", cfg.youtube.api_key)
    if cfg.youtube.api_key:
        err = _check_get("https://www.googleapis.com/youtube/v3/videos",
                         params={"part": "id", "chart": "mostPopular", "maxResults": 1, "key": cfg.youtube.api_key})
        say("   ✔ YouTube API key works" if not err else f"   ✘ YouTube didn't accept it: {err}")
    cfg.youtube.channel_id = _ask("Your channel ID (UC…):", cfg.youtube.channel_id, secret=False)

    say("\n6. Your @handle, shown faintly in the corner of each video (so re-uploads still point to you).")
    handle = _ask("Handle (e.g. @trendclipsuk):", cfg.video.handle, secret=False)
    cfg.video.handle = ("@" + handle.lstrip("@")) if handle else ""

    path = save_config(cfg)
    say(f"\nSaved your settings in {path}.")
    _restart_bot()
    say("\nNext: `trendclips demo` makes a test video, `trendclips make` makes a real one now, and the daily run "
        f"makes {cfg.video.per_run} at {cfg.schedule.daily_time}.")


# check ----------------------------------------------------------------------------------------------------------
def cmd_check(args) -> None:
    from . import assets, youtube
    from .llm import LLM
    from .pipeline import AUDIO_EXT, Paths
    from .render import ffmpeg_ok
    from .telegram import Telegram, TelegramError
    from .voice import Voice

    cfg = load_config()
    paths = Paths()
    ok_all = True

    def line(ok: bool | None, text: str):
        nonlocal ok_all
        mark = "✔" if ok else ("•" if ok is None else "✘")
        ok_all &= ok is not False
        say(f"  {mark} {text}")

    ok, msg = ffmpeg_ok()
    line(ok, msg)
    if cfg.video.style == "duo":
        from .pipeline import get_cast

        try:
            cast = get_cast(cfg, paths)
            line(True, "Format: two characters, " + " & ".join(f"{c.name} ({c.voice})" for c in cast))
        except (ValueError, RuntimeError) as e:
            line(False, f"Characters: {e}")
    else:
        line(True, "Format: one narrator over footage (video.style = \"explainer\")")
    line(assets.fonts_ready(paths.fonts), "Caption fonts" + ("" if assets.fonts_ready(paths.fonts)
                                                             else " missing: run trendclips setup"))
    line(Voice(paths.kokoro).ready(), "Voice model" + ("" if Voice(paths.kokoro).ready() else
                                                       " missing: run trendclips setup"))
    writers = LLM(cfg.ai).available()
    if writers and args.deep:
        err = _check_gemini(cfg) if "gemini" in writers else None
        line(not err, f"AI writer: {', '.join(writers)}" + (f" (Gemini: {err})" if err else ", Gemini answered"))
    else:
        line(bool(writers), f"AI writer: {', '.join(writers)}" if writers else
             "No AI writer: add a free Gemini key with `trendclips setup`, or install Ollama")
    sources = [n for n, k in (("Pexels", cfg.footage.pexels_api_key), ("Pixabay", cfg.footage.pixabay_api_key)) if k]
    line(True if sources else None, f"Stock footage: {', '.join(sources)}" if sources else
         "Stock footage: none yet; videos use animated backgrounds (add a free Pexels key with `trendclips setup`)")
    tg = Telegram(cfg.telegram.bot_token, cfg.telegram.chat_id)
    if tg.ready:
        try:
            line(True, f"Telegram: @{tg.me().get('username')}")
        except TelegramError as e:
            line(False, f"Telegram: {e}")
    else:
        line(None, "Telegram: not set up (videos are only saved to the folder)")
    yt = []
    if cfg.youtube.api_key:
        yt.append("trends")
    if cfg.youtube.channel_id or youtube.connected(paths.home):
        yt.append("stats")
    if cfg.youtube.upload:
        yt.append("uploads " + ("connected" if youtube.connected(paths.home) else "ON BUT NOT CONNECTED: run "
                                "trendclips youtube-login"))
    line(None if not yt else "NOT CONNECTED" not in " ".join(yt), "YouTube: " + (", ".join(yt) or "not set up"))
    tracks = [p for p in paths.music.rglob("*") if p.suffix.lower() in AUDIO_EXT] if paths.music.exists() else []
    line(True if tracks else None, f"Music: {len(tracks)} tracks" if tracks else
         f"Music: none; add royalty-free tracks to {paths.music} (see the README)")
    timer = _systemctl("is-active", "trendclips-run.timer")
    line(True if timer == "active" else None,
         f"Daily run at {cfg.schedule.daily_time}: " + ("on" if timer == "active" else "off (trendclips schedule on)"))
    say(f"  • Videos are saved in {cfg.output_dir}")
    if not ok_all:
        sys.exit(1)


# making videos ----------------------------------------------------------------------------------------------------
def _progress(msg: str) -> None:
    say(f"{time.strftime('%H:%M:%S')}  {msg}")


def cmd_demo(args) -> None:
    from .pipeline import make_demo

    cfg, store, paths = _objects()
    who = " with " + " and ".join(cfg.duo.characters) if cfg.video.style == "duo" else ""
    say(f"Making a test video about octopuses{who} (no AI writer needed)…")
    p = make_demo(cfg, store, paths, _progress)
    say(f"\n✔ Done in {p.seconds_taken / 60:.1f} minutes: {p.path}")
    say(f"  {p.duration:.0f} seconds long, {p.stock_shots} of {p.shots} shots from stock footage, voices: {p.voice}.")
    _open(p.path)


def cmd_make(args) -> None:
    from .pipeline import make_videos

    cfg, store, paths = _objects()
    made = make_videos(cfg, store, paths, args.count, topic=args.topic or "", send=not args.no_send,
                       progress=_progress)
    if made:
        say(f"\n✔ Made {len(made)} video(s). They're in {cfg.output_dir}")
        if len(made) == 1 and args.open:
            _open(Path(store.video(made[0])["path"]))
    else:
        say("\nNo videos were made this time (see the messages above).")
        sys.exit(1)


def cmd_run(args) -> None:
    """The daily job: make today's videos, refresh YouTube stats, and tell you if something went wrong."""
    from . import youtube
    from .pipeline import Busy, make_videos
    from .telegram import Telegram

    cfg, store, paths = _objects()
    log = logging.getLogger("trendclips.run")
    tg = Telegram(cfg.telegram.bot_token, cfg.telegram.chat_id)
    try:
        updated = youtube.update_stats(cfg, store, paths.home)
        if updated:
            log.info("Updated stats for %d videos", updated)
    except Exception as e:
        log.warning("Couldn't update YouTube stats: %s", e)
    try:
        made = make_videos(cfg, store, paths, cfg.video.per_run, progress=lambda m: (log.info(m), _progress(m)))
        if not made and tg.ready:
            tg.send("😕 No video today: nothing trending passed the checks. Send /trends to look, or /make <topic>.")
    except Busy:
        log.info("Another video job was already running")
    except Exception as e:
        log.exception("Daily run failed")
        if tg.ready:
            tg.send(f"⚠️ Today's videos failed: {e}")
        sys.exit(1)


def cmd_trends(args) -> None:
    from .trends import TrendScanner

    cfg, store, _ = _objects()
    trends, skipped = TrendScanner(cfg).scan(store.recent_topic_keys(cfg.trends.repeat_after_days))
    say("Trending now (best first):")
    for i, t in enumerate(trends[:args.limit], 1):
        say(f"{i:3d}. {t.title}  [{', '.join(t.sources)}; score {t.score:.2f}]")
        if t.context:
            say(f"       {t.context[0][:110]}")
    if skipped:
        say("\nSkipped:")
        for t, reason in skipped[:args.limit]:
            say(f"     {t.title}: {reason}")


def cmd_bot(args) -> None:
    from .telegram import Bot

    cfg, store, paths = _objects()
    if not (cfg.telegram.bot_token and cfg.telegram.chat_id):
        say("Telegram isn't set up yet, so there's nothing to listen to. Run `trendclips setup`.")
        return
    Bot(cfg, store, paths).run_forever()


def cmd_youtube_login(args) -> None:
    from . import youtube
    from .pipeline import Paths

    paths = Paths()
    channel = youtube.login(paths.home)
    say(f"✔ Connected to YouTube channel: {channel}")
    cfg = load_config()
    if not cfg.youtube.upload:
        cfg.youtube.upload = True
        save_config(cfg)
        say("  Approved videos will now be uploaded automatically. (Set youtube.upload = false to stop.)")
    _restart_bot()


def cmd_stats(args) -> None:
    from . import youtube
    from .telegram import stats_text

    cfg, store, paths = _objects()
    try:
        n = youtube.update_stats(cfg, store, paths.home)
        if n:
            say(f"Updated YouTube numbers for {n} videos.")
    except Exception as e:
        say(f"(Couldn't refresh YouTube numbers: {e})")
    say(stats_text(store))
    say("\nRecent videos:")
    for v in store.videos(limit=args.limit):
        views = f"{v['views']:,} views" if v.get("views") is not None else ""
        say(f"  #{v['id']:<4} {time.strftime('%d %b', time.localtime(v['created']))}  {v['status']:<8} "
            f"{v['category']:<13} {v['title'][:60]}  {views}")


# scheduling (systemd user units) --------------------------------------------------------------------------------
def _systemctl(*args: str) -> str:
    if not shutil.which("systemctl"):
        return ""
    p = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=30)
    return p.stdout.strip()


def _exe() -> str:
    exe = Path(sys.executable).parent / "trendclips"
    return str(exe if exe.exists() else (shutil.which("trendclips") or exe))


def write_units(daily_time: str) -> None:
    UNIT_DIR.mkdir(parents=True, exist_ok=True)
    exe = _exe()
    (UNIT_DIR / "trendclips-bot.service").write_text(f"""[Unit]
Description=Trend Clips Telegram bot (approve videos from your phone)
After=network-online.target

[Service]
ExecStart="{exe}" bot
Restart=on-failure
RestartSec=30
Nice=5

[Install]
WantedBy=default.target
""")
    (UNIT_DIR / "trendclips-run.service").write_text(f"""[Unit]
Description=Trend Clips: make today's videos
After=network-online.target

[Service]
Type=oneshot
ExecStart="{exe}" run
Nice=10
TimeoutStartSec=3h
""")
    (UNIT_DIR / "trendclips-run.timer").write_text(f"""[Unit]
Description=Make Trend Clips videos every day at {daily_time}

[Timer]
OnCalendar=*-*-* {daily_time}:00
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
""")


def cmd_schedule(args) -> None:
    cfg = load_config()
    if not shutil.which("systemctl"):
        sys.exit("This computer has no systemd, so add `trendclips run` to cron instead (see the README).")
    when = (args.when or "on").lower()
    if when == "off":
        _systemctl("disable", "--now", "trendclips-run.timer")
        say("Daily videos are off. The Telegram bot still runs; turn the daily run back on with: "
            "trendclips schedule on")
        return
    if when != "on":
        cfg.schedule.daily_time = when if len(when) == 5 else f"0{when}"
        save_config(cfg)  # validates the time
    write_units(cfg.schedule.daily_time)
    _systemctl("daemon-reload")
    _systemctl("enable", "--now", "trendclips-run.timer")
    _systemctl("enable", "trendclips-bot.service")
    _restart_bot()
    say(f"✔ Daily videos at {cfg.schedule.daily_time} ({cfg.video.per_run} per day). If the laptop is off or "
        "asleep then, they're made as soon as it's back on.")


def _restart_bot() -> None:
    if (UNIT_DIR / "trendclips-bot.service").exists() and shutil.which("systemctl"):
        _systemctl("restart", "trendclips-bot.service")


def _open(path: Path) -> None:
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        opener = shutil.which("xdg-open")
        if opener:
            subprocess.Popen([opener, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="trendclips", description="Finds what's trending, makes short videos about "
                                 "it with free AI, and sends them to your phone to approve.")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("setup", help="download the AI models and enter your free keys (re-run any time)")
    p.add_argument("--downloads-only", action="store_true", help="only download fonts and models")
    p.add_argument("--relink", action="store_true", help="connect Telegram to your chat again")
    p.set_defaults(func=cmd_setup)
    p = sub.add_parser("check", help="show what's set up and working")
    p.add_argument("--deep", action="store_true", help="also test that the AI writer answers")
    p.set_defaults(func=cmd_check)
    sub.add_parser("demo", help="make a test video (no AI writer needed)").set_defaults(func=cmd_demo)
    p = sub.add_parser("make", help="make videos about what's trending now")
    p.add_argument("--count", type=int, default=1)
    p.add_argument("--topic", help="make a video about this instead of a trend")
    p.add_argument("--no-send", action="store_true", help="don't send to Telegram")
    p.add_argument("--open", action="store_true", help="play the video when it's done")
    p.set_defaults(func=cmd_make)
    sub.add_parser("run", help="the daily job (what the schedule runs)").set_defaults(func=cmd_run)
    p = sub.add_parser("trends", help="list what's trending right now")
    p.add_argument("--limit", type=int, default=25)
    p.set_defaults(func=cmd_trends)
    sub.add_parser("bot", help="listen for your Telegram taps and commands").set_defaults(func=cmd_bot)
    sub.add_parser("youtube-login", help="connect YouTube so approved videos upload automatically"
                   ).set_defaults(func=cmd_youtube_login)
    p = sub.add_parser("stats", help="how your videos are doing")
    p.add_argument("--limit", type=int, default=15)
    p.set_defaults(func=cmd_stats)
    p = sub.add_parser("schedule", help="daily videos: `schedule 18:00`, `schedule off` or `schedule on`")
    p.add_argument("when", nargs="?", help="a time like 18:00, or on/off")
    p.set_defaults(func=cmd_schedule)

    args = ap.parse_args(argv)
    setup_logging(args.verbose)
    if args.command != "setup":
        _ensure_config()
    try:
        args.func(args)
    except KeyboardInterrupt:
        sys.exit("\nStopped.")
    except (ValueError, FileNotFoundError, RuntimeError) as e:
        logging.getLogger("trendclips").info("Error: %s", e)
        sys.exit(f"Error: {e}")


if __name__ == "__main__":
    main()

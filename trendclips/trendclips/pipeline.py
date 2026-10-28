"""From trend to finished video: scan, pick, research, write, voice, footage, render, then send it to your phone."""
from __future__ import annotations

import datetime as dt
import fcntl
import logging
import random
import re
import shutil
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .captions import build_ass
from .config import Config, home_dir
from .footage import Footage
from .llm import LLM, LLMError
from .render import RenderError, Shot, finish, plan_shots, probe, render_shots
from .research import Image, Researcher
from .sfx import make_all
from .store import Store
from .themes import theme_for
from .trends import Trend, TrendScanner
from .voice import Timer, Voice, write_wav
from .writer import Pick, Script, Writer

log = logging.getLogger(__name__)

AUDIO_EXT = (".mp3", ".m4a", ".wav", ".ogg", ".flac", ".aac", ".opus")


class Paths:
    def __init__(self, home: Path | None = None):
        self.home = Path(home or home_dir())
        self.assets = self.home / "assets"
        self.fonts = self.assets / "fonts"
        self.kokoro = self.assets / "kokoro"
        self.whisper = self.assets / "whisper"
        self.clip_model = self.assets / "clip"
        self.sfx = self.assets / "sfx"
        self.cache = self.home / "cache"
        self.work = self.home / "work"
        self.music = self.home / "music"
        self.db = self.home / "trendclips.db"
        self.lock = self.home / "job.lock"


@dataclass
class Produced:
    path: Path
    duration: float
    seconds_taken: float
    voice: str
    shots: int
    stock_shots: int


class Busy(RuntimeError):
    pass


@contextmanager
def job_lock(paths: Paths):
    """One video job at a time: the daily run and a /make from your phone shouldn't fight over the processor."""
    paths.home.mkdir(parents=True, exist_ok=True)
    with open(paths.lock, "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Busy("Another video is being made right now; try again when it's done.") from None
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def slug(text: str, limit: int = 60) -> str:
    s = re.sub(r"\s+", " ", re.sub(r"[^\w\s-]", "", text)).strip()
    if len(s) > limit:
        s = s[:limit].rsplit(" ", 1)[0]  # end on a whole word
    return s or "video"


def pick_music(folder: Path, mood: str, last: str = "") -> Path | None:
    """A random track from music/<mood>/ if that folder has any, otherwise from anywhere in music/."""
    if not folder.exists():
        return None
    mood_dir = folder / mood
    pool = [p for p in mood_dir.rglob("*") if p.suffix.lower() in AUDIO_EXT] if mood_dir.is_dir() else []
    if not pool:
        pool = [p for p in folder.rglob("*") if p.suffix.lower() in AUDIO_EXT]
    if len(pool) > 1:
        pool = [p for p in pool if str(p) != last] or pool
    return random.choice(pool) if pool else None


def prune(paths: Paths, days: float = 7) -> None:
    """Deletes downloaded stock clips and leftovers that haven't been used for a week."""
    cutoff = time.time() - days * 86400
    for sub in ("clips", "previews", "search", "images"):
        folder = paths.cache / sub
        if folder.exists():
            for f in folder.iterdir():
                if f.is_file() and f.stat().st_mtime < cutoff:
                    f.unlink(missing_ok=True)
    if paths.work.exists():
        for d in paths.work.iterdir():
            if d.is_dir() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)


class Studio:
    """Turns a script into a finished video file."""

    def __init__(self, cfg: Config, store: Store, paths: Paths):
        self.cfg, self.store, self.paths = cfg, store, paths
        self.voice = Voice(paths.kokoro)
        self.timer = Timer(paths.whisper)

    def produce(self, script: Script, image: Image | None = None, progress=lambda msg: None) -> Produced:
        t0 = time.time()
        theme = theme_for(script.category)
        voice = theme.voice if self.cfg.video.voice == "auto" else self.cfg.video.voice
        work = self.paths.work / f"{int(t0)}-{slug(script.title, 30).replace(' ', '-')}"
        work.mkdir(parents=True, exist_ok=True)
        texts = [s.text for s in script.scenes]

        progress("recording the voiceover")
        track = self.voice.track(texts, voice, self.cfg.video.voice_speed)
        write_wav(work / "voice.wav", track.audio)
        progress("timing the captions")
        words = self.timer.words(track, texts, [s.highlight for s in script.scenes])
        duration = round(track.duration + 0.45, 3)

        progress("finding footage")
        v = self.cfg.video
        footage = Footage(self.cfg.footage.pexels_api_key, self.cfg.footage.pixabay_api_key, self.paths.cache,
                          self.paths.clip_model, v.smart_footage, self.store.recently_used_clips())
        shots = []
        for n, (si, a, b, first) in enumerate(plan_shots(track.spans, duration)):
            if n == 0 and image:
                shots.append(Shot(a, b, "image", image.path, scene_start=True))
                continue
            scene = script.scenes[si]
            clip = footage.choose(scene.visual, b - a, f"{scene.visual}") if footage.enabled else None
            if clip and clip.path:
                try:
                    _, _, src = probe(clip.path)
                    shots.append(Shot(a, b, "video", clip.path, src, first, zoom_out=n % 2 == 1))
                    continue
                except RenderError:
                    pass
            shots.append(Shot(a, b, "background", scene_start=first, zoom_out=n % 2 == 1))

        (work / "captions.ass").write_text(build_ass(words, theme, duration, script.hook_text, v.handle))
        fonts = work / "fonts"
        if not fonts.exists():
            fonts.symlink_to(self.paths.fonts, target_is_directory=True)
        sfx = make_all(self.paths.sfx)
        music = pick_music(self.paths.music, script.mood, self.store.get("last_music", ""))
        whooshes = [max(0.0, s.start - 0.33) for s in shots[1:] if s.scene_start]

        progress(f"rendering {len(shots)} shots")
        segs = render_shots(shots, theme, work)
        progress("putting it all together")
        out_dir = self.cfg.output_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{dt.date.today():%Y-%m-%d} {slug(script.title)}.mp4"
        if out.exists():
            out = out.with_name(f"{out.stem} {int(t0) % 10000}.mp4")
        finish(work, segs, duration, theme, music, v.music_volume, sfx, whooshes, out, v.preset)
        out.with_suffix(".txt").write_text(post_text(script, long=True) + "\n")
        self.store.mark_clips_used(sorted(footage.used))
        if music:
            self.store.set("last_music", str(music))
        shutil.rmtree(work, ignore_errors=True)
        stock = sum(s.kind == "video" for s in shots)
        return Produced(out, duration, time.time() - t0, voice, len(shots), stock)


def post_text(script: Script, long: bool = False) -> str:
    """The caption to paste when posting. The long version (saved next to the video) adds sources and credits."""
    tags = " ".join(script.hashtags)
    text = f"{script.title}\n\n{script.description}\n\n{tags}".strip()
    if long:
        if script.credits:
            text += "\n\n" + "\n".join(script.credits)
        if script.sources:
            text += "\n\nSources:\n" + "\n".join(script.sources)
    elif script.credits:
        text += "\n\n" + "\n".join(script.credits)
    return text


def make_videos(cfg: Config, store: Store, paths: Paths, count: int, topic: str = "", send: bool = True,
                progress=print) -> list[int]:
    """Makes up to `count` videos about what's trending (or about `topic`). Returns the new video ids."""
    from .telegram import Telegram, send_for_approval

    with job_lock(paths):
        prune(paths)
        llm = LLM(cfg.ai)
        writer = Writer(llm, cfg.ai.audience, cfg.video.target_seconds, cfg.video.voice_speed)
        if topic:
            trend = Trend(topic, "you", 1.0, sources=["you"])
            picks = [Pick(trend, "news", topic)]
        else:
            progress("Checking what's trending…")
            recent = store.recent_topic_keys(cfg.trends.repeat_after_days)
            trends, skipped = TrendScanner(cfg).scan(recent)
            progress(f"Found {len(trends)} usable trends ({len(skipped)} skipped as sensitive or already covered).")
            if not trends:
                return []
            picks = writer.pick(trends, count, store.category_performance())
            if picks:
                progress("Picked: " + "; ".join(p.trend.title for p in picks[:count]))
            else:
                progress("No trend was worth a video today.")
        researcher = Researcher(paths.cache / "images", cfg.video.allow_share_alike_images)
        studio = Studio(cfg, store, paths)
        tg = Telegram(cfg.telegram.bot_token, cfg.telegram.chat_id) if send else None
        made: list[int] = []
        for pick in picks:
            if len(made) >= count:
                break
            title = pick.trend.title
            try:
                progress(f"[{title}] researching")
                research = researcher.gather(pick.trend)
                if len(research.as_text()) < 150:
                    progress(f"[{title}] not enough solid facts to make a video; skipping")
                    continue
                progress(f"[{title}] writing the script")
                script = writer.write(pick, research)
                produced = studio.produce(script, research.image, lambda m, t=title: progress(f"[{t}] {m}"))
            except Exception as e:  # one bad video mustn't stop the rest of an unattended run
                log.exception("Video about %s failed", title)
                progress(f"[{title}] failed: {e}")
                if isinstance(e, LLMError) and "No AI writer" in str(e):
                    raise
                continue
            meta = {"script": script.to_dict(), "duration": produced.duration, "voice": produced.voice,
                    "writer": llm.used, "sources": research.sources, "trend_sources": pick.trend.sources,
                    "stock_shots": produced.stock_shots, "shots": produced.shots}
            vid = store.add_video(pick.trend.title, pick.trend.key, "made", title=script.title,
                                  category=script.category, path=produced.path, meta=meta)
            made.append(vid)
            progress(f"[{title}] done in {produced.seconds_taken / 60:.1f} min: {produced.path}")
            if tg and tg.ready:
                try:
                    send_for_approval(tg, store, store.video(vid))
                    progress(f"[{title}] sent to Telegram for your approval")
                except Exception as e:
                    progress(f"[{title}] couldn't send to Telegram ({type(e).__name__}); the file is saved")
        return made


def demo_script() -> Script:
    import json

    return Script.from_dict(json.loads((Path(__file__).parent / "demo_script.json").read_text()))


def make_demo(cfg: Config, store: Store, paths: Paths, progress=print) -> Produced:
    with job_lock(paths):
        return Studio(cfg, store, paths).produce(demo_script(), None, lambda m: progress(f"[demo] {m}"))

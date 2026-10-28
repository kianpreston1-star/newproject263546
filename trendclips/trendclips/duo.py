"""Two-character videos: who's on screen when, mouths moving in time with the voice, a quick rise into view when a
character starts talking, the satisfying background loop, and the photo of the subject at the start."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .characters import SPRITE_H, SPRITE_W, Character
from .render import FPS, H, W, Shot
from .voice import SR, Track

CHAR_Y = H - SPRITE_H + 110  # partly below the bottom edge, like a presenter standing in front of the screen
CHAR_X = (-40, W - SPRITE_W + 40)  # first character on the left, second on the right
CAPTION_Y = 990  # between the photo card and the characters' heads
CARD_Y, CARD_MAX = 380, (720, 470)
SEGMENT = 6.0  # seconds of one background clip before cutting to the next
USER_BG_EXT = (".mp4", ".mkv", ".webm", ".mov")


@dataclass
class Overlay:
    """An extra picture stream laid over the video in the final pass."""
    args: list[str]  # FFmpeg input arguments
    prep: str  # filters applied to it first
    x: str
    y: str


def sprite_set(ch: Character, folder: Path) -> dict[str, Path]:
    """The character's frames plus rise-into-view frames and an empty frame for when they're quiet."""
    from PIL import Image

    folder.mkdir(parents=True, exist_ok=True)
    frames = dict(ch.images)
    talking = Image.open(ch.images["open"]).convert("RGBA")
    for name, drop in (("rise1", 300), ("rise2", 110), ("rise3", 25)):
        path = folder / f"{ch.id}_{name}.png"
        canvas = Image.new("RGBA", talking.size, (0, 0, 0, 0))
        canvas.paste(talking, (0, drop), talking)
        canvas.save(path)
        frames[name] = path
    blank = folder / f"{ch.id}_blank.png"
    Image.new("RGBA", talking.size, (0, 0, 0, 0)).save(blank)
    frames["blank"] = blank
    return frames


def frame_loudness(audio: np.ndarray, frames: int) -> np.ndarray:
    hop = SR // FPS
    out = np.zeros(frames, dtype=np.float32)
    for i in range(frames):
        seg = audio[i * hop:(i + 1) * hop]
        if len(seg):
            out[i] = float(np.sqrt(np.mean(seg * seg)))
    return out


def mouth_states(loud: np.ndarray, spans: list[tuple[float, float]], seed: int = 0) -> list[str]:
    """One state per video frame for one character: blank, rise1-3, open, closed or blink."""
    n = len(loud)
    states = ["blank"] * n
    rng = random.Random(seed)
    spans = sorted(spans)
    for i, (start, end) in enumerate(spans):
        a, b = int(start * FPS), min(n, math.ceil(end * FPS))
        if b <= a:
            continue
        line = loud[a:b]
        threshold = max(0.015, 0.3 * float(np.percentile(line, 90)))
        is_open = line > threshold
        smooth = is_open.copy()  # no single-frame flickers
        for k in range(1, len(line) - 1):
            smooth[k] = (int(is_open[k - 1]) + int(is_open[k]) + int(is_open[k + 1])) >= 2
        for k in range(a, b):
            states[k] = "open" if smooth[k - a] else "closed"
        # Rising into view, unless they were already on screen a moment ago.
        prev_end = spans[i - 1][1] if i else -1.0
        if start - prev_end > 0.6:
            for k, name in enumerate(("rise1", "rise2", "rise3")):
                if a + k < b:
                    states[a + k] = name
        else:  # same speaker again: stay on screen through the pause
            for k in range(int(prev_end * FPS), a):
                states[k] = "closed"
        # A blink now and then while the mouth is closed.
        k = a + rng.randint(30, 75)
        while k < b - 3:
            if states[k] == "closed" and states[k + 1] == "closed":
                states[k] = states[k + 1] = "blink"
                k += rng.randint(60, 110)
            else:
                k += 1
    if spans:  # whoever speaks last stays on screen until the end
        last_end = int(spans[-1][1] * FPS)
        if all(s == "blank" for s in states[last_end:]):
            for k in range(last_end, n):
                states[k] = "closed"
    return states


def concat_file(states: list[str], frames: dict[str, Path], path: Path) -> Path:
    """An FFmpeg concat list that shows each frame image for as long as it lasts: a tiny file instead of
    thousands of rendered frames."""
    runs: list[tuple[str, int]] = []
    for s in states:
        if runs and runs[-1][0] == s:
            runs[-1] = (s, runs[-1][1] + 1)
        else:
            runs.append((s, 1))
    lines = []
    for state, count in runs:
        lines += [f"file '{_quote(frames[state])}'", f"duration {count / FPS:.4f}"]
    if runs:
        lines.append(f"file '{_quote(frames[runs[-1][0]])}'")  # FFmpeg needs the last file repeated
    path.write_text("\n".join(lines) + "\n")
    return path


def _quote(p: Path) -> str:
    return str(p).replace("'", "'\\''")


def character_overlays(track: Track, speakers: list[str], cast: list[Character], duration: float,
                       work: Path) -> list[Overlay]:
    frames_total = math.ceil(duration * FPS)
    loud = frame_loudness(np.pad(track.audio, (0, max(0, frames_total * (SR // FPS) - len(track.audio)))),
                          frames_total)
    overlays = []
    for side, ch in enumerate(cast[:2]):
        spans = [span for span, who in zip(track.spans, speakers) if who == ch.id]
        states = mouth_states(loud, spans, seed=side)
        frames = sprite_set(ch, work / "sprites")
        lst = concat_file(states, frames, work / f"cast{side}.txt")
        # A gentle bob, out of step between the two, so they feel alive.
        overlays.append(Overlay(["-f", "concat", "-safe", "0", "-i", str(lst)], "format=rgba",
                                str(CHAR_X[side]), f"{CHAR_Y}+7*sin(2*PI*1.6*t+{side * 1.7:.1f})"))
    return overlays


def topic_card(image: Path, out: Path) -> Path:
    """The photo of the subject as a rounded card with a white border and a soft shadow."""
    from PIL import Image, ImageDraw, ImageFilter

    im = Image.open(image).convert("RGB")
    im.thumbnail(CARD_MAX)
    border, radius, pad = 12, 34, 30
    w, h = im.width + 2 * border, im.height + 2 * border
    canvas = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    shadow = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(shadow).rounded_rectangle((pad, pad + 10, pad + w, pad + h + 10), radius, fill=150)
    canvas.paste((0, 0, 0, 255), (0, 0), shadow.filter(ImageFilter.GaussianBlur(14)))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius, fill=255)
    card = Image.new("RGBA", (w, h), (255, 255, 255, 255))
    inner = Image.new("L", im.size, 0)
    ImageDraw.Draw(inner).rounded_rectangle((0, 0, im.width - 1, im.height - 1), radius - border, fill=255)
    card.paste(im, (border, border), inner)
    canvas.paste(card, (pad, pad), mask)
    canvas.save(out)
    return out


def card_overlay(card: Path, until: float) -> Overlay:
    fade_out = max(until - 0.3, 0.3)
    return Overlay(["-loop", "1", "-framerate", str(FPS), "-t", f"{until:.2f}", "-i", str(card)],
                   f"format=rgba,fade=t=in:st=0:d=0.25:alpha=1,fade=t=out:st={fade_out:.2f}:d=0.3:alpha=1",
                   "(W-w)/2", str(CARD_Y))


def background_plan(duration: float, clips: list[tuple[Path, float]], user: bool) -> list[Shot]:
    """Back-to-back background segments cycling through the clips, each starting somewhere new."""
    n = max(1, math.ceil(duration / SEGMENT))
    step = duration / n
    rng = random.Random(int(duration * 1000))
    shots = []
    for i in range(n):
        start, end = round(i * step, 3), round((i + 1) * step, 3)
        if not clips:
            shots.append(Shot(start, end, "background", zoom_out=i % 2 == 1))
            continue
        path, length = clips[i % len(clips)]
        # Long gameplay recordings: jump to a random point. Short stock clips: start near the beginning.
        offset = rng.uniform(0, max(0.0, length - step - 1)) if user or length > step * 3 else -1.0
        shots.append(Shot(start, end, "video", path, length, zoom_out=i % 2 == 1, offset=offset, dim=0.06))
    return shots


def user_backgrounds(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(p for p in folder.rglob("*") if p.suffix.lower() in USER_BG_EXT)

"""One-time downloads: caption fonts, the voice model, and the small AI models for caption timing and clip matching.
About 900 MB in total, all free, kept in ~/.trendclips/assets."""
from __future__ import annotations

import logging
from pathlib import Path

import requests

from .sfx import make_all
from .themes import FONT_URL, FONTS
from .voice import KOKORO_FILES

log = logging.getLogger(__name__)


def download(url: str, dest: Path, label: str, say=print) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, stream=True, timeout=60, headers={"User-Agent": "trendclips/0.1"}) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done, shown = 0, -10
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
                done += len(chunk)
                pct = int(done * 100 / total) if total else 0
                if total > 5_000_000 and pct >= shown + 10:
                    say(f"    {label}: {pct}% of {total / 1e6:.0f} MB")
                    shown = pct
    tmp.replace(dest)


def fonts_ready(folder: Path) -> bool:
    return all((folder / name).exists() for name in FONTS)


def ensure_fonts(folder: Path, say=print) -> None:
    for name, path in FONTS.items():
        if not (folder / name).exists():
            download(FONT_URL + path, folder / name, name, say)


def ensure_voice(folder: Path, say=print) -> None:
    for name, url in KOKORO_FILES.items():
        if not (folder / name).exists():
            download(url, folder / name, f"voice model ({name})", say)


def warm_whisper(folder: Path) -> None:
    from .voice import Timer

    Timer(folder)._whisper()


def warm_clip(folder: Path) -> None:
    from .footage import Ranker

    Ranker(folder)


def ensure_all(paths, say=print) -> list[str]:
    """Downloads whatever is missing. Returns problems (empty when everything is ready)."""
    problems = []
    steps = [
        ("caption fonts", lambda: ensure_fonts(paths.fonts, say)),
        ("voice model (about 350 MB)", lambda: ensure_voice(paths.kokoro, say)),
        ("caption timing model (about 150 MB)", lambda: warm_whisper(paths.whisper)),
        ("clip matching model (about 350 MB)", lambda: warm_clip(paths.clip_model)),
        ("sound effects", lambda: make_all(paths.sfx)),
    ]
    for label, step in steps:
        say(f"  • {label}…")
        try:
            step()
            say(f"  ✔ {label} ready")
        except Exception as e:
            problems.append(f"{label}: {type(e).__name__}: {e}")
            say(f"  ✘ {label} failed: {e}")
    return problems

"""Stock footage from Pexels and Pixabay (free for commercial use, no credit needed). For each scene it searches,
lets a small image-matching AI (CLIP) check which clip actually shows what's being said, and avoids clips used in
recent videos."""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import requests

log = logging.getLogger(__name__)


@dataclass
class Clip:
    source: str  # "pexels", "pixabay"
    id: str
    url: str  # the video file chosen for 1080x1920
    preview: str  # thumbnail image
    width: int
    height: int
    duration: float
    rank: int = 0  # position in the search results
    path: Path | None = None

    @property
    def key(self) -> tuple[str, str]:
        return (self.source, self.id)

    @property
    def portrait(self) -> bool:
        return self.height > self.width


def cover_scale(w: int, h: int) -> float:
    """How much a w x h video must be scaled to fill a 1080x1920 frame (above 1 means it gets blurrier)."""
    return max(1080 / max(w, 1), 1920 / max(h, 1))


def pick_rendition(files: list[dict]) -> dict | None:
    """The smallest file that fills the frame without upscaling (4K is wasted work for an older laptop)."""
    files = [f for f in files if f.get("width") and f.get("height") and f.get("link")]
    if not files:
        return None
    sharp = [f for f in files if cover_scale(f["width"], f["height"]) <= 1.05]
    if sharp:
        return min(sharp, key=lambda f: f["width"] * f["height"])
    return max(files, key=lambda f: f["width"] * f["height"])


def parse_pexels(data: dict) -> list[Clip]:
    out = []
    for i, v in enumerate(data.get("videos", [])):
        files = [{"width": f.get("width"), "height": f.get("height"), "link": f.get("link")}
                 for f in v.get("video_files", []) if f.get("file_type", "video/mp4") == "video/mp4"]
        best = pick_rendition(files)
        if best:
            out.append(Clip("pexels", str(v["id"]), best["link"], v.get("image", ""), best["width"],
                            best["height"], float(v.get("duration") or 0), i))
    return out


def parse_pixabay(data: dict) -> list[Clip]:
    out = []
    for i, hit in enumerate(data.get("hits", [])):
        sizes = hit.get("videos", {})
        files = [{"width": s.get("width"), "height": s.get("height"), "link": s.get("url")} for s in sizes.values()]
        best = pick_rendition(files)
        preview = next((s.get("thumbnail") for s in sizes.values() if s.get("thumbnail")), "")
        if best:
            out.append(Clip("pixabay", str(hit["id"]), best["link"], preview, best["width"], best["height"],
                            float(hit.get("duration") or 0), i))
    return out


class Ranker:
    """CLIP: scores how well each thumbnail matches a text description. Small enough for a laptop CPU."""

    def __init__(self, models_dir: Path):
        from fastembed import ImageEmbedding, TextEmbedding

        self.text = TextEmbedding("Qdrant/clip-ViT-B-32-text", cache_dir=str(models_dir))
        self.image = ImageEmbedding("Qdrant/clip-ViT-B-32-vision", cache_dir=str(models_dir))

    def scores(self, description: str, images: list[Path]) -> list[float]:
        t = np.array(list(self.text.embed([description])))[0]
        v = np.array(list(self.image.embed([str(p) for p in images])))
        t /= np.linalg.norm(t)
        v /= np.linalg.norm(v, axis=1, keepdims=True)
        return [float(x) for x in v @ t]


class Footage:
    def __init__(self, pexels_key: str, pixabay_key: str, cache_dir: Path, models_dir: Path | None = None,
                 smart: bool = True, avoid: set | None = None, session: requests.Session | None = None):
        self.keys = {"pexels": pexels_key, "pixabay": pixabay_key}
        self.cache = Path(cache_dir)
        self.http = session or requests.Session()
        self.avoid = set(avoid or ())  # clips used in recent videos
        self.used: set[tuple[str, str]] = set()  # clips used in this video
        self.blocked: set[str] = set()  # sources that hit their rate limit this run
        self._ranker = None
        self._ranker_failed = not smart
        self.models_dir = models_dir

    @property
    def enabled(self) -> bool:
        return any(self.keys.values())

    def _cached_json(self, source: str, query: str, fetch) -> dict:
        name = hashlib.sha1(f"{source}:{query}".encode()).hexdigest()[:16]
        path = self.cache / "search" / f"{name}.json"
        if path.exists() and time.time() - path.stat().st_mtime < 86400:  # Pixabay asks for 24 h caching
            return json.loads(path.read_text())
        data = fetch()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
        return data

    def search(self, query: str) -> list[Clip]:
        clips = []
        if self.keys["pexels"] and "pexels" not in self.blocked:
            clips += self._search("pexels", query, lambda: self._get(
                "https://api.pexels.com/videos/search", headers={"Authorization": self.keys["pexels"]},
                params={"query": query, "orientation": "portrait", "size": "medium", "per_page": 12}), parse_pexels)
        if self.keys["pixabay"] and "pixabay" not in self.blocked:
            clips += self._search("pixabay", query, lambda: self._get(
                "https://pixabay.com/api/videos/", params={"key": self.keys["pixabay"], "q": query[:100],
                                                           "per_page": 12, "safesearch": "true"}), parse_pixabay)
        return clips

    def _search(self, source: str, query: str, fetch, parse) -> list[Clip]:
        try:
            return parse(self._cached_json(source, query, fetch))
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else 0
            if code in (401, 403, 429):
                self.blocked.add(source)
                log.warning("%s refused the search (HTTP %s); %s", source.title(), code,
                            "check its API key" if code != 429 else "rate limit, skipping it for this video")
            return []
        except (requests.RequestException, ValueError) as e:
            log.warning("%s search failed (%s)", source.title(), type(e).__name__)
            return []

    def _get(self, url: str, **kw) -> dict:
        r = self.http.get(url, timeout=20, **kw)
        r.raise_for_status()
        return r.json()

    def _rank(self, description: str, clips: list[Clip], need: float) -> list[Clip]:
        def base(c: Clip) -> float:
            return (0.15 * c.portrait + 0.1 * (c.duration >= need) + 0.1 * (cover_scale(c.width, c.height) <= 1.3)
                    + 0.1 * (1 - c.rank / 12))

        scores = {c.key: base(c) for c in clips}
        ranker = self._load_ranker()
        if ranker and len(clips) > 1:
            previews = [(c, self._preview(c)) for c in clips[:16]]
            previews = [(c, p) for c, p in previews if p]
            if previews:
                try:
                    for (c, _), s in zip(previews, ranker.scores(description, [p for _, p in previews])):
                        scores[c.key] += 4 * s  # CLIP similarities differ by a few hundredths; scale them up
                except Exception as e:
                    log.warning("Clip matching failed (%s); using search order", type(e).__name__)
        return sorted(clips, key=lambda c: -scores[c.key])

    def _load_ranker(self):
        if self._ranker is None and not self._ranker_failed:
            try:
                self._ranker = Ranker(self.models_dir or self.cache / "models")
            except Exception as e:
                self._ranker_failed = True
                log.warning("The clip-matching AI couldn't load (%s); using search order instead", type(e).__name__)
        return self._ranker

    def _preview(self, clip: Clip) -> Path | None:
        if not clip.preview:
            return None
        path = self.cache / "previews" / f"{clip.source}_{clip.id}.jpg"
        if not path.exists():
            try:
                r = self.http.get(clip.preview, timeout=15)
                r.raise_for_status()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(r.content)
            except requests.RequestException:
                return None
        return path

    def choose(self, query: str, need: float, description: str = "") -> Clip | None:
        """The best unused clip for a scene, downloaded. Broadens the search if the first one finds too little."""
        queries = [query]
        words = query.split()
        if len(words) > 2:
            queries.append(" ".join(words[-2:]))
        for q in queries:
            fresh = [c for c in self.search(q) if c.key not in self.used and c.key not in self.avoid]
            if not fresh:
                fresh = [c for c in self.search(q) if c.key not in self.used]  # reuse an older clip over nothing
            for clip in self._rank(description or q, fresh, need)[:3]:
                if self.download(clip):
                    self.used.add(clip.key)
                    return clip
        return None

    def download(self, clip: Clip) -> Path | None:
        path = self.cache / "clips" / f"{clip.source}_{clip.id}_{clip.width}x{clip.height}.mp4"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".part")
            try:
                with self.http.get(clip.url, stream=True, timeout=60) as r:
                    r.raise_for_status()
                    with open(tmp, "wb") as f:
                        for chunk in r.iter_content(1 << 16):
                            f.write(chunk)
                tmp.replace(path)
            except requests.RequestException as e:
                tmp.unlink(missing_ok=True)
                log.warning("Couldn't download a %s clip (%s)", clip.source, type(e).__name__)
                return None
        clip.path = path
        return path

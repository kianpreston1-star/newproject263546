"""Gathers the facts a script is allowed to use (news articles and Wikipedia), plus a photo of the subject when
Wikimedia Commons has one under a license that allows it."""
from __future__ import annotations

import html
import logging
import re
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

from .trends import USER_AGENT, Trend, similar, tokens

log = logging.getLogger(__name__)

BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
WIKI_API = "https://en.wikipedia.org/w/api.php"


@dataclass
class Image:
    path: Path
    credit: str  # e.g. "Photo: Jane Doe, CC BY 2.0, via Wikimedia Commons"


@dataclass
class Research:
    topic: str
    notes: list[str] = field(default_factory=list)  # facts the script may use
    sources: list[str] = field(default_factory=list)  # where they came from (shown when you approve a video)
    wiki_title: str = ""
    image: Image | None = None

    def as_text(self, limit: int = 6000) -> str:
        text = "\n".join(f"- {n}" for n in self.notes)
        return text[:limit]


class _TextExtractor(HTMLParser):
    """Collects an article's meta description and paragraph text, ignoring scripts, menus and footers."""

    def __init__(self):
        super().__init__()
        self.description = ""
        self.paragraphs: list[str] = []
        self._skip = 0
        self._in_p = False
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta" and (a.get("property") == "og:description" or a.get("name") == "description"):
            self.description = self.description or (a.get("content") or "")
        elif tag in ("script", "style", "nav", "footer", "aside", "noscript", "form"):
            self._skip += 1
        elif tag == "p" and not self._skip:
            self._in_p, self._buf = True, []

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "footer", "aside", "noscript", "form"):
            self._skip = max(0, self._skip - 1)
        elif tag == "p" and self._in_p:
            self._in_p = False
            text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            if len(text) >= 60:
                self.paragraphs.append(text)

    def handle_data(self, data):
        if self._in_p and not self._skip:
            self._buf.append(data)


def article_text(page_html: str, limit: int = 1800) -> str:
    p = _TextExtractor()
    try:
        p.feed(page_html)
    except Exception:  # broken HTML: keep whatever was read
        pass
    parts = [html.unescape(p.description)] if p.description else []
    for para in p.paragraphs:
        if sum(len(x) for x in parts) > limit:
            break
        if not re.search(r"cookie|subscribe|newsletter|sign up|all rights reserved|advertisement", para, re.I):
            parts.append(html.unescape(para))
    return " ".join(parts)[:limit]


ALLOWED_LICENSES = re.compile(r"^(public domain|pd\b|cc0|cc[ -]by[ -]\d)", re.I)
SHARE_ALIKE = re.compile(r"^cc[ -]by[ -]sa[ -]\d", re.I)


def license_ok(short_name: str, allow_share_alike: bool) -> bool:
    name = (short_name or "").strip()
    return bool(ALLOWED_LICENSES.match(name) or (allow_share_alike and SHARE_ALIKE.match(name)))


class Researcher:
    def __init__(self, cache_dir: Path, allow_share_alike: bool = False, session: requests.Session | None = None):
        self.cache = Path(cache_dir)
        self.allow_sa = allow_share_alike
        self.http = session or requests.Session()
        self.http.headers["User-Agent"] = USER_AGENT

    def gather(self, trend: Trend) -> Research:
        res = Research(trend.title)
        res.notes += [c for c in trend.context[:8]]
        res.sources += [link for link in trend.links if "wikipedia.org" not in link][:3]
        for url in [u for u in trend.links if _is_article(u)][:2]:
            text = self._fetch_article(url)
            if text:
                res.notes.append(f"From {urlparse(url).netloc}: {text}")
        # A topic you typed yourself takes Wikipedia's best match ("why the clocks go back" finds "Daylight saving
        # time"); a trend has to match by name, so a vague trend doesn't pick up an unrelated article.
        title = trend.wiki_title or self._find_wiki(trend, strict=trend.source != "you")
        if title:
            summary = self._wiki_summary(title)
            if summary:
                res.wiki_title = title
                if not any(summary[-120:] in n for n in res.notes):
                    res.notes.append(f"Wikipedia ({title}): {summary}")
                res.sources.append(f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}")
                res.image = self._wiki_image(title)
        return res

    def _wiki_get(self, url: str, **params) -> requests.Response:
        """Wikipedia asks busy clients to slow down (HTTP 429); wait as asked, once, rather than lose the facts."""
        r = self.http.get(url, params=params or None, timeout=15)
        if r.status_code == 429:
            time.sleep(min(float(r.headers.get("Retry-After", 3) or 3), 10))
            r = self.http.get(url, params=params or None, timeout=15)
        return r

    def _fetch_article(self, url: str) -> str:
        try:
            r = self.http.get(url, headers={"User-Agent": BROWSER_UA, "Accept-Language": "en-GB,en;q=0.9"},
                              timeout=12)
            if not r.ok or "html" not in r.headers.get("content-type", ""):
                return ""
            return article_text(r.text)
        except requests.RequestException:
            return ""

    def _find_wiki(self, trend: Trend, strict: bool = True) -> str:
        try:
            r = self._wiki_get(WIKI_API, action="query", list="search", srsearch=trend.title, srlimit=3, format="json")
            r.raise_for_status()
            for hit in r.json().get("query", {}).get("search", []):
                if not strict or similar(tokens(hit["title"]), tokens(trend.title)):
                    return hit["title"]
        except (requests.RequestException, ValueError, KeyError):
            pass
        return ""

    def _wiki_summary(self, title: str) -> str:
        try:
            r = self._wiki_get("https://en.wikipedia.org/api/rest_v1/page/summary/" + title.replace(" ", "_"))
            if not r.ok:
                return ""
            d = r.json()
            if d.get("type") == "disambiguation":
                return ""
            desc = d.get("description", "")
            return (f"{desc}. " if desc else "") + d.get("extract", "")
        except (requests.RequestException, ValueError):
            return ""

    def _wiki_image(self, title: str) -> Image | None:
        """The article's main photo, only if it's on Commons under a license that allows reuse with credit."""
        try:
            r = self._wiki_get(WIKI_API, action="query", prop="pageimages", piprop="name", titles=title, format="json")
            pages = r.json().get("query", {}).get("pages", {})
            name = next((p.get("pageimage") for p in pages.values() if p.get("pageimage")), None)
            if not name:
                return None
            r = self._wiki_get(WIKI_API, action="query", titles=f"File:{name}", prop="imageinfo",
                               iiprop="url|extmetadata|size", iiurlwidth=1600, format="json")
            page = next(iter(r.json().get("query", {}).get("pages", {}).values()))
            if page.get("imagerepository") != "shared":  # files kept on Wikipedia itself are usually non-free
                return None
            info = page["imageinfo"][0]
            meta = info.get("extmetadata", {})
            lic = meta.get("LicenseShortName", {}).get("value", "")
            if not license_ok(lic, self.allow_sa):
                log.info("Skipping the Wikipedia photo of %s: its license (%s) isn't on the allowed list", title, lic)
                return None
            if min(info.get("width", 0), info.get("height", 0)) < 500 or name.lower().endswith((".svg", ".gif")):
                return None
            artist = re.sub(r"<[^>]+>", "", html.unescape(meta.get("Artist", {}).get("value", ""))).strip()
            credit = f"Photo: {artist + ', ' if artist else ''}{lic}, via Wikimedia Commons"
            url = info.get("thumburl") or info["url"]
            self.cache.mkdir(parents=True, exist_ok=True)
            stem = re.sub(r"[^\w.-]", "_", unquote(Path(urlparse(url).path).stem))[:80]
            path = self.cache / f"wiki_{stem}.jpg"
            if not path.exists():
                img = self.http.get(url, timeout=30)
                img.raise_for_status()
                if not save_jpeg(img.content, path):
                    return None
            return Image(path, credit)
        except (requests.RequestException, ValueError, KeyError, IndexError, StopIteration):
            return None


def save_jpeg(data: bytes, path: Path) -> bool:
    """Checks the download really is a photo (not an error page) and stores it as a plain JPEG FFmpeg can read."""
    import io

    from PIL import Image as PILImage, UnidentifiedImageError

    try:
        with PILImage.open(io.BytesIO(data)) as im:
            im = im.convert("RGB")
            im.thumbnail((1600, 1600))
            if min(im.size) < 400:
                return False
            path.parent.mkdir(parents=True, exist_ok=True)
            im.save(path, "JPEG", quality=90)
        return True
    except (UnidentifiedImageError, OSError, ValueError):
        return False


def _is_article(url: str) -> bool:
    host = urlparse(url).netloc
    return bool(host) and not any(s in host for s in ("wikipedia.org", "reddit.com", "youtu", "google."))

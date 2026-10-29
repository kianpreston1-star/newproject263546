"""Finds what's trending right now: Google Trends, Wikipedia pages whose views just spiked, top Reddit posts and
YouTube's trending list. The same topic showing up in several places is merged and ranked higher."""
from __future__ import annotations

import datetime as dt
import html
import logging
import math
import re
import statistics
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import requests

from .config import Config

log = logging.getLogger(__name__)

USER_AGENT = "trendclips/0.1 (+https://github.com/kianpreston1-star/newproject263546)"
HT = "{https://trends.google.com/trending/rss}"
SOURCE_WEIGHT = {"google": 1.0, "wikipedia": 0.9, "youtube": 0.8, "reddit": 0.7}

STOPWORDS = set("""a an the and or of to in on at for with from by is are was were be been it its this that these
those as vs v what why how who when where new news today live latest update after over into about your you our we
their his her they them up out just than then not no yes will can may might all more most video official""".split())

# Topics that are cruel to cover with stock footage and a cheerful voice, that advertisers avoid, or that invite
# misinformation strikes. The AI picker filters more subtly as well; these words catch the obvious ones.
SENSITIVE = {
    "a death or tragedy": r"died|dies|dead|death|deaths|killed|kills|murder\w*|shooting|shot dead|stabb\w*|funeral|"
                          r"obituar\w*|rip|passed away|tributes?|mourn\w*|massacre|tragedy|tragic|victims?|inquest",
    # Not plain "attack": football is full of attackers.
    "violence or war": r"terror\w*|(?:knife|gun|terror|missile|drone) attacks?|attacked|bomb(?:s|ing|ings|ed)?|"
                       r"explosions?|war|invasion|hostages?|gunman|riots?|airstrikes?",
    "a disaster": r"earthquake|flood\w*|hurricane|tornado|wildfires?|tsunami|evacuat\w*",
    "crime": r"true crime|charged|trial|sentenced|jailed|convicted|abuse\w*|assault\w*|rape\w*|traffick\w*|"
             r"kidnap\w*|missing (?:girl|boy|woman|man|child|teen)|paedophile|pedophile|arrested",
    "health or self-harm": r"cancer|diagnos\w*|hospitali[sz]ed|suicide|overdose|self[- ]harm",
    "adult content": r"porn\w*|onlyfans|nude\w*|sex tape|xxx",
}
POLITICS = (r"elections?|electoral|voters?|voting|polls?|parliament\w*|prime minister|president\w*|senat\w*|"
            r"congress\w*|"
            r"labour party|conservatives?|tory|tories|reform uk|democrats?|republicans?|referendum|minister|mps?|"
            r"chancellor|white house|downing street|trump|biden|harris|starmer|farage|badenoch|sunak|putin|zelensky\w*")


@dataclass
class Trend:
    title: str
    source: str
    score: float  # 0-1 within its source, before weighting
    context: list[str] = field(default_factory=list)  # headlines, descriptions: what the trend is about
    links: list[str] = field(default_factory=list)
    wiki_title: str = ""
    sources: list[str] = field(default_factory=list)  # filled in when trends are merged

    @property
    def key(self) -> str:
        return topic_key(self.title)


def tokens(text: str) -> set[str]:
    text = html.unescape(text).lower().replace("'", "").replace("’", "")
    words = re.findall(r"[a-z0-9]+", text)
    return {w for w in words if len(w) > 1 and w not in STOPWORDS and not re.fullmatch(r"(19|20)\d\d", w)}


def topic_key(text: str) -> str:
    return " ".join(sorted(tokens(text)))


def similar(a: str | set, b: str | set) -> bool:
    """True when two titles (or topic keys) are about the same thing, e.g. "Ballon d'Or" and "2026 Ballon d'Or"."""
    a = tokens(a) if isinstance(a, str) else a
    b = tokens(b) if isinstance(b, str) else b
    if not a or not b:
        return False
    common = len(a & b)
    if common == 0:
        return False
    if common / len(a | b) >= 0.5:
        return True
    small = min(len(a), len(b))
    return small <= 3 and common == small


def sensitive_reason(trend: Trend, allow_politics: bool = False, avoid_words: tuple = ()) -> str | None:
    text = " ".join([trend.title, *trend.context[:4]]).lower()
    for reason, pattern in SENSITIVE.items():
        if re.search(rf"\b(?:{pattern})\b", text):
            return reason
    if not allow_politics and re.search(rf"\b(?:{POLITICS})\b", text):
        return "politics"
    for word in avoid_words:
        if word.strip() and re.search(rf"\b{re.escape(word.strip().lower())}\b", text):
            return f'your avoid list ("{word}")'
    return None


def _rank_scores(n: int) -> list[float]:
    return [1 - i / max(n, 1) for i in range(n)]


# Google Trends: the daily trending-searches feed, with the news stories behind each search.
def parse_google_trends(xml_text: str) -> list[Trend]:
    root = ET.fromstring(xml_text)
    out = []
    for item in root.iter("item"):
        title = html.unescape((item.findtext("title") or "").strip())
        if not title:
            continue
        traffic = _traffic(item.findtext(f"{HT}approx_traffic") or "")
        context, links = [], []
        for news in item.findall(f"{HT}news_item"):
            headline = html.unescape((news.findtext(f"{HT}news_item_title") or "").strip())
            snippet = html.unescape((news.findtext(f"{HT}news_item_snippet") or "").strip())
            source = (news.findtext(f"{HT}news_item_source") or "").strip()
            if headline:
                context.append(f"{headline} ({source})" if source else headline)
            if snippet:
                context.append(snippet)
            url = (news.findtext(f"{HT}news_item_url") or "").strip()
            if url:
                links.append(url)
        out.append(Trend(title, "google", traffic, context, links))
    if out:
        top = max(t.score for t in out) or 1
        for t in out:  # log scale: 2,000 searches isn't 1% of 200,000 in "how trending" terms
            t.score = round(0.4 + 0.6 * math.log10(max(t.score, 1)) / math.log10(max(top, 10)), 3)
    return out


def _traffic(text: str) -> float:
    m = re.match(r"([\d.,]+)\s*([KMB]?)", text.strip().upper())
    if not m:
        return 100.0
    return float(m.group(1).replace(",", "")) * {"": 1, "K": 1e3, "M": 1e6, "B": 1e9}[m.group(2)]


# Wikipedia: yesterday's most-read articles, kept only when views jumped well above their usual level.
NAMESPACES = ("special", "wikipedia", "file", "portal", "template", "help", "category", "user", "talk", "draft")


def parse_wikipedia_mostread(data: dict, today: dt.date | None = None, min_spike: float = 3.0) -> list[Trend]:
    year = (today or dt.date.today()).year
    articles = (data.get("mostread") or {}).get("articles") or []
    out = []
    for a in articles:
        title = a.get("normalizedtitle") or a.get("title", "").replace("_", " ")
        if not title or title == "Main Page" or title.startswith(("Deaths in", "List of deaths")):
            continue
        if ":" in title and title.split(":", 1)[0].strip().lower() in NAMESPACES:
            continue
        history = [h.get("views", 0) for h in a.get("view_history") or []]
        views = a.get("views", 0)
        usual = statistics.median(history[:-1]) if len(history) > 1 else 0
        spike = views / max(usual, 500)
        if spike < min_spike:
            continue  # always popular (e.g. "YouTube"), not trending
        description = a.get("description", "")
        context = [f"{title}: {description}" if description else title]
        if a.get("extract"):
            context.append(a["extract"])
        m = re.search(r"\(\D*\d{3,4}\s*[–-]\s*(\d{4})\)", description)
        if m and int(m.group(1)) >= year - 1:
            context.insert(0, f"{title} died recently.")  # caught by the sensitive-topic filter
        score = min(1.0, math.log10(spike) / 2.5)
        link = f"https://en.wikipedia.org/wiki/{a.get('title', title.replace(' ', '_'))}"
        out.append(Trend(title, "wikipedia", score, context, [link], wiki_title=title))
    for t, rank in zip(out, _rank_scores(len(out))):
        t.score = round(0.5 * t.score + 0.5 * rank, 3)
    return out


# Reddit: the day's top posts in a few broad, visual subreddits.
def parse_reddit(data: dict, sub: str) -> list[Trend]:
    posts = [c.get("data", {}) for c in (data.get("data") or {}).get("children", [])]
    posts = [p for p in posts if not p.get("over_18") and not p.get("stickied") and p.get("title")]
    out = []
    for p, rank in zip(posts, _rank_scores(len(posts))):
        title = re.sub(r"^TIL(?::|\s+that\b)?\s*", "", html.unescape(p["title"]), flags=re.I).strip()
        context = [f"Top post today in r/{sub} ({p.get('ups', 0):,} upvotes): {title}"]
        if p.get("selftext"):
            context.append(p["selftext"][:500])
        out.append(Trend(title[:200], "reddit", round(rank, 3), context,
                         [f"https://www.reddit.com{p.get('permalink', '')}"]))
    return out


# YouTube: the trending chart. Music videos are skipped: you can't use the song, and "new song out" isn't a story.
def parse_youtube(data: dict) -> list[Trend]:
    items = [i for i in data.get("items", []) if i.get("snippet", {}).get("categoryId") != "10"]
    items.sort(key=lambda i: -int(i.get("statistics", {}).get("viewCount", 0)))
    out = []
    for item, rank in zip(items, _rank_scores(len(items))):
        sn = item["snippet"]
        title = re.sub(r"\s*[\(\[][^)\]]*(official|video|trailer|teaser|lyric)[^)\]]*[\)\]]", "", sn["title"],
                       flags=re.I)
        title = re.split(r"\s+[|]\s+", title)[0].strip()
        context = [f"Trending YouTube video by {sn.get('channelTitle', '')}: {sn['title']}"]
        if sn.get("description"):
            context.append(sn["description"][:400])
        if sn.get("tags"):
            context.append("Tags: " + ", ".join(sn["tags"][:10]))
        out.append(Trend(title, "youtube", round(rank, 3), context, [f"https://youtu.be/{item['id']}"]))
    return out


def merge(trends: list[Trend]) -> list[Trend]:
    """Groups trends about the same topic. Each extra source showing it adds to the score."""
    groups: list[list[Trend]] = []
    for t in sorted(trends, key=lambda t: -t.score * SOURCE_WEIGHT.get(t.source, 0.5)):
        toks = tokens(t.title)
        for g in groups:
            if any(similar(toks, tokens(o.title)) for o in g):
                g.append(t)
                break
        else:
            groups.append([t])
    merged = []
    for g in groups:
        best = g[0]
        sources = sorted({t.source for t in g})
        weighted = [t.score * SOURCE_WEIGHT.get(t.source, 0.5) for t in g]
        score = max(weighted) + 0.25 * (len(sources) - 1)
        context, links = [], []
        for t in g:
            context += [c for c in t.context if c not in context]
            links += [link for link in t.links if link not in links]
        wiki = next((t.wiki_title for t in g if t.wiki_title), "")
        merged.append(Trend(best.title, best.source, round(score, 3), context[:12], links[:6], wiki, sources))
    return sorted(merged, key=lambda t: -t.score)


class TrendScanner:
    def __init__(self, cfg: Config, session: requests.Session | None = None):
        self.cfg = cfg
        self.http = session or requests.Session()
        self.http.headers["User-Agent"] = USER_AGENT  # Wikipedia and Reddit refuse requests' default one

    def fetch_all(self) -> list[Trend]:
        tc = self.cfg.trends
        jobs = []
        if tc.google_trends:
            jobs += [(f"Google Trends {r}", lambda r=r: self.google(r)) for r in tc.regions]
        if tc.wikipedia:
            jobs.append(("Wikipedia", self.wikipedia))
        if tc.reddit:
            jobs.append(("Reddit", self.reddit))
        if tc.youtube and self.cfg.youtube.api_key:
            jobs += [(f"YouTube {r}", lambda r=r: self.youtube(r)) for r in tc.regions]
        found = []
        for name, job in jobs:
            try:
                got = job()
                log.info("%s: %d trends", name, len(got))
                found += got
            except (requests.RequestException, ET.ParseError, ValueError, KeyError) as e:
                log.warning("Couldn't read %s (%s)", name, type(e).__name__)
        return found

    def scan(self, recent_keys: list[str] = ()) -> tuple[list[Trend], list[tuple[Trend, str]]]:
        """Returns (usable trends best first, skipped trends with the reason)."""
        kept, skipped = [], []
        tc = self.cfg.trends
        for t in merge(self.fetch_all()):
            reason = sensitive_reason(t, tc.allow_politics, tc.avoid_words)
            if not reason and any(similar(t.key, k) for k in recent_keys):
                reason = "already covered recently"
            if reason:
                skipped.append((t, reason))
            else:
                kept.append(t)
        return kept, skipped

    def google(self, region: str) -> list[Trend]:
        r = self.http.get("https://trends.google.com/trending/rss", params={"geo": region}, timeout=20)
        r.raise_for_status()
        return parse_google_trends(r.text)

    def wikipedia(self) -> list[Trend]:
        day = dt.datetime.now(dt.timezone.utc).date()
        for back in range(3):  # today's feed appears once yesterday's numbers are in
            d = day - dt.timedelta(days=back)
            r = self.http.get(f"https://en.wikipedia.org/api/rest_v1/feed/featured/{d:%Y/%m/%d}", timeout=20)
            if r.ok and r.json().get("mostread"):
                return parse_wikipedia_mostread(r.json(), day)
        return []

    def reddit(self) -> list[Trend]:
        out = []
        for sub in self.cfg.trends.reddit_subs:
            r = self.http.get(f"https://www.reddit.com/r/{sub}/top.json", params={"t": "day", "limit": 4}, timeout=15)
            if r.status_code in (403, 429):
                log.info("Reddit is refusing requests right now (HTTP %s); skipping it this run", r.status_code)
                break
            r.raise_for_status()
            out += parse_reddit(r.json(), sub)
        return out

    def youtube(self, region: str) -> list[Trend]:
        r = self.http.get("https://www.googleapis.com/youtube/v3/videos", timeout=20, params={
            "part": "snippet,statistics", "chart": "mostPopular", "regionCode": region, "maxResults": 30,
            "key": self.cfg.youtube.api_key})
        r.raise_for_status()
        return parse_youtube(r.json())

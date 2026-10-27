"""The logic behind Date Night Picker: ideas, picking, memories, weather, sharing and calendars.

No Tkinter in here, so it can be tested on its own.
"""
from __future__ import annotations

import base64
import html
import json
import math
import random
import re
import shutil
import struct
import subprocess
import urllib.request
import wave
from collections import Counter, deque
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote_plus

HOME_POSTCODE = "LE8 8AL"
IDEAS_FILE = Path(__file__).with_name("ideas.json")
SETTINGS_FILE = Path.home() / ".config" / "datenight" / "settings.json"
MEMORIES_FILE = SETTINGS_FILE.with_name("memories.json")
FLECKNEY = (52.535, -1.046)
WEATHER_URL = ("https://api.open-meteo.com/v1/forecast?latitude={0}&longitude={1}&timezone=Europe%2FLondon"
               "&forecast_days=1&daily=weather_code,temperature_2m_max,precipitation_probability_max")
VIBES = ("inside", "outside", "chill")
SIZES = ("city", "town", "village")
BUDGET_MAX = 200  # the top of the slider means "no limit"
DRIVE_MAX = 60
FIELDS = {"name", "where", "minutes", "cost", "vibes", "about"}
TIMES = ("day", "evening", "late")
TIME_LABELS = {"day": "Daytime", "evening": "Evening", "late": "Late night"}
PHOTOS_DIR = SETTINGS_FILE.with_name("photos")
CACHE_DIR = Path.home() / ".cache" / "datenight"
OVERPASS_URLS = ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter")
MILESTONES = {1: "First date logged", 5: "High five", 10: "Perfect ten", 25: "Quarter century",
              50: "Half century", 75: "Diamond dates", 100: "A hundred dates of love"}

HEART = "♥"


# Data

def _check(idea: dict, where: str) -> dict:
    missing = FIELDS - idea.keys()
    if missing:
        raise ValueError(f"{idea.get('name', 'An idea')} in {where} is missing {', '.join(sorted(missing))}")
    unknown = set(idea["vibes"]) - set(VIBES)
    if unknown:
        raise ValueError(f"{idea['name']} has an unknown vibe: {', '.join(sorted(unknown))}")
    idea.setdefault("maps", "")
    idea["times"] = list(idea.get("times") or guess_times(idea))
    if set(idea["times"]) - set(TIMES):
        raise ValueError(f"{idea['name']} has an unknown time: use day, evening or late")
    months = idea.get("months") or []
    if any(not isinstance(m, int) or not 1 <= m <= 12 for m in months):
        raise ValueError(f"{idea['name']} has a month that isn't 1 to 12")
    idea["months"] = list(months)
    return idea


_DAY_WORDS = ("castle", "zoo", "museum", "garden", "park", "walk", "railway", "hall", "abbey", "house", "wood",
              "reservoir", "water", "market", "brunch", "coffee", "tea", "races", "cruise", "bike", "cycle",
              "paddle", "steam", "gallery", "cathedral", "centre", "forest", "ruins", "locks", "lunch", "picnic",
              "shopping", "trip", "day", "farm", "nature", "railway", "snowdome", "skating", "match")
_EVENING_WORDS = ("dinner", "theatre", "show", "curry", "pub", "gig", "comedy", "cinema", "sunset", "match",
                  "spa", "restaurant", "music", "concert", "bowling", "escape", "karaoke", "cocktail", "skating")
_LATE_WORDS = ("cocktail", "karaoke", "comedy", "gig", "late", "stargaz", "dessert", "cinema", "night")


def guess_times(idea: dict) -> list[str]:
    """A best guess at when an idea works, for ideas that don't say."""
    if idea["minutes"] == 0:
        return list(TIMES)
    text = f"{idea['name']} {idea['about']}".lower()
    times = []
    if any(w in text for w in _DAY_WORDS):
        times.append("day")
    if any(w in text for w in _EVENING_WORDS):
        times.append("evening")
    if any(w in text for w in _LATE_WORDS):
        times.append("late")
    return times or ["day", "evening"]


def expand(data: dict) -> list[dict]:
    """The hand-written ideas plus every template filled in for each matching town or option."""
    ideas = [_check(dict(i), "ideas") for i in data.get("ideas", [])]
    towns = data.get("towns", [])
    for town in towns:
        if town.get("size") not in SIZES:
            raise ValueError(f"Town {town.get('name')} needs a size of city, town or village")
    for t in data.get("templates", []):
        if "sizes" in t:
            for town in towns:
                if town["size"] in t["sizes"]:
                    fill = lambda s: s.replace("{town}", town["name"])  # noqa: E731
                    ideas.append(_check({
                        "name": fill(t["name"]), "where": town["name"], "minutes": town["minutes"],
                        "cost": t["cost"], "vibes": t["vibes"], "about": fill(t["about"]),
                        "maps": fill(t.get("maps", "{town}")), "times": t.get("times"),
                        "months": t.get("months")}, "templates"))
        elif "options" in t:
            for option in t["options"]:
                fill = lambda s: s.replace("{x}", option)  # noqa: E731
                ideas.append(_check({
                    "name": fill(t["name"]), "where": t["where"], "minutes": t["minutes"], "cost": t["cost"],
                    "vibes": t["vibes"], "about": fill(t["about"]), "maps": fill(t.get("maps", "")),
                    "times": t.get("times"), "months": t.get("months")}, "templates"))
        else:
            raise ValueError(f"Template {t.get('name')} needs either sizes or options")
    names = set()
    for idea in ideas:
        if idea["name"] in names:
            raise ValueError(f"Two ideas are called {idea['name']}")
        names.add(idea["name"])
    return ideas


def load_data(path: Path = IDEAS_FILE) -> tuple[list[dict], list[str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):  # an older ideas.json was a plain list of ideas
        data = {"ideas": data}
    return expand(data), list(data.get("twists", []))


def load_ideas(path: Path = IDEAS_FILE) -> list[dict]:
    return load_data(path)[0]


def in_season(idea: dict, month: int | None) -> bool:
    return month is None or not idea.get("months") or month in idea["months"]


def matching(ideas: list[dict], budget: int, minutes: int, vibe: str | None, when: str | None = None,
             month: int | None = None) -> list[dict]:
    """Ideas within the budget (BUDGET_MAX means any price), drive time, vibe and time of day (None means
    any), that are on in this month."""
    return [i for i in ideas
            if (budget >= BUDGET_MAX or i["cost"] <= budget)
            and i["minutes"] <= minutes
            and (vibe is None or vibe in i["vibes"])
            and (when is None or when in i.get("times", TIMES))
            and in_season(i, month)]


def both_match(ideas: list[dict], a: dict, b: dict, when: str | None = None, month: int | None = None) -> list[dict]:
    """Ideas you'd both say yes to: within the smaller budget and drive, and a vibe each of you ticked."""
    budget = min(a["budget"], b["budget"])
    minutes = min(a["minutes"], b["minutes"])
    likes_a = set(a.get("vibes") or VIBES)
    likes_b = set(b.get("vibes") or VIBES)
    return [i for i in matching(ideas, budget, minutes, None, when, month)
            if likes_a & set(i["vibes"]) and likes_b & set(i["vibes"])]


def is_special(idea: dict) -> bool:
    """Good for an anniversary or birthday: something a bit fancier than usual."""
    text = idea["name"].lower()
    return idea["cost"] >= 60 or any(w in text for w in ("fancy", "spa", "afternoon tea", "valentine", "theatre",
                                                           "show", "candlelit", "love letter"))


def weight(idea: dict, favourites=(), done=(), rainy: bool = False, month: int | None = None,
           occasion_soon: bool = False) -> float:
    """How likely an idea is to be picked: favourites, seasonal treats and (near an anniversary or
    birthday) special dates more; dates you've done and soggy ones less."""
    w = 1.0
    if idea["name"] in favourites:
        w *= 3
    if idea["name"] in done:
        w *= 0.25
    if rainy and "outside" in idea["vibes"] and "inside" not in idea["vibes"]:
        w *= 0.3
    if month is not None and idea.get("months") and month in idea["months"] and len(idea["months"]) <= 3:
        w *= 3  # only on for a few weeks a year, so make the most of it
    if occasion_soon and is_special(idea):
        w *= 2.5
    return w


def pick(candidates: list[dict], recent: deque, rng: random.Random = random, weigh=None) -> dict | None:
    """A random idea, avoiding recent picks while there are other options."""
    if not candidates:
        return None
    pool = [i for i in candidates if i["name"] not in recent] or candidates
    if weigh is None:
        return rng.choice(pool)
    return rng.choices(pool, weights=[weigh(i) for i in pool])[0]


def directions_url(idea: dict, origin: str = HOME_POSTCODE) -> str | None:
    if not idea.get("maps"):
        return None
    return ("https://www.google.com/maps/dir/?api=1&travelmode=driving"
            f"&origin={quote_plus(origin)}&destination={quote_plus(idea['maps'] + ', UK')}")


def describe_cost(cost: int) -> str:
    return "Free" if cost == 0 else f"About £{cost} for two"


def describe_drive(minutes: int) -> str:
    return "No driving" if minutes == 0 else f"About {minutes} min drive"


def surprise_clues(idea: dict) -> str:
    """What the not-planner gets to know: how far, how fancy and what to wear, but not where."""
    vibes = idea["vibes"]
    if idea["minutes"] == 0:
        wear = "You won't even need to leave the house. Comfy clothes are perfect."
    elif "outside" in vibes and "inside" not in vibes:
        wear = "Wear comfy shoes and bring a coat."
    elif idea["cost"] >= 80:
        wear = "Dress up a bit: it's a fancy one."
    elif "chill" in vibes:
        wear = "Something comfy but cute."
    else:
        wear = "Wear something nice."
    return f"Clue: {describe_drive(idea['minutes']).lower()}. {wear}"


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(settings: dict) -> None:
    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(settings), encoding="utf-8")
    except OSError:
        pass  # remembering the sliders is a nicety, not worth an error


# Memories: favourites, dates you've done, and your own ideas. Kept apart from ideas.json so updates never
# touch them.

def load_memories(path: Path | None = None) -> dict:
    path = path or MEMORIES_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {"favourites": list(data.get("favourites", [])), "done": [normalise_entry(d) for d in data.get("done", [])],
            "my_ideas": list(data.get("my_ideas", [])), "retired": list(data.get("retired", []))}


# "Not this one": out for the rest of this session, and back next time unless you've already done it

def still_on(ideas: list[dict], skipped=(), retired=()) -> list[dict]:
    """Ideas you haven't said no to this session, or for good."""
    return [i for i in ideas if i["name"] not in skipped and i["name"] not in retired]


def say_no(memories: dict, skipped: set, name: str) -> bool:
    """Skips an idea for this session. If you've already done it, it stays out for good (True)."""
    skipped.add(name)
    if any(d.get("name") == name for d in memories.get("done", [])):
        retired = memories.setdefault("retired", [])
        if name not in retired:
            retired.append(name)
        return True
    return False


def bring_back(memories: dict, skipped: set, name: str) -> None:
    skipped.discard(name)
    if name in memories.get("retired", []):
        memories["retired"].remove(name)


def entry_photos(entry: dict) -> list[str]:
    """Photo file names for a logged date. Older entries had a single "photo"."""
    photos = list(entry.get("photos") or [])
    if entry.get("photo") and entry["photo"] not in photos:
        photos.insert(0, entry["photo"])
    return photos


def normalise_entry(entry: dict) -> dict:
    entry = dict(entry)
    photos = entry_photos(entry)
    entry.pop("photo", None)
    if photos:
        entry["photos"] = photos
    else:
        entry.pop("photos", None)
    return entry


def photo_in_use(memories: dict, name: str) -> bool:
    return any(name in entry_photos(d) for d in memories.get("done", []))


def forget_photo(memories: dict, name: str, photos_dir: Path | None = None) -> None:
    """Deletes a photo file once no logged date uses it."""
    if not photo_in_use(memories, name):
        try:
            ((photos_dir or PHOTOS_DIR) / Path(name).name).unlink()
        except OSError:
            pass


def save_memories(memories: dict, path: Path | None = None) -> bool:
    path = path or MEMORIES_FILE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(memories, indent=1), encoding="utf-8")
        tmp.replace(path)
        return True
    except OSError:
        return False


def merge_my_ideas(ideas: list[dict], my_ideas: list[dict]) -> list[dict]:
    """Your own ideas join the list; a broken one is skipped rather than stopping the app."""
    names = {i["name"] for i in ideas}
    merged = list(ideas)
    for idea in my_ideas:
        try:
            idea = _check(dict(idea), "your ideas")
        except (ValueError, AttributeError):
            continue
        if idea["name"] not in names:
            idea["mine"] = True
            merged.append(idea)
            names.add(idea["name"])
    return merged


def memory_stats(done: list[dict]) -> str:
    if not done:
        return "No dates logged yet. Press \"We did it!\" after your next one."
    spent = sum(d.get("cost", 0) for d in done)
    rated = [d["rating"] for d in done if d.get("rating")]
    vibes = Counter(v for d in done for v in d.get("vibes", []))
    parts = [f"{len(done)} date{'s' if len(done) != 1 else ''} together", f"about £{spent} spent"]
    if rated:
        parts.append(f"average {sum(rated) / len(rated):.1f} hearts")
    if vibes:
        parts.append(f"favourite vibe: {vibes.most_common(1)[0][0]}")
    return "  \u2665  ".join(parts)


# Sharing

def share_text(idea: dict, twist: str | None = None) -> str:
    lines = [f"{HEART} Date night plan {HEART}", f"{idea['name']} ({idea['where']})",
             f"{describe_drive(idea['minutes'])}, {describe_cost(idea['cost']).lower()}", idea["about"]]
    if twist:
        lines.append(f"Cute twist: {twist}")
    url = directions_url(idea)
    if url:
        lines.append(f"Directions: {url}")
    return "\n".join(lines)


def _ics_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def start_time(idea: dict) -> tuple[int, int]:
    """Outdoor days start late morning; everything else is an evening date."""
    return (11, 0) if "outside" in idea["vibes"] and "inside" not in idea["vibes"] else (18, 30)


def make_ics(idea: dict, day: date, twist: str | None = None, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    hour, minute = start_time(idea)
    start = datetime(day.year, day.month, day.day, hour, minute)
    end = start + timedelta(hours=3)
    about = idea["about"] + (f"\nCute twist: {twist}" if twist else "")
    url = directions_url(idea)
    if url:
        about += f"\nDirections: {url}"
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Date Night Picker//EN", "BEGIN:VEVENT",
             f"UID:{now.strftime('%Y%m%dT%H%M%S%f')}-{abs(hash(idea['name']))}@datenight",
             f"DTSTAMP:{now.strftime('%Y%m%dT%H%M%SZ')}",
             f"DTSTART:{start.strftime('%Y%m%dT%H%M%S')}", f"DTEND:{end.strftime('%Y%m%dT%H%M%S')}",
             f"SUMMARY:{_ics_escape('Date night: ' + idea['name'])}",
             f"LOCATION:{_ics_escape(idea['where'])}", f"DESCRIPTION:{_ics_escape(about)}",
             "BEGIN:VALARM", "TRIGGER:-PT2H", "ACTION:DISPLAY", "DESCRIPTION:Date night soon!", "END:VALARM",
             "END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(lines) + "\r\n"


def next_saturday(today: date) -> date:
    return today + timedelta(days=(5 - today.weekday()) % 7 or 7)


def calendar_days(today: date) -> list[tuple[str, date]]:
    tomorrow = today + timedelta(days=1)
    sat = next_saturday(today)
    days = [("Tonight", today), ("Tomorrow", tomorrow)]
    if today.weekday() == 5:
        days.append(("Next Saturday", sat))
    else:
        if sat != tomorrow:
            days.append(("This Saturday", sat))
        days.append(("Saturday after", sat + timedelta(days=7)))
    return days


def desktop_dir() -> Path:
    desk = Path.home() / "Desktop"
    return desk if desk.is_dir() else Path.home()


# Weather

WEATHER_WORDS = [(0, "Clear skies"), (3, "Cloudy"), (48, "Foggy"), (57, "Drizzle"), (67, "Rain"), (77, "Snow"),
                 (82, "Showers"), (86, "Snow showers"), (99, "Thunderstorms")]


def parse_weather(data: dict) -> dict | None:
    try:
        daily = data["daily"]
        code = int(daily["weather_code"][0])
        top = round(float(daily["temperature_2m_max"][0]))
        rain = int(daily["precipitation_probability_max"][0] or 0)
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    words = next(w for limit, w in WEATHER_WORDS if code <= limit) if code <= 99 else "Mixed"
    rainy = rain >= 60 or 51 <= code <= 67 or code >= 80
    return {"summary": f"Today: {words}, {top}\u00b0C, {rain}% chance of rain", "rainy": rainy}


def fetch_weather(timeout: float = 6) -> dict | None:
    try:
        req = urllib.request.Request(WEATHER_URL.format(*FLECKNEY), headers={"User-Agent": "DateNightPicker"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return parse_weather(json.loads(resp.read().decode("utf-8")))
    except (OSError, ValueError):
        return None


# Anniversaries, birthdays and Valentine's Day

def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _next_date(month: int, day: int, today: date) -> date:
    for year in (today.year, today.year + 1):
        try:
            when = date(year, month, day)
        except ValueError:  # 29 February in a normal year
            when = date(year, 2, 28)
        if when >= today:
            return when
    return when


def _parse_day(text: str | None) -> date | None:
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        return None


def parse_uk_date(text: str) -> date | None:
    """Reads 14/03/2024, 14-3-2024, 14.03.24 or 2024-03-14."""
    text = text.strip()
    iso = _parse_day(text)
    if iso:
        return iso
    m = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2}|\d{4})", text)
    if not m:
        return None
    day, month, year = (int(g) for g in m.groups())
    if year < 100:
        year += 2000 if year <= date.today().year % 100 else 1900
    try:
        return date(year, month, day)
    except ValueError:
        return None


def occasions(settings: dict, today: date) -> list[tuple[int, str, date]]:
    """Upcoming occasions as (days away, label, date), soonest first."""
    you, her = settings.get("your_name") or "Your", settings.get("her_name") or "Her"
    found = [( _next_date(2, 14, today), "Valentine's Day")]
    anniversary = _parse_day(settings.get("anniversary"))
    if anniversary:
        when = _next_date(anniversary.month, anniversary.day, today)
        years = when.year - anniversary.year
        found.append((when, f"our {ordinal(years)} anniversary" if years > 0 else "our anniversary"))
    for key, who in (("her_birthday", her), ("your_birthday", you)):
        born = _parse_day(settings.get(key))
        if born:
            name = "your" if who == "Your" else "her" if who == "Her" else f"{who}'s"
            found.append((_next_date(born.month, born.day, today), f"{name} birthday"))
    return sorted(((when - today).days, label, when) for when, label in found)


def countdown_text(settings: dict, today: date) -> str:
    days, label, _when = occasions(settings, today)[0]
    if days == 0:
        return f"It's {label} today!"
    if days == 1:
        return f"{label[0].upper() + label[1:]} is tomorrow!"
    return f"{days} days until {label}"


def occasion_soon(settings: dict, today: date, within: int = 14) -> bool:
    """True when an anniversary or birthday you've set (not just Valentine's) is close."""
    return any(days <= within for days, label, _ in occasions(settings, today)) and bool(
        settings.get("anniversary") or settings.get("her_birthday") or settings.get("your_birthday")
        or today.month == 2)


# Streaks and milestones

def date_streak(done: list[dict], today: date) -> int:
    """How many weeks in a row (up to this one, or last one if this week hasn't had a date yet) had a date."""
    weeks = set()
    for d in done:
        day = _parse_day(d.get("date"))
        if day:
            weeks.add(day - timedelta(days=day.weekday()))
    week = today - timedelta(days=today.weekday())
    if week not in weeks:
        week -= timedelta(days=7)
    streak = 0
    while week in weeks:
        streak += 1
        week -= timedelta(days=7)
    return streak


def dates_this_month(done: list[dict], today: date) -> int:
    return sum(1 for d in done if (_parse_day(d.get("date")) or date.min).replace(day=1) == today.replace(day=1))


def badges(count: int) -> list[str]:
    return [name for n, name in MILESTONES.items() if count >= n]


def new_milestone(count: int) -> str | None:
    return MILESTONES.get(count)


# Opening hours, from OpenStreetMap (free, no account)

_DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
_RULE = re.compile(r"^\s*((?:(?:Mo|Tu|We|Th|Fr|Sa|Su)(?:-(?:Mo|Tu|We|Th|Fr|Sa|Su))?,?)+)?\s*(.*)$")


def hours_on(opening_hours: str, day: date) -> str | None:
    """Today's hours from a simple OpenStreetMap opening_hours value, like "Mo-Fr 09:00-17:00; Sa 10:00-16:00".
    Returns "10:00-17:00", "closed", or None when the value is too complicated to read."""
    text = opening_hours.strip()
    if text == "24/7":
        return "open 24 hours"
    today = _DAYS[day.weekday()]
    result = None
    for rule in filter(None, (r.strip() for r in text.split(";"))):
        m = _RULE.match(rule)
        days_part, times = m.group(1), m.group(2).strip()
        if re.search(r"[A-Z][a-z]{2}|PH|SH|week|\[|easter|sunrise|sunset|\+", times) and times not in ("off", "closed"):
            return None  # months, holidays and other rules we don't try to read
        if days_part:
            covered = set()
            for chunk in filter(None, days_part.split(",")):
                if "-" in chunk:
                    a, b = (_DAYS.index(x) for x in chunk.split("-"))
                    span = range(a, b + 1) if a <= b else list(range(a, 7)) + list(range(0, b + 1))
                    covered.update(_DAYS[k] for k in span)
                else:
                    covered.add(chunk)
            if today not in covered:
                continue
        if times in ("off", "closed"):
            result = "closed"
        elif re.fullmatch(r"\d\d:\d\d-\d\d:\d\d(,\s*\d\d:\d\d-\d\d:\d\d)*", times):
            result = times.replace(",", ", ")
        else:
            return None
    return result or "closed"


def fetch_opening_hours(idea: dict, timeout: float = 8) -> tuple[str, str] | None:
    """(OpenStreetMap name, opening_hours) for a named place within about 45 miles of Fleckney."""
    for query in dict.fromkeys(filter(None, (idea.get("maps"), idea["name"]))):
        pattern = re.escape(query).replace("\\ ", " ")
        overpass = (f'[out:json][timeout:{int(timeout)}];'
                    f'nwr["name"~"^{pattern}$",i]["opening_hours"](around:75000,{FLECKNEY[0]},{FLECKNEY[1]});'
                    "out tags 1;")
        for url in OVERPASS_URLS:
            try:
                req = urllib.request.Request(url, data=f"data={quote_plus(overpass)}".encode(),
                                             headers={"User-Agent": "DateNightPicker"})
                with urllib.request.urlopen(req, timeout=timeout + 5) as resp:
                    found = json.loads(resp.read().decode("utf-8")).get("elements", [])
                break
            except (OSError, ValueError):
                found = None
        if found is None:
            return None  # offline, or both servers are down
        if found:
            tags = found[0].get("tags", {})
            return tags.get("name", query), tags["opening_hours"]
    return None


def hours_search_url(idea: dict) -> str:
    return "https://www.google.com/search?q=" + quote_plus(f"{idea.get('maps') or idea['name']} opening times")


# Little sounds, made on the fly so there are no audio files to ship

def make_tone(path: Path, notes: list[tuple[float, float]], volume: float = 0.35) -> Path:
    rate = 22050
    frames = bytearray()
    for freq, length in notes:
        n = int(rate * length)
        for k in range(n):
            t = k / rate
            env = min(1.0, k / 300) * math.exp(-4 * t / length)  # soft attack, bell-like fade
            sample = env * (math.sin(2 * math.pi * freq * t) + 0.3 * math.sin(4 * math.pi * freq * t)) / 1.3
            frames += struct.pack("<h", int(sample * volume * 32767))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    return path


SOUNDS = {
    "spin": [(659, 0.07), (784, 0.07), (988, 0.07), (1175, 0.09)],
    "chime": [(1047, 0.18), (1319, 0.18), (1568, 0.45)],
    "yay": [(784, 0.1), (988, 0.1), (1175, 0.1), (1568, 0.5)],
}


def sound_player() -> list[str] | None:
    for cmd in (["pw-play"], ["paplay"], ["aplay", "-q"]):
        if shutil.which(cmd[0]):
            return cmd
    return None


def play_sound(name: str) -> None:
    """Plays a sound in the background; silently does nothing if the computer can't."""
    player = sound_player()
    if not player:
        return
    try:
        path = CACHE_DIR / f"{name}.wav"
        if not path.exists():
            make_tone(path, SOUNDS[name])
        subprocess.Popen(player + [str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, KeyError, wave.Error):
        pass


# Photos

def save_photo(source: Path, when: str, name: str) -> str | None:
    """Copies a photo into ~/.config/datenight/photos and returns its new file name."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "date"
    target = PHOTOS_DIR / f"{when}-{slug}{source.suffix.lower()}"
    k = 2
    while target.exists():
        target = PHOTOS_DIR / f"{when}-{slug}-{k}{source.suffix.lower()}"
        k += 1
    try:
        PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    except OSError:
        return None
    return target.name


# Backups: one JSON file with memories and photos, which the phone version can read and write too

def make_backup(memories: dict, photos_dir: Path | None = None) -> dict:
    photos_dir = photos_dir or PHOTOS_DIR
    photos = {}
    for d in memories.get("done", []):
        for name in entry_photos(d):
            if (photos_dir / name).is_file():
                photos[name] = base64.b64encode((photos_dir / name).read_bytes()).decode("ascii")
    return {"app": "datenight", "version": 1, "saved": datetime.now().isoformat(timespec="seconds"),
            "memories": memories, "photos": photos}


def merge_memories(mine: dict, theirs: dict) -> tuple[dict, int]:
    """Adds anything from another backup that isn't here yet. Returns the merged memories and how many
    things were new."""
    merged = {k: list(mine.get(k, [])) for k in ("favourites", "done", "my_ideas", "retired")}
    added = 0
    for key in ("favourites", "retired"):
        for name in theirs.get(key, []):
            if name not in merged[key]:
                merged[key].append(name)
                added += 1
    merged["done"] = [normalise_entry(d) for d in merged["done"]]
    by_key = {(d.get("name"), d.get("date")): d for d in merged["done"]}
    for d in theirs.get("done", []):
        d = normalise_entry(d)
        key = (d.get("name"), d.get("date"))
        if key not in by_key:
            merged["done"].append(d)
            by_key[key] = d
            added += 1
        else:  # the same date logged on both devices: keep every photo from either
            here = by_key[key]
            extra = [p for p in entry_photos(d) if p not in entry_photos(here)]
            if extra:
                here["photos"] = entry_photos(here) + extra
                added += len(extra)
    merged["done"].sort(key=lambda d: d.get("date", ""))
    names = {i.get("name") for i in merged["my_ideas"]}
    for idea in theirs.get("my_ideas", []):
        if idea.get("name") not in names:
            merged["my_ideas"].append(idea)
            names.add(idea.get("name"))
            added += 1
    return merged, added


def restore_backup(backup: dict, mine: dict, photos_dir: Path | None = None) -> tuple[dict, int]:
    if backup.get("app") != "datenight" or "memories" not in backup:
        raise ValueError("That file isn't a Date Night Picker backup")
    photos_dir = photos_dir or PHOTOS_DIR
    for name, data in (backup.get("photos") or {}).items():
        safe = Path(name).name
        if safe and not (photos_dir / safe).exists():
            photos_dir.mkdir(parents=True, exist_ok=True)
            (photos_dir / safe).write_bytes(base64.b64decode(data))
    return merge_memories(mine, backup["memories"])


# Year in review: a pink page to print or save as a PDF

def year_review_html(done: list[dict], year: int, names: tuple[str, str] = ("", ""),
                     photos_dir: Path | None = None) -> str:
    photos_dir = photos_dir or PHOTOS_DIR
    dates = [d for d in done if (d.get("date") or "").startswith(str(year))]
    esc = html.escape
    who = " & ".join(n for n in names if n) or "us"
    spent = sum(d.get("cost", 0) for d in dates)
    rated = [d["rating"] for d in dates if d.get("rating")]
    best = max(dates, key=lambda d: (d.get("rating", 0), d.get("date", "")), default=None)
    places = Counter(d.get("where", "") for d in dates if d.get("where") and d.get("where") != "At home")
    vibes = Counter(v for d in dates for v in d.get("vibes", []))
    tiles = [(str(len(dates)), "dates together"), (f"£{spent}", "spent on each other"),
             (f"{sum(rated) / len(rated):.1f}" if rated else "-", "average hearts"),
             (vibes.most_common(1)[0][0].capitalize() if vibes else "-", "favourite vibe"),
             (places.most_common(1)[0][0] if places else "Home", "favourite place")]
    cards = []
    for d in dates:
        imgs = []
        for photo in entry_photos(d):
            if (photos_dir / photo).is_file():
                kind = "png" if photo.lower().endswith(".png") else "gif" if photo.lower().endswith(".gif") else "jpeg"
                data = base64.b64encode((photos_dir / photo).read_bytes()).decode("ascii")
                imgs.append(f'<img src="data:image/{kind};base64,{data}" alt="">')
        img = (imgs[0] + (f'<div class="more">{"".join(imgs[1:])}</div>' if len(imgs) > 1 else "")) if imgs else ""
        try:
            when = date.fromisoformat(d["date"]).strftime("%A %d %B")
        except (KeyError, ValueError):
            when = ""
        r = int(d.get("rating", 5))
        note = f'<p class="note">\u201c{esc(d["note"])}\u201d</p>' if d.get("note") else ""
        cards.append(f'<div class="card">{img}<div class="body"><div class="when">{esc(when)}</div>'
                     f'<h3>{esc(d.get("name", ""))}</h3><div class="where">{esc(d.get("where", ""))}</div>'
                     f'<div class="hearts">{"&#9829;" * r}<span>{"&#9825;" * (5 - r)}</span></div>{note}</div></div>')
    best_html = (f'<p class="best">Best date of the year: <b>{esc(best["name"])}</b></p>' if best else "")
    empty = "" if dates else "<p class='best'>No dates logged this year yet. Go and make some memories!</p>"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Our {year} in dates</title>
<style>
:root {{ --pink:#e0115f; --hot:#ff4d8d; --blush:#ffe3ee; --ink:#5a1a35; --muted:#b0607f; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; font-family: "DejaVu Sans", "Segoe UI", sans-serif; color:var(--ink);
       background: linear-gradient(#ffe4ef, #ffc2d8) fixed; padding: 32px 16px; }}
main {{ max-width: 900px; margin: 0 auto; }}
h1 {{ color:var(--pink); font-size: 44px; text-align:center; margin: 0 0 4px; }}
.sub {{ text-align:center; color:var(--muted); margin: 0 0 28px; font-size: 18px; }}
.tiles {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 18px; }}
.tile {{ background:#fff7fa; border:2px solid #ffb3cc; border-radius: 20px; padding: 16px; text-align:center; }}
.tile b {{ display:block; font-size: 26px; color:var(--pink); overflow-wrap: anywhere; }}
.tile span {{ color:var(--muted); font-size: 13px; }}
.best {{ text-align:center; font-size: 18px; margin: 8px 0 24px; }}
.cards {{ display:grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 16px; align-items: start; }}
.card {{ background:#fff; border-radius: 20px; overflow:hidden; box-shadow: 0 4px 14px rgba(224,17,95,.15);
         break-inside: avoid; }}
.card img {{ width:100%; height: 200px; object-fit: cover; display:block; }}
.more {{ display:grid; grid-template-columns: repeat(3, 1fr); gap: 3px; margin-top: 3px; }}
.more img {{ height: 80px; }}
.body {{ padding: 14px 16px 16px; }}
.when {{ color:var(--muted); font-size: 13px; }}
h3 {{ margin: 4px 0 2px; font-size: 18px; }}
.where {{ color:var(--pink); font-size: 14px; }}
.hearts {{ color:var(--pink); font-size: 20px; margin-top: 6px; }}
.hearts span {{ color:#f3c3d4; }}
.note {{ font-style: italic; color:#b80d4d; margin: 8px 0 0; }}
footer {{ text-align:center; color:var(--muted); margin-top: 30px; font-size: 32px; }}
@media print {{ body {{ background: #fff; padding: 0; }} .card {{ box-shadow:none; border:1px solid #ffb3cc; }} }}
</style></head>
<body><main>
<h1>&#9829; Our {year} in dates &#9829;</h1>
<p class="sub">A year of date nights for {esc(who)}</p>
<div class="tiles">{"".join(f'<div class="tile"><b>{esc(v)}</b><span>{esc(k)}</span></div>' for v, k in tiles)}</div>
{best_html}{empty}
<div class="cards">{"".join(cards)}</div>
<footer>&#9829; &#9829; &#9829;</footer>
</main></body></html>
"""

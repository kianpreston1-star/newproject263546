#!/usr/bin/env python3
"""Date Night Picker: answer three questions, press the button, get a date idea near Fleckney.

Everything runs offline from ideas.json next to this file. Two things go online, and the app works
without them: a weather check at start-up (Open-Meteo, no account needed) and the Directions button,
which opens Google Maps in your browser. Plain Tkinter, no extra packages, a few MB of RAM.

    python3 datenight.py           open the app
    python3 datenight.py --check   check that the app can start, then exit
"""
from __future__ import annotations

import json
import math
import random
import sys
import threading
import urllib.request
import webbrowser
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

HEART = "♥"
HEART_FONT = "DejaVu Sans"  # has the heart glyph, so Tk never falls back to a colour-emoji font
FONT = "Sans"
W, H = 940, 620

BG_TOP = "#ffe4ef"
BG_BOTTOM = "#ffc2d8"
PANEL = "#fff7fa"
PANEL_EDGE = "#ffb3cc"
BLUSH = "#ffe3ee"
INK = "#5a1a35"
MUTED = "#b0607f"
DEEP = "#e0115f"
DEEPER = "#b80d4d"
HOT = "#ff4d8d"
TRACK = "#ffd6e5"
DIM = "#f6d6e2"
OFF = "#f3c3d4"
VIBE_COLOURS = {"inside": "#ff4d8d", "outside": "#ff8fab", "chill": "#d96bd0"}
FLOATY = ("#ff8fb1", "#ffb3cb", "#ff6f9c", "#ffd1e0", "#ff4d8d", "#ffa6c9")


# Data

def _check(idea: dict, where: str) -> dict:
    missing = FIELDS - idea.keys()
    if missing:
        raise ValueError(f"{idea.get('name', 'An idea')} in {where} is missing {', '.join(sorted(missing))}")
    unknown = set(idea["vibes"]) - set(VIBES)
    if unknown:
        raise ValueError(f"{idea['name']} has an unknown vibe: {', '.join(sorted(unknown))}")
    idea.setdefault("maps", "")
    return idea


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
                        "maps": fill(t.get("maps", "{town}"))}, "templates"))
        elif "options" in t:
            for option in t["options"]:
                fill = lambda s: s.replace("{x}", option)  # noqa: E731
                ideas.append(_check({
                    "name": fill(t["name"]), "where": t["where"], "minutes": t["minutes"], "cost": t["cost"],
                    "vibes": t["vibes"], "about": fill(t["about"]), "maps": fill(t.get("maps", ""))}, "templates"))
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


def matching(ideas: list[dict], budget: int, minutes: int, vibe: str | None) -> list[dict]:
    """Ideas within the budget (BUDGET_MAX means any price), drive time and vibe (None means any)."""
    return [i for i in ideas
            if (budget >= BUDGET_MAX or i["cost"] <= budget)
            and i["minutes"] <= minutes
            and (vibe is None or vibe in i["vibes"])]


def weight(idea: dict, favourites=(), done=(), rainy: bool = False) -> float:
    """How likely an idea is to be picked: favourites more, dates you've done and soggy ones less."""
    w = 1.0
    if idea["name"] in favourites:
        w *= 3
    if idea["name"] in done:
        w *= 0.25
    if rainy and "outside" in idea["vibes"] and "inside" not in idea["vibes"]:
        w *= 0.3
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
    return {"favourites": list(data.get("favourites", [])), "done": list(data.get("done", [])),
            "my_ideas": list(data.get("my_ideas", []))}


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


# Drawing helpers

def blend(a: str, b: str, t: float) -> str:
    pa = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    pb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(pa, pb))


def round_rect(c, x0, y0, x1, y1, r, **kw):
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
           x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return c.create_polygon(pts, smooth=True, **kw)


def heart_points(cx, cy, size):
    pts = []
    for k in range(40):
        t = 2 * math.pi * k / 40
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts += [cx + x * size / 16, cy - y * size / 16 - size * 0.1]
    return pts


class HeartSlider:
    """A pink track with a heart you drag."""

    def __init__(self, c, x, y, length, top, step, value, on_change):
        self.c, self.x0, self.x1, self.y = c, x, x + length, y
        self.top, self.step, self.value, self.on_change = top, step, value, on_change
        tag = f"slider{id(self)}"
        c.create_rectangle(x - 12, y - 16, x + length + 12, y + 16, fill=PANEL, outline="", tags=tag)
        c.create_line(x, y, x + length, y, width=10, capstyle="round", fill=TRACK, tags=tag)
        self.fill = c.create_line(x, y, x, y, width=10, capstyle="round", fill=HOT, tags=tag)
        self.knob = c.create_text(x, y, text=HEART, font=(HEART_FONT, 24), fill=DEEP, tags=tag)
        for event in ("<Button-1>", "<B1-Motion>"):
            c.tag_bind(tag, event, self._drag)
        c.tag_bind(tag, "<Enter>", lambda _e: c.config(cursor="hand2"))
        c.tag_bind(tag, "<Leave>", lambda _e: c.config(cursor=""))
        self.draw()

    def _drag(self, event):
        frac = min(1, max(0, (event.x - self.x0) / (self.x1 - self.x0)))
        value = int(round(frac * self.top / self.step) * self.step)
        if value != self.value:
            self.value = value
            self.draw()
            self.on_change(value)

    def draw(self):
        px = self.x0 + (self.x1 - self.x0) * self.value / self.top
        self.c.coords(self.fill, self.x0, self.y, px, self.y)
        self.c.coords(self.knob, px, self.y - 1)


class PinkButton:
    def __init__(self, c, box, text, command, size=11, fill=HOT, hover=DEEP, fg="white"):
        self.c, self.command = c, command
        self.fill, self.hover, self.fg = fill, hover, fg
        self.enabled = True
        tag = f"button{id(self)}"
        x0, y0, x1, y1 = box
        self.shape = round_rect(c, x0, y0, x1, y1, min(22, (y1 - y0) / 2), fill=fill, outline="", tags=tag)
        self.label = c.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=text, fill=fg,
                                   font=(FONT, size, "bold"), tags=tag)
        c.tag_bind(tag, "<Enter>", lambda _e: self._hover(True))
        c.tag_bind(tag, "<Leave>", lambda _e: self._hover(False))
        c.tag_bind(tag, "<Button-1>", lambda _e: self.enabled and self.command())

    def _hover(self, inside):
        if self.enabled:
            self.c.itemconfig(self.shape, fill=self.hover if inside else self.fill)
            self.c.itemconfig(self.label, fill="white" if inside else self.fg)
        self.c.config(cursor="hand2" if inside and self.enabled else "")

    def set_enabled(self, enabled: bool):
        self.enabled = enabled
        self.c.itemconfig(self.shape, fill=self.fill if enabled else OFF)
        self.c.itemconfig(self.label, fill=self.fg if enabled else "white")

    def set_text(self, text: str):
        self.c.itemconfig(self.label, text=text)

    def set_look(self, fill: str, fg: str):
        self.fill, self.fg = fill, fg
        self.set_enabled(self.enabled)


class App:
    DISC_X, DISC_Y = 238, 370
    RADIUS = 88
    HUB = 30
    SECTORS = {"inside": 90, "chill": 210, "outside": 330}  # start angle of each 120° slice
    CARD_X, CARD_W = 506, 384

    def __init__(self, root, ideas: list[dict], twists: list[str], weather: bool = True):
        import tkinter as tk

        self.tk = tk
        self.root = root
        self.memories = load_memories()
        self.ideas = merge_my_ideas(ideas, self.memories["my_ideas"])
        self.twists = twists or ["Hold hands the whole time."]
        self.recent: deque = deque(maxlen=30)
        self.spinning = False
        self.current: dict | None = None
        self.floaters: list[list] = []
        self.frame = 0
        self.surprise = False
        self.revealed = True
        self.twist_now: str | None = None
        self.rainy = False
        self.weather_result: list = []

        saved = load_settings()
        self.budget = int(saved.get("budget", 50))
        self.minutes = int(saved.get("minutes", 30))
        self.vibe: str | None = saved.get("vibe") if saved.get("vibe") in VIBES else None

        root.title(f"{HEART} Date Night Picker {HEART}")
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.quit)
        self.c = c = tk.Canvas(root, width=W, height=H, highlightthickness=0, bg=BG_TOP)
        c.pack()

        # Pink gradient, then hearts floating up behind everything else.
        for i in range(62):
            y0 = i * H / 62
            c.create_rectangle(0, y0, W, y0 + H / 62 + 1, fill=blend(BG_TOP, BG_BOTTOM, i / 61), outline="")
        for _ in range(26):
            self._new_floater(random.uniform(0, H))

        c.create_text(31, 41, text=f"{HEART} Date Night Picker {HEART}", font=(FONT, 25, "bold"),
                      fill="#ffffff", anchor="w")
        c.create_text(28, 38, text=f"{HEART} Date Night Picker {HEART}", font=(FONT, 25, "bold"),
                      fill=DEEP, anchor="w")
        c.create_text(30, 72, text=f"Made with love, for the two of us  {HEART}  {HOME_POSTCODE}, Fleckney",
                      font=(FONT, 10), fill=MUTED, anchor="w")

        round_rect(c, 24, 96, 452, 600, 26, fill=PANEL, outline=PANEL_EDGE, width=2)
        round_rect(c, 476, 96, 916, 600, 26, fill=PANEL, outline=PANEL_EDGE, width=2)
        c.create_polygon(heart_points(846, 446, 40), smooth=True, fill=BLUSH, outline="")
        c.create_polygon(heart_points(888, 404, 16), smooth=True, fill=BLUSH, outline="")

        # Header pills and the weather line
        pill = dict(size=9, fill=PANEL, hover=HOT, fg=DEEP)
        PinkButton(c, (596, 18, 718, 46), f"Our memories {HEART}", self.open_memories, **pill)
        PinkButton(c, (726, 18, 826, 46), "+ Add idea", self.open_add_idea, **pill)
        self.surprise_button = PinkButton(c, (834, 18, 916, 46), "Surprise", self.toggle_surprise, **pill)
        self.weather_text = c.create_text(916, 72, text="Checking the weather..." if weather else "",
                                          font=(FONT, 9), fill=MUTED, anchor="e")

        # Questions
        c.create_text(50, 122, text="1. How much would you like to spend?", font=(FONT, 11, "bold"),
                      fill=INK, anchor="w")
        HeartSlider(c, 60, 156, 230, BUDGET_MAX, 5, self.budget, self._set_budget)
        self.budget_text = c.create_text(312, 156, font=(FONT, 11, "bold"), fill=DEEP, anchor="w")
        c.create_text(50, 194, text=f"2. How many minutes' drive from {HOME_POSTCODE}?",
                      font=(FONT, 11, "bold"), fill=INK, anchor="w")
        HeartSlider(c, 60, 228, 230, DRIVE_MAX, 5, self.minutes, self._set_minutes)
        self.minutes_text = c.create_text(312, 228, font=(FONT, 11, "bold"), fill=DEEP, anchor="w")
        c.create_text(50, 254, text="3. Spin the love disc: pick a vibe", font=(FONT, 11, "bold"),
                      fill=INK, anchor="w")
        self.vibe_text = c.create_text(self.DISC_X, 482, font=(FONT, 10), fill=MUTED)
        c.tag_bind("disc", "<Button-1>", self._disc_click)
        c.tag_bind("disc", "<Enter>", lambda _e: c.config(cursor="hand2"))
        c.tag_bind("disc", "<Leave>", lambda _e: c.config(cursor=""))

        self.go = PinkButton(c, (50, 500, 426, 550), f"{HEART}  Pick our date night  {HEART}", self.spin,
                             size=14, fill=DEEP, hover=DEEPER)
        c.create_text(self.DISC_X, 576, text="or press Enter / Space", font=(FONT, 9), fill=MUTED)
        root.bind("<Return>", lambda _e: self.spin())
        root.bind("<space>", lambda _e: self.spin())

        # Result card
        x = self.CARD_X
        self.kicker = c.create_text(x, 124, text=f"{HEART} TONIGHT'S DATE {HEART}", font=(FONT, 9, "bold"),
                                    fill=MUTED, anchor="nw")
        self.name = c.create_text(x, 148, text="Ready when you are, lovebirds", font=(FONT, 22, "bold"),
                                  fill=INK, anchor="nw", width=self.CARD_W)
        self.where = c.create_text(x, 0, font=(FONT, 11, "bold"), fill=DEEP, anchor="nw", width=self.CARD_W)
        self.facts = c.create_text(x, 0, font=(FONT, 10), fill=MUTED, anchor="nw", width=self.CARD_W)
        self.about = c.create_text(x, 0, text="Answer the three questions, then press the big pink button.",
                                   font=(FONT, 12), fill=INK, anchor="nw", width=self.CARD_W)
        self.twist_box = round_rect(c, 0, 0, 1, 1, 14, fill=BLUSH, outline=PANEL_EDGE, state="hidden")
        self.twist = c.create_text(x + 14, 0, font=(FONT, 10, "italic"), fill=DEEPER, anchor="nw",
                                   width=self.CARD_W - 28, state="hidden")
        small = dict(size=9, fill=BLUSH, hover=HOT, fg=DEEP)
        self.fav = PinkButton(c, (x, 500, x + 90, 534), f"{HEART} Save", self.toggle_favourite, **small)
        self.did = PinkButton(c, (x + 98, 500, x + 188, 534), "We did it!", self.open_did_it, **small)
        self.share = PinkButton(c, (x + 196, 500, x + 286, 534), "Copy for her", self.copy_for_her, **small)
        self.cal = PinkButton(c, (x + 294, 500, x + 384, 534), "Calendar", self.open_calendar, **small)
        self.directions = PinkButton(c, (x, 546, x + 130, 582), "Directions", self.open_directions, size=10,
                                     fill=BLUSH, hover=HOT, fg=DEEP)
        self.again = PinkButton(c, (x + 142, 546, x + 290, 582), f"Pick another {HEART}", self.spin, size=10,
                                fill=BLUSH, hover=HOT, fg=DEEP)
        self.surprise_note = c.create_text(x + self.CARD_W, 486, text="", font=(FONT, 9, "italic"),
                                           fill=MUTED, anchor="e")
        for button in (self.fav, self.did, self.share, self.cal, self.directions, self.again):
            button.set_enabled(False)
        self.count = c.create_text(x + self.CARD_W, 124, font=(FONT, 9), fill=MUTED, anchor="ne")

        self._set_budget(self.budget)
        self._set_minutes(self.minutes)
        self._draw_disc()
        self._layout_card()
        self._animate()
        if weather:
            threading.Thread(target=lambda: self.weather_result.append(fetch_weather()), daemon=True).start()
            self._wait_for_weather(0)

    # Questions

    def _set_budget(self, value):
        self.budget = value
        text = (f"£{BUDGET_MAX}+ no limit" if value >= BUDGET_MAX else "Free only" if value == 0
                else f"Up to £{value}")
        self.c.itemconfig(self.budget_text, text=text)
        self._update_count()

    def _set_minutes(self, value):
        self.minutes = value
        text = "Stay at home" if value == 0 else "Up to an hour" if value >= DRIVE_MAX else f"Up to {value} min"
        self.c.itemconfig(self.minutes_text, text=text)
        self._update_count()

    # The love disc

    def _draw_disc(self):
        c = self.c
        c.delete("disc")
        cx, cy, r = self.DISC_X, self.DISC_Y, self.RADIUS
        c.create_oval(cx - r - 10, cy - r - 10, cx + r + 10, cy + r + 10, fill=BLUSH, outline=PANEL_EDGE,
                      width=2, tags=("disc",))
        for k in range(12):  # little hearts round the rim
            a = math.radians(k * 30 + 15)
            c.create_text(cx + math.cos(a) * (r + 5), cy - math.sin(a) * (r + 5), text=HEART,
                          font=(HEART_FONT, 7), fill=HOT, tags=("disc",))
        for vibe, start in self.SECTORS.items():
            chosen = self.vibe in (None, vibe)
            c.create_arc(cx - r, cy - r, cx + r, cy + r, start=start, extent=120,
                         fill=VIBE_COLOURS[vibe] if chosen else DIM, outline=PANEL, width=3, tags=("disc",))
            a = math.radians(start + 60)
            lx = cx + math.cos(a) * (r + self.HUB) / 2
            ly = cy - math.sin(a) * (r + self.HUB) / 2
            c.create_text(lx, ly, text=vibe.capitalize(), font=(FONT, 11, "bold"),
                          fill="white" if chosen else MUTED, tags=("disc",))
        any_on = self.vibe is None
        c.create_polygon(heart_points(cx, cy + 2, self.HUB + 6), smooth=True, fill=DEEP if any_on else "white",
                         outline=PANEL, width=3, tags=("disc",))
        c.create_text(cx, cy - 1, text="Any", font=(FONT, 10, "bold"), fill="white" if any_on else DEEP,
                      tags=("disc",))
        c.itemconfig(self.vibe_text, text=f"Any vibe {HEART} click a slice to choose" if any_on
                     else f"{self.vibe.capitalize()} only {HEART} click the heart for any")

    def _disc_click(self, event):
        if self.spinning:
            return
        dx, dy = event.x - self.DISC_X, self.DISC_Y - event.y
        dist = math.hypot(dx, dy)
        if dist > self.RADIUS:
            return
        if dist <= self.HUB:
            self.vibe = None
        else:
            angle = math.degrees(math.atan2(dy, dx)) % 360
            for vibe, start in self.SECTORS.items():
                if (angle - start) % 360 < 120:
                    self.vibe = None if self.vibe == vibe else vibe
                    break
        self._draw_disc()
        self._update_count()

    # Floating hearts

    def _new_floater(self, y):
        size = random.randint(10, 30)
        x = random.uniform(0, W)
        # Drawn right after the gradient, so they stay behind the panels.
        item = self.c.create_text(x, y, text=HEART, font=(HEART_FONT, size), fill=random.choice(FLOATY))
        self.floaters.append([item, x, y, random.uniform(0.4, 1.3), random.uniform(0, 6.3)])

    def _animate(self):
        self.frame += 1
        if self.root.state() != "iconic":
            for f in self.floaters:
                f[2] -= f[3]
                if f[2] < -30:
                    f[1], f[2] = random.uniform(0, W), H + 30
                self.c.coords(f[0], f[1] + math.sin(f[4] + self.frame * 0.04) * 10, f[2])
        self.root.after(60, self._animate)

    def _burst(self, x, y):
        bits = []
        for _ in range(16):
            a = random.uniform(0, 2 * math.pi)
            speed = random.uniform(3, 8)
            item = self.c.create_text(x, y, text=HEART, font=(HEART_FONT, random.randint(10, 22)),
                                      fill=random.choice(FLOATY + (DEEP,)))
            bits.append([item, math.cos(a) * speed, math.sin(a) * speed - 2])
        self._burst_step(bits, 0)

    def _burst_step(self, bits, step):
        if step > 22:
            for b in bits:
                self.c.delete(b[0])
            return
        for b in bits:
            self.c.move(b[0], b[1], b[2])
            b[2] += 0.35  # gravity
        self.root.after(35, self._burst_step, bits, step + 1)

    # Picking

    def _candidates(self):
        return matching(self.ideas, self.budget, self.minutes, self.vibe)

    def _update_count(self):
        if hasattr(self, "count"):
            n = len(self._candidates())
            self.c.itemconfig(self.count, text=f"{HEART} {n} idea{'s' if n != 1 else ''} match")

    def spin(self):
        if self.spinning:
            return
        candidates = self._candidates()
        self._save()
        if not candidates:
            self._show_none()
            return
        favourites = set(self.memories["favourites"])
        done = {d["name"] for d in self.memories["done"]}
        choice = pick(candidates, self.recent, weigh=lambda i: weight(i, favourites, done, self.rainy))
        self.recent.append(choice["name"])
        self._start_shuffle(candidates, choice)

    def _start_shuffle(self, candidates, choice):
        self.spinning = True
        for button in (self.go, self.again, self.directions, self.fav, self.did, self.share, self.cal):
            button.set_enabled(False)
        self.c.itemconfig(self.surprise_note, text="")
        self.c.itemconfig(self.kicker, text=f"{HEART} PICKING {HEART}")
        for item in (self.where, self.facts, self.about):
            self.c.itemconfig(item, text="")
        self._hide_twist()
        self._shuffle(candidates, choice, 0)

    def _shuffle(self, candidates, choice, step, frames=18):
        if step < frames:
            teaser = ("Shh" + "." * (step % 4)) if self.surprise else random.choice(candidates)["name"]
            self.c.itemconfig(self.name, text=teaser, fill=MUTED)
            self._layout_card()
            self._spin_marker(step)
            self.root.after(40 + step * 8, self._shuffle, candidates, choice, step + 1, frames)
            return
        self.c.delete("marker")
        self.spinning = False
        self._show(choice)

    def _spin_marker(self, step):
        self.c.delete("marker")
        a = math.radians(90 - step * 47)
        x = self.DISC_X + math.cos(a) * (self.RADIUS - 12)
        y = self.DISC_Y - math.sin(a) * (self.RADIUS - 12)
        self.c.create_text(x, y, text=HEART, font=(HEART_FONT, 20), fill="white", tags=("marker",))

    def _show(self, idea, new_twist=True, reveal=False):
        self.current = idea
        self.revealed = reveal or not self.surprise
        if new_twist:
            self.twist_now = random.choice(self.twists)
        c = self.c
        vibes = " / ".join(v.capitalize() for v in idea["vibes"])
        facts = f"{describe_drive(idea['minutes'])}   {HEART}   {describe_cost(idea['cost'])}   {HEART}   {vibes}"
        if self.revealed:
            c.itemconfig(self.kicker, text=f"{HEART} TONIGHT'S DATE {HEART}")
            c.itemconfig(self.name, text=idea["name"], fill=INK)
            c.itemconfig(self.where, text=idea["where"] + ("  (your idea)" if idea.get("mine") else ""))
            past = [d for d in self.memories["done"] if d["name"] == idea["name"]]
            if past:
                facts += f"\nYou've done this before and gave it {past[-1].get('rating', 5)} hearts"
            if self.rainy and "outside" in idea["vibes"] and "inside" not in idea["vibes"]:
                facts += "\nRain is likely today: take a brolly, or pick Inside"
            c.itemconfig(self.facts, text=facts)
            c.itemconfig(self.about, text=idea["about"])
            c.itemconfig(self.surprise_note, text="")
        else:
            c.itemconfig(self.kicker, text=f"{HEART} SURPRISE DATE {HEART}")
            c.itemconfig(self.name, text="Top secret date", fill=INK)
            c.itemconfig(self.where, text="Only the planner gets to know")
            c.itemconfig(self.facts, text=facts)
            c.itemconfig(self.about, text=surprise_clues(idea))
            c.itemconfig(self.surprise_note, text="Planner: press Reveal to see it")
        c.itemconfig(self.twist, text=f"{HEART} Cute twist: {self.twist_now}", state="normal")
        c.itemconfig(self.twist_box, state="normal")
        self._layout_card()
        self.go.set_enabled(True)
        self.again.set_enabled(True)
        self.directions.set_text("Directions" if self.revealed else f"Reveal {HEART}")
        self.directions.set_enabled(not self.revealed or directions_url(idea) is not None)
        for button in (self.fav, self.did):
            button.set_enabled(self.revealed)
        self.share.set_enabled(True)
        self.cal.set_enabled(True)
        self._refresh_fav()
        if new_twist:
            bbox = c.bbox(self.name)
            self._burst((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)

    def _show_none(self):
        self.current = None
        c = self.c
        c.itemconfig(self.kicker, text=f"{HEART} NOTHING MATCHES {HEART}")
        c.itemconfig(self.name, text="No ideas fit that yet", fill=INK)
        c.itemconfig(self.where, text="")
        c.itemconfig(self.facts, text="")
        c.itemconfig(self.about, text="Try a bigger budget, a longer drive, or click the heart in the middle "
                                      "of the disc for any vibe.")
        self._hide_twist()
        self._layout_card()
        for button in (self.directions, self.again, self.fav, self.did, self.share, self.cal):
            button.set_enabled(False)

    def _hide_twist(self):
        self.c.itemconfig(self.twist, state="hidden")
        self.c.itemconfig(self.twist_box, state="hidden")

    def _layout_card(self):
        """Stack the card's texts under each other, however many lines the name wraps to."""
        c = self.c
        y = c.bbox(self.name)[3] + 4
        for item, gap in ((self.where, 4), (self.facts, 14), (self.about, 16)):
            c.coords(item, self.CARD_X, y)
            box = c.bbox(item)
            if box and c.itemcget(item, "text"):
                y = box[3] + gap
        c.coords(self.twist, self.CARD_X + 14, y + 10)
        box = c.bbox(self.twist)
        if box:
            c.coords(self.twist_box, *self._rounded(self.CARD_X, y, self.CARD_X + self.CARD_W, box[3] + 10, 14))

    @staticmethod
    def _rounded(x0, y0, x1, y1, r):
        return [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
                x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]

    def open_directions(self):
        if self.current and not self.revealed:
            self._show(self.current, new_twist=False, reveal=True)
            bbox = self.c.bbox(self.name)
            self._burst((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)
            return
        url = self.current and directions_url(self.current)
        if url:
            webbrowser.open(url)

    # Header toggles and weather

    def toggle_surprise(self):
        self.surprise = not self.surprise
        self.surprise_button.set_look(DEEP if self.surprise else PANEL, "white" if self.surprise else DEEP)
        self.surprise_button.set_text(f"Surprise {HEART}" if self.surprise else "Surprise")
        self.toast("Surprise mode on: the next pick stays secret until you press Reveal" if self.surprise
                   else "Surprise mode off")

    def _wait_for_weather(self, tries):
        if self.weather_result:
            result = self.weather_result[0]
            if result:
                self.rainy = result["rainy"]
                self.c.itemconfig(self.weather_text, text=result["summary"] +
                                  (f"  {HEART}  fewer outdoor picks" if self.rainy else ""))
            else:
                self.c.itemconfig(self.weather_text, text="Weather unavailable (offline?)")
        elif tries < 40:
            self.root.after(250, self._wait_for_weather, tries + 1)
        else:
            self.c.itemconfig(self.weather_text, text="Weather unavailable (offline?)")

    # Favourites, memories and your own ideas

    def _refresh_fav(self):
        saved = self.current is not None and self.current["name"] in self.memories["favourites"]
        self.fav.set_text(f"{HEART} Saved" if saved else f"{HEART} Save")
        self.fav.set_look(HOT if saved else BLUSH, "white" if saved else DEEP)

    def _store(self):
        if not save_memories(self.memories):
            self.toast("Couldn't save to ~/.config/datenight")

    def toggle_favourite(self):
        name = self.current["name"]
        favs = self.memories["favourites"]
        if name in favs:
            favs.remove(name)
            self.toast("Removed from favourites")
        else:
            favs.append(name)
            self.toast(f"Saved to favourites {HEART} it'll come up more often")
        self._store()
        self._refresh_fav()

    def _dialog(self, title, width, height):
        tk = self.tk
        win = tk.Toplevel(self.root, bg=PANEL)
        win.title(title)
        win.resizable(False, False)
        win.transient(self.root)
        x = self.root.winfo_rootx() + (W - width) // 2
        y = self.root.winfo_rooty() + (H - height) // 2
        win.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")
        tk.Label(win, text=title, font=(FONT, 16, "bold"), fg=DEEP, bg=PANEL).pack(anchor="w", padx=22, pady=(18, 4))
        win.bind("<Escape>", lambda _e: win.destroy())
        return win

    def _button(self, parent, text, command, primary=True):
        return self.tk.Button(parent, text=text, command=command, font=(FONT, 10, "bold"), relief="flat", bd=0,
                              bg=DEEP if primary else BLUSH, fg="white" if primary else DEEP,
                              activebackground=DEEPER if primary else HOT, activeforeground="white",
                              padx=14, pady=6, cursor="hand2", highlightthickness=0)

    def open_did_it(self):
        tk, idea = self.tk, self.current
        win = self._dialog("We did it!", 420, 300)
        tk.Label(win, text=idea["name"], font=(FONT, 12, "bold"), fg=INK, bg=PANEL, wraplength=370,
                 justify="left").pack(anchor="w", padx=22)
        tk.Label(win, text="How was it?", font=(FONT, 10), fg=MUTED, bg=PANEL).pack(anchor="w", padx=22, pady=(10, 0))
        rating = tk.IntVar(value=5)
        hearts = tk.Canvas(win, width=230, height=44, bg=PANEL, highlightthickness=0, cursor="hand2")
        hearts.pack(anchor="w", padx=18)

        def draw(*_):
            hearts.delete("all")
            for k in range(5):
                hearts.create_text(22 + k * 44, 22, text=HEART, font=(HEART_FONT, 26),
                                   fill=DEEP if k < rating.get() else DIM)
        hearts.bind("<Button-1>", lambda e: (rating.set(min(5, max(1, e.x // 44 + 1))), draw()))
        draw()
        tk.Label(win, text="A little note to remember it by (optional)", font=(FONT, 10), fg=MUTED,
                 bg=PANEL).pack(anchor="w", padx=22, pady=(8, 2))
        note = tk.Entry(win, font=(FONT, 11), relief="flat", bg="white", fg=INK, highlightthickness=1,
                        highlightbackground=PANEL_EDGE, highlightcolor=HOT, insertbackground=DEEP)
        note.pack(fill="x", padx=22, ipady=4)
        note.focus_set()

        def save(*_):
            self.memories["done"].append({"name": idea["name"], "where": idea["where"], "date": date.today().isoformat(),
                                          "rating": rating.get(), "note": note.get().strip(), "cost": idea["cost"],
                                          "vibes": list(idea["vibes"])})
            self._store()
            win.destroy()
            self.toast(f"Saved to your memories {HEART}")
            self._show(idea, new_twist=False, reveal=True)
        note.bind("<Return>", save)
        row = tk.Frame(win, bg=PANEL)
        row.pack(fill="x", padx=22, pady=16)
        self._button(row, f"Save memory {HEART}", save).pack(side="right")
        self._button(row, "Cancel", win.destroy, primary=False).pack(side="right", padx=8)

    def open_memories(self):
        tk = self.tk
        win = self._dialog(f"Our memories {HEART}", 560, 560)
        tk.Label(win, text=memory_stats(self.memories["done"]), font=(FONT, 10), fg=MUTED, bg=PANEL,
                 wraplength=510, justify="left").pack(anchor="w", padx=22)
        frame = tk.Frame(win, bg=PANEL)
        frame.pack(fill="both", expand=True, padx=22, pady=10)
        text = tk.Text(frame, font=(FONT, 11), bg="white", fg=INK, relief="flat", wrap="word", padx=12, pady=10,
                       highlightthickness=1, highlightbackground=PANEL_EDGE, cursor="arrow")
        bar = tk.Scrollbar(frame, command=text.yview, troughcolor=BLUSH, bg=TRACK, activebackground=HOT,
                           relief="flat", bd=0)
        text.config(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        text.tag_config("h", font=(FONT, 12, "bold"), foreground=DEEP, spacing1=6, spacing3=4)
        text.tag_config("hearts", font=(HEART_FONT, 11), foreground=DEEP)
        text.tag_config("muted", foreground=MUTED, font=(FONT, 9))
        text.tag_config("b", font=(FONT, 11, "bold"))
        text.tag_config("note", font=(FONT, 10, "italic"), foreground=DEEPER, spacing3=8)

        text.insert("end", "Dates we've done\n", "h")
        if not self.memories["done"]:
            text.insert("end", "Nothing yet. After your next date, press \"We did it!\".\n\n", "muted")
        for d in reversed(self.memories["done"]):
            r = int(d.get("rating", 5))
            try:
                when = date.fromisoformat(d["date"]).strftime("%a %d %b %Y")
            except (KeyError, ValueError):
                when = ""
            text.insert("end", HEART * r + "\u2661" * (5 - r), "hearts")
            text.insert("end", f"   {when}\n", "muted")
            text.insert("end", f"{d['name']}", "b")
            text.insert("end", f"  ({d.get('where', '')})\n")
            text.insert("end", f"\u201c{d['note']}\u201d\n" if d.get("note") else "\n", "note")

        by_name = {i["name"]: i for i in self.ideas}
        favs = [by_name[n] for n in self.memories["favourites"] if n in by_name]
        text.insert("end", "Our favourites\n", "h")
        if not favs:
            text.insert("end", f"None yet. Press \"{HEART} Save\" on an idea you like.\n\n", "muted")
        for i in favs:
            text.insert("end", f"{HEART} ", "hearts")
            text.insert("end", f"{i['name']}  ")
            text.insert("end", f"{describe_drive(i['minutes'])}, {describe_cost(i['cost']).lower()}\n", "muted")
        mine = [i for i in self.ideas if i.get("mine")]
        if mine:
            text.insert("end", "\nOur own ideas\n", "h")
            for i in mine:
                text.insert("end", f"{HEART} ", "hearts")
                text.insert("end", f"{i['name']}\n")
        text.config(state="disabled")

        row = tk.Frame(win, bg=PANEL)
        row.pack(fill="x", padx=22, pady=(0, 16))
        self._button(row, "Close", win.destroy, primary=False).pack(side="right")
        if favs:
            def pick_favourite():
                win.destroy()
                if not self.spinning:
                    choice = pick(favs, self.recent)
                    self.recent.append(choice["name"])
                    self._start_shuffle(favs, choice)
            self._button(row, f"Pick one of our favourites {HEART}", pick_favourite).pack(side="right", padx=8)

    def open_add_idea(self):
        tk = self.tk
        win = self._dialog("Add your own idea", 470, 500)
        form = tk.Frame(win, bg=PANEL)
        form.pack(fill="both", expand=True, padx=22)
        entry = dict(font=(FONT, 11), relief="flat", bg="white", fg=INK, highlightthickness=1,
                     highlightbackground=PANEL_EDGE, highlightcolor=HOT, insertbackground=DEEP)
        label = dict(font=(FONT, 10, "bold"), fg=INK, bg=PANEL, anchor="w")
        fields = {}
        for row, (key, text, hint) in enumerate([("name", "Name", "Ice cream at the seaside"),
                                                 ("where", "Where", "Skegness"),
                                                 ("maps", "Google Maps search (optional)", "")]):
            tk.Label(form, text=text, **label).grid(row=row * 2, column=0, columnspan=2, sticky="w", pady=(6, 0))
            fields[key] = tk.Entry(form, **entry)
            fields[key].grid(row=row * 2 + 1, column=0, columnspan=2, sticky="ew", ipady=3)
        form.columnconfigure(0, weight=1)
        form.columnconfigure(1, weight=1)
        minutes, cost = tk.IntVar(value=20), tk.IntVar(value=30)
        tk.Label(form, text="Minutes' drive", **label).grid(row=6, column=0, sticky="w", pady=(8, 0))
        tk.Label(form, text="Cost for two (£)", **label).grid(row=6, column=1, sticky="w", pady=(8, 0))
        spin = dict(font=(FONT, 11), relief="flat", bg="white", fg=INK, width=8, buttonbackground=BLUSH,
                    highlightthickness=1, highlightbackground=PANEL_EDGE)
        tk.Spinbox(form, from_=0, to=DRIVE_MAX, increment=5, textvariable=minutes, **spin).grid(row=7, column=0,
                                                                                               sticky="w")
        tk.Spinbox(form, from_=0, to=1000, increment=5, textvariable=cost, **spin).grid(row=7, column=1, sticky="w")
        tk.Label(form, text="Vibe", **label).grid(row=8, column=0, sticky="w", pady=(8, 0))
        checks = tk.Frame(form, bg=PANEL)
        checks.grid(row=9, column=0, columnspan=2, sticky="w")
        vibe_vars = {}
        for v in VIBES:
            vibe_vars[v] = tk.BooleanVar(value=(v == self.vibe))
            tk.Checkbutton(checks, text=v.capitalize(), variable=vibe_vars[v], font=(FONT, 10), bg=PANEL, fg=INK,
                           activebackground=PANEL, selectcolor="white", highlightthickness=0).pack(side="left",
                                                                                                    padx=(0, 10))
        tk.Label(form, text="What you'll do", **label).grid(row=10, column=0, sticky="w", pady=(8, 0))
        about = tk.Entry(form, **entry)
        about.grid(row=11, column=0, columnspan=2, sticky="ew", ipady=3)
        error = tk.Label(form, text="", font=(FONT, 9), fg=DEEP, bg=PANEL)
        error.grid(row=12, column=0, columnspan=2, sticky="w", pady=(6, 0))
        fields["name"].focus_set()

        def save(*_):
            name = fields["name"].get().strip()
            vibes = [v for v in VIBES if vibe_vars[v].get()]
            try:
                mins, price = int(minutes.get()), int(cost.get())
            except (ValueError, self.tk.TclError):
                mins = price = -1
            if not name:
                return error.config(text="Give your idea a name.")
            if any(i["name"].lower() == name.lower() for i in self.ideas):
                return error.config(text="There's already an idea with that name.")
            if not vibes:
                return error.config(text="Tick at least one vibe.")
            if not (0 <= mins <= DRIVE_MAX and price >= 0):
                return error.config(text=f"Drive must be 0 to {DRIVE_MAX} minutes and cost 0 or more.")
            idea = {"name": name, "where": fields["where"].get().strip() or "Somewhere special", "minutes": mins,
                    "cost": price, "vibes": vibes, "about": about.get().strip() or "Your own idea.",
                    "maps": fields["maps"].get().strip()}
            self.memories["my_ideas"].append(idea)
            self._store()
            self.ideas = merge_my_ideas(self.ideas, [idea])
            self._update_count()
            win.destroy()
            self.toast(f"Added \u201c{name}\u201d {HEART} {len(self.ideas)} ideas now")
        win.bind("<Return>", save)
        row = tk.Frame(win, bg=PANEL)
        row.pack(fill="x", padx=22, pady=16)
        self._button(row, f"Add idea {HEART}", save).pack(side="right")
        self._button(row, "Cancel", win.destroy, primary=False).pack(side="right", padx=8)

    # Sharing

    def copy_for_her(self):
        idea = self.current
        if self.revealed:
            message = share_text(idea, self.twist_now)
        else:
            message = (f"{HEART} I've planned a surprise date for us! {HEART}\n"
                       f"{surprise_clues(idea)}\nCute twist: {self.twist_now}")
        self.root.clipboard_clear()
        self.root.clipboard_append(message)
        self.toast("Copied! Paste it into WhatsApp or a text now (Ctrl+V)")

    def open_calendar(self):
        tk, idea = self.tk, self.current
        secret = not self.revealed
        win = self._dialog("Add to calendar", 380, 330)
        hour, minute = start_time(idea)
        tk.Label(win, text=f"When? It starts at {hour}:{minute:02d} and lasts three hours, with a reminder "
                           "two hours before.", font=(FONT, 10), fg=MUTED, bg=PANEL, wraplength=330,
                 justify="left").pack(anchor="w", padx=22, pady=(0, 8))

        def save(day):
            event = dict(idea, name="Surprise date night", where="It's a surprise",
                         about=surprise_clues(idea), maps="") if secret else idea
            path = desktop_dir() / f"date-night-{day.isoformat()}.ics"
            try:
                path.write_text(make_ics(event, day, self.twist_now), encoding="utf-8", newline="")
            except OSError:
                self.toast("Couldn't save the calendar file")
                return
            win.destroy()
            self.toast(f"Saved {path.name} to your {'Desktop' if path.parent.name == 'Desktop' else 'home folder'}: "
                       "open it to add to your calendar")
        for text, day in calendar_days(date.today()):
            self._button(win, f"{text}  ({day.strftime('%a %d %b')})", lambda d=day: save(d),
                         primary=False).pack(fill="x", padx=22, pady=3)

    def toast(self, message):
        c = self.c
        c.delete("toast")
        text = c.create_text(W / 2, H - 22, text=message, font=(FONT, 10, "bold"), fill="white", tags=("toast",))
        x0, y0, x1, y1 = c.bbox(text)
        box = round_rect(c, x0 - 16, y0 - 7, x1 + 16, y1 + 7, 14, fill=DEEP, outline="", tags=("toast",))
        c.tag_raise(text, box)
        if getattr(self, "_toast_job", None):
            self.root.after_cancel(self._toast_job)
        self._toast_job = self.root.after(3200, lambda: c.delete("toast"))

    def _save(self):
        save_settings({"budget": self.budget, "minutes": self.minutes, "vibe": self.vibe})

    def quit(self):
        self._save()
        self.root.destroy()


def main(argv: list[str]) -> int:
    try:
        import tkinter as tk
    except ImportError:
        print("Tkinter is missing. Install it with: sudo apt install python3-tk", file=sys.stderr)
        return 1
    try:
        ideas, twists = load_data()
    except (OSError, ValueError) as exc:
        print(f"Couldn't read the date ideas: {exc}", file=sys.stderr)
        return 1

    if "--check" in argv:
        try:
            root = tk.Tk(className="datenight")
            root.withdraw()
            App(root, ideas, twists, weather=False)
            root.update_idletasks()
            root.destroy()
        except tk.TclError as exc:
            print(f"The window couldn't open: {exc}", file=sys.stderr)
            return 1
        print(f"Date Night Picker works: {len(ideas)} ideas loaded, Tk {tk.TkVersion}.")
        return 0

    root = tk.Tk(className="datenight")
    App(root, ideas, twists)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

#!/usr/bin/env python3
"""Date Night Picker: answer three questions, press the button, get a date idea near Fleckney.

Everything runs offline from ideas.json next to this file. Only the Directions button goes online,
by opening Google Maps in your browser. Plain Tkinter, no extra packages, a few MB of RAM.

    python3 datenight.py           open the app
    python3 datenight.py --check   check that the app can start, then exit
"""
from __future__ import annotations

import json
import math
import random
import sys
import webbrowser
from collections import deque
from pathlib import Path
from urllib.parse import quote_plus

HOME_POSTCODE = "LE8 8AL"
IDEAS_FILE = Path(__file__).with_name("ideas.json")
SETTINGS_FILE = Path.home() / ".config" / "datenight" / "settings.json"
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


def pick(candidates: list[dict], recent: deque, rng: random.Random = random) -> dict | None:
    """A random idea, avoiding recent picks while there are other options."""
    if not candidates:
        return None
    fresh = [i for i in candidates if i["name"] not in recent]
    return rng.choice(fresh or candidates)


def directions_url(idea: dict, origin: str = HOME_POSTCODE) -> str | None:
    if not idea.get("maps"):
        return None
    return ("https://www.google.com/maps/dir/?api=1&travelmode=driving"
            f"&origin={quote_plus(origin)}&destination={quote_plus(idea['maps'] + ', UK')}")


def describe_cost(cost: int) -> str:
    return "Free" if cost == 0 else f"About £{cost} for two"


def describe_drive(minutes: int) -> str:
    return "No driving" if minutes == 0 else f"About {minutes} min drive"


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


class App:
    DISC_X, DISC_Y = 238, 370
    RADIUS = 88
    HUB = 30
    SECTORS = {"inside": 90, "chill": 210, "outside": 330}  # start angle of each 120° slice
    CARD_X, CARD_W = 506, 384

    def __init__(self, root, ideas: list[dict], twists: list[str]):
        import tkinter as tk

        self.root = root
        self.ideas = ideas
        self.twists = twists or ["Hold hands the whole time."]
        self.recent: deque = deque(maxlen=30)
        self.spinning = False
        self.current: dict | None = None
        self.floaters: list[list] = []
        self.frame = 0

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
        c.create_text(30, 72, text=f"Made with love, for the two of us  {HEART}  within an hour of "
                                   f"{HOME_POSTCODE}, Fleckney", font=(FONT, 10), fill=MUTED, anchor="w")

        round_rect(c, 24, 96, 452, 600, 26, fill=PANEL, outline=PANEL_EDGE, width=2)
        round_rect(c, 476, 96, 916, 600, 26, fill=PANEL, outline=PANEL_EDGE, width=2)
        c.create_polygon(heart_points(826, 470, 64), smooth=True, fill=BLUSH, outline="")
        c.create_polygon(heart_points(866, 420, 26), smooth=True, fill=BLUSH, outline="")

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
        self.directions = PinkButton(c, (x, 546, x + 130, 582), "Directions", self.open_directions, size=10,
                                     fill=BLUSH, hover=HOT, fg=DEEP)
        self.again = PinkButton(c, (x + 142, 546, x + 290, 582), f"Pick another {HEART}", self.spin, size=10,
                                fill=BLUSH, hover=HOT, fg=DEEP)
        self.directions.set_enabled(False)
        self.again.set_enabled(False)
        self.count = c.create_text(x + self.CARD_W, 124, font=(FONT, 9), fill=MUTED, anchor="ne")

        self._set_budget(self.budget)
        self._set_minutes(self.minutes)
        self._draw_disc()
        self._layout_card()
        self._animate()

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
        choice = pick(candidates, self.recent)
        self.recent.append(choice["name"])
        self.spinning = True
        for button in (self.go, self.again, self.directions):
            button.set_enabled(False)
        self.c.itemconfig(self.kicker, text=f"{HEART} PICKING {HEART}")
        for item in (self.where, self.facts, self.about):
            self.c.itemconfig(item, text="")
        self._hide_twist()
        self._shuffle(candidates, choice, 0)

    def _shuffle(self, candidates, choice, step, frames=18):
        if step < frames:
            self.c.itemconfig(self.name, text=random.choice(candidates)["name"], fill=MUTED)
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

    def _show(self, idea):
        self.current = idea
        c = self.c
        c.itemconfig(self.kicker, text=f"{HEART} TONIGHT'S DATE {HEART}")
        c.itemconfig(self.name, text=idea["name"], fill=INK)
        c.itemconfig(self.where, text=idea["where"])
        vibes = " / ".join(v.capitalize() for v in idea["vibes"])
        c.itemconfig(self.facts, text=f"{describe_drive(idea['minutes'])}   {HEART}   {describe_cost(idea['cost'])}"
                                      f"   {HEART}   {vibes}")
        c.itemconfig(self.about, text=idea["about"])
        c.itemconfig(self.twist, text=f"{HEART} Cute twist: {random.choice(self.twists)}", state="normal")
        c.itemconfig(self.twist_box, state="normal")
        self._layout_card()
        self.go.set_enabled(True)
        self.again.set_enabled(True)
        self.directions.set_enabled(directions_url(idea) is not None)
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
        self.directions.set_enabled(False)
        self.again.set_enabled(False)

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
        url = self.current and directions_url(self.current)
        if url:
            webbrowser.open(url)

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
            App(root, ideas, twists)
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

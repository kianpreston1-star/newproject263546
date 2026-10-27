#!/usr/bin/env python3
"""Date Night Picker: answer three questions, press the button, get a date idea near Fleckney.

Everything runs offline from ideas.json next to this file. Two things go online, and the app works
without them: a weather check at start-up (Open-Meteo, no account needed) and the Directions button,
which opens Google Maps in your browser. Plain Tkinter, no extra packages, a few MB of RAM.

    python3 datenight.py           open the app
    python3 datenight.py --check   check that the app can start, then exit
"""
from __future__ import annotations

import copy
import json
import math
import random
import sys
import threading
import webbrowser
from collections import deque
from datetime import date
from pathlib import Path

from datecore import *  # noqa: F401,F403

HEART_FONT = "DejaVu Sans"  # has the heart glyph, so Tk never falls back to a colour-emoji font
FONT = "Sans"
W, H = 940, 680

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


SYNC_GUIDE_URL = ("https://github.com/kianpreston1-star/newproject263546/blob/claude/determined-bardeen-vvrlm3/"
                  "datenight/sync/README.md")


def _same_memories(a: dict, b: dict) -> bool:
    return json.dumps(sync_shape(a), sort_keys=True) == json.dumps(sync_shape(b), sort_keys=True)


def datetime_now_hm() -> str:
    from datetime import datetime
    return datetime.now().strftime("%H:%M")


class HeartSlider:
    """A pink track with a heart you drag."""

    def __init__(self, c, x, y, length, top, step, value, on_change, bg=PANEL):
        self.c, self.x0, self.x1, self.y = c, x, x + length, y
        self.top, self.step, self.value, self.on_change = top, step, value, on_change
        tag = f"slider{id(self)}"
        c.create_rectangle(x - 12, y - 16, x + length + 12, y + 16, fill=bg, outline="", tags=tag)
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
        self.skipped: set[str] = set()  # "Not this one" for this session only
        self.spinning = False
        self.current: dict | None = None
        self.floaters: list[list] = []
        self.frame = 0
        self.surprise = False
        self.revealed = True
        self.twist_now: str | None = None
        self.rainy = False
        self.weather_result: list = []

        self.settings = saved = load_settings()
        saved.update(shared_values(self.memories))
        self.budget = int(saved.get("budget", 50))
        self.minutes = int(saved.get("minutes", 30))
        self.vibe: str | None = saved.get("vibe") if saved.get("vibe") in VIBES else None
        self.when: str | None = saved.get("when") if saved.get("when") in TIMES else None
        self.sound = bool(saved.get("sound", True)) and weather  # no sounds during --check
        self.hours_result: list = []

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
        self.subtitle = c.create_text(30, 72, font=(FONT, 10), fill=MUTED, anchor="w")

        round_rect(c, 24, 96, 452, 660, 26, fill=PANEL, outline=PANEL_EDGE, width=2)
        round_rect(c, 476, 96, 916, 660, 26, fill=PANEL, outline=PANEL_EDGE, width=2)
        c.create_polygon(heart_points(846, 506, 40), smooth=True, fill=BLUSH, outline="")
        c.create_polygon(heart_points(888, 464, 16), smooth=True, fill=BLUSH, outline="")

        # Header pills and the weather line
        pill = dict(size=9, fill=PANEL, hover=HOT, fg=DEEP)
        PinkButton(c, (452, 18, 542, 46), f"Memories {HEART}", self.open_memories, **pill)
        PinkButton(c, (548, 18, 610, 46), "+ Idea", self.open_add_idea, **pill)
        PinkButton(c, (616, 18, 702, 46), "Both of us", self.open_both, **pill)
        self.surprise_button = PinkButton(c, (708, 18, 782, 46), "Surprise", self.toggle_surprise, **pill)
        PinkButton(c, (788, 18, 858, 46), "Settings", self.open_settings, **pill)
        self.sound_button = PinkButton(c, (864, 18, 916, 46), "", self.toggle_sound, **pill)
        self._refresh_sound()
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

        c.create_text(50, 508, text="4. When?", font=(FONT, 11, "bold"), fill=INK, anchor="w")
        self.time_buttons = {}
        x0 = 50
        for when, label, width in ((None, "Any time", 82), ("day", "Daytime", 90), ("evening", "Evening", 90),
                                   ("late", "Late night", 100)):
            self.time_buttons[when] = PinkButton(c, (x0, 522, x0 + width, 552), label,
                                                 lambda w=when: self._set_when(w), size=9, fill=BLUSH, hover=HOT,
                                                 fg=DEEP)
            x0 += width + 8
        self.go = PinkButton(c, (50, 566, 426, 616), f"{HEART}  Pick our date night  {HEART}", self.spin,
                             size=14, fill=DEEP, hover=DEEPER)
        self.footnote = c.create_text(self.DISC_X, 640, text="or press Enter / Space", font=(FONT, 9), fill=MUTED)
        self.sync_busy = False
        self.sync_again = False
        self.sync_results: list = []
        self._sync_job = None
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
        self.fav = PinkButton(c, (x, 560, x + 90, 594), f"{HEART} Save", self.toggle_favourite, **small)
        self.did = PinkButton(c, (x + 98, 560, x + 188, 594), "We did it!", self.open_did_it, **small)
        self.share = PinkButton(c, (x + 196, 560, x + 286, 594), "Copy for her", self.copy_for_her, **small)
        self.cal = PinkButton(c, (x + 294, 560, x + 384, 594), "Calendar", self.open_calendar, **small)
        self.directions = PinkButton(c, (x, 606, x + 98, 642), "Directions", self.open_directions, size=10,
                                     fill=BLUSH, hover=HOT, fg=DEEP)
        self.nope = PinkButton(c, (x + 104, 606, x + 210, 642), "Not this one", self.not_this_one, size=10,
                               fill=BLUSH, hover=HOT, fg=DEEP)
        self.again = PinkButton(c, (x + 216, 606, x + 318, 642), "Pick another", self.spin, size=10,
                                fill=BLUSH, hover=HOT, fg=DEEP)
        self.hours = PinkButton(c, (x + 324, 606, x + 384, 642), "Open?", self.check_hours, size=10,
                                fill=BLUSH, hover=HOT, fg=DEEP)
        self.surprise_note = c.create_text(x + self.CARD_W, 546, text="", font=(FONT, 9, "italic"),
                                           fill=MUTED, anchor="e")
        self.card_buttons = (self.fav, self.did, self.share, self.cal, self.directions, self.nope, self.again,
                             self.hours)
        for button in self.card_buttons:
            button.set_enabled(False)
        self.count = c.create_text(x + self.CARD_W, 124, font=(FONT, 9), fill=MUTED, anchor="ne")

        self._set_budget(self.budget)
        self._set_minutes(self.minutes)
        self._set_when(self.when)
        self._refresh_subtitle()
        self._draw_disc()
        self._layout_card()
        self._animate()
        if weather:
            threading.Thread(target=lambda: self.weather_result.append(fetch_weather()), daemon=True).start()
            self._wait_for_weather(0)
            if self.settings.get("sync"):
                self._set_sync_status("Syncing...")
                self.schedule_sync(800)
                self.root.after(120_000, self._sync_tick)

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

    def _set_when(self, when):
        self.when = when
        for key, button in self.time_buttons.items():
            button.set_look(HOT if key == when else BLUSH, "white" if key == when else DEEP)
        self._update_count()

    def _still_on(self, ideas):
        return still_on(ideas, self.skipped, self.memories["retired"])

    def _candidates(self):
        return self._still_on(matching(self.ideas, self.budget, self.minutes, self.vibe, self.when,
                                       date.today().month))

    def not_this_one(self):
        if self.spinning or not self.current:
            return
        name = self.current["name"]
        for_good = say_no(self.memories, self.skipped, name)
        if for_good:
            self._store()
        self._update_count()
        self.spin()
        self.toast("You've done that one, so it won't come up again (Memories can bring it back)" if for_good
                   else f"Not that one {HEART} it's out until you next open the app")

    def _weigher(self):
        favourites = set(self.memories["favourites"])
        done = {d["name"] for d in self.memories["done"]}
        month, soon = date.today().month, occasion_soon(self.settings, date.today())
        return lambda i: weight(i, favourites, done, self.rainy, month, soon)

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
        choice = pick(candidates, self.recent, weigh=self._weigher())
        self.recent.append(choice["name"])
        self._start_shuffle(candidates, choice)

    def _start_shuffle(self, candidates, choice, kicker=None):
        self.spinning = True
        self.kicker_label = kicker
        self.beep("spin")
        self.go.set_enabled(False)
        for button in self.card_buttons:
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
            label = getattr(self, "kicker_label", None) or "TONIGHT'S DATE"
            c.itemconfig(self.kicker, text=f"{HEART} {label} {HEART}")
            c.itemconfig(self.name, text=idea["name"], fill=INK)
            c.itemconfig(self.where, text=idea["where"] + ("  (your idea)" if idea.get("mine") else ""))
            past = [d for d in self.memories["done"] if d["name"] == idea["name"]]
            if past:
                facts += f"\nYou've done this before and gave it {past[-1].get('rating', 5)} hearts"
            if self.rainy and "outside" in idea["vibes"] and "inside" not in idea["vibes"]:
                facts += "\nRain is likely today: take a brolly, or pick Inside"
            days, occasion, _ = occasions(self.settings, date.today())[0]
            if days <= 14 and is_special(idea):
                facts += f"\nPerfect for {occasion} ({'today' if days == 0 else f'in {days} days'})"
            if idea.get("months") and len(idea["months"]) <= 3:
                facts += "\nOnly on at this time of year, so make the most of it!"
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
        self.nope.set_enabled(True)
        self.directions.set_text("Directions" if self.revealed else f"Reveal {HEART}")
        self.directions.set_enabled(not self.revealed or directions_url(idea) is not None)
        for button in (self.fav, self.did):
            button.set_enabled(self.revealed)
        self.share.set_enabled(True)
        self.cal.set_enabled(True)
        self.hours.set_enabled(self.revealed and bool(idea.get("maps")))
        self._refresh_fav()
        if new_twist:
            self.beep("chime")
            bbox = c.bbox(self.name)
            self._burst((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)

    def _show_none(self):
        self.current = None
        c = self.c
        c.itemconfig(self.kicker, text=f"{HEART} NOTHING MATCHES {HEART}")
        c.itemconfig(self.name, text="No ideas fit that yet", fill=INK)
        c.itemconfig(self.where, text="")
        c.itemconfig(self.facts, text="")
        said_no = matching(self.ideas, self.budget, self.minutes, self.vibe, self.when, date.today().month)
        c.itemconfig(self.about, text="You've said no to everything that fits. Bring them back in Memories, or "
                                      "change your answers." if said_no else
                     "Try a bigger budget, a longer drive, or click the heart in the middle of the disc for any vibe.")
        self._hide_twist()
        self._layout_card()
        for button in self.card_buttons:
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
        if self.settings.get("sync"):
            self.schedule_sync(3000)

    def toggle_favourite(self):
        name = self.current["name"]
        favs = self.memories["favourites"]
        if name in favs:
            set_flag(self.memories, "favourites", name, False)
            self.toast("Removed from favourites")
        else:
            set_flag(self.memories, "favourites", name, True)
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
        self.open_log(idea=self.current)

    def _pick_photos(self, parent) -> list[Path]:
        from tkinter import filedialog
        pictures = Path.home() / "Pictures"
        paths = filedialog.askopenfilenames(parent=parent, title="Pick photos from the date",
                                            initialdir=str(pictures if pictures.is_dir() else Path.home()),
                                            filetypes=[("Photos", "*.jpg *.jpeg *.png *.gif *.webp *.JPG *.JPEG *.PNG"),
                                                       ("All files", "*")])
        return [Path(p) for p in paths]

    def open_log(self, idea=None, index=None, after=None):
        """One dialog for "We did it!" (idea given), logging any date (nothing given) and editing (index given)."""
        tk = self.tk
        entry = dict(self.memories["done"][index]) if index is not None else {}
        if idea:
            entry = {"name": idea["name"], "where": idea["where"], "cost": idea["cost"], "vibes": list(idea["vibes"])}
        title = "Edit this date" if index is not None else "We did it!" if idea else "Log a date"
        win = self._dialog(title, 460, 560)
        form = tk.Frame(win, bg=PANEL)
        form.pack(fill="both", expand=True, padx=22)
        form.columnconfigure(1, weight=1)
        style = dict(font=(FONT, 11), relief="flat", bg="white", fg=INK, highlightthickness=1,
                     highlightbackground=PANEL_EDGE, highlightcolor=HOT, insertbackground=DEEP)
        label = dict(font=(FONT, 10, "bold"), fg=INK, bg=PANEL, anchor="w")
        fields = {}
        when = date.fromisoformat(entry["date"]) if entry.get("date") else date.today()
        for row, (key, text, value) in enumerate([
                ("name", "What did you do?", entry.get("name", "")), ("where", "Where", entry.get("where", "")),
                ("date", "When (DD/MM/YYYY)", when.strftime("%d/%m/%Y")), ("cost", "Spent (£, roughly)",
                                                                             str(entry.get("cost", 0)))]):
            tk.Label(form, text=text, **label).grid(row=row, column=0, sticky="w", pady=5)
            fields[key] = tk.Entry(form, **style)
            fields[key].insert(0, value)
            fields[key].grid(row=row, column=1, sticky="ew", padx=(10, 0), ipady=3)
        tk.Label(form, text="How was it?", **label).grid(row=4, column=0, sticky="w", pady=(8, 0))
        rating = tk.IntVar(value=int(entry.get("rating", 5)))
        hearts = tk.Canvas(form, width=230, height=44, bg=PANEL, highlightthickness=0, cursor="hand2")
        hearts.grid(row=4, column=1, sticky="w", pady=(8, 0))

        def draw(*_):
            hearts.delete("all")
            for k in range(5):
                hearts.create_text(22 + k * 44, 22, text=HEART, font=(HEART_FONT, 26),
                                   fill=DEEP if k < rating.get() else DIM)
        hearts.bind("<Button-1>", lambda e: (rating.set(min(5, max(1, e.x // 44 + 1))), draw()))
        draw()
        tk.Label(form, text="A little note to remember it by", **label).grid(row=5, column=0, columnspan=2,
                                                                             sticky="w", pady=(8, 2))
        note = tk.Text(form, height=3, wrap="word", **style)
        note.insert("1.0", entry.get("note", ""))
        note.grid(row=6, column=0, columnspan=2, sticky="ew")
        tk.Label(form, text="Vibe", **label).grid(row=7, column=0, sticky="w", pady=(8, 0))
        checks = tk.Frame(form, bg=PANEL)
        checks.grid(row=7, column=1, sticky="w", pady=(8, 0), padx=(6, 0))
        vibe_vars = {}
        for v in VIBES:
            vibe_vars[v] = tk.BooleanVar(value=v in entry.get("vibes", []))
            tk.Checkbutton(checks, text=v.capitalize(), variable=vibe_vars[v], font=(FONT, 10), bg=PANEL, fg=INK,
                           activebackground=PANEL, selectcolor="white", highlightthickness=0).pack(side="left")
        chosen: list[Path] = []
        have = len(entry_photos(entry))
        photo_row = tk.Frame(form, bg=PANEL)
        photo_row.grid(row=8, column=0, columnspan=2, sticky="w", pady=(12, 0))
        photo_label = tk.Label(photo_row, font=(FONT, 9), fg=MUTED, bg=PANEL)

        def show_count():
            parts = [f"{have} photo{'s' if have != 1 else ''} already"] if have else []
            if chosen:
                parts.append(f"{len(chosen)} new photo{'s' if len(chosen) != 1 else ''} to add")
            photo_label.config(text=", ".join(parts) or "No photos yet")

        def add_photos():
            chosen.extend(p for p in self._pick_photos(win) if p not in chosen)
            show_count()
        self._button(photo_row, "Add photos", add_photos, primary=False).pack(side="left")
        photo_label.pack(side="left", padx=10)
        show_count()
        error = tk.Label(form, text="", font=(FONT, 9), fg=DEEP, bg=PANEL)
        error.grid(row=9, column=0, columnspan=2, sticky="w", pady=(6, 0))
        fields["name"].focus_set()

        def save(*_):
            name = fields["name"].get().strip()
            day = parse_uk_date(fields["date"].get())
            try:
                cost = max(0, int(float(fields["cost"].get().strip().lstrip("£") or 0)))
            except ValueError:
                cost = None
            if not name:
                return error.config(text="Say what you did.")
            if not day or day > date.today():
                return error.config(text="Use a date like 14/02/2026 that isn't in the future.")
            if cost is None:
                return error.config(text="Spent should be a number of pounds.")
            new = dict(entry, name=name, where=fields["where"].get().strip(), date=day.isoformat(),
                       rating=rating.get(), note=note.get("1.0", "end").strip(), cost=cost,
                       vibes=[v for v in VIBES if vibe_vars[v].get()], updated=now_stamp())
            if index is None:
                new["id"] = new_entry_id()
            photos = entry_photos(entry)
            for path in chosen:
                saved_name = save_photo(path, new["date"], name)
                if saved_name:
                    photos.append(saved_name)
                else:
                    self.toast(f"Couldn't copy {path.name}")
            new = normalise_entry(dict(new, photos=photos))
            done = self.memories["done"]
            if index is None:
                done.append(new)
            else:
                done[index] = new
            done.sort(key=lambda d: d.get("date", ""))
            self._store()
            win.destroy()
            if idea and self.current is idea:
                self._show(idea, new_twist=False, reveal=True)
            if after:
                after()
            milestone = new_milestone(len(done)) if index is None else None
            if milestone:
                self.beep("yay")
                for k in range(3):
                    self.root.after(k * 250, lambda: self._burst(W / 2 + random.uniform(-200, 200),
                                                                 H / 2 + random.uniform(-100, 100)))
                self.toast(f"{HEART} New badge: {milestone}! {len(done)} date{'s' if len(done) != 1 else ''} logged {HEART}")
            else:
                self.toast(f"Saved to your memories {HEART}" if index is None else f"Updated {HEART}")
        row = tk.Frame(win, bg=PANEL)
        row.pack(fill="x", padx=22, pady=16)
        self._button(row, f"Save memory {HEART}", save).pack(side="right")
        self._button(row, "Cancel", win.destroy, primary=False).pack(side="right", padx=8)

    def open_memories(self, scroll: float = 0.0):
        tk = self.tk
        win = self._dialog(f"Our memories {HEART}", 620, 640)
        done = self.memories["done"]
        today = date.today()

        def refresh():
            position = text.yview()[0]
            win.destroy()
            self.open_memories(position)

        def add_photos(i):
            paths = self._pick_photos(win)
            if not paths:
                return
            entry = done[i]
            photos = entry_photos(entry)
            for path in paths:
                saved_name = save_photo(path, entry.get("date", today.isoformat()), entry["name"])
                if saved_name:
                    photos.append(saved_name)
            done[i] = normalise_entry(dict(entry, photos=photos, updated=now_stamp()))
            self._store()
            refresh()
            self.toast(f"Added {len(paths)} photo{'s' if len(paths) != 1 else ''} {HEART}")

        def remove_photo(i, name):
            from tkinter import messagebox
            if not messagebox.askyesno("Remove photo", "Remove this photo from the date?", parent=win):
                return
            done[i] = normalise_entry(dict(done[i], photos=[p for p in entry_photos(done[i]) if p != name],
                                           updated=now_stamp()))
            self._store()
            forget_photo(self.memories, name)
            refresh()

        def delete(i):
            from tkinter import messagebox
            if not messagebox.askyesno("Delete date", f"Delete “{done[i]['name']}” and its photos?",
                                       parent=win):
                return
            gone = delete_entry(self.memories, done[i]["id"])
            self._store()
            for name in entry_photos(gone):
                forget_photo(self.memories, name)
            refresh()
            self.toast("Deleted")

        tk.Label(win, text=memory_stats(done), font=(FONT, 10), fg=MUTED, bg=PANEL,
                 wraplength=570, justify="left").pack(anchor="w", padx=22)
        streak, month_count = date_streak(done, today), dates_this_month(done, today)
        tk.Label(win, text=f"This month: {month_count} date{'s' if month_count != 1 else ''}"
                           f"  {HEART}  Streak: {streak} week{'s' if streak != 1 else ''} in a row",
                 font=(FONT, 10, "bold"), fg=DEEP, bg=PANEL).pack(anchor="w", padx=22, pady=(4, 0))
        frame = tk.Frame(win, bg=PANEL)
        frame.pack(fill="both", expand=True, padx=22, pady=10)
        text = tk.Text(frame, font=(FONT, 11), bg="white", fg=INK, relief="flat", wrap="word", padx=12, pady=10,
                       highlightthickness=1, highlightbackground=PANEL_EDGE, cursor="arrow", height=8)
        bar = tk.Scrollbar(frame, command=text.yview, troughcolor=BLUSH, bg=TRACK, activebackground=HOT,
                           relief="flat", bd=0)
        text.config(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        text.tag_config("h", font=(FONT, 12, "bold"), foreground=DEEP, spacing1=6, spacing3=4)
        text.tag_config("hearts", font=(HEART_FONT, 11), foreground=DEEP)
        text.tag_config("muted", foreground=MUTED, font=(FONT, 9))
        text.tag_config("b", font=(FONT, 11, "bold"))
        text.tag_config("note", font=(FONT, 10, "italic"), foreground=DEEPER)
        text.tag_config("gap", spacing3=14)

        def small(label, command, primary=False):
            return tk.Button(text, text=label, command=command, font=(FONT, 8, "bold"), relief="flat", bd=0,
                             bg=DEEP if primary else BLUSH, fg="white" if primary else DEEP,
                             activebackground=HOT, activeforeground="white", padx=8, pady=2, cursor="hand2",
                             highlightthickness=0)

        earned = badges(len(done))
        upcoming = next((f"{n - len(done)} more for “{name}”" for n, name in MILESTONES.items()
                         if n > len(done)), "every badge earned!")
        text.insert("end", "Badges\n", "h")
        text.insert("end", ("  ".join(f"{HEART} {b}" for b in earned) or "None yet") + "\n", "b")
        text.insert("end", f"Next: {upcoming}\n\n", "muted")
        text.insert("end", "Dates we've done   ", "h")
        text.window_create("end", window=small(f"+ Log a date {HEART}", lambda: self.open_log(after=refresh),
                                               primary=True))
        text.insert("end", "\n", "h")
        self._thumbs = []
        if not done:
            text.insert("end", "Nothing yet. Press “+ Log a date” to add one you've been on, or "
                               "“We did it!” after a pick.\n\n", "muted")
        for i in reversed(range(len(done))):
            d = done[i]
            r = int(d.get("rating", 5))
            try:
                when = date.fromisoformat(d["date"]).strftime("%a %d %b %Y")
            except (KeyError, ValueError):
                when = ""
            text.insert("end", HEART * r + "♡" * (5 - r), "hearts")
            text.insert("end", f"   {when}\n", "muted")
            text.insert("end", f"{d['name']}", "b")
            text.insert("end", f"  ({d['where']})\n" if d.get("where") else "\n")
            if d.get("note"):
                text.insert("end", f"“{d['note']}”\n", "note")
            photos = entry_photos(d)
            hidden = 0
            for name in photos:
                thumb = self._thumbnail(PHOTOS_DIR / name)
                if thumb:
                    self._thumbs.append(thumb)
                    text.image_create("end", image=thumb, padx=2, pady=4)
                    text.window_create("end", window=small("×", lambda i=i, n=name: remove_photo(i, n)))
                    text.insert("end", "  ")
                else:
                    hidden += 1
            if photos:
                text.insert("end", "\n")
            if hidden:
                text.insert("end", f"{hidden} photo{'s' if hidden != 1 else ''} saved (install python3-pil.imagetk "
                                   "to see JPEGs here; they show in the year in review)\n", "muted")
            for label, command in ((f"Add photos ({len(photos)})" if photos else "Add photos",
                                    lambda i=i: add_photos(i)),
                                   ("Edit", lambda i=i: self.open_log(index=i, after=refresh)),
                                   ("Delete", lambda i=i: delete(i))):
                text.window_create("end", window=small(label, command), padx=2)
            text.insert("end", "\n", "gap")

        by_name = {i["name"]: i for i in self.ideas}
        favs = self._still_on([by_name[n] for n in self.memories["favourites"] if n in by_name])

        def bring(names):
            for n in names:
                bring_back(self.memories, self.skipped, n)
            self._store()
            self._update_count()
            refresh()
            self.toast(f"Back in the mix {HEART}")
        if self.skipped - set(self.memories["retired"]):
            today_only = sorted(self.skipped - set(self.memories["retired"]))
            text.insert("end", "\nSkipped today   ", "h")
            text.window_create("end", window=small("Bring them all back", lambda: bring(today_only)))
            text.insert("end", "\n" + ", ".join(today_only) + "\n", "muted")
            text.insert("end", "They come back by themselves next time you open the app.\n", "muted")
        if self.memories["retired"]:
            text.insert("end", "\nSaid no to for good\n", "h")
            text.insert("end", "Dates you'd already done and said \u201cNot this one\u201d to.\n", "muted")
            for n in list(self.memories["retired"]):
                text.insert("end", f"{n}  ")
                text.window_create("end", window=small("Bring back", lambda n=n: bring([n])))
                text.insert("end", "\n")
        text.insert("end", "\nOur favourites\n", "h")
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
        if scroll:
            win.after(50, lambda: text.yview_moveto(scroll))

        tools = tk.Frame(win, bg=PANEL)
        tools.pack(fill="x", padx=22, pady=(0, 8))
        self._button(tools, f"Our {today.year} in review", lambda: self.year_review(today.year),
                     primary=False).pack(side="left")
        self._button(tools, "Back up", lambda: self.back_up(win), primary=False).pack(side="left", padx=8)
        self._button(tools, "Restore", lambda: self.restore(win), primary=False).pack(side="left")
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
            self.memories.setdefault("stamps", {})[f"my_ideas:{name}"] = [True, now_stamp()]
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

    def _thumbnail(self, path: Path):
        """A small version of a photo for the memories window, or None if it can't be shown."""
        if not path.is_file():
            return None
        try:
            from PIL import Image, ImageTk  # optional: sudo apt install python3-pil.imagetk
            img = Image.open(path)
            img.thumbnail((240, 180))
            return ImageTk.PhotoImage(img)
        except Exception:  # noqa: BLE001 - Pillow missing or a broken file: fall back below
            pass
        if path.suffix.lower() not in (".png", ".gif"):
            return None
        try:
            img = self.tk.PhotoImage(file=str(path))
            factor = max(1, -(-img.width() // 240), -(-img.height() // 180))
            return img.subsample(factor) if factor > 1 else img
        except self.tk.TclError:
            return None

    def year_review(self, year):
        names = (self.settings.get("your_name", ""), self.settings.get("her_name", ""))
        path = desktop_dir() / f"our-{year}-in-dates.html"
        try:
            path.write_text(year_review_html(self.memories["done"], year, names), encoding="utf-8")
        except OSError:
            self.toast("Couldn't save the year in review")
            return
        webbrowser.open(path.as_uri())
        self.toast(f"Saved {path.name}: print it, or save it as a PDF from the browser")

    def back_up(self, parent):
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(parent=parent, title="Back up our memories",
                                            initialdir=str(desktop_dir()), defaultextension=".json",
                                            initialfile=f"date-night-backup-{date.today().isoformat()}.json",
                                            filetypes=[("Date Night backup", "*.json")])
        if not path:
            return
        try:
            Path(path).write_text(json.dumps(make_backup(self.memories)), encoding="utf-8")
        except OSError:
            self.toast("Couldn't save the backup there")
            return
        self.toast(f"Backed up to {Path(path).name}. Keep a copy on a USB stick or Google Drive")

    def restore(self, parent):
        from tkinter import filedialog
        path = filedialog.askopenfilename(parent=parent, title="Restore a backup", initialdir=str(desktop_dir()),
                                          filetypes=[("Date Night backup", "*.json"), ("All files", "*")])
        if not path:
            return
        try:
            backup = json.loads(Path(path).read_text(encoding="utf-8"))
            merged, added = restore_backup(backup, self.memories)
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            self.toast(f"Couldn't restore: {exc}" if isinstance(exc, ValueError) and "backup" in str(exc)
                       else "Couldn't read that backup file")
            return
        self.memories = merged
        self._store()
        self.ideas = merge_my_ideas(self.ideas, merged["my_ideas"])
        self._update_count()
        parent.destroy()
        self.open_memories()
        self.toast(f"Restored {added} new thing{'s' if added != 1 else ''} from the backup {HEART}")

    # Sound

    def beep(self, name):
        if self.sound:
            play_sound(name)

    def _refresh_sound(self):
        self.sound_button.set_text("\u266a On" if self.sound else "\u266a Off")
        self.sound_button.set_look(PANEL if self.sound else OFF, DEEP if self.sound else "white")

    def toggle_sound(self):
        self.sound = not self.sound
        self._refresh_sound()
        self._save()
        if self.sound and sound_player() is None:
            self.toast("Sound on, but this computer has no sound player (pw-play, paplay or aplay)")
            return
        self.beep("chime")
        self.toast("Sound on" if self.sound else "Sound off")

    # Opening hours

    def check_hours(self):
        idea = self.current
        self.hours.set_enabled(False)
        self.hours.set_text("Checking")
        self.hours_result = []
        threading.Thread(target=lambda: self.hours_result.append(fetch_opening_hours(idea)), daemon=True).start()
        self._wait_for_hours(idea, 0)

    def _wait_for_hours(self, idea, tries):
        if not self.hours_result and tries < 100:
            self.root.after(250, self._wait_for_hours, idea, tries + 1)
            return
        self.hours.set_text("Open?")
        self.hours.set_enabled(self.current is idea)
        found = self.hours_result[0] if self.hours_result else None
        if self.current is not idea:
            return
        if not found:
            webbrowser.open(hours_search_url(idea))
            self.toast("Not listed on OpenStreetMap, so I've opened a search for its opening times")
            return
        name, raw = found
        today = hours_on(raw, date.today())
        if today is None:
            self.toast(f"{name}: {raw[:70]}")
        elif today == "closed":
            self.toast(f"{name} looks closed today. Check their website to be sure")
        else:
            self.toast(f"{name} is open {today} today (from OpenStreetMap)")

    # Settings and "both of us"

    def _refresh_subtitle(self):
        you, her = self.settings.get("your_name"), self.settings.get("her_name")
        who = f"for {you} & {her}" if you and her else "for the two of us"
        self.c.itemconfig(self.subtitle, text=f"Made with love, {who}  {HEART}  {countdown_text(self.settings, date.today())}")

    def open_settings(self):
        tk = self.tk
        win = self._dialog(f"Settings {HEART}", 440, 540)
        form = tk.Frame(win, bg=PANEL)
        form.pack(fill="both", expand=True, padx=22)
        entry = dict(font=(FONT, 11), relief="flat", bg="white", fg=INK, highlightthickness=1,
                     highlightbackground=PANEL_EDGE, highlightcolor=HOT, insertbackground=DEEP, width=16)
        label = dict(font=(FONT, 10, "bold"), fg=INK, bg=PANEL, anchor="w")
        fields = {}
        rows = [("your_name", "Your name"), ("her_name", "Her name"),
                ("anniversary", "Anniversary (DD/MM/YYYY)"), ("her_birthday", "Her birthday (DD/MM/YYYY)"),
                ("your_birthday", "Your birthday (DD/MM/YYYY)")]
        for row, (key, text) in enumerate(rows):
            tk.Label(form, text=text, **label).grid(row=row, column=0, sticky="w", pady=6)
            fields[key] = tk.Entry(form, **entry)
            fields[key].grid(row=row, column=1, sticky="e", ipady=3, padx=(10, 0))
            value = self.settings.get(key, "")
            if key.endswith(("anniversary", "birthday")) and value:
                try:
                    value = date.fromisoformat(value).strftime("%d/%m/%Y")
                except ValueError:
                    pass
            fields[key].insert(0, value)
        sound = tk.BooleanVar(value=self.sound)
        tk.Checkbutton(form, text="Play little sounds when picking", variable=sound, font=(FONT, 10), bg=PANEL,
                       fg=INK, activebackground=PANEL, selectcolor="white",
                       highlightthickness=0).grid(row=len(rows), column=0, columnspan=2, sticky="w", pady=(10, 0))
        tk.Label(form, text="Dates power the countdown at the top, and special dates come up more often in the "
                            "two weeks before.", font=(FONT, 9), fg=MUTED, bg=PANEL, wraplength=390,
                 justify="left").grid(row=len(rows) + 1, column=0, columnspan=2, sticky="w", pady=(10, 0))
        sync_row = tk.Frame(form, bg=PANEL)
        sync_row.grid(row=len(rows) + 2, column=0, columnspan=2, sticky="w", pady=(12, 0))
        self._button(sync_row, f"Sync between our devices {HEART}", lambda: (win.destroy(), self.open_sync()),
                     primary=False).pack(side="left")
        tk.Label(sync_row, text="On" if self.settings.get("sync") else "Off", font=(FONT, 9, "bold"),
                 fg=DEEP if self.settings.get("sync") else MUTED, bg=PANEL).pack(side="left", padx=10)
        error = tk.Label(form, text="", font=(FONT, 9), fg=DEEP, bg=PANEL)
        error.grid(row=len(rows) + 3, column=0, columnspan=2, sticky="w", pady=(6, 0))

        def save(*_):
            values = {}
            for key, field in fields.items():
                text = field.get().strip()
                if key.endswith(("anniversary", "birthday")) and text:
                    parsed = parse_uk_date(text)
                    if not parsed:
                        return error.config(text=f"Couldn't read the date \u201c{text}\u201d. Use DD/MM/YYYY.")
                    text = parsed.isoformat()
                values[key] = text
            self.settings.update(values)
            for key, value in values.items():
                if key in SHARED_SETTINGS and value != shared_values(self.memories).get(key):
                    set_shared(self.memories, key, value)
            self._store()
            self.sound = sound.get()
            self._refresh_sound()
            self._save()
            self._refresh_subtitle()
            win.destroy()
            self.toast(f"Saved {HEART} {countdown_text(self.settings, date.today())}")
        win.bind("<Return>", save)
        row = tk.Frame(win, bg=PANEL)
        row.pack(fill="x", padx=22, pady=16)
        self._button(row, f"Save {HEART}", save).pack(side="right")
        self._button(row, "Cancel", win.destroy, primary=False).pack(side="right", padx=8)

    def open_both(self):
        tk = self.tk
        win = self._dialog(f"Both say yes {HEART}", 560, 470)
        tk.Label(win, text="Each of you answers on your own side. The app only picks dates you'd both say yes to.",
                 font=(FONT, 10), fg=MUTED, bg=PANEL, wraplength=510, justify="left").pack(anchor="w", padx=22)
        sides = tk.Frame(win, bg=PANEL)
        sides.pack(fill="both", expand=True, padx=22, pady=10)
        saved = self.settings.get("both", {})
        prefs = {}
        names = (self.settings.get("your_name") or "You", self.settings.get("her_name") or "Her")
        for col, (key, name) in enumerate(zip(("a", "b"), names)):
            box = tk.Frame(sides, bg="white", highlightthickness=1, highlightbackground=PANEL_EDGE)
            box.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 6, 6 if col == 0 else 0))
            sides.columnconfigure(col, weight=1)
            mine = saved.get(key, {})
            tk.Label(box, text=f"{HEART} {name}", font=(FONT, 13, "bold"), fg=DEEP, bg="white").pack(anchor="w",
                                                                                                padx=12, pady=(10, 4))
            budget = tk.IntVar(value=int(mine.get("budget", self.budget)))
            minutes = tk.IntVar(value=int(mine.get("minutes", self.minutes)))
            for text, var, top, fmt in (
                    ("Spend up to", budget, BUDGET_MAX,
                     lambda v: f"£{BUDGET_MAX}+" if v >= BUDGET_MAX else "Free" if v == 0 else f"£{v}"),
                    ("Drive up to", minutes, DRIVE_MAX, lambda v: "Home" if v == 0 else f"{v} min")):
                tk.Label(box, text=text, font=(FONT, 9, "bold"), fg=INK, bg="white").pack(anchor="w", padx=12)
                canvas = tk.Canvas(box, width=236, height=36, bg="white", highlightthickness=0)
                canvas.pack(anchor="w", padx=6)
                shown = canvas.create_text(232, 18, text=fmt(var.get()), font=(FONT, 10, "bold"), fill=DEEP,
                                           anchor="e")
                HeartSlider(canvas, 16, 18, 150, top, 5, var.get(),
                            lambda v, var=var, canvas=canvas, shown=shown, fmt=fmt: (
                                var.set(v), canvas.itemconfig(shown, text=fmt(v))), bg="white")
            tk.Label(box, text="Happy with", font=(FONT, 9, "bold"), fg=INK, bg="white").pack(anchor="w", padx=12,
                                                                                              pady=(4, 0))
            vibes = {}
            for v in VIBES:
                vibes[v] = tk.BooleanVar(value=v in mine.get("vibes", VIBES))
                tk.Checkbutton(box, text=v.capitalize(), variable=vibes[v], font=(FONT, 10), bg="white", fg=INK,
                               activebackground="white", selectcolor="white",
                               highlightthickness=0).pack(anchor="w", padx=12)
            tk.Frame(box, bg="white", height=8).pack()
            prefs[key] = (budget, minutes, vibes)
        error = tk.Label(win, text="", font=(FONT, 9), fg=DEEP, bg=PANEL, wraplength=510, justify="left")
        error.pack(anchor="w", padx=22)

        def go(*_):
            answers = {k: {"budget": b.get(), "minutes": m.get(), "vibes": [v for v, on in vs.items() if on.get()]}
                       for k, (b, m, vs) in prefs.items()}
            self.settings["both"] = answers
            set_shared(self.memories, "both", answers)
            self._store()
            self._save()
            candidates = self._still_on(both_match(self.ideas, answers["a"], answers["b"], self.when,
                                                   date.today().month))
            if not candidates:
                return error.config(text="Nothing fits you both yet. Try a bigger budget, a longer drive or more vibes.")
            win.destroy()
            if self.spinning:
                return
            choice = pick(candidates, self.recent, weigh=self._weigher())
            self.recent.append(choice["name"])
            self._start_shuffle(candidates, choice, kicker="YOU BOTH SAID YES")
        row = tk.Frame(win, bg=PANEL)
        row.pack(fill="x", padx=22, pady=(4, 16))
        self._button(row, f"Find a date we both love {HEART}", go).pack(side="right")
        self._button(row, "Cancel", win.destroy, primary=False).pack(side="right", padx=8)

    # Syncing between devices

    def _set_sync_status(self, text):
        self.c.itemconfig(self.footnote, text=f"{HEART} {text}" if text else "or press Enter / Space")

    def _sync_tick(self):
        if self.settings.get("sync"):
            self.schedule_sync(0)
        self.root.after(120_000, self._sync_tick)

    def schedule_sync(self, delay_ms=0):
        if self._sync_job:
            self.root.after_cancel(self._sync_job)
        self._sync_job = self.root.after(delay_ms, self._start_sync)

    def _start_sync(self):
        self._sync_job = None
        config = self.settings.get("sync")
        if not config:
            return
        if self.sync_busy:
            self.sync_again = True
            return
        self.sync_busy = True
        self._set_sync_status("Syncing...")
        snapshot = copy.deepcopy(self.memories)
        client = SyncClient(config["url"], config["key"], config["code"])

        def work():
            try:
                self.sync_results.append(("ok", snapshot, *sync_once(client, snapshot)))
            except SyncError as exc:
                self.sync_results.append(("error", snapshot, str(exc), None))
            except Exception as exc:  # noqa: BLE001 - report anything unexpected rather than dying quietly
                self.sync_results.append(("error", snapshot, f"Sync failed: {exc}", None))
        threading.Thread(target=work, daemon=True).start()
        self._wait_for_sync()

    def _wait_for_sync(self):
        if not self.sync_results:
            self.root.after(300, self._wait_for_sync)
            return
        status, snapshot, result, stats = self.sync_results.pop(0)
        self.sync_busy = False
        if status == "error":
            self._set_sync_status(result)
            self.root.after(60_000, lambda: self.settings.get("sync") and self.schedule_sync(0))
            return
        changed_here = not _same_memories(snapshot, self.memories)  # edits made while syncing
        merged = merge_sync(self.memories, result) if changed_here else result
        new_things = count_changes(self.memories, merged)
        self.memories = merged
        save_memories(self.memories)
        self._apply_synced()
        when = datetime_now_hm()
        extra = f", {stats['too_big']} photo(s) too big to send" if stats.get("too_big") else ""
        self._set_sync_status(f"Synced at {when}{extra}")
        if new_things:
            self.toast(f"Synced {HEART} {new_things} new thing{'s' if new_things != 1 else ''} from your other devices")
        if changed_here or self.sync_again:
            self.sync_again = False
            self.schedule_sync(1500)

    def _apply_synced(self):
        shared = shared_values(self.memories)
        if any(self.settings.get(k) != v for k, v in shared.items()):
            self.settings.update(shared)
            save_settings(self.settings)
            self._refresh_subtitle()
        self.ideas = merge_my_ideas(self.ideas, self.memories["my_ideas"])
        mine = {i["name"] for i in self.memories["my_ideas"]}
        self.ideas = [i for i in self.ideas if not i.get("mine") or i["name"] in mine]
        self._update_count()
        if self.current:
            self._refresh_fav()

    def open_sync(self):
        tk = self.tk
        config = self.settings.get("sync")
        win = self._dialog(f"Sync between our devices {HEART}", 520, 520)
        body = tk.Frame(win, bg=PANEL)
        body.pack(fill="both", expand=True, padx=22)
        entry = dict(font=(FONT, 10), relief="flat", bg="white", fg=INK, highlightthickness=1,
                     highlightbackground=PANEL_EDGE, highlightcolor=HOT, insertbackground=DEEP)
        say = lambda text, **kw: tk.Label(body, text=text, font=kw.pop("font", (FONT, 10)), fg=kw.pop("fg", INK),  # noqa: E731
                                          bg=PANEL, wraplength=470, justify="left", **kw)
        error = tk.Label(body, text="", font=(FONT, 9), fg=DEEP, bg=PANEL, wraplength=470, justify="left")

        def copy_text(text):
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.toast("Copied! Send it to her phone and paste it into the app's Settings, then Sync")

        if config:
            pairing = make_pairing(config)
            say("Sync is on. Dates, photos, favourites, your own ideas, names and dates stay the same on every "
                "device that has this pairing text.").pack(anchor="w", pady=(0, 8))
            say("Pairing text (treat it like a password):", font=(FONT, 10, "bold")).pack(anchor="w")
            box = tk.Text(body, height=4, wrap="char", **entry)
            box.insert("1.0", pairing)
            box.config(state="disabled")
            box.pack(fill="x", pady=(2, 6))
            say("To add a phone: send this text to it (WhatsApp works), then in the phone app open Settings, "
                "tap Sync between our devices, paste it and tap Join.", fg=MUTED).pack(anchor="w")
            status = self.c.itemcget(self.footnote, "text")
            say(status if status.startswith(HEART) else "Waiting for the first sync", fg=DEEP,
                font=(FONT, 10, "bold")).pack(anchor="w", pady=8)
            row = tk.Frame(body, bg=PANEL)
            row.pack(fill="x", pady=4)
            self._button(row, "Copy pairing text", lambda: copy_text(pairing)).pack(side="left")
            self._button(row, "Sync now", lambda: (self.schedule_sync(0), win.destroy()),
                         primary=False).pack(side="left", padx=8)

            def stop():
                from tkinter import messagebox
                if messagebox.askyesno("Stop syncing", "Stop syncing on this laptop? Everything already here "
                                       "stays here, and the phones keep syncing with each other.", parent=win):
                    self.settings.pop("sync", None)
                    save_settings(self.settings)
                    self._set_sync_status("")
                    win.destroy()
                    self.toast("Sync is off on this laptop")
            self._button(row, "Stop syncing here", stop, primary=False).pack(side="left")
        else:
            say("Keep your dates, photos and favourites the same on both phones and this laptop. It uses your own "
                "free Supabase project; setting it up takes about 5 minutes and is explained in "
                "datenight/sync/README.md.").pack(anchor="w")
            link = tk.Label(body, text="Open the setup guide", font=(FONT, 10, "underline"), fg=DEEP, bg=PANEL,
                            cursor="hand2")
            link.pack(anchor="w", pady=(2, 10))
            link.bind("<Button-1>", lambda _e: webbrowser.open(SYNC_GUIDE_URL))
            say("Already set up on another device? Paste its pairing text:", font=(FONT, 10, "bold")).pack(anchor="w")
            paste = tk.Entry(body, **entry)
            paste.pack(fill="x", ipady=3, pady=(2, 4))
            say("First device? Enter your Supabase details:", font=(FONT, 10, "bold")).pack(anchor="w", pady=(12, 0))
            fields = {}
            for key, text in (("url", "Project URL (like https://abcd1234.supabase.co)"),
                              ("key", "Publishable or anon key")):
                say(text, fg=MUTED, font=(FONT, 9)).pack(anchor="w")
                fields[key] = tk.Entry(body, **entry)
                fields[key].pack(fill="x", ipady=3, pady=(0, 4))

            def connect(new_config, creating):
                error.config(text="Checking...")
                win.update()
                client = SyncClient(new_config["url"], new_config["key"], new_config["code"], timeout=15)
                try:
                    _doc, _photos, version = client.pull()
                except SyncError as exc:
                    return error.config(text=str(exc))
                if creating and version:
                    return error.config(text="That sync code is already in use. Try again.")
                self.settings["sync"] = new_config
                save_settings(self.settings)
                win.destroy()
                self.schedule_sync(0)
                self.root.after(120_000, self._sync_tick)
                self.open_sync()
                self.toast(f"Sync is on {HEART}")

            def join():
                parsed = parse_pairing(paste.get())
                if not parsed:
                    return error.config(text="That doesn't look like a pairing text. Copy the whole thing, "
                                             "starting with datenight-sync:")
                connect(parsed, creating=False)

            def create():
                url, key = clean_url(fields["url"].get()), fields["key"].get().strip()
                if not url or not key:
                    return error.config(text="Fill in both the project URL and the key.")
                connect({"url": url, "key": key, "code": new_sync_code()}, creating=True)
            row = tk.Frame(body, bg=PANEL)
            row.pack(fill="x", pady=(8, 0))
            self._button(row, "Join", join).pack(side="left")
            self._button(row, "Create our sync", create).pack(side="left", padx=8)
        error.pack(anchor="w", pady=(8, 0))
        bottom = tk.Frame(win, bg=PANEL)
        bottom.pack(fill="x", padx=22, pady=14)
        self._button(bottom, "Close", win.destroy, primary=False).pack(side="right")

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
        self.settings.update({"budget": self.budget, "minutes": self.minutes, "vibe": self.vibe, "when": self.when,
                              "sound": self.sound})
        save_settings(self.settings)

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

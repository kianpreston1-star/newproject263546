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
BUDGET_MAX = 200  # the top of the slider means "no limit"
DRIVE_MAX = 60

BG = "#fff6f2"
CARD = "#ffffff"
INK = "#3b2430"
MUTED = "#8a6f7a"
ACCENT = "#d6336c"
ACCENT_DARK = "#a61e4d"
VIBE_COLOURS = {"inside": "#4c6ef5", "outside": "#2f9e44", "chill": "#9c36b5"}
DIM = "#e9dfe3"


def load_ideas(path: Path = IDEAS_FILE) -> list[dict]:
    ideas = json.loads(path.read_text(encoding="utf-8"))
    for idea in ideas:
        missing = {"name", "where", "minutes", "cost", "vibes", "about"} - idea.keys()
        if missing:
            raise ValueError(f"{idea.get('name', 'An idea')} in {path.name} is missing {', '.join(sorted(missing))}")
        unknown = set(idea["vibes"]) - set(VIBES)
        if unknown:
            raise ValueError(f"{idea['name']} has an unknown vibe: {', '.join(sorted(unknown))}")
    return ideas


def matching(ideas: list[dict], budget: int, minutes: int, vibe: str | None) -> list[dict]:
    """Ideas within the budget (None or BUDGET_MAX means any price), drive time and vibe (None means any)."""
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


class App:
    DISC = 220          # canvas size
    RADIUS = 100        # outer radius of the disc
    HUB = 36            # radius of the "Any" button in the middle
    SECTORS = {"inside": 90, "chill": 210, "outside": 330}  # start angle of each 120° slice

    def __init__(self, root, ideas: list[dict]):
        import tkinter as tk

        self.tk = tk
        self.root = root
        self.ideas = ideas
        self.recent: deque = deque(maxlen=12)
        self.spinning = False
        self.current: dict | None = None

        saved = load_settings()
        self.budget = tk.IntVar(value=int(saved.get("budget", 50)))
        self.minutes = tk.IntVar(value=int(saved.get("minutes", 30)))
        self.vibe: str | None = saved.get("vibe") if saved.get("vibe") in VIBES else None

        root.title("Date Night Picker")
        root.configure(bg=BG)
        root.minsize(820, 540)
        root.geometry("900x580")
        root.protocol("WM_DELETE_WINDOW", self.quit)

        title = tk.Frame(root, bg=BG)
        title.pack(fill="x", padx=24, pady=(18, 6))
        tk.Label(title, text="Date Night Picker ♥", font=("Sans", 20, "bold"), fg=ACCENT, bg=BG).pack(anchor="w")
        tk.Label(title, text=f"Ideas within an hour of {HOME_POSTCODE}, Fleckney", font=("Sans", 10),
                 fg=MUTED, bg=BG).pack(anchor="w")

        body = tk.Frame(root, bg=BG)
        body.pack(fill="both", expand=True, padx=24, pady=(6, 18))
        left = tk.Frame(body, bg=BG)
        left.pack(side="left", fill="y")
        right = tk.Frame(body, bg=CARD, highlightthickness=1, highlightbackground=DIM)
        right.pack(side="left", fill="both", expand=True, padx=(24, 0))

        self.budget_label = self._question(left, "1. How much would you like to spend?", self.budget, BUDGET_MAX, 5,
                                           self._budget_text)
        self.minutes_label = self._question(left, "2. How many minutes' drive from LE8 8AL?", self.minutes, DRIVE_MAX, 5,
                                            self._minutes_text)

        tk.Label(left, text="3. Pick a vibe", font=("Sans", 11, "bold"), fg=INK, bg=BG).pack(anchor="w", pady=(8, 2))
        self.disc = tk.Canvas(left, width=self.DISC, height=self.DISC, bg=BG, highlightthickness=0, cursor="hand2")
        self.disc.pack(anchor="center")
        self.disc.bind("<Button-1>", self._disc_click)
        self.vibe_label = tk.Label(left, font=("Sans", 10), fg=MUTED, bg=BG)
        self.vibe_label.pack(anchor="center")

        self.go = tk.Button(left, text="Pick our date night", command=self.spin, font=("Sans", 13, "bold"),
                            bg=ACCENT, fg="white", activebackground=ACCENT_DARK, activeforeground="white",
                            relief="flat", bd=0, padx=18, pady=10, cursor="hand2")
        self.go.pack(fill="x", pady=(10, 0))
        root.bind("<Return>", lambda _e: self.spin())
        root.bind("<space>", lambda _e: self.spin())

        inner = tk.Frame(right, bg=CARD)
        inner.pack(fill="both", expand=True, padx=24, pady=22)
        self.result_kicker = tk.Label(inner, text="TONIGHT'S DATE", font=("Sans", 9, "bold"), fg=MUTED, bg=CARD)
        self.result_kicker.pack(anchor="w")
        self.result_name = tk.Label(inner, text="Ready when you are", font=("Sans", 22, "bold"), fg=INK, bg=CARD,
                                    justify="left", anchor="w", wraplength=420)
        self.result_name.pack(anchor="w", fill="x", pady=(4, 2))
        self.result_where = tk.Label(inner, text="", font=("Sans", 11), fg=ACCENT_DARK, bg=CARD, anchor="w")
        self.result_where.pack(anchor="w", fill="x")
        self.result_facts = tk.Label(inner, text="", font=("Sans", 11), fg=MUTED, bg=CARD, anchor="w",
                                     justify="left", wraplength=420)
        self.result_facts.pack(anchor="w", fill="x", pady=(2, 10))
        self.result_about = tk.Label(inner, text="Answer the three questions on the left, then press the button.",
                                     font=("Sans", 12), fg=INK, bg=CARD, justify="left", anchor="nw", wraplength=420)
        self.result_about.pack(anchor="w", fill="both", expand=True)
        inner.bind("<Configure>", self._rewrap)

        buttons = tk.Frame(inner, bg=CARD)
        buttons.pack(anchor="w", fill="x", pady=(12, 0))
        self.directions = tk.Button(buttons, text="Directions", command=self.open_directions, font=("Sans", 11),
                                    relief="flat", bg=DIM, fg=INK, activebackground="#ddd0d6", padx=14, pady=6,
                                    state="disabled", cursor="hand2")
        self.directions.pack(side="left")
        self.again = tk.Button(buttons, text="Pick another", command=self.spin, font=("Sans", 11), relief="flat",
                               bg=DIM, fg=INK, activebackground="#ddd0d6", padx=14, pady=6, state="disabled",
                               cursor="hand2")
        self.again.pack(side="left", padx=(8, 0))
        self.count = tk.Label(buttons, text="", font=("Sans", 9), fg=MUTED, bg=CARD)
        self.count.pack(side="right")

        self._draw_disc()
        self._update_count()

    # Questions

    def _question(self, parent, text, var, top, step, fmt):
        tk = self.tk
        tk.Label(parent, text=text, font=("Sans", 11, "bold"), fg=INK, bg=BG).pack(anchor="w", pady=(4, 0))
        row = tk.Frame(parent, bg=BG)
        row.pack(anchor="w", fill="x")
        label = tk.Label(row, text=fmt(var.get()), font=("Sans", 11), fg=ACCENT_DARK, bg=BG, width=20, anchor="w")
        scale = tk.Scale(row, from_=0, to=top, resolution=step, orient="horizontal", variable=var, showvalue=False,
                         length=220, width=14, sliderlength=24, bg=ACCENT, troughcolor=DIM, highlightthickness=0,
                         bd=0, sliderrelief="flat", activebackground=ACCENT_DARK, cursor="hand2", command=lambda _v: self._changed(label, var, fmt))
        scale.pack(side="left")
        label.pack(side="left", padx=(10, 0))
        return label

    def _changed(self, label, var, fmt):
        label.config(text=fmt(var.get()))
        self._update_count()

    @staticmethod
    def _budget_text(value: int) -> str:
        if value >= BUDGET_MAX:
            return f"£{BUDGET_MAX}+ (no limit)"
        return "Free only" if value == 0 else f"Up to £{value}"

    @staticmethod
    def _minutes_text(value: int) -> str:
        if value == 0:
            return "Stay at home"
        return "Up to an hour" if value >= DRIVE_MAX else f"Up to {value} min"

    # The vibe disc

    def _draw_disc(self):
        c = self.disc
        c.delete("all")
        mid = self.DISC / 2
        r = self.RADIUS
        for vibe, start in self.SECTORS.items():
            chosen = self.vibe in (None, vibe)
            colour = VIBE_COLOURS[vibe] if chosen else DIM
            c.create_arc(mid - r, mid - r, mid + r, mid + r, start=start, extent=120, fill=colour,
                         outline=BG, width=3, tags=("sector",))
            angle = math.radians(start + 60)
            lx = mid + math.cos(angle) * (r + self.HUB) / 2
            ly = mid - math.sin(angle) * (r + self.HUB) / 2
            c.create_text(lx, ly, text=vibe.capitalize(), font=("Sans", 11, "bold"),
                          fill="white" if chosen else MUTED)
        hub = self.HUB
        c.create_oval(mid - hub, mid - hub, mid + hub, mid + hub, fill=ACCENT if self.vibe is None else CARD,
                      outline=BG, width=3)
        c.create_text(mid, mid, text="Any", font=("Sans", 10, "bold"), fill="white" if self.vibe is None else INK)
        self.vibe_label.config(text="Any vibe: click a slice to choose" if self.vibe is None
                               else f"{self.vibe.capitalize()} only: click the middle for any")

    def _disc_click(self, event):
        if self.spinning:
            return
        mid = self.DISC / 2
        dx, dy = event.x - mid, mid - event.y
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

    # Picking

    def _candidates(self):
        return matching(self.ideas, self.budget.get(), self.minutes.get(), self.vibe)

    def _update_count(self):
        n = len(self._candidates())
        self.count.config(text=f"{n} idea{'s' if n != 1 else ''} match")

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
            button.config(state="disabled")
        self.result_kicker.config(text="PICKING...")
        self._shuffle(candidates, choice, step=0)

    def _shuffle(self, candidates, choice, step, frames=18):
        if step < frames:
            teaser = random.choice(candidates)
            self.result_name.config(text=teaser["name"], fg=MUTED)
            self.result_where.config(text="")
            self.result_facts.config(text="")
            self.result_about.config(text="")
            self._spin_marker(step)
            delay = 40 + step * 8  # slows down like a wheel
            self.root.after(delay, self._shuffle, candidates, choice, step + 1, frames)
            return
        self.disc.delete("marker")
        self.spinning = False
        self._show(choice)

    def _spin_marker(self, step):
        c = self.disc
        c.delete("marker")
        mid = self.DISC / 2
        angle = math.radians(90 - step * 47)
        x = mid + math.cos(angle) * (self.RADIUS - 8)
        y = mid - math.sin(angle) * (self.RADIUS - 8)
        c.create_oval(x - 7, y - 7, x + 7, y + 7, fill="white", outline=INK, width=2, tags=("marker",))

    def _show(self, idea):
        self.current = idea
        self.result_kicker.config(text="TONIGHT'S DATE")
        self.result_name.config(text=idea["name"], fg=INK)
        self.result_where.config(text=idea["where"])
        vibes = " / ".join(v.capitalize() for v in idea["vibes"])
        self.result_facts.config(text=f"{describe_drive(idea['minutes'])}   •   {describe_cost(idea['cost'])}"
                                      f"   •   {vibes}")
        self.result_about.config(text=idea["about"])
        self.go.config(state="normal")
        self.again.config(state="normal")
        self.directions.config(state="normal" if directions_url(idea) else "disabled")

    def _show_none(self):
        self.current = None
        self.result_kicker.config(text="NOTHING MATCHES")
        self.result_name.config(text="No ideas fit that yet", fg=INK)
        self.result_where.config(text="")
        self.result_facts.config(text="")
        self.result_about.config(text="Try a bigger budget, a longer drive, or click the middle of the disc "
                                      "for any vibe.")
        self.directions.config(state="disabled")
        self.again.config(state="disabled")

    def open_directions(self):
        url = self.current and directions_url(self.current)
        if url:
            webbrowser.open(url)

    def _rewrap(self, event):
        width = max(240, event.width - 8)
        self.result_name.config(wraplength=width)
        self.result_facts.config(wraplength=width)
        self.result_about.config(wraplength=width)

    def _save(self):
        save_settings({"budget": self.budget.get(), "minutes": self.minutes.get(), "vibe": self.vibe})

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
        ideas = load_ideas()
    except (OSError, ValueError) as exc:
        print(f"Couldn't read the date ideas: {exc}", file=sys.stderr)
        return 1

    if "--check" in argv:
        try:
            root = tk.Tk(className="datenight")
            root.withdraw()
            App(root, ideas)
            root.update_idletasks()
            root.destroy()
        except tk.TclError as exc:
            print(f"The window couldn't open: {exc}", file=sys.stderr)
            return 1
        print(f"Date Night Picker works: {len(ideas)} ideas loaded, Tk {tk.TkVersion}.")
        return 0

    root = tk.Tk(className="datenight")
    App(root, ideas)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

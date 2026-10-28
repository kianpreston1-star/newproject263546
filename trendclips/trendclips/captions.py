"""Animated captions as an ASS subtitle file, burned in by FFmpeg: big bold words in short chunks that pop in,
with the word being spoken lit up, plus the opening headline and your @handle."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .themes import Theme, ass_color

W, H = 1080, 1920
CAPTION_Y = 1150  # a little below the middle: clear of the app buttons on the right and the text at the bottom
HOOK_Y = 330  # below TikTok's and YouTube's top bar
HOOK_SECONDS = 2.6


@dataclass
class Word:
    text: str
    start: float
    end: float
    scene: int = 0
    keyword: bool = False


def _ts(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _clean(text: str) -> str:
    return re.sub(r"[{}\\]", "", text)


def group_words(words: list[Word], max_chars: int, max_words: int = 3) -> list[list[Word]]:
    """Short chunks read faster than full lines. A chunk never spans two scenes and ends at punctuation."""
    groups: list[list[Word]] = []
    cur: list[Word] = []
    for w in words:
        letters = sum(len(x.text) for x in cur) + len(w.text)
        if cur and (w.scene != cur[-1].scene or len(cur) >= max_words or letters > max_chars
                    or cur[-1].text.endswith((".", "!", "?", ",", ";", ":"))):
            groups.append(cur)
            cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    return groups


def _hook_lines(text: str, per_line: int = 14) -> str:
    """One line if it fits, otherwise two lines of similar length ("3 HEARTS." / "BLUE BLOOD.")."""
    words = text.split()
    if len(text) <= per_line or len(words) < 2:
        return text
    best = min(range(1, len(words)),
               key=lambda i: max(len(" ".join(words[:i])), len(" ".join(words[i:]))))
    return " ".join(words[:best]) + r"\N" + " ".join(words[best:])


def build_ass(words: list[Word], theme: Theme, duration: float, hook: str = "", handle: str = "") -> str:
    up = (lambda s: s.upper()) if theme.uppercase else (lambda s: s)
    hook_size = max(70, round(theme.size * 0.8))
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {W}",
        f"PlayResY: {H}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: TV.709",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        f"Style: Caption,{theme.font},{theme.size},{ass_color(theme.text)},{ass_color(theme.text)},&H00000000,"
        f"&H7A000000,0,0,0,0,100,100,1,0,1,{theme.outline},5,5,80,80,0,1",
        # BorderStyle 3 draws a solid box behind the text in the outline colour.
        f"Style: Hook,{theme.font},{hook_size},{ass_color(theme.hook_text)},{ass_color(theme.hook_text)},"
        f"{ass_color(theme.accent)},&H64000000,0,0,0,0,100,100,1,0,3,16,0,8,60,60,{HOOK_Y},1",
        f"Style: Handle,{theme.font},42,&H50FFFFFF,&H50FFFFFF,&H90000000,&H00000000,0,0,0,0,100,100,1,0,1,2,0,9,"
        "40,40,230,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    hl, accent = ass_color(theme.highlight), ass_color(theme.accent)
    groups = group_words(words, theme.max_chars)
    for gi, group in enumerate(groups):
        g_start = group[0].start
        nxt = groups[gi + 1][0].start if gi + 1 < len(groups) else duration
        g_end = max(min(nxt, group[-1].end + 0.6), g_start + 0.25)
        for wi, w in enumerate(group):
            start = g_start if wi == 0 else w.start
            end = group[wi + 1].start if wi + 1 < len(group) else g_end
            if end - start < 0.02:
                continue
            parts = []
            for j, x in enumerate(group):
                t = _clean(up(x.text))
                if j == wi:
                    parts.append(rf"{{\c{hl}\fscx112\fscy112}}{t}{{\r}}")
                elif x.keyword:
                    parts.append(rf"{{\c{accent}}}{t}{{\r}}")
                else:
                    parts.append(t)
            pop = r"\fscx72\fscy72\t(0,90,\fscx106\fscy106)\t(90,170,\fscx100\fscy100)" if wi == 0 else ""
            lines.append(f"Dialogue: 1,{_ts(start)},{_ts(end)},Caption,,0,0,0,,"
                         rf"{{\an5\pos({W // 2},{CAPTION_Y}){pop}}}" + " ".join(parts))
    if hook:
        text = _clean(up(hook))
        anim = r"\fscx40\fscy40\t(0,160,\fscx108\fscy108)\t(160,260,\fscx100\fscy100)\fad(0,220)"
        lines.append(f"Dialogue: 2,{_ts(0.05)},{_ts(min(HOOK_SECONDS, duration))},Hook,,0,0,0,,"
                     rf"{{{anim}}}{_hook_lines(text)}")
    if handle:
        lines.append(f"Dialogue: 0,{_ts(0)},{_ts(duration)},Handle,,0,0,0,,{_clean(handle)}")
    return "\n".join(lines) + "\n"

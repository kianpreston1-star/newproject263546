"""The look of each kind of video: caption font and colours, colour grade, fallback background and voice.
A channel covering whatever's trending still looks deliberate when sport, tech and showbiz each get their own style."""
from __future__ import annotations

from dataclasses import dataclass

# Free fonts (SIL Open Font License / Apache), downloaded from Google Fonts' repository by `trendclips setup`.
FONTS = {
    "Anton-Regular.ttf": "ofl/anton/Anton-Regular.ttf",
    "Poppins-ExtraBold.ttf": "ofl/poppins/Poppins-ExtraBold.ttf",
    "BebasNeue-Regular.ttf": "ofl/bebasneue/BebasNeue-Regular.ttf",
    "LuckiestGuy-Regular.ttf": "apache/luckiestguy/LuckiestGuy-Regular.ttf",
    "ArchivoBlack-Regular.ttf": "ofl/archivoblack/ArchivoBlack-Regular.ttf",
    "Bangers-Regular.ttf": "ofl/bangers/Bangers-Regular.ttf",
}
FONT_URL = "https://raw.githubusercontent.com/google/fonts/main/"


@dataclass(frozen=True)
class Theme:
    name: str
    font: str  # family name as the font file declares it
    size: int  # caption size on the 1080x1920 frame
    max_chars: int  # letters per caption chunk (narrow fonts fit more)
    highlight: str  # the word being spoken
    accent: str  # key words, the headline box and the progress bar
    hook_text: str  # text colour inside the headline box
    voice: str  # Kokoro voice used when video.voice is "auto"
    saturation: float
    contrast: float
    background: tuple[str, str]  # (dark, glow): the animated backdrop used when no stock footage is found
    text: str = "#FFFFFF"
    uppercase: bool = True
    outline: int = 7


THEMES = {
    "tech": Theme("tech", "Poppins ExtraBold", 96, 13, "#00E5FF", "#8B5CFF", "#FFFFFF", "af_bella",
                  1.12, 1.06, ("#05081A", "#007A94")),
    "money": Theme("money", "Anton", 137, 16, "#39FF88", "#FFC400", "#111111", "am_michael",
                   1.15, 1.08, ("#03100A", "#8A6B00")),
    "sport": Theme("sport", "Anton", 139, 16, "#FFE600", "#FF2D2D", "#FFFFFF", "am_fenrir",
                   1.22, 1.10, ("#0E0303", "#B34A00")),
    "entertainment": Theme("entertainment", "Luckiest Guy", 112, 13, "#FFE14D", "#FF3FB4", "#FFFFFF", "af_heart",
                           1.20, 1.05, ("#14041D", "#B32C63")),
    "science": Theme("science", "Archivo Black", 99, 13, "#7CFFB2", "#00C2FF", "#06131A", "am_puck",
                     1.10, 1.06, ("#021018", "#0E7A63")),
    "gaming": Theme("gaming", "Bangers", 139, 15, "#B6FF00", "#9B5CFF", "#FFFFFF", "am_puck",
                    1.25, 1.08, ("#08031A", "#008F53")),
    "news": Theme("news", "Bebas Neue", 157, 17, "#FFD400", "#E8002D", "#FFFFFF", "af_heart",
                  1.05, 1.08, ("#04060B", "#661016")),
    "lifestyle": Theme("lifestyle", "Poppins ExtraBold", 96, 13, "#FFB84D", "#FF5E7A", "#FFFFFF", "af_heart",
                       1.15, 1.04, ("#140806", "#B36B40")),
}


def theme_for(category: str) -> Theme:
    return THEMES.get(category, THEMES["news"])


def kokoro_lang(voice: str) -> str:
    """Kokoro's voice names start with a for American English and b for British English."""
    return "en-gb" if voice.startswith("b") else "en-us"


def ass_color(hex_color: str, alpha: int = 0) -> str:
    """#RRGGBB to ASS subtitle colour &HAABBGGRR (alpha 0 = solid)."""
    h = hex_color.lstrip("#")
    return f"&H{alpha:02X}{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def ffmpeg_color(hex_color: str) -> str:
    return "0x" + hex_color.lstrip("#").upper()

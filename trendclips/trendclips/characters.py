"""The cast for two-character videos: who they are (for the scriptwriter), how they sound and how they look.

The two built-in characters are original and drawn here as vector art, so you own them outright: no copyright claims,
no demonetization for someone else's character. Each comes in three frames (mouth closed, mouth open, blinking),
which are switched in time with the voice so they look like they're talking. Your own characters can be added as
images in ~/.trendclips/characters/<name>/ (see the README)."""
from __future__ import annotations

import logging
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

SPRITE_W, SPRITE_H = 750, 925  # each frame image; the drawings are made on a 600x740 grid and scaled up
FRAMES = ("closed", "open", "blink")


@dataclass
class Character:
    id: str
    name: str
    personality: str  # given to the scriptwriter
    voice: str  # Kokoro voice
    speed: float = 1.0  # speaking pace relative to video.voice_speed
    pitch: float = 1.0  # above 1 is higher and more cartoonish
    color: str = "#FFE600"  # colour of their spoken word in the captions
    images: dict = field(default_factory=dict)  # frame name -> PNG path, filled in by load_cast()


BUILT_IN = {
    "dave": Character(
        "dave", "Big Dave",
        "A loud, lovable, clueless bloke in a backwards cap. He gets facts hilariously wrong, compares everything to "
        "kebabs, his nan, the pub or football, overreacts, and asks the questions viewers are secretly thinking.",
        voice="am_fenrir", speed=0.97, pitch=0.93, color="#FFE600"),
    "nibbles": Character(
        "nibbles", "Professor Nibbles",
        "A posh, smug genius hamster in round glasses and a bow tie. He explains the real facts clearly and "
        "correctly, is exasperated by Dave, uses dry sarcasm, and now and then mentions his wheel or his seeds.",
        voice="bm_george", speed=1.0, pitch=1.16, color="#5CE1FF"),
}

OUTLINE = "#22160C"
def _svg(body: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{SPRITE_W}" height="{SPRITE_H}" '
            f'viewBox="0 0 600 740"><defs>'
            '<radialGradient id="shine" cx="0.35" cy="0.3" r="0.7"><stop offset="0" stop-color="#FFFFFF" '
            'stop-opacity="0.35"/><stop offset="1" stop-color="#FFFFFF" stop-opacity="0"/></radialGradient>'
            f'</defs><g stroke="{OUTLINE}" stroke-width="7" stroke-linejoin="round" '
            f'stroke-linecap="round">{body}</g></svg>')


def dave_svg(frame: str) -> str:
    skin, skin_dark, hoodie, hoodie_dark, cap = "#F4C29A", "#E2A57A", "#E23B3B", "#B82828", "#2F62C9"
    eyes = (f'<ellipse cx="240" cy="330" rx="30" ry="26" fill="#FFFFFF"/>'
            f'<ellipse cx="362" cy="330" rx="30" ry="26" fill="#FFFFFF"/>'
            f'<circle cx="246" cy="326" r="11" fill="{OUTLINE}" stroke="none"/>'
            f'<circle cx="356" cy="326" r="11" fill="{OUTLINE}" stroke="none"/>'
            '<circle cx="250" cy="322" r="4" fill="#FFFFFF" stroke="none"/>'
            '<circle cx="360" cy="322" r="4" fill="#FFFFFF" stroke="none"/>')
    if frame == "blink":
        eyes = ('<path d="M212 332 Q240 346 268 332" fill="none"/><path d="M334 332 Q362 346 390 332" fill="none"/>')
    if frame == "open":
        mouth = ('<path d="M222 448 Q300 440 380 448 Q372 540 300 545 Q228 540 222 448 Z" fill="#7A1F1F"/>'
                 '<path d="M232 452 Q300 446 370 452 L366 474 Q300 468 236 474 Z" fill="#FFFFFF" stroke-width="5"/>'
                 '<path d="M262 528 Q300 500 340 528 Q300 545 262 528 Z" fill="#E86A6A" stroke-width="5"/>')
    else:
        mouth = ('<path d="M222 458 Q300 512 382 452" fill="none" stroke-width="8"/>'
                 '<path d="M214 450 Q220 462 230 462" fill="none" stroke-width="6"/>'
                 '<path d="M390 444 Q384 458 374 458" fill="none" stroke-width="6"/>')
    return _svg(f"""
<path d="M40 800 L60 640 Q80 560 190 548 L410 548 Q520 560 540 640 L560 800 Z" fill="{hoodie}"/>
<path d="M190 548 Q300 640 410 548 Q400 610 300 628 Q200 610 190 548 Z" fill="{hoodie_dark}"/>
<path d="M262 600 L252 700" fill="none" stroke="#FFFFFF" stroke-width="9"/>
<path d="M338 600 L348 700" fill="none" stroke="#FFFFFF" stroke-width="9"/>
<path d="M240 520 L250 585 Q300 610 350 585 L360 520 Z" fill="{skin_dark}"/>
<ellipse cx="118" cy="350" rx="34" ry="48" fill="{skin}"/><ellipse cx="482" cy="350" rx="34" ry="48" fill="{skin}"/>
<path d="M125 300 Q125 135 300 130 Q475 135 475 300 L470 420 Q455 560 300 568 Q145 560 130 420 Z" fill="{skin}"/>
<path d="M150 430 Q160 545 300 556 Q440 545 450 430 Q420 500 300 505 Q180 500 150 430 Z" fill="#8C7A6B"
      fill-opacity="0.28" stroke="none"/>
<path d="M120 250 Q118 120 300 105 Q482 120 480 250 Q470 205 300 198 Q130 205 120 250 Z" fill="{cap}"/>
<path d="M150 214 Q300 175 450 214" fill="none" stroke="#24499A" stroke-width="7"/>
<path d="M120 250 Q60 248 52 285 Q100 300 150 262 Z" fill="{cap}"/>
<path d="M140 262 Q120 300 128 320" fill="none" stroke="#6B4423" stroke-width="12"/>
<path d="M460 262 Q482 300 474 320" fill="none" stroke="#6B4423" stroke-width="12"/>
<path d="M205 282 Q240 262 275 282" fill="none" stroke="#5A3A1E" stroke-width="13"/>
<path d="M327 282 Q362 262 397 282" fill="none" stroke="#5A3A1E" stroke-width="13"/>
{eyes}
<ellipse cx="300" cy="392" rx="40" ry="33" fill="{skin_dark}"/>
<ellipse cx="288" cy="382" rx="12" ry="8" fill="#FFFFFF" fill-opacity="0.6" stroke="none"/>
<ellipse cx="185" cy="420" rx="30" ry="18" fill="#F08A7A" fill-opacity="0.45" stroke="none"/>
<ellipse cx="415" cy="420" rx="30" ry="18" fill="#F08A7A" fill-opacity="0.45" stroke="none"/>
{mouth}
<path d="M125 300 Q125 135 300 130 Q475 135 475 300 L470 420 Q455 560 300 568 Q145 560 130 420 Z"
      fill="url(#shine)" stroke="none"/>
""")


def nibbles_svg(frame: str) -> str:
    fur, fur_dark, cream, pink, tweed, tweed_dark = "#E9A24C", "#C9822F", "#FFE9C7", "#F4A0A8", "#8A6A4A", "#6E5236"
    eyes = (f'<ellipse cx="240" cy="318" rx="22" ry="27" fill="{OUTLINE}" stroke="none"/>'
            f'<ellipse cx="360" cy="318" rx="22" ry="27" fill="{OUTLINE}" stroke="none"/>'
            '<circle cx="232" cy="307" r="8" fill="#FFFFFF" stroke="none"/>'
            '<circle cx="352" cy="307" r="8" fill="#FFFFFF" stroke="none"/>')
    if frame == "blink":
        eyes = '<path d="M218 322 Q240 334 262 322" fill="none"/><path d="M338 322 Q360 334 382 322" fill="none"/>'
    if frame == "open":
        mouth = ('<path d="M262 400 Q300 392 338 400 Q336 462 300 466 Q264 462 262 400 Z" fill="#7A1F1F"/>'
                 '<rect x="284" y="398" width="15" height="22" rx="3" fill="#FFFFFF" stroke-width="4"/>'
                 '<rect x="301" y="398" width="15" height="22" rx="3" fill="#FFFFFF" stroke-width="4"/>'
                 '<path d="M276 452 Q300 432 324 452 Q300 462 276 452 Z" fill="#E86A6A" stroke-width="4"/>')
    else:
        mouth = ('<path d="M268 402 Q284 418 300 402 Q316 418 332 402" fill="none" stroke-width="6"/>'
                 '<rect x="286" y="404" width="13" height="16" rx="3" fill="#FFFFFF" stroke-width="4"/>'
                 '<rect x="301" y="404" width="13" height="16" rx="3" fill="#FFFFFF" stroke-width="4"/>')
    return _svg(f"""
<ellipse cx="300" cy="760" rx="250" ry="210" fill="{fur}"/>
<path d="M95 800 Q110 620 215 575 L262 800 Z" fill="{tweed}"/>
<path d="M505 800 Q490 620 385 575 L338 800 Z" fill="{tweed}"/>
<path d="M130 690 L240 680 M120 740 L250 735 M470 690 L360 680 M480 740 L350 735" fill="none"
      stroke="{tweed_dark}" stroke-width="5"/>
<path d="M215 575 Q300 610 385 575 L338 800 L262 800 Z" fill="#FFFFFF"/>
<circle cx="300" cy="680" r="8" fill="#D9C27A" stroke-width="4"/><circle cx="300" cy="730" r="8" fill="#D9C27A"
      stroke-width="4"/>
<path d="M300 600 L240 568 L240 632 Z" fill="#D62F4B"/><path d="M300 600 L360 568 L360 632 Z" fill="#D62F4B"/>
<circle cx="300" cy="600" r="16" fill="#B5203A"/>
<circle cx="150" cy="170" r="58" fill="{fur}"/><circle cx="450" cy="170" r="58" fill="{fur}"/>
<circle cx="152" cy="174" r="32" fill="{pink}" stroke="none"/><circle cx="448" cy="174" r="32" fill="{pink}"
      stroke="none"/>
<ellipse cx="300" cy="330" rx="210" ry="200" fill="{fur}"/>
<path d="M300 140 Q270 200 300 250 Q330 200 300 140 Z" fill="{fur_dark}" stroke="none"/>
<ellipse cx="190" cy="420" rx="92" ry="78" fill="{cream}"/>
<ellipse cx="410" cy="420" rx="92" ry="78" fill="{cream}"/>
<ellipse cx="300" cy="405" rx="70" ry="64" fill="{cream}" stroke="none"/>
<path d="M200 270 Q236 248 272 262" fill="none" stroke="#7A4A1A" stroke-width="10"/>
<path d="M328 256 Q366 238 402 262" fill="none" stroke="#7A4A1A" stroke-width="10"/>
{eyes}
<circle cx="240" cy="318" r="50" fill="#FFFFFF" fill-opacity="0.18" stroke="#2B2B2B" stroke-width="9"/>
<circle cx="360" cy="318" r="50" fill="#FFFFFF" fill-opacity="0.18" stroke="#2B2B2B" stroke-width="9"/>
<path d="M290 316 Q300 306 310 316" fill="none" stroke="#2B2B2B" stroke-width="8"/>
<path d="M190 312 L120 300 M410 312 L480 300" fill="none" stroke="#2B2B2B" stroke-width="8"/>
<path d="M284 372 Q300 364 316 372 Q312 388 300 392 Q288 388 284 372 Z" fill="{pink}"/>
{mouth}
<path d="M150 410 L60 392 M150 432 L58 440 M450 410 L540 392 M450 432 L542 440" fill="none" stroke-width="4"/>
<ellipse cx="300" cy="330" rx="210" ry="200" fill="url(#shine)" stroke="none"/>
""")


DRAWINGS = {"dave": dave_svg, "nibbles": nibbles_svg}


def draw_builtin(char_id: str, folder: Path) -> dict[str, Path]:
    """Renders a built-in character's frames to PNG with FFmpeg's SVG renderer (librsvg)."""
    folder.mkdir(parents=True, exist_ok=True)
    out = {}
    for frame in FRAMES:
        png = folder / f"{frame}.png"
        if png.exists() and _size(png) != (SPRITE_W, SPRITE_H):
            png.unlink()  # drawn at an older size
        if not png.exists():
            svg = folder / f"{frame}.svg"
            svg.write_text(DRAWINGS[char_id](frame))
            p = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(svg),
                                "-frames:v", "1", "-pix_fmt", "rgba", str(png)], capture_output=True, text=True)
            svg.unlink(missing_ok=True)
            if p.returncode:
                raise RuntimeError(f"Couldn't draw {char_id}: {p.stderr.strip()[-200:]}")
            sticker(png)
        out[frame] = png
    return out


def sticker(path: Path, border: float = 5.0) -> None:
    """Adds a white sticker outline and a soft drop shadow, so a character stands out on any background."""
    from PIL import Image, ImageFilter

    im = Image.open(path).convert("RGBA")
    alpha = im.getchannel("A")
    # Blurring the outline and keeping everything above 3% grows the shape by about two blur widths.
    fat = alpha.filter(ImageFilter.GaussianBlur(border)).point(lambda v: 255 if v > 8 else 0)
    fat = fat.filter(ImageFilter.GaussianBlur(1))
    shadow = fat.filter(ImageFilter.GaussianBlur(9)).point(lambda v: int(v * 0.45))
    out = Image.new("RGBA", im.size, (0, 0, 0, 0))
    out.paste((0, 0, 0, 255), (0, 12), shadow.crop((0, 0, im.width, im.height - 12)))
    out.paste((255, 255, 255, 255), (0, 0), fat)
    out.alpha_composite(im)
    out.save(path)


def _size(path: Path) -> tuple[int, int]:
    from PIL import Image

    with Image.open(path) as im:
        return im.size


def prepare_image(src: Path, dest: Path) -> Path:
    """Fits your own character picture into the sprite frame, bottom-centred. If it has a plain background
    (as AI image generators usually give), that background is made transparent."""
    from PIL import Image, ImageDraw

    im = Image.open(src).convert("RGBA")
    if im.getextrema()[3][0] == 255:  # no transparency: clear the background from the corners inwards
        w, h = im.size
        for corner in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
            if im.getpixel(corner)[3]:
                ImageDraw.floodfill(im, corner, (0, 0, 0, 0), thresh=40)
    box = im.getbbox() or (0, 0, *im.size)
    im = im.crop(box)
    im.thumbnail((SPRITE_W - 40, SPRITE_H - 20))
    canvas = Image.new("RGBA", (SPRITE_W, SPRITE_H), (0, 0, 0, 0))
    canvas.paste(im, ((SPRITE_W - im.width) // 2, SPRITE_H - im.height), im)
    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dest)
    sticker(dest)
    return dest


def load_cast(ids: tuple[str, ...], custom_dir: Path, sprite_dir: Path) -> list[Character]:
    """The characters for a video. Your own folder wins over a built-in one with the same name."""
    cast = []
    for cid in ids:
        folder = custom_dir / cid
        if (folder / "character.toml").exists():
            with open(folder / "character.toml", "rb") as f:
                data = tomllib.load(f)
            known = set(Character.__dataclass_fields__) - {"id", "images"}
            unknown = set(data) - known
            if unknown:
                raise ValueError(f"Unknown setting(s) {', '.join(sorted(unknown))} in {folder / 'character.toml'}")
            ch = Character(cid, **{k: v for k, v in data.items()})
            images = {}
            for frame in FRAMES:
                src = next((folder / f"{frame}{ext}" for ext in (".png", ".jpg", ".jpeg", ".webp")
                            if (folder / f"{frame}{ext}").exists()), None)
                if src:
                    images[frame] = prepare_image(src, sprite_dir / cid / f"{frame}.png")
            if "closed" not in images:
                raise ValueError(f"{folder} needs at least closed.png (and ideally open.png and blink.png)")
            images.setdefault("open", images["closed"])
            images.setdefault("blink", images["closed"])
            ch.images = images
        elif cid in BUILT_IN:
            base = BUILT_IN[cid]
            ch = Character(**{k: getattr(base, k) for k in Character.__dataclass_fields__ if k != "images"})
            ch.images = draw_builtin(cid, sprite_dir / cid)
        else:
            raise ValueError(f"No character called '{cid}'. Built-in ones: {', '.join(BUILT_IN)}; or make a folder "
                             f"{custom_dir / cid} (see the README)")
        cast.append(ch)
    return cast

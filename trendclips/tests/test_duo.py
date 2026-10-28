"""Two-character videos: the dialogue, the cast, mouths moving with the voice, and a real render."""
import numpy as np
import pytest

from conftest import FakeLLM, needs_ffmpeg
from trendclips.captions import Word, build_ass
from trendclips.characters import BUILT_IN, SPRITE_H, SPRITE_W, load_cast, prepare_image
from trendclips.duo import concat_file, mouth_states
from trendclips.render import FPS, Shot, finish, probe, render_shots
from trendclips.research import Research
from trendclips.sfx import make_all
from trendclips.themes import theme_for
from trendclips.trends import Trend
from trendclips.voice import SR, Track, write_wav
from trendclips.writer import Pick, Writer, tidy_script

CAST = [BUILT_IN["dave"], BUILT_IN["nibbles"]]


def test_dialogue_keeps_speakers_and_fixes_labels():
    data = {"title": "T", "category": "science", "lines": [
        {"speaker": "Big Dave", "text": "Hang on, octopuses have three hearts?", "visual": "octopus"},
        {"speaker": "NIBBLES", "text": "Professor Nibbles: Yes, Dave. Three of them.", "visual": "ocean"},
        {"speaker": "narrator", "text": "So it's got a spare one, like me with kebabs.", "visual": "kebab"},
        {"speaker": "dave", "text": " ".join(["word"] * 30) + ".", "visual": "city"},
    ]}
    s = tidy_script(data, cast=CAST)
    assert [x.speaker for x in s.scenes] == ["dave", "nibbles", "dave", "dave"]  # stray label: other speaker
    assert s.scenes[1].text == "Yes, Dave. Three of them."  # the name at the start isn't spoken
    assert len(s.scenes) == 4  # dialogue lines are never split up


def test_dialogue_prompt_introduces_the_cast():
    reply = {"title": "T", "category": "science", "mood": "upbeat", "hashtags": [], "lines": [
        {"speaker": "dave" if i % 2 == 0 else "nibbles", "text": " ".join(["word"] * 15) + "."} for i in range(12)]}
    llm = FakeLLM(reply)
    script = Writer(llm).write(Pick(Trend("polar vortex", "google", 1), "science", "early"),
                               Research("polar vortex", ["It is weakening early."]), CAST)
    prompt = llm.prompts[0]
    assert "Big Dave" in prompt and "Professor Nibbles" in prompt and "kebabs" in prompt
    assert "only Professor Nibbles states facts" in prompt
    assert [s.speaker for s in script.scenes[:2]] == ["dave", "nibbles"]


def _loudness(talk: list[tuple[float, float]], seconds: float) -> np.ndarray:
    loud = np.zeros(int(seconds * FPS), dtype=np.float32)
    for a, b in talk:  # syllables: loud, quiet, loud, quiet…
        for k in range(int(a * FPS), int(b * FPS)):
            loud[k] = 0.3 if (k // 3) % 2 == 0 else 0.01
    return loud


def test_mouth_moves_with_the_voice_and_characters_rise_into_view():
    loud = _loudness([(0.0, 2.0), (2.2, 4.0), (5.0, 6.0)], 7.0)
    states = mouth_states(loud, [(0.0, 2.0), (2.2, 4.0)])
    assert states[:3] == ["rise1", "rise2", "rise3"]
    talking = states[3:60]
    assert "open" in talking and "closed" in talking  # the mouth flaps
    assert states[62] == "closed" and states[66] != "rise1"  # same speaker again: stays on screen, no re-entrance
    assert states[-1] == "closed"  # the last speaker stays until the end
    other = mouth_states(loud, [(5.0, 6.0)], seed=1)
    assert set(other[:150]) == {"blank"} and other[150] == "rise1"


def test_concat_file_lists_each_image_for_its_duration(tmp_path):
    frames = {s: tmp_path / f"{s}.png" for s in ("blank", "open", "closed")}
    path = concat_file(["blank"] * 30 + ["open"] * 3 + ["closed"] * 6, frames, tmp_path / "c.txt")
    lines = path.read_text().splitlines()
    assert lines[1] == "duration 1.0000" and lines[3] == "duration 0.1000" and lines[5] == "duration 0.2000"
    assert lines[-1] == lines[-3]  # last image repeated, as FFmpeg's concat reader needs


@needs_ffmpeg
def test_built_in_characters_are_drawn(tmp_path):
    from PIL import Image

    cast = load_cast(("dave", "nibbles"), tmp_path / "custom", tmp_path / "sprites")
    for ch in cast:
        for frame in ("closed", "open", "blink"):
            with Image.open(ch.images[frame]) as im:
                assert im.size == (SPRITE_W, SPRITE_H) and im.mode == "RGBA"
                assert im.getpixel((0, 0))[3] == 0 and im.getpixel((SPRITE_W // 2, SPRITE_H - 5))[3] == 255
    with Image.open(cast[0].images["closed"]) as a, Image.open(cast[0].images["open"]) as b:
        assert a.tobytes() != b.tobytes()  # the mouth really opens


def test_your_own_character(tmp_path):
    from PIL import Image, ImageDraw

    folder = tmp_path / "custom" / "gran"
    folder.mkdir(parents=True)
    im = Image.new("RGB", (400, 500), (255, 255, 255))  # a plain white background, as image generators give
    ImageDraw.Draw(im).ellipse((100, 100, 300, 480), fill=(200, 60, 120))
    im.save(folder / "closed.png")
    (folder / "character.toml").write_text('name = "Gran"\npersonality = "A sassy gran."\nvoice = "bf_emma"\n'
                                           'pitch = 1.05\ncolor = "#FF77CC"\n')
    gran, dave = load_cast(("gran", "dave"), tmp_path / "custom", tmp_path / "sprites")
    assert gran.name == "Gran" and gran.voice == "bf_emma" and dave.name == "Big Dave"
    with Image.open(gran.images["open"]) as sprite:  # one picture is enough
        assert sprite.size == (SPRITE_W, SPRITE_H)
        assert sprite.getpixel((SPRITE_W // 2, 10))[3] == 0  # the white background is gone
    (folder / "character.toml").write_text('name = "Gran"\npersonality = "x"\nvoice = "bf_emma"\nvoise = "x"\n')
    with pytest.raises(ValueError, match="voise"):
        load_cast(("gran", "dave"), tmp_path / "custom", tmp_path / "sprites")
    with pytest.raises(ValueError, match="No character called"):
        load_cast(("nobody", "dave"), tmp_path / "custom", tmp_path / "sprites")


def test_prepare_image_keeps_transparent_pictures(tmp_path):
    from PIL import Image

    src = tmp_path / "a.png"
    Image.new("RGBA", (300, 300), (10, 20, 30, 255)).save(src)
    out = prepare_image(src, tmp_path / "out.png")
    with Image.open(out) as im:
        assert im.size == (SPRITE_W, SPRITE_H)


@needs_ffmpeg
def test_render_a_two_character_video(tmp_path):
    from trendclips.duo import character_overlays

    work = tmp_path / "work"
    work.mkdir()
    theme = theme_for("science")
    t = np.arange(int(SR * 2.4)) / SR
    audio = (0.3 * np.sin(2 * np.pi * 180 * t) * (np.sin(2 * np.pi * 4 * t) > 0)).astype(np.float32)
    write_wav(work / "voice.wav", audio)
    track = Track(audio, [(0.0, 1.1), (1.25, 2.4)])
    cast = load_cast(("dave", "nibbles"), tmp_path / "custom", tmp_path / "sprites")
    overlays = character_overlays(track, ["dave", "nibbles"], cast, 2.6, work)
    words = [Word("Hang", 0.1, 0.5, 0, color="#FFE600"), Word("on.", 0.5, 1.0, 0, color="#FFE600"),
             Word("Indeed.", 1.3, 2.2, 1, color="#5CE1FF")]
    (work / "captions.ass").write_text(build_ass(words, theme, 2.6, hook="Wait what", caption_y=990))
    (work / "fonts").mkdir()
    segs = render_shots([Shot(0, 2.6, "background")], theme, work)
    out = tmp_path / "duo.mp4"
    finish(work, segs, 2.6, theme, None, 0.2, make_all(tmp_path / "sfx"), [], out, "ultrafast", overlays,
           pops=(0.04, 1.25))
    w, h, dur = probe(out)
    assert (w, h) == (1080, 1920) and 2.4 <= dur <= 2.8

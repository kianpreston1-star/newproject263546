"""Captions, word timing, footage choice and rendering."""
import subprocess

import numpy as np

from conftest import FakeResponse, FakeSession, needs_ffmpeg
from trendclips.captions import Word, build_ass, group_words
from trendclips.footage import Footage, cover_scale, parse_pexels, parse_pixabay, pick_rendition
from trendclips.render import Shot, final_command, finish, plan_shots, probe, render_shots, video_kbps
from trendclips.research import article_text, license_ok, save_jpeg
from trendclips.sfx import make_all
from trendclips.themes import ass_color, theme_for
from trendclips.voice import SR, align, estimate_times, trim_silence, write_wav


def test_align_uses_whisper_times_whatever_it_misheard():
    words = ["Elon's", "new", "rocket", "just", "flew."]
    heard = [("Alon's", 0.0, 0.5), ("new", 0.5, 0.65), ("just", 1.0, 1.3), ("flew.", 1.3, 1.8)]
    times = align(words, heard, 0.0, 2.0)
    assert times[1] == (0.5, 0.65) and times[3] == (1.0, 1.3)
    assert 0.65 <= times[2][0] < times[2][1] <= 1.0  # "rocket" was missed: placed between its neighbours
    assert all(b[0] >= a[0] for a, b in zip(times, times[1:]))


def test_estimates_cover_the_span_in_order():
    t = estimate_times(["Hello,", "big", "world."], 1.0, 3.0)
    assert t[0][0] == 1.0 and abs(t[-1][1] - 3.0) < 1e-9 and t[0][1] <= t[1][0]


def test_trim_silence():
    a = np.concatenate([np.zeros(SR), np.ones(SR // 10) * 0.5, np.zeros(SR)]).astype(np.float32)
    assert len(trim_silence(a)) < SR // 5


def test_caption_chunks_break_at_punctuation_and_scenes():
    words = [Word(w, i * 0.3, i * 0.3 + 0.25, scene) for i, (w, scene) in
             enumerate([("This", 0), ("animal", 0), ("has", 0), ("three", 0), ("hearts,", 0), ("blue", 0),
                        ("blood.", 0), ("Meet", 1), ("it.", 1)])]
    chunks = [" ".join(w.text for w in g) for g in group_words(words, max_chars=14)]
    assert chunks == ["This animal has", "three hearts,", "blue blood.", "Meet it."]


def test_ass_file_has_styles_events_and_highlights():
    theme = theme_for("sport")
    words = [Word("Kane", 0.1, 0.4, 0, keyword=True), Word("scores", 0.4, 0.8, 0), Word("again.", 0.8, 1.2, 0)]
    ass = build_ass(words, theme, 2.0, hook="Record breaker", handle="@me")
    assert "Style: Caption,Anton," in ass and "PlayResY: 1920" in ass
    assert ass.count("Dialogue: 1,") == 3  # one event per spoken word
    assert ass_color(theme.highlight) in ass and ass_color(theme.accent) in ass
    assert "RECORD BREAKER" in ass and "@me" in ass
    assert "0:00:00.10" in ass


def test_footage_picks_a_sharp_but_small_file():
    files = [{"width": 3840, "height": 2160, "link": "4k"}, {"width": 1920, "height": 1080, "link": "hd"},
             {"width": 1080, "height": 1920, "link": "portrait"}, {"width": 2160, "height": 3840, "link": "p4k"}]
    assert pick_rendition(files)["link"] == "portrait"
    assert pick_rendition(files[:2])["link"] == "4k"  # HD landscape would be blurry once cropped
    assert cover_scale(1080, 1920) == 1.0


PEXELS = {"videos": [{"id": 11, "duration": 8, "image": "https://img/11.jpg", "video_files": [
    {"file_type": "video/mp4", "width": 1080, "height": 1920, "link": "https://v/11.mp4"}]},
    {"id": 12, "duration": 2, "image": "https://img/12.jpg", "video_files": [
        {"file_type": "video/mp4", "width": 1080, "height": 1920, "link": "https://v/12.mp4"}]}]}
PIXABAY = {"hits": [{"id": 21, "duration": 9, "videos": {"large": {"url": "https://v/21.mp4", "width": 3840,
                                                                   "height": 2160, "thumbnail": "https://img/21"}}}]}


def test_footage_parsing():
    clips = parse_pexels(PEXELS)
    assert [(c.source, c.id, c.portrait) for c in clips] == [("pexels", "11", True), ("pexels", "12", True)]
    assert parse_pixabay(PIXABAY)[0].preview == "https://img/21"


def test_footage_choose_skips_recently_used_clips(tmp_path):
    http = FakeSession({"api.pexels.com": FakeResponse(PEXELS),
                        "https://v/": FakeResponse(None, text="", headers={})})
    http.get = _streaming(http.get)
    f = Footage("key", "", tmp_path, smart=False, avoid={("pexels", "11")}, session=http)
    clip = f.choose("ocean waves", need=2.0)
    assert clip.id == "12" and clip.path.exists()
    again = f.choose("ocean waves", need=2.0)
    assert again.id == "11"  # nothing fresh left, so an older clip beats no clip


def _streaming(get):
    class Stream(FakeResponse):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def iter_content(self, n):
            yield b"fake video bytes"

    def wrapped(url, **kw):
        if url.startswith("https://v/"):
            return Stream(None, text="")
        return get(url, **kw)
    return wrapped


def test_research_helpers(tmp_path):
    page = """<html><head><meta property="og:description" content="Big news today."></head><body>
    <nav><p>Menu menu menu menu menu menu menu menu menu menu menu menu menu menu menu</p></nav>
    <p>The polar vortex is weakening unusually early this year, forecasters said on Tuesday.</p>
    <p>Sign up to our newsletter for more weather news and updates every day of the week!</p>
    <script>var x = "<p>not text</p>";</script></body></html>"""
    text = article_text(page)
    assert text.startswith("Big news today.") and "weakening unusually early" in text
    assert "Menu" not in text and "newsletter" not in text
    assert license_ok("CC BY 2.0", False) and license_ok("Public domain", False) and license_ok("CC0", False)
    assert not license_ok("CC BY-SA 4.0", False) and license_ok("CC BY-SA 4.0", True)
    assert not license_ok("Fair use", True)
    assert not save_jpeg(b"<html>error page</html>", tmp_path / "x.jpg")


def test_shot_plan_covers_the_timeline_without_gaps():
    spans = [(0.0, 4.0), (4.14, 11.0), (11.14, 12.0)]
    shots = plan_shots(spans, 12.45)
    assert shots[0][1] == 0.0 and abs(shots[-1][2] - 12.45) < 1e-6
    assert all(abs(a[2] - b[1]) < 1e-6 for a, b in zip(shots, shots[1:]))
    assert max(e - s for _, s, e, _ in shots) <= 3.2 + 1e-6
    assert [first for *_, first in shots].count(True) == 3


def test_bitrate_keeps_files_under_telegrams_limit():
    for seconds in (30, 65, 120, 170):
        assert (video_kbps(seconds) + 160) * seconds / 8 / 1000 <= 46.5 or video_kbps(seconds) == 2500
    assert video_kbps(20) == 8000


@needs_ffmpeg
def test_render_a_short_video_end_to_end(tmp_path):
    """Two background shots, real captions, voice, music and sound effects: a playable 1080x1920 MP4."""
    work = tmp_path / "work"
    work.mkdir()
    theme = theme_for("science")
    t = np.arange(int(SR * 2.0)) / SR
    write_wav(work / "voice.wav", (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32))
    music = tmp_path / "music.wav"
    write_wav(music, (0.2 * np.sin(2 * np.pi * 330 * t)).astype(np.float32))
    words = [Word("Three", 0.1, 0.5, 0), Word("hearts.", 0.5, 1.0, 0), Word("Wow.", 1.2, 1.8, 1)]
    (work / "captions.ass").write_text(build_ass(words, theme, 2.2, hook="Hello"))
    (work / "fonts").mkdir()
    shots = [Shot(0, 1.1, "background", scene_start=True), Shot(1.1, 2.2, "background", scene_start=True)]
    segs = render_shots(shots, theme, work)
    out = tmp_path / "out.mp4"
    finish(work, segs, 2.2, theme, music, 0.2, make_all(tmp_path / "sfx"), [0.8], out, preset="ultrafast")
    w, h, dur = probe(out)
    assert (w, h) == (1080, 1920) and 2.0 <= dur <= 2.4
    streams = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0",
                              str(out)], capture_output=True, text=True).stdout.split()
    assert sorted(streams) == ["audio", "video"]


def test_final_command_without_music(tmp_path):
    cmd = final_command(tmp_path, [tmp_path / "shot000.mp4"], 10.0, theme_for("news"), None, 0.2,
                        {"whoosh": tmp_path / "w.wav", "pop": tmp_path / "p.wav"}, [], tmp_path / "o.mp4")
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "anullsink" in graph and "sidechaincompress" not in graph and "loudnorm=I=-14" in graph


def test_your_own_topic_takes_wikipedias_best_match(tmp_path):
    from trendclips.research import Researcher
    from trendclips.trends import Trend

    search = FakeResponse({"query": {"search": [{"title": "Daylight saving time"}]}})
    summary = FakeResponse({"description": "Practice of advancing clocks", "extract": "Clocks go forward in spring."})
    http = FakeSession({"page/summary": summary,
                        "w/api.php": lambda url, kw: search if kw["params"].get("list") == "search"
                        else FakeResponse({"query": {"pages": {}}})})
    r = Researcher(tmp_path, session=http)
    mine = r.gather(Trend("why the clocks go back", "you", 1.0))
    assert mine.wiki_title == "Daylight saving time" and "Clocks go forward" in mine.as_text()
    trend = r.gather(Trend("why the clocks go back", "google", 1.0))
    assert trend.wiki_title == ""  # a trend must match by name

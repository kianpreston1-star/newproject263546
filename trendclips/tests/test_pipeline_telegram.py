"""The whole run (with the slow parts replaced) and the Telegram approval flow."""
import pytest

from conftest import FakeLLM, script_reply
from trendclips import pipeline
from trendclips.pipeline import Busy, Produced, job_lock, make_videos, pick_music, post_text, slug
from trendclips.research import Research
from trendclips.telegram import Bot, approval_caption, stats_text
from trendclips.trends import Trend
from trendclips.writer import tidy_script


class FakeTelegram:
    def __init__(self, chat_id="42"):
        self.chat_id = chat_id
        self.sent, self.videos, self.answers, self.buttons = [], [], [], []

    ready = True

    def send(self, text, buttons=None, html_mode=False):
        self.sent.append(text)
        return {"message_id": len(self.sent)}

    def send_video(self, path, caption, buttons=None):
        self.videos.append((path, caption, buttons))
        return {"message_id": 100 + len(self.videos)}

    def answer(self, cid, text=""):
        self.answers.append(text)

    def set_buttons(self, mid, buttons):
        self.buttons.append((mid, buttons))


@pytest.fixture
def fake_run(monkeypatch, cfg, tmp_path):
    """Trends, research and rendering replaced by quick fakes; the AI is a canned reply."""
    trends = [Trend("polar vortex", "google", 1.0, ["The polar vortex is weakening early (BBC)"], sources=["google"]),
              Trend("ballon dor", "wikipedia", 0.9, ["Football's top award"], sources=["wikipedia"])]
    monkeypatch.setattr(pipeline.TrendScanner, "scan", lambda self, recent=(): (trends, []))
    monkeypatch.setattr(pipeline.Researcher, "gather", lambda self, t: Research(
        t.title, ["A solid fact about the topic. " * 8], ["https://www.bbc.co.uk/news/1"]))

    def produce(self, script, image=None, progress=lambda m: None):
        path = tmp_path / f"{slug(script.title)}.mp4"
        path.write_bytes(b"video")
        return Produced(path, 64.0, 300.0, "af_heart", 22, 20)

    monkeypatch.setattr(pipeline.Studio, "produce", produce)
    llm = FakeLLM({"picks": [{"number": 1, "category": "science", "angle": "Early this year"}]},
                  script_reply(words_per_scene=15, scenes=12))
    monkeypatch.setattr(pipeline, "LLM", lambda cfg: llm)
    tg = FakeTelegram()
    monkeypatch.setattr("trendclips.telegram.Telegram", lambda token, chat: tg)
    return tg


def test_make_videos_records_and_sends_for_approval(cfg, store, paths, fake_run):
    lines = []
    made = make_videos(cfg, store, paths, 1, progress=lines.append)
    assert len(made) == 1
    video = store.video(made[0])
    assert video["status"] == "sent" and video["topic"] == "polar vortex" and video["category"] == "science"
    assert video["meta"]["writer"] == "fake" and video["meta"]["sources"] == ["https://www.bbc.co.uk/news/1"]
    path, caption, buttons = fake_run.videos[0]
    assert "The polar vortex is waking up early" in caption and "bbc.co.uk" in caption
    assert buttons["inline_keyboard"][0][0]["callback_data"] == f"post:{made[0]}"
    assert any(line.startswith("Picked: polar vortex") for line in lines)
    assert store.recent_topic_keys(10) == ["polar vortex"]


def test_one_job_at_a_time(paths):
    with job_lock(paths):
        with pytest.raises(Busy):
            with job_lock(paths):
                pass
    with job_lock(paths):  # released afterwards
        pass


def _video(store, tmp_path):
    script = tidy_script(script_reply())
    path = tmp_path / "v.mp4"
    path.write_bytes(b"v")
    vid = store.add_video("polar vortex", "polar vortex", "sent", title=script.title, category="science", path=path,
                          meta={"script": script.to_dict(), "duration": 64, "sources": ["https://a.com/x"],
                                "trend_sources": ["google"], "writer": "gemini", "shots": 20, "stock_shots": 18})
    return vid


def _callback(data, chat="42"):
    return {"callback_query": {"id": "cb1", "data": data, "message": {"message_id": 7, "chat": {"id": int(chat)}}}}


def test_bot_post_and_skip(cfg, store, paths, tmp_path):
    cfg.telegram.chat_id = "42"
    tg = FakeTelegram()
    bot = Bot(cfg, store, paths, tg)
    a, b = _video(store, tmp_path), _video(store, tmp_path)
    bot.handle(_callback(f"post:{a}", chat="999"))  # someone else's chat: ignored
    assert store.video(a)["status"] == "sent" and not tg.sent
    bot.handle(_callback(f"post:{a}"))
    assert store.video(a)["status"] == "approved"
    assert any("TikTok" in s for s in tg.sent) and tg.sent[-1].startswith("<code>")
    assert "#polarvortex" in tg.sent[-1]
    bot.handle(_callback(f"post:{a}"))  # a second tap does nothing
    assert tg.answers[-1] == "Already done"
    bot.handle(_callback(f"skip:{b}"))
    assert store.video(b)["status"] == "skipped"


def test_bot_commands(cfg, store, paths):
    cfg.telegram.chat_id = "42"
    tg = FakeTelegram()
    bot = Bot(cfg, store, paths, tg)
    bot.handle({"message": {"chat": {"id": 42}, "text": "/help"}})
    assert "/make" in tg.sent[-1]
    bot.handle({"message": {"chat": {"id": 42}, "text": "/stats"}})
    assert "No videos yet" in tg.sent[-1]
    bot.handle({"message": {"chat": {"id": 7}, "text": "/make"}})  # not your chat
    assert len(tg.sent) == 2


def test_captions_and_texts(store, tmp_path):
    vid = _video(store, tmp_path)
    video = store.video(vid)
    cap = approval_caption(video)
    assert "a.com" in cap and "18/20 stock shots" in cap and "gemini" in cap
    script = tidy_script(script_reply())
    script.credits = ["Photo: Jane, CC BY 2.0, via Wikimedia Commons"]
    script.sources = ["https://a.com/x"]
    assert "Photo: Jane" in post_text(script) and "Sources" not in post_text(script)
    assert "Sources:\nhttps://a.com/x" in post_text(script, long=True)
    store.update_video(vid, views=1234, status="posted")
    assert "1,234" in stats_text(store)


def test_pick_music_prefers_the_mood_folder(tmp_path):
    (tmp_path / "dramatic").mkdir()
    (tmp_path / "dramatic" / "a.mp3").write_bytes(b"x")
    (tmp_path / "b.mp3").write_bytes(b"x")
    assert pick_music(tmp_path, "dramatic").name == "a.mp3"
    assert pick_music(tmp_path, "chill").name in ("a.mp3", "b.mp3")
    assert pick_music(tmp_path / "missing", "chill") is None


def test_make_from_phone_runs_in_its_own_thread_safely(cfg, store, paths, monkeypatch):
    """/make runs in a background thread, which needs its own database connection."""
    cfg.telegram.chat_id = "42"
    tg = FakeTelegram()

    def fake_make(cfg, thread_store, paths, count, topic="", send=True, progress=print):
        return [thread_store.add_video(topic, topic)]  # fails if the bot's connection was shared

    monkeypatch.setattr(pipeline, "make_videos", fake_make)
    bot = Bot(cfg, store, paths, tg)
    bot.handle({"message": {"chat": {"id": 42}, "text": "/make why the clocks go back"}})
    bot.job.join(10)
    assert not any("failed" in s or "No video" in s for s in tg.sent)
    assert store.videos()[0]["topic"] == "why the clocks go back"

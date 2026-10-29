import json
import shutil

import pytest

from trendclips.config import Config
from trendclips.pipeline import Paths
from trendclips.store import Store


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("TRENDCLIPS_HOME", str(tmp_path / "home"))
    for var in ("TRENDCLIPS_GEMINI_KEY", "TRENDCLIPS_PEXELS_KEY", "TRENDCLIPS_PIXABAY_KEY", "TRENDCLIPS_TELEGRAM_TOKEN",
                "TRENDCLIPS_TELEGRAM_CHAT", "TRENDCLIPS_YOUTUBE_KEY"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path / "home"


@pytest.fixture
def paths(home):
    return Paths(home)


@pytest.fixture
def store(paths):
    s = Store(paths.db)
    yield s
    s.close()


@pytest.fixture
def cfg(tmp_path):
    c = Config()
    c.video.output_dir = str(tmp_path / "videos")
    return c


class FakeResponse:
    def __init__(self, data=None, status=200, text=None, headers=None):
        self._data = data
        self.status_code = status
        self.ok = status < 400
        self.text = text if text is not None else json.dumps(data)
        self.headers = headers or {}

    def json(self):
        if self._data is None:
            raise ValueError("no json")
        return self._data

    def raise_for_status(self):
        import requests

        if self.status_code >= 400:
            raise requests.HTTPError(response=self)


class FakeSession:
    """Answers requests by URL substring; records every call."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls = []
        self.headers = {}

    def _answer(self, method, url, **kw):
        self.calls.append((method, url, kw))
        for part, resp in self.routes.items():
            if part in url:
                return resp(url, kw) if callable(resp) else resp
        return FakeResponse({}, 404)

    def get(self, url, **kw):
        return self._answer("GET", url, **kw)

    def post(self, url, **kw):
        return self._answer("POST", url, **kw)


class FakeLLM:
    """Returns canned replies in order; records the prompts."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []
        self.used = "fake"

    def json(self, system, prompt, temperature=0.8):
        self.prompts.append(prompt)
        return self.replies.pop(0)


def script_reply(words_per_scene: int = 15, scenes: int = 12, category: str = "science") -> dict:
    sentence = " ".join(["word"] * (words_per_scene - 1)) + " end."
    return {
        "title": "The polar vortex is waking up early",
        "hook_text": "Winter is coming early",
        "category": category,
        "mood": "dramatic",
        "scenes": [{"text": sentence, "visual": "snow storm city", "highlight": ["end"]} for _ in range(scenes)],
        "description": "The polar vortex is weakening early this year.",
        "hashtags": ["#weather", "polarvortex", "#winter"],
    }


needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg isn't installed")

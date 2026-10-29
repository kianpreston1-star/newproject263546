"""The AI provider chain, settings and the database."""
import os
import stat
from pathlib import Path

import pytest

from conftest import FakeResponse, FakeSession
from trendclips.config import Config, load_config, save_config
from trendclips.llm import LLM, LLMError, parse_json
from trendclips.store import Store


def test_parse_json_tolerates_fences_and_chatter():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Sure! Here it is: {"a": [1, 2]} Hope that helps') == {"a": [1, 2]}
    with pytest.raises(LLMError):
        parse_json("no json here")


def test_llm_falls_back_to_the_next_provider():
    cfg = Config().ai
    cfg.gemini_api_key = "g-key"
    cfg.openai_base_url, cfg.openai_model, cfg.openai_api_key = "https://api.example.com/v1", "m", "k"
    cfg.providers = ("gemini", "openai")
    http = FakeSession({
        "generativelanguage": FakeResponse({"error": "slow down"}, 429),
        "api.example.com": FakeResponse({"choices": [{"message": {"content": '{"ok": true}'}}]}),
    })
    llm = LLM(cfg, http)
    assert llm.json("sys", "prompt") == {"ok": True}
    assert llm.used == "openai"
    gemini_call = http.calls[0]
    assert gemini_call[2]["headers"]["x-goog-api-key"] == "g-key"  # the key goes in a header, not the URL


def test_llm_with_nothing_set_up_says_how_to_fix_it():
    cfg = Config().ai
    cfg.providers = ("gemini",)
    with pytest.raises(LLMError, match="No AI writer"):
        LLM(cfg, FakeSession({})).json("s", "p")


def test_gemini_reply_skips_thoughts():
    cfg = Config().ai
    cfg.gemini_api_key, cfg.providers = "k", ("gemini",)
    reply = {"candidates": [{"content": {"parts": [{"text": "thinking…", "thought": True}, {"text": '{"x": 2}'}]}}]}
    assert LLM(cfg, FakeSession({"generativelanguage": FakeResponse(reply)})).json("s", "p") == {"x": 2}


def test_config_round_trip_and_validation(home, monkeypatch):
    path = home / "config.toml"
    cfg = Config()
    cfg.ai.gemini_api_key = "secret"
    cfg.video.per_run = 3
    cfg.trends.regions = ("GB",)
    save_config(cfg, path)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    text = path.read_text()
    assert "per_run = 3" in text and "target_seconds" not in text  # only changes are saved
    loaded = load_config(path)
    assert loaded.ai.gemini_api_key == "secret" and loaded.trends.regions == ("GB",)
    monkeypatch.setenv("TRENDCLIPS_GEMINI_KEY", "from-env")
    assert load_config(path).ai.gemini_api_key == "from-env"
    for bad in ["[video]\nper_run = 50", "[video]\nper_rnu = 2", '[schedule]\ndaily_time = "7pm"',
                '[ai]\nproviders = ["chatgpt"]', "[trends]\nregions = \"GB\"", "not toml ["]:
        path.write_text(bad)
        with pytest.raises(ValueError):
            load_config(path)


def test_example_config_loads(tmp_path):
    import trendclips

    example = Path(trendclips.__file__).parent / "config.example.toml"
    cfg = load_config(example)
    assert cfg.video.per_run == 2 and cfg.schedule.daily_time == "17:30"


def test_store(tmp_path):
    s = Store(tmp_path / "db.sqlite")
    a = s.add_video("Polar vortex", "polar vortex", title="T", category="science", meta={"x": 1})
    b = s.add_video("Ballon d'Or", "ballon dor", category="sport")
    s.update_video(a, status="posted", views=1000, meta={"x": 2})
    s.update_video(b, status="posted", views=3000)
    assert s.video(a)["meta"] == {"x": 2}
    assert set(s.recent_topic_keys(10)) == {"polar vortex", "ballon dor"}
    assert list(s.category_performance()) == ["sport", "science"]
    s.mark_clips_used([("pexels", "1"), ("pixabay", 2)])
    assert s.recently_used_clips() == {("pexels", "1"), ("pixabay", "2")}
    s.set("offset", 5)
    assert s.get("offset") == "5" and s.get("missing", "d") == "d"

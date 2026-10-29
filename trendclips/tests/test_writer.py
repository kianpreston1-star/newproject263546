"""Picking trends and turning the AI's reply into a clean, speakable script."""
import pytest

from conftest import FakeLLM, script_reply
from trendclips.llm import LLMError
from trendclips.research import Research
from trendclips.trends import Trend
from trendclips.writer import Pick, Scene, Writer, clean_spoken, fit_length, split_long, tidy_script, word_budget


def test_clean_spoken_makes_text_readable_aloud():
    assert clean_spoken("Kane earns £5m a year 🤯") == "Kane earns 5 million pounds a year"
    assert clean_spoken("Up 40% vs last year (a record)") == "Up 40 percent versus last year, a record"
    assert clean_spoken("**Bold** #hashtag & more") == "Bold hashtag and more"
    assert clean_spoken("It costs $2bn") == "It costs 2 billion dollars"


def test_tidy_script_fixes_common_model_mistakes():
    data = script_reply()
    data["scenes"][0]["highlight"] = ["end", "notthere"]
    data["scenes"][1] = "A bare string scene."
    data["scenes"][2]["visual"] = ""
    data["category"] = "Weather"
    s = tidy_script(data, fallback_category="science")
    assert s.category == "science"  # unknown category falls back
    assert s.scenes[0].highlight == ["end"]  # words not in the text are dropped
    assert s.scenes[1].text == "A bare string scene." and s.scenes[1].visual == "snow storm city"
    assert s.scenes[2].visual == s.scenes[1].visual  # borrowed from its neighbour
    assert s.hashtags == ["#weather", "#polarvortex", "#winter"]
    with pytest.raises(LLMError):
        tidy_script({"scenes": [{"text": "one"}]})


def test_long_scenes_split_and_overlong_scripts_trimmed():
    long = Scene(" ".join(["Short sentence here."] * 12), "city", [])
    parts = split_long([long], max_words=10)
    assert len(parts) > 1 and all(len(p.text.split()) <= 10 for p in parts)
    s = tidy_script(script_reply(words_per_scene=20, scenes=14))
    first, last = s.scenes[0].text, s.scenes[-1].text
    fit_length(s, hi=150)
    assert s.word_count() <= 150 and s.scenes[0].text == first and s.scenes[-1].text == last


def test_word_budget():
    target, lo, hi = word_budget(65, 1.12)
    assert 170 <= target <= 200 and lo < target < hi


def test_pick_maps_numbers_to_trends_and_ignores_junk():
    trends = [Trend(f"trend {i}", "google", 1.0, [f"news {i}"]) for i in range(5)]
    llm = FakeLLM({"picks": [{"number": 3, "category": "sport", "angle": "A record"}, {"number": 99},
                             {"number": "x"}, {"number": 3}, {"number": 1, "category": "made-up"}]})
    picks = Writer(llm).pick(trends, 2, {"sport": {"videos": 3, "avg_views": 1200}})
    assert [(p.trend.title, p.category, p.angle) for p in picks] == [
        ("trend 2", "sport", "A record"), ("trend 0", "news", "trend 0")]
    assert "sport: 1,200" in llm.prompts[0]


def test_write_asks_for_a_rewrite_when_the_length_is_wrong():
    short, right = script_reply(words_per_scene=5, scenes=6), script_reply(words_per_scene=15, scenes=12)
    llm = FakeLLM(short, right)
    w = Writer(llm, target_seconds=65, voice_speed=1.12)
    research = Research("polar vortex", ["The polar vortex is weakening early."], ["https://example.com/a"])
    script = w.write(Pick(Trend("polar vortex", "google", 1), "science", "It's early this year"), research)
    assert len(llm.prompts) == 2 and "needs" in llm.prompts[1]
    assert w.lo <= script.word_count() <= w.hi
    assert script.topic == "polar vortex" and script.sources == ["https://example.com/a"]
    assert "The polar vortex is weakening early." in llm.prompts[0]  # the research reaches the writer
    assert "British spelling" in llm.prompts[0]

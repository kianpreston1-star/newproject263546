import random
import sys
from collections import deque
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import datenight as dn  # noqa: E402

IDEAS = dn.load_ideas()


def test_every_idea_is_within_an_hour_and_has_a_sensible_price():
    for idea in IDEAS:
        assert 0 <= idea["minutes"] <= dn.DRIVE_MAX, idea["name"]
        assert idea["cost"] >= 0, idea["name"]
        assert idea["vibes"], idea["name"]


def test_names_are_unique():
    names = [i["name"] for i in IDEAS]
    assert len(names) == len(set(names))


def test_every_vibe_has_free_and_cheap_options_nearby():
    for vibe in dn.VIBES:
        assert dn.matching(IDEAS, 0, 60, vibe), vibe
        assert len(dn.matching(IDEAS, 30, 30, vibe)) >= 3, vibe


def test_matching_respects_all_three_answers():
    found = dn.matching(IDEAS, 40, 25, "outside")
    assert found
    for idea in found:
        assert idea["cost"] <= 40 and idea["minutes"] <= 25 and "outside" in idea["vibes"]


def test_top_of_budget_slider_means_no_limit():
    pricey = [i for i in IDEAS if i["cost"] > dn.BUDGET_MAX - 1]
    everything = dn.matching(IDEAS, dn.BUDGET_MAX, dn.DRIVE_MAX, None)
    assert len(everything) == len(IDEAS)
    assert all(i in everything for i in pricey)


def test_zero_minutes_means_staying_home():
    assert all(i["where"] == "At home" for i in dn.matching(IDEAS, dn.BUDGET_MAX, 0, None))


def test_pick_avoids_recent_ideas_until_it_runs_out():
    candidates = dn.matching(IDEAS, 30, 20, None)
    recent = deque([c["name"] for c in candidates[:-1]])
    assert dn.pick(candidates, recent, random.Random(1)) is candidates[-1]
    recent.append(candidates[-1]["name"])
    assert dn.pick(candidates, recent, random.Random(1)) in candidates
    assert dn.pick([], recent) is None


def test_directions_start_from_home_postcode():
    idea = next(i for i in IDEAS if i["name"] == "Bradgate Park walk")
    query = parse_qs(urlsplit(dn.directions_url(idea)).query)
    assert query["origin"] == ["LE8 8AL"]
    assert query["destination"] == ["Bradgate Park, UK"]
    assert query["travelmode"] == ["driving"]
    assert dn.directions_url({"maps": ""}) is None


def test_bad_ideas_file_is_reported(tmp_path):
    bad = tmp_path / "ideas.json"
    bad.write_text('[{"name": "Oops", "where": "x", "minutes": 5, "cost": 0, "vibes": ["wild"], "about": "y"}]')
    try:
        dn.load_ideas(bad)
    except ValueError as exc:
        assert "wild" in str(exc)
    else:
        raise AssertionError("expected a ValueError")

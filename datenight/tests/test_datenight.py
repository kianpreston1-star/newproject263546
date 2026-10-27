import random
import time
import sys
from collections import deque
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import datenight as dn  # noqa: E402

IDEAS, TWISTS = dn.load_data()


def test_there_are_about_a_thousand_ideas_and_plenty_of_twists():
    assert len(IDEAS) >= 1000
    assert len(TWISTS) >= 30


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


def test_templates_fill_in_each_town_and_option():
    data = {"towns": [{"name": "Rugby", "minutes": 25, "size": "town"},
                      {"name": "Kibworth", "minutes": 8, "size": "village"}],
            "templates": [{"name": "Dinner in {town}", "sizes": ["town"], "cost": 40, "vibes": ["inside"],
                           "about": "Eat in {town}.", "maps": "restaurants {town}"},
                          {"name": "Cook {x}", "options": ["Thai", "Greek"], "where": "At home", "minutes": 0,
                           "cost": 20, "vibes": ["chill"], "about": "{x} night."}]}
    ideas = {i["name"]: i for i in dn.expand(data)}
    assert set(ideas) == {"Dinner in Rugby", "Cook Thai", "Cook Greek"}
    assert ideas["Dinner in Rugby"]["minutes"] == 25
    assert ideas["Dinner in Rugby"]["maps"] == "restaurants Rugby"
    assert ideas["Cook Greek"]["about"] == "Greek night."


def test_old_list_format_still_loads(tmp_path):
    old = tmp_path / "ideas.json"
    old.write_text('[{"name": "Walk", "where": "x", "minutes": 5, "cost": 0, "vibes": ["outside"], "about": "y"}]')
    ideas, twists = dn.load_data(old)
    assert [i["name"] for i in ideas] == ["Walk"] and twists == []


def test_bad_ideas_file_is_reported(tmp_path):
    bad = tmp_path / "ideas.json"
    bad.write_text('[{"name": "Oops", "where": "x", "minutes": 5, "cost": 0, "vibes": ["wild"], "about": "y"}]')
    try:
        dn.load_ideas(bad)
    except ValueError as exc:
        assert "wild" in str(exc)
    else:
        raise AssertionError("expected a ValueError")


def test_favourites_are_picked_more_and_done_dates_and_rainy_walks_less():
    walk = {"name": "Walk", "vibes": ["outside"]}
    museum = {"name": "Museum", "vibes": ["inside"]}
    assert dn.weight(walk, favourites={"Walk"}) == 3
    assert dn.weight(walk, done={"Walk"}) == 0.25
    assert dn.weight(walk, rainy=True) < 1
    assert dn.weight(museum, rainy=True) == 1
    rng = random.Random(7)
    picks = [dn.pick([walk, museum], deque(), rng, weigh=lambda i: dn.weight(i, favourites={"Museum"}))["name"]
             for _ in range(400)]
    assert picks.count("Museum") > picks.count("Walk") * 2


def test_memories_round_trip_and_your_ideas_join_the_list(tmp_path):
    path = tmp_path / "memories.json"
    assert dn.load_memories(path) == {"favourites": [], "done": [], "my_ideas": [], "retired": [], "deleted": {},
                                      "stamps": {}, "shared": {}}
    mine = {"name": "Chips at Skegness", "where": "Skegness", "minutes": 60, "cost": 20, "vibes": ["outside"],
            "about": "Seaside."}
    assert dn.save_memories({"favourites": ["Walk"], "done": [], "my_ideas": [mine, {"name": "broken"}]}, path)
    loaded = dn.load_memories(path)
    merged = dn.merge_my_ideas(IDEAS, loaded["my_ideas"])
    assert len(merged) == len(IDEAS) + 1 and merged[-1]["mine"]
    assert len(dn.merge_my_ideas(merged, [mine])) == len(merged)  # no duplicates


def test_memory_stats():
    assert "No dates" in dn.memory_stats([])
    done = [{"name": "a", "rating": 4, "cost": 30, "vibes": ["inside"]},
            {"name": "b", "rating": 5, "cost": 10, "vibes": ["inside", "chill"]}]
    stats = dn.memory_stats(done)
    assert "2 dates" in stats and "£40" in stats and "4.5 hearts" in stats and "inside" in stats


def test_share_text_has_everything_she_needs():
    idea = next(i for i in IDEAS if i["name"] == "Bradgate Park walk")
    text = dn.share_text(idea, "Hold hands.")
    assert "Bradgate Park walk" in text and "Hold hands." in text and "google.com/maps" in text


def test_surprise_clues_never_give_the_place_away():
    for idea in IDEAS[:300]:
        clue = dn.surprise_clues(idea)
        assert idea["name"] not in clue and (idea["where"] == "At home" or idea["where"] not in clue)


def test_calendar_file():
    idea = next(i for i in IDEAS if i["name"] == "Warwick Castle")
    ics = dn.make_ics(idea, dn.date(2026, 10, 31), "Wear pink, of course; obviously")
    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n")
    assert "DTSTART:20261031T110000" in ics  # outdoor days start late morning
    assert r"Wear pink\, of course\; obviously" in ics
    assert "BEGIN:VALARM" in ics


def test_calendar_days():
    tuesday = dn.date(2026, 10, 27)
    days = dict(dn.calendar_days(tuesday))
    assert days["Tonight"] == tuesday and days["This Saturday"] == dn.date(2026, 10, 31)
    assert days["Saturday after"] == dn.date(2026, 11, 7)
    saturday = dict(dn.calendar_days(dn.date(2026, 10, 31)))
    assert "This Saturday" not in saturday and saturday["Next Saturday"] == dn.date(2026, 11, 7)
    friday = dict(dn.calendar_days(dn.date(2026, 10, 30)))
    assert "This Saturday" not in friday and friday["Saturday after"] == dn.date(2026, 11, 7)


def test_weather_parsing():
    wet = {"daily": {"weather_code": [63], "temperature_2m_max": [11.4], "precipitation_probability_max": [85]}}
    dry = {"daily": {"weather_code": [1], "temperature_2m_max": [19.6], "precipitation_probability_max": [5]}}
    assert dn.parse_weather(wet) == {"summary": "Today: Rain, 11°C, 85% chance of rain", "rainy": True}
    assert dn.parse_weather(dry)["rainy"] is False
    assert dn.parse_weather({"oops": 1}) is None


def test_every_idea_has_times_and_valid_months():
    for idea in IDEAS:
        assert idea["times"] and set(idea["times"]) <= set(dn.TIMES), idea["name"]
        assert all(1 <= m <= 12 for m in idea["months"]), idea["name"]


def test_time_of_day_and_season_filters():
    late = dn.matching(IDEAS, dn.BUDGET_MAX, dn.DRIVE_MAX, None, "late", 7)
    assert late and all("late" in i["times"] for i in late)
    names_july = {i["name"] for i in dn.matching(IDEAS, dn.BUDGET_MAX, dn.DRIVE_MAX, None, None, 7)}
    names_dec = {i["name"] for i in dn.matching(IDEAS, dn.BUDGET_MAX, dn.DRIVE_MAX, None, None, 12)}
    assert "Paddleboarding on Rutland Water" in names_july and "Paddleboarding on Rutland Water" not in names_dec
    assert "Christmas lights drive" in names_dec and "Christmas lights drive" not in names_july
    xmas = next(i for i in IDEAS if i["name"] == "Christmas lights drive")
    assert dn.weight(xmas, month=12) == 3


def test_every_month_and_time_still_has_plenty_to_pick():
    for month in range(1, 13):
        for when in dn.TIMES:
            assert len(dn.matching(IDEAS, 50, 30, None, when, month)) >= 20, (month, when)


def test_both_say_yes():
    a = {"budget": 30, "minutes": 60, "vibes": ["outside"]}
    b = {"budget": 200, "minutes": 20, "vibes": ["chill"]}
    both = dn.both_match(IDEAS, a, b)
    assert both
    for i in both:
        assert i["cost"] <= 30 and i["minutes"] <= 20 and "outside" in i["vibes"] and "chill" in i["vibes"]


def test_occasions_and_countdown():
    today = dn.date(2026, 10, 27)
    settings = {"anniversary": "2024-11-10", "her_name": "Ellie", "her_birthday": "2001-10-28"}
    first = dn.occasions(settings, today)[0]
    assert first[0] == 1 and first[1] == "Ellie's birthday"
    assert dn.countdown_text(settings, today) == "Ellie's birthday is tomorrow!"
    assert dn.countdown_text({"anniversary": "2024-11-10"}, today) == "14 days until our 2nd anniversary"
    assert dn.countdown_text({}, today).endswith("until Valentine's Day")
    assert dn.occasion_soon(settings, today) and not dn.occasion_soon({}, today)
    leap = dn.occasions({"anniversary": "2024-02-29"}, dn.date(2026, 3, 1))
    assert any(when == dn.date(2027, 2, 28) for _, _, when in leap)


def test_uk_dates():
    assert dn.parse_uk_date("14/03/2024") == dn.date(2024, 3, 14)
    assert dn.parse_uk_date("2024-03-14") == dn.date(2024, 3, 14)
    assert dn.parse_uk_date("1.2.99") == dn.date(1999, 2, 1)
    assert dn.parse_uk_date("31/02/2024") is None and dn.parse_uk_date("soon") is None


def test_streaks_and_badges():
    today = dn.date(2026, 10, 27)  # a Tuesday
    done = [{"date": "2026-10-24"}, {"date": "2026-10-17"}, {"date": "2026-10-10"}, {"date": "2026-09-01"}]
    assert dn.date_streak(done, today) == 3  # nothing yet this week, but the last three weeks in a row
    assert dn.date_streak(done + [{"date": "2026-10-26"}], today) == 4
    assert dn.dates_this_month(done, today) == 3
    assert dn.badges(5) == ["First date logged", "High five"]
    assert dn.new_milestone(10) == "Perfect ten" and dn.new_milestone(11) is None


def test_opening_hours():
    tuesday, saturday = dn.date(2026, 10, 27), dn.date(2026, 10, 31)
    assert dn.hours_on("Mo-Fr 09:00-17:00; Sa 10:00-16:00", tuesday) == "09:00-17:00"
    assert dn.hours_on("Mo-Fr 09:00-17:00; Sa 10:00-16:00", saturday) == "10:00-16:00"
    assert dn.hours_on("Mo-Fr 09:00-17:00", saturday) == "closed"
    assert dn.hours_on("Mo-Su 10:00-16:00; Tu off", tuesday) == "closed"
    assert dn.hours_on("Sa-Mo 10:00-15:00", saturday) == "10:00-15:00"
    assert dn.hours_on("24/7", tuesday) == "open 24 hours"
    assert dn.hours_on("Apr-Sep Mo-Su 10:00-17:00", tuesday) is None
    assert "opening+times" in dn.hours_search_url({"name": "Warwick Castle", "maps": "Warwick Castle"})


def test_backup_and_restore_merge(tmp_path):
    photos = tmp_path / "photos"
    photos.mkdir()
    (photos / "a.png").write_bytes(b"\x89PNG fake")
    mine = {"favourites": ["A"], "done": [{"name": "Walk", "date": "2026-01-01", "photo": "a.png"}], "my_ideas": []}
    backup = dn.make_backup(mine, photos)
    assert backup["photos"] == {"a.png": dn.base64.b64encode(b"\x89PNG fake").decode()}
    elsewhere = tmp_path / "phone"
    other = {"favourites": ["B"], "done": [{"name": "Cinema", "date": "2025-12-01"}], "my_ideas": [{"name": "X"}]}
    merged, added = dn.restore_backup(backup, other, elsewhere)
    assert added == 2 and (elsewhere / "a.png").read_bytes() == b"\x89PNG fake"
    assert [d["name"] for d in merged["done"]] == ["Cinema", "Walk"] and merged["favourites"] == ["B", "A"]
    assert dn.merge_memories(merged, mine)[1] == 0  # restoring twice adds nothing
    try:
        dn.restore_backup({"hello": 1}, other, elsewhere)
    except ValueError:
        pass
    else:
        raise AssertionError("expected a ValueError")


def test_year_review_page():
    done = [{"name": "Walk <b>", "where": "Foxton", "date": "2026-05-01", "rating": 4, "note": "Lovely", "cost": 0,
             "vibes": ["outside"]}, {"name": "Old", "date": "2025-01-01"}]
    page = dn.year_review_html(done, 2026, ("Kian", "Ellie"))
    assert "Our 2026 in dates" in page and "Kian &amp; Ellie" in page and "Walk &lt;b&gt;" in page
    assert "Old" not in page and "Lovely" in page


def test_sounds_are_made_on_the_fly(tmp_path):
    path = dn.make_tone(tmp_path / "chime.wav", dn.SOUNDS["chime"])
    with dn.wave.open(str(path)) as w:
        assert w.getnframes() > 10000


def test_several_photos_per_date_and_old_single_photo_entries(tmp_path):
    old = {"name": "Walk", "date": "2026-01-01", "photo": "a.jpg"}
    assert dn.entry_photos(old) == ["a.jpg"]
    assert {k: v for k, v in dn.normalise_entry(old).items() if k != "id"} == {"name": "Walk", "date": "2026-01-01",
                                                                             "photos": ["a.jpg"]}
    assert dn.normalise_entry(old)["id"] == dn.normalise_entry(dict(old))["id"]  # same id on every device
    assert "photos" not in dn.normalise_entry({"name": "Walk", "date": "2026-01-01", "photos": []})
    path = tmp_path / "memories.json"
    path.write_text('{"done": [{"name": "Walk", "date": "2026-01-01", "photo": "a.jpg"}]}')
    assert dn.load_memories(path)["done"][0]["photos"] == ["a.jpg"]


def test_same_date_on_two_devices_keeps_every_photo():
    laptop = {"favourites": [], "done": [{"name": "Walk", "date": "2026-01-01", "photos": ["a.jpg"]}], "my_ideas": []}
    phone = {"done": [{"name": "Walk", "date": "2026-01-01", "photos": ["a.jpg", "b.jpg"]}]}
    merged, added = dn.merge_memories(laptop, phone)
    assert added == 1 and len(merged["done"]) == 1 and merged["done"][0]["photos"] == ["a.jpg", "b.jpg"]
    assert dn.merge_memories(merged, phone)[1] == 0


def test_photo_files_are_only_deleted_when_unused(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"x")
    memories = {"done": [{"name": "Walk", "photos": ["a.jpg"]}]}
    dn.forget_photo(memories, "a.jpg", tmp_path)
    assert (tmp_path / "a.jpg").exists()
    memories["done"][0]["photos"] = []
    dn.forget_photo(memories, "a.jpg", tmp_path)
    assert not (tmp_path / "a.jpg").exists()


def test_year_review_shows_every_photo(tmp_path):
    for name in ("a.png", "b.png", "c.png"):
        (tmp_path / name).write_bytes(b"\x89PNG")
    page = dn.year_review_html([{"name": "Walk", "date": "2026-05-01", "photos": ["a.png", "b.png", "c.png"]}],
                               2026, photos_dir=tmp_path)
    assert page.count("data:image/png;base64") == 3 and 'class="more"' in page


def test_not_this_one_is_for_this_session_unless_you_have_done_it():
    memories = {"favourites": [], "done": [{"name": "Bradgate Park walk", "date": "2026-01-01"}], "my_ideas": [],
                "retired": []}
    skipped = set()
    assert dn.say_no(memories, skipped, "Warwick Castle") is False
    assert dn.say_no(memories, skipped, "Bradgate Park walk") is True
    names = {i["name"] for i in dn.still_on(IDEAS, skipped, memories["retired"])}
    assert "Warwick Castle" not in names and "Bradgate Park walk" not in names
    next_session = {i["name"] for i in dn.still_on(IDEAS, set(), memories["retired"])}
    assert "Warwick Castle" in next_session and "Bradgate Park walk" not in next_session
    dn.bring_back(memories, skipped, "Bradgate Park walk")
    assert memories["retired"] == [] and "Bradgate Park walk" in {i["name"] for i in dn.still_on(IDEAS, skipped, [])}
    merged, added = dn.merge_memories({"retired": []}, {"retired": ["Warwick Castle"]})
    assert merged["retired"] == ["Warwick Castle"] and added == 1


# Syncing

from fake_supabase import KEY, FakeSupabase  # noqa: E402


def _entry(name, day, **extra):
    return dict({"id": dn.new_entry_id(), "name": name, "date": day, "updated": dn.now_stamp(), "rating": 5}, **extra)


def test_merge_sync_newest_change_wins_and_deletes_spread():
    walk = _entry("Walk", "2026-01-01")
    a = {"done": [walk]}
    b = dn.merge_sync({}, a)
    time.sleep(0.002)
    edited = dict(walk, note="Lovely", updated=dn.now_stamp())
    b["done"] = [edited]
    merged = dn.merge_sync(a, b)
    assert merged["done"][0]["note"] == "Lovely"
    dn.delete_entry(merged, walk["id"])
    assert dn.merge_sync(a, merged)["done"] == [] and dn.merge_sync(merged, b)["done"] == []


def test_merge_sync_favourites_retired_and_shared_settings():
    a, b = dn.sync_shape({}), dn.sync_shape({})
    dn.set_flag(a, "favourites", "Bradgate Park walk", True)
    merged = dn.merge_sync(a, b)
    assert merged["favourites"] == ["Bradgate Park walk"]
    dn.set_flag(b, "favourites", "Bradgate Park walk", False)  # later, on the other phone
    b["stamps"]["favourites:Bradgate Park walk"][1] = "9999"
    assert dn.merge_sync(merged, b)["favourites"] == []
    dn.set_shared(a, "her_name", "Ellie")
    assert dn.shared_values(dn.merge_sync(b, a)) == {"her_name": "Ellie"}


def test_pairing_text_round_trip():
    config = {"url": "abc.supabase.co", "key": "sb_publishable_x", "code": dn.new_sync_code()}
    parsed = dn.parse_pairing(dn.make_pairing(config))
    assert parsed == dict(config, url="https://abc.supabase.co")
    assert dn.parse_pairing("hello") is None and dn.parse_pairing(dn.PAIRING_PREFIX + "!!!") is None


def test_three_devices_sync_dates_photos_edits_and_deletes(tmp_path):
    server = FakeSupabase().start()
    try:
        code = dn.new_sync_code()
        laptop, kian, ellie = (dn.SyncClient(server.url, KEY, code) for _ in range(3))
        dirs = {n: tmp_path / n for n in ("laptop", "kian", "ellie")}
        dirs["kian"].mkdir()
        (dirs["kian"] / "pic.jpg").write_bytes(b"\xff\xd8 photo")
        kian_mem = dn.sync_shape({"done": [_entry("Foxton walk", "2026-09-14", photos=["pic.jpg"])]})
        dn.set_flag(kian_mem, "favourites", "Warwick Castle", True)
        kian_mem, stats = dn.sync_once(kian, kian_mem, dirs["kian"])
        assert stats["uploaded"] == 1

        laptop_mem, stats = dn.sync_once(laptop, dn.sync_shape({}), dirs["laptop"])
        assert [d["name"] for d in laptop_mem["done"]] == ["Foxton walk"] and stats["downloaded"] == 1
        assert (dirs["laptop"] / "pic.jpg").read_bytes() == b"\xff\xd8 photo"
        assert laptop_mem["favourites"] == ["Warwick Castle"]

        # Ellie and the laptop both change things before syncing: both changes survive.
        ellie_mem, _ = dn.sync_once(ellie, dn.sync_shape({}), dirs["ellie"])
        ellie_mem["done"].append(_entry("Cinema", "2026-10-03"))
        laptop_mem["done"][0] = dict(laptop_mem["done"][0], note="Boats!", updated=dn.now_stamp())
        ellie_mem, _ = dn.sync_once(ellie, ellie_mem, dirs["ellie"])
        laptop_mem, _ = dn.sync_once(laptop, laptop_mem, dirs["laptop"])
        kian_mem, _ = dn.sync_once(kian, kian_mem, dirs["kian"])
        assert [(d["name"], d.get("note")) for d in kian_mem["done"]] == [("Foxton walk", "Boats!"), ("Cinema", None)]

        # A deletion on one phone disappears everywhere.
        cinema = next(d for d in kian_mem["done"] if d["name"] == "Cinema")
        dn.delete_entry(kian_mem, cinema["id"])
        dn.sync_once(kian, kian_mem, dirs["kian"])
        laptop_mem, _ = dn.sync_once(laptop, laptop_mem, dirs["laptop"])
        assert [d["name"] for d in laptop_mem["done"]] == ["Foxton walk"]

        # A device with nothing new doesn't keep re-saving.
        before = server.docs[code][1]
        dn.sync_once(laptop, laptop_mem, dirs["laptop"])
        assert server.docs[code][1] == before

        try:
            dn.sync_once(dn.SyncClient(server.url, "wrong", code), laptop_mem, dirs["laptop"])
        except dn.SyncError as exc:
            assert "key" in str(exc)
        else:
            raise AssertionError("expected a SyncError")
    finally:
        server.stop()

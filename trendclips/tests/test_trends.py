"""Reading the trend feeds, merging duplicates and keeping sensitive topics out."""
import datetime as dt

from trendclips.trends import (Trend, merge, parse_google_trends, parse_reddit, parse_wikipedia_mostread,
                               parse_youtube, sensitive_reason, similar, tokens, topic_key)

GOOGLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:ht="https://trends.google.com/trending/rss" version="2.0"><channel>
<item><title>polar vortex</title><ht:approx_traffic>20K+</ht:approx_traffic>
  <ht:news_item><ht:news_item_title>The polar vortex shows signs of a rare early weakening</ht:news_item_title>
  <ht:news_item_snippet>Forecasters say&apos;s colder air may arrive.</ht:news_item_snippet>
  <ht:news_item_url>https://example.com/vortex</ht:news_item_url><ht:news_item_source>The Globe</ht:news_item_source>
  </ht:news_item></item>
<item><title>itvx</title><ht:approx_traffic>2000+</ht:approx_traffic></item>
</channel></rss>"""


def test_google_trends_feed():
    trends = parse_google_trends(GOOGLE_RSS)
    assert [t.title for t in trends] == ["polar vortex", "itvx"]
    vortex = trends[0]
    assert vortex.score > trends[1].score
    assert vortex.context[0] == "The polar vortex shows signs of a rare early weakening (The Globe)"
    assert "Forecasters say's colder air may arrive." in vortex.context
    assert vortex.links == ["https://example.com/vortex"]


def _article(title, views, history, description=""):
    return {"normalizedtitle": title, "title": title.replace(" ", "_"), "views": views, "description": description,
            "view_history": [{"views": v} for v in history + [views]], "extract": f"About {title}."}


def test_wikipedia_keeps_spikes_and_flags_recent_deaths():
    data = {"mostread": {"articles": [
        _article("Ballon d'Or", 271061, [12677, 11309, 15455, 219157]),
        _article("YouTube", 150000, [140000, 150000, 160000, 155000]),  # always popular: not a trend
        _article("Main Page", 9_000_000, [1, 1, 1, 1]),
        _article("Deaths in 2026", 144961, [1000, 1000, 1000, 1000]),
        _article("Special:Search", 99999, [1, 1, 1, 1]),
        _article("Eric Bauza", 156871, [1164, 1547, 1406, 511715], "Canadian voice actor (1979–2026)"),
    ]}}
    trends = parse_wikipedia_mostread(data, today=dt.date(2026, 10, 28))
    assert [t.title for t in trends] == ["Ballon d'Or", "Eric Bauza"]
    assert trends[0].wiki_title == "Ballon d'Or"
    assert sensitive_reason(trends[1]) == "a death or tragedy"
    assert sensitive_reason(trends[0]) is None


def test_reddit_and_youtube_parsing():
    reddit = {"data": {"children": [
        {"data": {"title": "TIL that octopuses have three hearts", "ups": 50000, "permalink": "/r/til/1"}},
        {"data": {"title": "NSFW thing", "over_18": True}},
        {"data": {"title": "Mod post", "stickied": True}},
    ]}}
    posts = parse_reddit(reddit, "todayilearned")
    assert [p.title for p in posts] == ["octopuses have three hearts"]
    yt = {"items": [
        {"id": "a", "snippet": {"title": "Big Song (Official Video)", "categoryId": "10", "channelTitle": "x"},
         "statistics": {"viewCount": "9000000"}},
        {"id": "b", "snippet": {"title": "Modern Warfare 4 | Official Reveal Trailer", "categoryId": "20",
                                "channelTitle": "COD", "tags": ["cod"]}, "statistics": {"viewCount": "100"}},
    ]}
    videos = parse_youtube(yt)
    assert [v.title for v in videos] == ["Modern Warfare 4"]  # music videos are skipped


def test_similar_titles_merge_and_score_higher():
    assert tokens("2026 Ballon d'Or") == tokens("Ballon d'Or") == {"ballon", "dor"}
    assert similar("Harry Kane", "harry kane hat trick")
    assert not similar("Harry Kane", "Harry Styles tour")
    merged = merge([
        Trend("Ballon d'Or", "google", 0.8, ["Google headline"]),
        Trend("2026 Ballon d'Or", "wikipedia", 0.9, ["Wikipedia text"], wiki_title="2026 Ballon d'Or"),
        Trend("itvx", "google", 0.95),
    ])
    top = merged[0]
    assert top.sources == ["google", "wikipedia"] and top.wiki_title == "2026 Ballon d'Or"
    assert set(top.context) == {"Google headline", "Wikipedia text"}
    assert topic_key("The Ballon d'Or 2026") == "ballon dor"


def test_sensitive_topics_are_skipped_but_sport_words_are_not():
    def reason(title, *ctx, **kw):
        return sensitive_reason(Trend(title, "google", 1, list(ctx)), **kw)

    assert reason("Walter Koenig", "Star Trek actor dies aged 90") == "a death or tragedy"
    assert reason("hurricane milton") == "a disaster"
    assert reason("general election", "Polls open across the country") == "politics"
    assert reason("general election", "Polls open", allow_politics=True) is None
    assert reason("arsenal", "Saka named best attacking midfielder of the month") is None
    assert reason("crypto news", avoid_words=("crypto",)) == 'your avoid list ("crypto")'
    assert reason("Star Wars", "New Star Wars trailer drops") is None

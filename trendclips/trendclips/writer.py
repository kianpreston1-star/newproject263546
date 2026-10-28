"""The editor and the scriptwriter: picks which trends make good videos, then writes a script that only uses
the researched facts and is built to keep people watching."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field

from .llm import LLM, LLMError
from .research import Research
from .trends import Trend

log = logging.getLogger(__name__)

CATEGORIES = ("tech", "money", "sport", "entertainment", "science", "gaming", "news", "lifestyle")
MOODS = ("energetic", "dramatic", "upbeat", "chill")
WORDS_PER_SECOND = 2.55  # Kokoro's pace at speed 1.0, pauses included

PICK_SYSTEM = """You are the producer of a fast-growing faceless short-video channel (YouTube Shorts, TikTok and \
Instagram Reels) for viewers in {audience}. Each day you choose which of today's trends become one-minute videos \
made from stock footage, an AI voice and big captions. You only choose trends that are safe, have a real story and \
will make a stranger stop scrolling."""

PICK_PROMPT = """Today's trends (number, title, where it's trending, what the news says):

{trends}
{performance}
Choose the {n} best trends for videos, best first, plus up to {spare} spares in case one doesn't work out.

A good pick:
- has broad appeal: people outside a niche would stop scrolling for it
- has a real story or a surprising, explainable angle (a record, a first, a twist, a mystery, a "why is everyone \
talking about this", an explainer like "why the clocks change")
- can be shown with generic stock footage; no need for the actual match, clip or person
- has clear facts in the news lines, not just rumours

Never pick: deaths, illness, crime, violence, war, disasters or tragedies; politics, elections or politicians; \
religion; adult content; anything about children; gossip about private people; a match fixture that's just a \
score (unless there's a bigger story, like a record); trends where the news lines don't make clear what happened.

Reply with JSON only:
{{"picks": [{{"number": <trend number>, "category": "<one of: {categories}>", "angle": "<the specific story or \
surprising angle of the video, one sentence>"}}]}}"""

SCRIPT_SYSTEM = """You write scripts for viral faceless short videos (YouTube Shorts, TikTok, Instagram Reels) for \
viewers in {audience}. An AI voice reads the script over stock footage with big animated captions. Your scripts \
are accurate, gripping from the first second and written for the ear."""

SCRIPT_PROMPT = """Write a video about this trend.

TREND: {topic}
ANGLE: {angle}

RESEARCH NOTES (the only facts you may use):
{notes}

RULES
1. Facts: use only facts from the research notes. Never invent names, numbers, quotes, dates, scores, prices or \
reasons. If the notes don't say it, leave it out. Widely known background is fine (e.g. what the Ballon d'Or is). \
If the story is still developing, say "so far" or "reportedly".
2. Hook: the first sentence (12 words at most) must stop the scroll: a surprising fact, a bold claim the video then \
proves, or a question the viewer needs answered. No greetings, no "in this video", no "did you know", no channel name.
3. Flow: hook, then what happened, then the two or three most interesting details or twists, then the payoff. \
Every sentence must make the viewer want the next one; use open loops like "but here's the twist".
4. Ending: the last sentence must lead straight back into the first sentence, so the video loops seamlessly when it \
replays, or ask a sharp question people will want to answer in the comments. Never "like and subscribe".
5. Style: spoken, punchy, simple words, sentences of 15 words or fewer, mostly present tense. {spelling} spelling. \
Write money, numbers and symbols the way they're said: "5 million pounds", "40 percent", "versus". No emojis, \
hashtags, abbreviations or brackets.
6. Length: {lo} to {hi} words of narration in total (about {seconds} seconds).
7. Scenes: split the narration into {min_scenes} to {max_scenes} scenes of one or two sentences each. For each \
scene, "visual" is a 2 to 5 word stock-footage search showing something concrete on screen at that moment \
("packed football stadium at night", "clock hands spinning", "woman laughing on stage"). Never put names of people, \
brands, teams, shows or events in "visual"; stock libraries don't have them. Use a different visual each scene.
8. "highlight": the one or two most important words of each scene, copied exactly from its text; they're coloured \
in the captions.
9. Neutral and respectful. No insults, no political opinions, no medical or money advice.

Reply with JSON only:
{{"title": "<YouTube title, 70 characters max: the subject plus curiosity; no false clickbait, no hashtags>",
"hook_text": "<2 to 6 word on-screen headline shown for the first 2 seconds>",
"category": "<one of: {categories}>",
"mood": "<one of: {moods}>",
"scenes": [{{"text": "<narration>", "visual": "<stock footage search>", "highlight": ["<word>"]}}],
"description": "<2 or 3 factual sentences for the video description>",
"hashtags": ["#<tag>", "<3 to 5 relevant hashtags>"]}}"""

DUO_SYSTEM = """You write viral two-character comedy explainer shorts (YouTube Shorts, TikTok, Instagram Reels) \
for viewers in {audience}: two cartoon characters bicker their way through today's trending story while big \
captions play over a satisfying background video. Your scripts are genuinely funny, accurate and fast."""

DUO_PROMPT = """Write a dialogue about this trend.

TREND: {topic}
ANGLE: {angle}

RESEARCH NOTES (the only facts you may use):
{notes}

CAST
- "{a_id}", {a_name}: {a_bio}
- "{b_id}", {b_name}: {b_bio}
{a_name} asks the questions and gets things wrong; {b_name} knows the facts.

RULES
1. Facts: only {b_name} states facts, and only facts from the research notes. Never invent names, numbers, quotes, \
dates, scores or reasons. {a_name}'s wrong guesses must be obviously silly and get corrected.
2. Hook: line 1 is {a_name}, 12 words at most: a shocked or ridiculous question or claim that names the topic and \
makes viewers need the answer.
3. Comedy: at least three genuinely funny moments: absurd comparisons, misunderstandings, deadpan sarcasm, a callback \
to an earlier joke. The banter is affectionate; they only ever tease each other.
4. Flow: mostly alternate speakers. {b_name} explains the real story in small bites; {a_name} reacts, jokes and asks \
the next question viewers are thinking. Every line makes the viewer want the next.
5. Ending: finish on a punchline. Best of all, the last line leads straight back into the first so the video loops \
when it replays. Never "like and subscribe".
6. Lines: {min_lines} to {max_lines} lines of 4 to 20 words, written to be spoken: contractions, {spelling} \
spelling, money and numbers as they're said ("5 million pounds", "40 percent"). No emojis, stage directions, \
brackets, or the speaker's own name at the start of a line.
7. Length: {lo} to {hi} words in total (about {seconds} seconds).
8. Never mock real people, groups, illness or tragedies; no swearing stronger than "bloody"; no political opinions.
9. For each line, "visual" is a 2 to 5 word stock-footage search showing what the line is about ("polar ice \
aerial", "football stadium crowd"), never names of people or brands; "highlight" is the one or two most important \
words, copied exactly from the line.

Reply with JSON only:
{{"title": "<YouTube title, 70 characters max: the subject plus curiosity; no false clickbait, no hashtags>",
"hook_text": "<2 to 6 word on-screen headline shown for the first 2 seconds>",
"category": "<one of: {categories}>",
"mood": "<one of: {moods}>",
"lines": [{{"speaker": "<{a_id} or {b_id}>", "text": "<what they say>", "visual": "<search>", \
"highlight": ["<word>"]}}],
"description": "<2 or 3 factual sentences for the video description>",
"hashtags": ["#<tag>", "<3 to 5 relevant hashtags>"]}}"""

REPAIR_PROMPT = """Your script has {words} words of narration, but it needs {lo} to {hi}. Rewrite it to fit: same \
facts, same hook, same rules and the same JSON format. Here it is:

{script}"""


@dataclass
class Scene:
    text: str
    visual: str
    highlight: list[str] = field(default_factory=list)
    speaker: str = ""  # character id in two-character videos


@dataclass
class Script:
    title: str
    hook_text: str
    category: str
    mood: str
    scenes: list[Scene]
    description: str
    hashtags: list[str]
    topic: str = ""
    sources: list[str] = field(default_factory=list)
    credits: list[str] = field(default_factory=list)

    @property
    def narration(self) -> str:
        return " ".join(s.text for s in self.scenes)

    def word_count(self) -> int:
        return len(self.narration.split())

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Script":
        d = dict(d)
        d["scenes"] = [Scene(**s) if isinstance(s, dict) else s for s in d.get("scenes", [])]
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Pick:
    trend: Trend
    category: str
    angle: str


def word_budget(seconds: int, voice_speed: float) -> tuple[int, int, int]:
    """(target, minimum, maximum) narration words for a video of about `seconds`."""
    target = round(seconds * WORDS_PER_SECOND * voice_speed)
    return target, round(target * 0.82), round(target * 1.15)


SPOKEN = [
    (r"£\s?(\d[\d,.]*)\s?(bn|billion)\b", r"\1 billion pounds"),
    (r"£\s?(\d[\d,.]*)\s?(m|million)\b", r"\1 million pounds"),
    (r"£\s?(\d[\d,.]*)\s?(k)\b", r"\1 thousand pounds"),
    (r"£\s?(\d[\d,.]*)", r"\1 pounds"),
    (r"\$\s?(\d[\d,.]*)\s?(bn|billion)\b", r"\1 billion dollars"),
    (r"\$\s?(\d[\d,.]*)\s?(m|million)\b", r"\1 million dollars"),
    (r"\$\s?(\d[\d,.]*)", r"\1 dollars"),
    (r"€\s?(\d[\d,.]*)", r"\1 euros"),
    (r"(\d)\s?%", r"\1 percent"),
    (r"\s&\s", " and "),
    (r"\bvs\.?(?=\s)", "versus"),
    (r"\be\.g\.", "for example"),
    (r"\bi\.e\.", "that is"),
]


def clean_spoken(text: str) -> str:
    """Makes text safe to read aloud and to show as captions: no symbols the voice would stumble on."""
    for pattern, repl in SPOKEN:
        text = re.sub(pattern, repl, text, flags=re.I)
    text = re.sub(r"[\U00010000-\U0010FFFF☀-➿️]", "", text)  # emojis
    text = re.sub(r"[#*_~`<>\[\]{}|\\^]", "", text)
    text = re.sub(r"\(([^)]*)\)", r", \1,", text)
    text = text.replace("—", ", ").replace("–", " to ").replace(" - ", ", ")
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    text = re.sub(r",\s*,", ",", text)
    return re.sub(r"\s+", " ", text).strip(" ,")


def split_long(scenes: list[Scene], max_words: int = 26) -> list[Scene]:
    out = []
    for s in scenes:
        if len(s.text.split()) <= max_words:
            out.append(s)
            continue
        sentences = re.split(r"(?<=[.!?])\s+", s.text)
        chunk: list[str] = []
        for sent in sentences:
            if chunk and len(" ".join(chunk + [sent]).split()) > max_words:
                out.append(Scene(" ".join(chunk), s.visual, s.highlight, s.speaker))
                chunk = []
            chunk.append(sent)
        if chunk:
            out.append(Scene(" ".join(chunk), s.visual, s.highlight, s.speaker))
    return out


def _speaker(raw: str, cast: list, previous: str) -> str:
    """Matches the AI's speaker label ("Dave", "Big Dave", "dave") to a cast id; a stray label alternates."""
    raw = str(raw or "").strip().lower()
    for c in cast:
        if raw and (raw == c.id or raw == c.name.lower() or raw in c.name.lower().split() or c.id in raw):
            return c.id
    others = [c.id for c in cast if c.id != previous]
    return others[0] if others else cast[0].id


def tidy_script(data: dict, fallback_category: str = "news", cast: list | None = None) -> Script:
    """Turns the AI's JSON into a clean Script, fixing the small mistakes models make. With a cast, it's a
    dialogue: each line keeps its speaker."""
    if not isinstance(data, dict):
        raise LLMError("The script wasn't a JSON object")
    raw_scenes = data.get("lines") or data.get("scenes") or []
    scenes = []
    previous = ""
    for s in raw_scenes:
        if isinstance(s, str):
            s = {"text": s}
        if not isinstance(s, dict):
            continue
        text = clean_spoken(str(s.get("text") or s.get("narration") or ""))
        if not text:
            continue
        visual = re.sub(r"[^\w\s'-]", " ", str(s.get("visual") or s.get("footage") or "")).strip()
        visual = " ".join(visual.split()[:6])
        hl = s.get("highlight") or []
        hl = [hl] if isinstance(hl, str) else hl
        words = {w.strip(".,!?;:\"'").lower() for w in text.split()}
        hl = [str(h).strip() for h in hl if str(h).strip().lower() in words][:2]
        speaker = ""
        if cast:
            speaker = previous = _speaker(s.get("speaker") or s.get("character") or "", cast, previous)
            for c in cast:  # "Big Dave: ..." or "Dave, ..." at the start of a line isn't meant to be spoken
                for label in (c.name, c.name.split()[-1], c.id):
                    if text.lower().startswith(label.lower() + ":"):
                        text = text[len(label) + 1:].strip()
        scenes.append(Scene(text, visual, hl, speaker))
    if len(scenes) < 3:
        raise LLMError("The script had fewer than 3 scenes")
    if not cast:
        scenes = split_long(scenes)
    for i, s in enumerate(scenes):  # a missing visual borrows its neighbour's
        if not s.visual:
            s.visual = scenes[i - 1].visual if i else next((x.visual for x in scenes if x.visual), "city timelapse")
    category = str(data.get("category", "")).lower().strip()
    mood = str(data.get("mood", "")).lower().strip()
    tags = data.get("hashtags") or []
    tags = [tags] if isinstance(tags, str) else tags
    hashtags = []
    for t in tags:
        t = "#" + re.sub(r"[^\w]", "", str(t))
        if len(t) > 2 and t.lower() not in {h.lower() for h in hashtags}:
            hashtags.append(t)
    title = clean_spoken(str(data.get("title", "")))[:100] or scenes[0].text[:70]
    hook = clean_spoken(str(data.get("hook_text") or data.get("hook") or "")) or title
    return Script(
        title=title,
        hook_text=" ".join(hook.split()[:7]),
        category=category if category in CATEGORIES else fallback_category,
        mood=mood if mood in MOODS else "energetic",
        scenes=scenes,
        description=clean_spoken(str(data.get("description", ""))),
        hashtags=hashtags[:5],
    )


def fit_length(script: Script, hi: int) -> Script:
    """Last resort for a script that's still too long: drop scenes from the middle, keeping hook and ending."""
    while script.word_count() > hi and len(script.scenes) > 4:
        script.scenes.pop(len(script.scenes) // 2)
    return script


class Writer:
    def __init__(self, llm: LLM, audience: str = "the UK and the US", target_seconds: int = 65,
                 voice_speed: float = 1.12):
        self.llm = llm
        self.audience = audience
        self.seconds = target_seconds
        self.target, self.lo, self.hi = word_budget(target_seconds, voice_speed)

    def pick(self, trends: list[Trend], n: int, performance: dict | None = None) -> list[Pick]:
        if not trends:
            return []
        shown = trends[:30]
        lines = []
        for i, t in enumerate(shown, 1):
            news = " / ".join(c[:160] for c in t.context[:3])
            lines.append(f"{i}. {t.title} [{', '.join(t.sources or [t.source])}] {news}")
        perf = ""
        if performance:
            perf = "\nHow past videos did, by category (average views): " + ", ".join(
                f"{c}: {p['avg_views']:,} over {p['videos']} videos" for c, p in performance.items()) + \
                   ". Lean towards what works, but a great story beats the category.\n"
        prompt = PICK_PROMPT.format(trends="\n".join(lines), performance=perf, n=n, spare=max(2, n),
                                    categories=", ".join(CATEGORIES))
        data = self.llm.json(PICK_SYSTEM.format(audience=self.audience), prompt, temperature=0.4)
        items = data.get("picks", data) if isinstance(data, dict) else data
        picks, seen = [], set()
        for item in items if isinstance(items, list) else []:
            try:
                idx = int(item.get("number", item.get("index", 0))) - 1
            except (TypeError, ValueError, AttributeError):
                continue
            if 0 <= idx < len(shown) and idx not in seen:
                seen.add(idx)
                cat = str(item.get("category", "")).lower()
                picks.append(Pick(shown[idx], cat if cat in CATEGORIES else "news",
                                  str(item.get("angle", "")).strip() or shown[idx].title))
        return picks

    def write(self, pick: Pick, research: Research, cast: list | None = None) -> Script:
        """A narrated script, or with a cast of two, a dialogue between them."""
        spelling = "British" if "UK" in self.audience or "Britain" in self.audience else "American"
        common = dict(topic=pick.trend.title, angle=pick.angle, notes=research.as_text(), spelling=spelling,
                      lo=self.lo, hi=self.hi, seconds=self.seconds, categories=", ".join(CATEGORIES),
                      moods=", ".join(MOODS))
        if cast:
            a, b = cast[0], cast[1]
            n_lines = max(8, round(self.seconds / 4))
            prompt = DUO_PROMPT.format(**common, a_id=a.id, a_name=a.name, a_bio=a.personality, b_id=b.id,
                                       b_name=b.name, b_bio=b.personality, min_lines=n_lines - 3,
                                       max_lines=n_lines + 3)
            system = DUO_SYSTEM.format(audience=self.audience)
        else:
            n_scenes = max(6, round(self.seconds / 4.5))
            prompt = SCRIPT_PROMPT.format(**common, min_scenes=n_scenes - 3, max_scenes=n_scenes + 3)
            system = SCRIPT_SYSTEM.format(audience=self.audience)
        data = self.llm.json(system, prompt, temperature=0.9 if cast else 0.85)
        script = tidy_script(data, pick.category, cast)
        words = script.word_count()
        if not self.lo <= words <= self.hi:
            log.info("Script is %d words (wanted %d-%d); asking for a rewrite", words, self.lo, self.hi)
            try:
                data = self.llm.json(system, REPAIR_PROMPT.format(words=words, lo=self.lo, hi=self.hi,
                                                                  script=json.dumps(data, ensure_ascii=False)),
                                     temperature=0.5)
                fixed = tidy_script(data, pick.category, cast)
                if abs(fixed.word_count() - self.target) < abs(words - self.target):
                    script = fixed
            except LLMError as e:
                log.info("Rewrite failed (%s); keeping the first version", e)
        script = fit_length(script, self.hi)
        script.topic = pick.trend.title
        script.sources = research.sources
        if research.image:
            script.credits.append(research.image.credit)
        return script

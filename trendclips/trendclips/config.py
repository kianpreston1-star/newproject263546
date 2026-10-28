"""Settings. Every value has a default here; ~/.trendclips/config.toml overrides any of them."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path

import tomllib


def home_dir() -> Path:
    """Where Trend Clips keeps its config, keys, models, database and logs. Never inside the repository."""
    return Path(os.environ.get("TRENDCLIPS_HOME") or Path.home() / ".trendclips").expanduser()


@dataclass
class TrendsConfig:
    regions: tuple = ("GB", "US")  # Google Trends countries to watch
    google_trends: bool = True
    wikipedia: bool = True  # articles whose views suddenly jumped
    reddit: bool = True
    reddit_subs: tuple = ("technology", "movies", "television", "gaming", "sports", "soccer", "space",
                          "science", "todayilearned", "interestingasfuck", "Damnthatsinteresting")
    youtube: bool = True  # trending videos; needs youtube.api_key
    repeat_after_days: int = 10  # don't cover the same topic again sooner than this
    allow_politics: bool = False  # elections, parties and politicians attract strikes and arguments
    avoid_words: tuple = ()  # skip any trend containing one of these words


@dataclass
class AIConfig:
    providers: tuple = ("gemini", "openai", "ollama")  # tried in this order; ones that aren't set up are skipped
    gemini_api_key: str = ""  # free from https://aistudio.google.com/apikey
    gemini_model: str = "gemini-flash-latest"
    openai_base_url: str = ""  # any OpenAI-compatible API, e.g. https://api.groq.com/openai/v1
    openai_api_key: str = ""
    openai_model: str = ""
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "gemma3:4b"
    audience: str = "the UK and the US"


@dataclass
class VideoConfig:
    per_run: int = 2  # videos made by each daily run
    target_seconds: int = 65  # over 60 s qualifies for TikTok's Creator Rewards; still a YouTube Short
    voice: str = "af_heart"  # one recognisable narrator; "auto" picks a voice per topic instead
    voice_speed: float = 1.12
    music_volume: float = 0.16  # background music level (it also drops automatically under the voice)
    handle: str = ""  # your @name, shown faintly on every video so re-uploads still credit you
    smart_footage: bool = True  # an image-matching AI checks each stock clip fits what's being said
    allow_share_alike_images: bool = False  # also use CC BY-SA photos from Wikipedia (see README)
    output_dir: str = "~/Videos/TrendClips"
    preset: str = "veryfast"  # x264 speed: slower presets make slightly smaller files but take longer


@dataclass
class FootageConfig:
    pexels_api_key: str = ""  # free from https://www.pexels.com/api/
    pixabay_api_key: str = ""  # free from https://pixabay.com/api/docs/


@dataclass
class TelegramConfig:
    bot_token: str = ""  # from @BotFather
    chat_id: str = ""  # found automatically by `trendclips setup`


@dataclass
class YouTubeConfig:
    api_key: str = ""  # free; reads trending videos and your video stats
    channel_id: str = ""  # your channel (starts with UC), for stats
    upload: bool = False  # post approved videos automatically (needs `trendclips youtube-login`)
    privacy: str = "public"  # "public", "unlisted" or "private"


@dataclass
class ScheduleConfig:
    daily_time: str = "17:30"  # when the daily run makes videos (24-hour clock); the laptop must be on


@dataclass
class Config:
    trends: TrendsConfig = field(default_factory=TrendsConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    video: VideoConfig = field(default_factory=VideoConfig)
    footage: FootageConfig = field(default_factory=FootageConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    youtube: YouTubeConfig = field(default_factory=YouTubeConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)

    def validate(self) -> None:
        v = self.video
        if not 1 <= v.per_run <= 10:
            raise ValueError("video.per_run must be between 1 and 10")
        if not 20 <= v.target_seconds <= 170:
            raise ValueError("video.target_seconds must be between 20 and 170 (Shorts can't pass 3 minutes)")
        if not 0.7 <= v.voice_speed <= 1.5:
            raise ValueError("video.voice_speed must be between 0.7 and 1.5")
        if not 0 <= v.music_volume <= 1:
            raise ValueError("video.music_volume must be between 0 and 1")
        if self.youtube.privacy not in ("public", "unlisted", "private"):
            raise ValueError('youtube.privacy must be "public", "unlisted" or "private"')
        known = {"gemini", "openai", "ollama"}
        bad = [p for p in self.ai.providers if p not in known]
        if bad or not self.ai.providers:
            raise ValueError(f"ai.providers can only list {', '.join(sorted(known))}")
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", self.schedule.daily_time):
            raise ValueError('schedule.daily_time must look like "17:30"')
        if self.trends.repeat_after_days < 0:
            raise ValueError("trends.repeat_after_days can't be negative")

    @property
    def output_dir(self) -> Path:
        return Path(self.video.output_dir).expanduser()


ENV_OVERRIDES = {
    "TRENDCLIPS_GEMINI_KEY": ("ai", "gemini_api_key"),
    "TRENDCLIPS_PEXELS_KEY": ("footage", "pexels_api_key"),
    "TRENDCLIPS_PIXABAY_KEY": ("footage", "pixabay_api_key"),
    "TRENDCLIPS_TELEGRAM_TOKEN": ("telegram", "bot_token"),
    "TRENDCLIPS_TELEGRAM_CHAT": ("telegram", "chat_id"),
    "TRENDCLIPS_YOUTUBE_KEY": ("youtube", "api_key"),
}


def _merge(obj, data: dict, where: str) -> None:
    known = {f.name for f in fields(obj)}
    for key, value in data.items():
        if key not in known:
            raise ValueError(f"Unknown setting '{where}{key}' in the config file")
        current = getattr(obj, key)
        if is_dataclass(current):
            if not isinstance(value, dict):
                raise ValueError(f"'{where}{key}' must be a [{where}{key}] section")
            _merge(current, value, f"{where}{key}.")
            continue
        if isinstance(current, tuple):
            if not isinstance(value, list):
                raise ValueError(f"'{where}{key}' must be a list, like [\"a\", \"b\"]")
            value = tuple(value)
        elif isinstance(current, bool):
            if not isinstance(value, bool):
                raise ValueError(f"'{where}{key}' must be true or false")
        elif isinstance(current, float) and isinstance(value, int) and not isinstance(value, bool):
            value = float(value)
        elif type(current) is not type(value):
            raise ValueError(f"'{where}{key}' should be a {type(current).__name__}, got {value!r}")
        setattr(obj, key, value)


def load_config(path: str | Path | None = None) -> Config:
    cfg = Config()
    path = Path(path) if path else home_dir() / "config.toml"
    if path.exists():
        with open(path, "rb") as f:
            try:
                data = tomllib.load(f)
            except tomllib.TOMLDecodeError as e:
                raise ValueError(f"{path} has a typo: {e}") from None
        _merge(cfg, data, "")
    for env, (section, key) in ENV_OVERRIDES.items():
        if os.environ.get(env):
            setattr(getattr(cfg, section), key, os.environ[env])
    cfg.validate()
    return cfg


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value)  # JSON string escapes are valid TOML basic strings
    if isinstance(value, (tuple, list)):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    raise TypeError(f"Can't save {value!r} in the config file")


def save_config(cfg: Config, path: str | Path | None = None) -> Path:
    """Writes only the settings that differ from the defaults, so future default improvements still apply."""
    cfg.validate()
    path = Path(path) if path else home_dir() / "config.toml"
    default = Config()
    lines = ["# Trend Clips settings. Anything not listed uses the default in trendclips/config.py;",
             "# config.example.toml in the source folder explains every setting."]
    for section in fields(cfg):
        current, base = getattr(cfg, section.name), getattr(default, section.name)
        changed = [(f.name, getattr(current, f.name)) for f in fields(current)
                   if getattr(current, f.name) != getattr(base, f.name)]
        if changed:
            lines += ["", f"[{section.name}]"] + [f"{name} = {_toml_value(value)}" for name, value in changed]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n")
    os.chmod(tmp, 0o600)  # holds API keys
    os.replace(tmp, path)
    return path

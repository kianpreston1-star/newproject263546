"""YouTube: uploads approved videos (optional, after a one-time sign-in) and reads view counts so the picker learns
which kinds of topics work for your channel. Both use the free YouTube Data API."""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

import requests

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"]
API = "https://www.googleapis.com/youtube/v3"
CATEGORY_IDS = {"tech": "28", "science": "28", "money": "27", "sport": "17", "entertainment": "24",
                "gaming": "20", "news": "25", "lifestyle": "26"}


def secret_path(home: Path) -> Path:
    return Path(home) / "youtube-client-secret.json"


def token_path(home: Path) -> Path:
    return Path(home) / "youtube-token.json"


def login(home: Path) -> str:
    """Opens Google's sign-in page in the browser and saves the permission it grants. Returns the channel name."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    secret = secret_path(home)
    if not secret.exists():
        raise FileNotFoundError(f"Put the OAuth client file you downloaded from Google Cloud at {secret} first "
                                "(the README's YouTube section shows how)")
    flow = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True, prompt="consent",
                                  authorization_prompt_message="Opening Google sign-in in your browser…",
                                  success_message="Done! You can close this tab and go back to the terminal.")
    path = token_path(home)
    path.write_text(creds.to_json())
    os.chmod(path, 0o600)
    channel = _session(home).get(f"{API}/channels", params={"part": "snippet", "mine": "true"}, timeout=30).json()
    items = channel.get("items") or []
    return items[0]["snippet"]["title"] if items else "(no channel found on this Google account)"


def _session(home: Path):
    from google.auth.transport.requests import AuthorizedSession, Request
    from google.oauth2.credentials import Credentials

    path = token_path(home)
    if not path.exists():
        raise RuntimeError("YouTube isn't connected. Run: trendclips youtube-login")
    creds = Credentials.from_authorized_user_file(str(path), SCOPES)
    if not creds.valid:
        try:
            creds.refresh(Request())
        except Exception as e:
            raise RuntimeError("YouTube's sign-in has expired. Run: trendclips youtube-login "
                               "(and see the README about publishing the Google app so it lasts)") from e
        path.write_text(creds.to_json())
        os.chmod(path, 0o600)
    return AuthorizedSession(creds)


def connected(home: Path) -> bool:
    return token_path(home).exists()


def upload_video(home: Path, cfg, video: dict) -> tuple[str, str]:
    """Uploads one approved video. Returns (YouTube video id, a note to show you, or "")."""
    from .pipeline import post_text
    from .writer import Script

    script = Script.from_dict(video["meta"]["script"])
    description = post_text(script) + "\n\n#shorts"
    tags = [h.lstrip("#") for h in script.hashtags]
    body = {
        "snippet": {"title": script.title[:100], "description": description[:4900], "tags": tags,
                    "categoryId": CATEGORY_IDS.get(script.category, "24"),
                    "defaultLanguage": "en", "defaultAudioLanguage": "en"},
        "status": {"privacyStatus": cfg.youtube.privacy, "selfDeclaredMadeForKids": False},
    }
    path = Path(video["path"])
    sess = _session(home)
    headers = {"X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(path.stat().st_size)}
    init = sess.post("https://www.googleapis.com/upload/youtube/v3/videos", headers=headers, json=body, timeout=60,
                     params={"uploadType": "resumable", "part": "snippet,status"})
    _raise(init)
    location = init.headers["Location"]
    for attempt in range(3):
        try:
            with open(path, "rb") as f:
                r = sess.put(location, data=f, headers={"Content-Type": "video/mp4"}, timeout=900)
            if r.status_code < 500:
                break
        except requests.RequestException:
            if attempt == 2:
                raise
        time.sleep(5 * (attempt + 1))
    _raise(r)
    result = r.json()
    note = ""
    if cfg.youtube.privacy == "public" and result.get("status", {}).get("privacyStatus") == "private":
        note = ("YouTube kept it private: Google only lets audited apps publish publicly. Make it public in "
                "YouTube Studio, and see the README's YouTube section about the free audit.")
    return result["id"], note


def _raise(r) -> None:
    if r.status_code < 400:
        return
    try:
        err = r.json().get("error", {})
        reason = (err.get("errors") or [{}])[0].get("reason", "")
        msg = err.get("message", "")
    except ValueError:
        reason, msg = "", r.text[:200]
    if reason == "quotaExceeded":
        raise RuntimeError("YouTube's daily upload allowance is used up; it resets at midnight Pacific time")
    if reason == "uploadLimitExceeded":
        raise RuntimeError("YouTube's upload limit for this channel was reached; try again tomorrow")
    raise RuntimeError(f"YouTube said: {msg or reason or r.status_code}")


def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", t.lower())


def update_stats(cfg, store, home: Path) -> int:
    """Finds your recent uploads (including ones you posted by hand, matched by title) and saves their views."""
    use_oauth = connected(home)
    if not use_oauth and not (cfg.youtube.api_key and cfg.youtube.channel_id):
        return 0
    if use_oauth:
        sess = _session(home)

        def get(path, **params):
            r = sess.get(f"{API}/{path}", params=params, timeout=30)
            _raise(r)
            return r.json()
        channel = get("channels", part="contentDetails", mine="true")
    else:
        def get(path, **params):
            r = requests.get(f"{API}/{path}", params={**params, "key": cfg.youtube.api_key}, timeout=30)
            _raise(r)
            return r.json()
        channel = get("channels", part="contentDetails", id=cfg.youtube.channel_id)
    items = channel.get("items") or []
    if not items:
        return 0
    uploads = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    latest = get("playlistItems", part="snippet", playlistId=uploads, maxResults=50).get("items", [])
    by_title = {_norm_title(i["snippet"]["title"]): i["snippet"]["resourceId"]["videoId"] for i in latest}
    ours = [v for v in store.videos(limit=300) if v["status"] in ("sent", "approved", "posted")]
    for v in ours:
        if not v.get("youtube_id") and _norm_title(v["title"]) in by_title:
            store.update_video(v["id"], youtube_id=by_title[_norm_title(v["title"])], status="posted")
    ids = {v["youtube_id"]: v["id"] for v in store.videos(limit=300) if v.get("youtube_id")}
    updated = 0
    id_list = list(ids)
    for i in range(0, len(id_list), 50):
        stats = get("videos", part="statistics", id=",".join(id_list[i:i + 50]))
        for item in stats.get("items", []):
            s = item.get("statistics", {})
            store.update_video(ids[item["id"]], views=int(s.get("viewCount", 0)), likes=int(s.get("likeCount", 0)),
                               comments=int(s.get("commentCount", 0)), stats_updated=time.time())
            updated += 1
    return updated


def client_secret_ok(path: Path) -> bool:
    try:
        data = json.loads(Path(path).read_text())
        return "installed" in data or "web" in data
    except (OSError, ValueError):
        return False

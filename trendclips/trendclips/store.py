"""A small SQLite database: every video made, which stock clips were used, and a few saved values."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created REAL NOT NULL,
    topic TEXT NOT NULL,
    topic_key TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,            -- made, sent, posted, skipped, failed
    path TEXT NOT NULL DEFAULT '',
    meta TEXT NOT NULL DEFAULT '{}', -- title, description, hashtags, sources, credits (JSON)
    telegram_message_id INTEGER,
    youtube_id TEXT,
    posted REAL,
    views INTEGER,
    likes INTEGER,
    comments INTEGER,
    stats_updated REAL
);
CREATE TABLE IF NOT EXISTS clips (
    source TEXT NOT NULL,
    clip_id TEXT NOT NULL,
    used REAL NOT NULL,
    PRIMARY KEY (source, clip_id)
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # The Telegram listener and a video job can run at the same time; WAL lets them share the file.
        self.db = sqlite3.connect(self.path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # Videos
    def add_video(self, topic: str, topic_key: str, status: str = "made", **fields) -> int:
        meta = json.dumps(fields.pop("meta", {}))
        cur = self.db.execute(
            "INSERT INTO videos (created, topic, topic_key, status, meta, title, category, path) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (time.time(), topic, topic_key, status, meta, fields.get("title", ""), fields.get("category", ""),
             str(fields.get("path", ""))))
        self.db.commit()
        return cur.lastrowid

    def update_video(self, video_id: int, **fields) -> None:
        if "meta" in fields:
            fields["meta"] = json.dumps(fields["meta"])
        if "path" in fields:
            fields["path"] = str(fields["path"])
        cols = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(f"UPDATE videos SET {cols} WHERE id = ?", (*fields.values(), video_id))
        self.db.commit()

    def video(self, video_id: int) -> dict | None:
        row = self.db.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
        return _video(row) if row else None

    def videos(self, status: str | None = None, limit: int = 100) -> list[dict]:
        if status:
            rows = self.db.execute("SELECT * FROM videos WHERE status = ? ORDER BY id DESC LIMIT ?", (status, limit))
        else:
            rows = self.db.execute("SELECT * FROM videos ORDER BY id DESC LIMIT ?", (limit,))
        return [_video(r) for r in rows]

    def recent_topic_keys(self, days: float) -> list[str]:
        """Topics already covered (or deliberately skipped) recently, so the same trend isn't made twice."""
        since = time.time() - days * 86400
        rows = self.db.execute("SELECT topic_key FROM videos WHERE created >= ? AND status != 'failed'", (since,))
        return [r[0] for r in rows]

    def category_performance(self, days: float = 60) -> dict[str, dict]:
        """Average views per category for posted videos that have stats, best first."""
        since = time.time() - days * 86400
        rows = self.db.execute(
            "SELECT category, COUNT(*) n, AVG(views) avg_views FROM videos "
            "WHERE views IS NOT NULL AND created >= ? GROUP BY category ORDER BY avg_views DESC", (since,))
        return {r["category"]: {"videos": r["n"], "avg_views": round(r["avg_views"] or 0)} for r in rows}

    # Stock clips: don't show the same clip in back-to-back videos.
    def mark_clips_used(self, clips: list[tuple[str, str]]) -> None:
        now = time.time()
        self.db.executemany("INSERT OR REPLACE INTO clips (source, clip_id, used) VALUES (?, ?, ?)",
                            [(s, str(c), now) for s, c in clips])
        self.db.commit()

    def recently_used_clips(self, days: float = 21) -> set[tuple[str, str]]:
        since = time.time() - days * 86400
        return {(r[0], r[1]) for r in self.db.execute("SELECT source, clip_id FROM clips WHERE used >= ?", (since,))}

    # Saved values (e.g. the Telegram update offset)
    def get(self, key: str, default: str | None = None) -> str | None:
        row = self.db.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def set(self, key: str, value) -> None:
        self.db.execute("INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)", (key, str(value)))
        self.db.commit()


def _video(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["meta"] = json.loads(d.get("meta") or "{}")
    return d

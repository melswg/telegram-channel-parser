"""SQLite database layer. Upsert-based, idempotent."""

import json
import sqlite3
from datetime import datetime
from typing import Optional

from .models import Channel, Post, Comment, Media, Transcript, now_iso


# ── Schema ────────────────────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS channels (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT NOT NULL,
    telegram_id     INTEGER UNIQUE NOT NULL,
    title           TEXT DEFAULT '',
    access_hash     INTEGER DEFAULT 0,
    last_post_id_seen INTEGER,
    created_at      TEXT DEFAULT '',
    updated_at      TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS posts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id      INTEGER NOT NULL REFERENCES channels(id),
    post_msg_id     INTEGER NOT NULL,
    date            TEXT DEFAULT '',
    text            TEXT DEFAULT '',
    views           INTEGER,
    forwards        INTEGER,
    raw_json        TEXT DEFAULT '',
    UNIQUE(channel_id, post_msg_id)
);

CREATE TABLE IF NOT EXISTS comments (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id          INTEGER NOT NULL,
    post_msg_id         INTEGER NOT NULL,
    comment_msg_id      INTEGER NOT NULL,
    discussion_chat_id  INTEGER,
    sender_id           INTEGER,
    sender_username     TEXT,
    date                TEXT DEFAULT '',
    text                TEXT DEFAULT '',
    reply_to_comment_id INTEGER,
    has_voice           INTEGER DEFAULT 0,
    media_type          TEXT,
    raw_json            TEXT DEFAULT '',
    UNIQUE(channel_id, post_msg_id, comment_msg_id)
);

CREATE TABLE IF NOT EXISTS media (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    comment_id      INTEGER NOT NULL REFERENCES comments(id),
    document_id     INTEGER,
    mime_type       TEXT DEFAULT '',
    local_path      TEXT DEFAULT '',
    size            INTEGER,
    duration        REAL,
    sha256          TEXT DEFAULT '',
    download_status TEXT DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS transcripts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    media_id        INTEGER NOT NULL REFERENCES media(id),
    engine          TEXT DEFAULT 'faster-whisper',
    language        TEXT DEFAULT '',
    text            TEXT DEFAULT '',
    segments_json   TEXT DEFAULT '',
    created_at      TEXT DEFAULT ''
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_posts_channel ON posts(channel_id, post_msg_id);
CREATE INDEX IF NOT EXISTS idx_comments_post ON comments(channel_id, post_msg_id);
CREATE INDEX IF NOT EXISTS idx_media_status ON media(download_status);
CREATE INDEX IF NOT EXISTS idx_transcripts_media ON transcripts(media_id);
"""


# ── Database class ──────────────────────────────────────────────────────────

class Database:
    """Thread-safe SQLite database with idempotent upserts."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None

    def open(self):
        """Open connection and create schema if needed."""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None

    # ── Channel ──────────────────────────────────────────────────────────

    def upsert_channel(self, ch: Channel) -> int:
        now = now_iso()
        self.conn.execute("""
            INSERT INTO channels (username, telegram_id, title, access_hash, last_post_id_seen, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username = excluded.username,
                title = excluded.title,
                access_hash = excluded.access_hash,
                updated_at = excluded.updated_at
        """, (ch.username, ch.telegram_id, ch.title, ch.access_hash,
              ch.last_post_id_seen, now, now))
        self.conn.commit()
        cur = self.conn.execute("SELECT id FROM channels WHERE telegram_id = ?", (ch.telegram_id,))
        return cur.fetchone()[0]

    def get_channel_by_username(self, username: str) -> Optional[Channel]:
        cur = self.conn.execute("SELECT * FROM channels WHERE username = ?", (username,))
        row = cur.fetchone()
        return self._row_to_channel(row) if row else None

    def get_channel_by_id(self, channel_id: int) -> Optional[Channel]:
        cur = self.conn.execute("SELECT * FROM channels WHERE id = ?", (channel_id,))
        row = cur.fetchone()
        return self._row_to_channel(row) if row else None

    def update_channel_last_post(self, channel_id: int, post_msg_id: int):
        self.conn.execute(
            "UPDATE channels SET last_post_id_seen = ?, updated_at = ? WHERE id = ?",
            (post_msg_id, now_iso(), channel_id)
        )
        self.conn.commit()

    # ── Post ──────────────────────────────────────────────────────────────

    def upsert_post(self, post: Post) -> int:
        self.conn.execute("""
            INSERT INTO posts (channel_id, post_msg_id, date, text, views, forwards, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(channel_id, post_msg_id) DO UPDATE SET
                date = excluded.date,
                text = excluded.text,
                views = excluded.views,
                forwards = excluded.forwards,
                raw_json = excluded.raw_json
        """, (post.channel_id, post.post_msg_id, post.date, post.text,
              post.views, post.forwards, post.raw_json))
        self.conn.commit()
        cur = self.conn.execute(
            "SELECT id FROM posts WHERE channel_id = ? AND post_msg_id = ?",
            (post.channel_id, post.post_msg_id)
        )
        row = cur.fetchone()
        return row[0] if row else 0

    def get_post(self, channel_id: int, post_msg_id: int) -> Optional[Post]:
        cur = self.conn.execute(
            "SELECT * FROM posts WHERE channel_id = ? AND post_msg_id = ?",
            (channel_id, post_msg_id)
        )
        row = cur.fetchone()
        return self._row_to_post(row) if row else None

    def get_last_post_id(self, channel_id: int) -> Optional[int]:
        cur = self.conn.execute(
            "SELECT MAX(post_msg_id) FROM posts WHERE channel_id = ?",
            (channel_id,)
        )
        row = cur.fetchone()
        return row[0] if row and row[0] else None

    # ── Comment ──────────────────────────────────────────────────────────

    def upsert_comment(self, cmt: Comment) -> int:
        self.conn.execute("""
            INSERT INTO comments (channel_id, post_msg_id, comment_msg_id, discussion_chat_id,
                sender_id, sender_username, date, text, reply_to_comment_id, has_voice, media_type, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(channel_id, post_msg_id, comment_msg_id) DO UPDATE SET
                date = excluded.date,
                text = excluded.text,
                sender_id = excluded.sender_id,
                sender_username = excluded.sender_username,
                reply_to_comment_id = excluded.reply_to_comment_id,
                has_voice = excluded.has_voice,
                media_type = excluded.media_type,
                raw_json = excluded.raw_json
        """, (cmt.channel_id, cmt.post_msg_id, cmt.comment_msg_id,
              cmt.discussion_chat_id, cmt.sender_id, cmt.sender_username,
              cmt.date, cmt.text, cmt.reply_to_comment_id,
              1 if cmt.has_voice else 0, cmt.media_type, cmt.raw_json))
        self.conn.commit()
        cur = self.conn.execute(
            "SELECT id FROM comments WHERE channel_id = ? AND post_msg_id = ? AND comment_msg_id = ?",
            (cmt.channel_id, cmt.post_msg_id, cmt.comment_msg_id)
        )
        row = cur.fetchone()
        return row[0] if row else 0

    # ── Media ────────────────────────────────────────────────────────────

    def upsert_media(self, m: Media) -> int:
        self.conn.execute("""
            INSERT INTO media (comment_id, document_id, mime_type, local_path, size, duration, sha256, download_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ROWID) DO UPDATE SET
                local_path = excluded.local_path,
                size = excluded.size,
                duration = excluded.duration,
                sha256 = excluded.sha256,
                download_status = excluded.download_status
        """, (m.comment_id, m.document_id, m.mime_type, m.local_path,
              m.size, m.duration, m.sha256, m.download_status))
        self.conn.commit()
        cur = self.conn.execute("SELECT last_insert_rowid()")
        return cur.fetchone()[0]

    def get_pending_media(self) -> list:
        cur = self.conn.execute("""
            SELECT m.* FROM media m
            WHERE m.download_status = 'pending'
            ORDER BY m.id
        """)
        return [self._row_to_media(r) for r in cur.fetchall()]

    def update_media_status(self, media_id: int, status: str):
        self.conn.execute(
            "UPDATE media SET download_status = ? WHERE id = ?",
            (status, media_id)
        )
        self.conn.commit()

    def get_undownloaded_voice_comments(self) -> list:
        """Get comments with has_voice=1 that have no media record yet."""
        cur = self.conn.execute("""
            SELECT c.* FROM comments c
            LEFT JOIN media m ON m.comment_id = c.id
            WHERE c.has_voice = 1 AND m.id IS NULL
            ORDER BY c.id
            LIMIT 500
        """)
        return [self._row_to_comment(r) for r in cur.fetchall()]

    def get_untranscribed_media(self) -> list:
        """Get downloaded media without transcripts."""
        cur = self.conn.execute("""
            SELECT m.* FROM media m
            LEFT JOIN transcripts t ON t.media_id = m.id
            WHERE m.download_status = 'downloaded' AND t.id IS NULL
            ORDER BY m.id
        """)
        return [self._row_to_media(r) for r in cur.fetchall()]

    # ── Transcript ───────────────────────────────────────────────────────

    def insert_transcript(self, t: Transcript) -> int:
        now = now_iso()
        self.conn.execute("""
            INSERT INTO transcripts (media_id, engine, language, text, segments_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (t.media_id, t.engine, t.language, t.text, t.segments_json, now))
        self.conn.commit()
        cur = self.conn.execute("SELECT last_insert_rowid()")
        return cur.fetchone()[0]

    # ── Export helpers ────────────────────────────────────────────────────

    def get_comments_for_export(self, channel_username: Optional[str] = None,
                                since: Optional[str] = None,
                                until: Optional[str] = None) -> list[dict]:
        query = """
            SELECT
                c.id AS comment_id, c.channel_id, c.post_msg_id, c.comment_msg_id,
                c.sender_id, c.sender_username, c.date AS comment_date,
                c.text AS comment_text, c.has_voice, c.media_type,
                ch.username AS channel_username, ch.title AS channel_title,
                p.date AS post_date, p.text AS post_text,
                tr.text AS transcript_text, tr.language AS transcript_language
            FROM comments c
            JOIN channels ch ON ch.id = c.channel_id
            JOIN posts p ON p.channel_id = c.channel_id AND p.post_msg_id = c.post_msg_id
            LEFT JOIN media m ON m.comment_id = c.id
            LEFT JOIN transcripts tr ON tr.media_id = m.id
            WHERE 1=1
        """
        params = []
        if channel_username:
            query += " AND ch.username = ?"
            params.append(channel_username.lstrip("@"))
        if since:
            query += " AND c.date >= ?"
            params.append(since)
        if until:
            query += " AND c.date <= ?"
            params.append(until)
        query += " ORDER BY c.date"

        cur = self.conn.execute(query, params)
        rows = cur.fetchall()
        columns = [desc[0] for desc in cur.description]

        results = []
        for row in rows:
            d = dict(zip(columns, row))
            # Build analysis_text
            parts = []
            if d.get("comment_text"):
                parts.append(d["comment_text"])
            if d.get("transcript_text"):
                parts.append(f"[transcript: {d['transcript_text']}]")
            d["analysis_text"] = " ".join(parts)
            results.append(d)
        return results

    # ── Row-to-model helpers ──────────────────────────────────────────────

    @staticmethod
    def _row_to_channel(row) -> Optional[Channel]:
        if not row:
            return None
        return Channel(
            id=row[0], username=row[1], telegram_id=row[2], title=row[3] or "",
            access_hash=row[4] or 0, last_post_id_seen=row[5],
            created_at=row[6] or "", updated_at=row[7] or ""
        )

    @staticmethod
    def _row_to_post(row) -> Optional[Post]:
        if not row:
            return None
        return Post(
            id=row[0], channel_id=row[1], post_msg_id=row[2], date=row[3] or "",
            text=row[4] or "", views=row[5], forwards=row[6], raw_json=row[7] or ""
        )

    @staticmethod
    def _row_to_comment(row) -> Comment:
        return Comment(
            id=row[0], channel_id=row[1], post_msg_id=row[2], comment_msg_id=row[3],
            discussion_chat_id=row[4], sender_id=row[5], sender_username=row[6],
            date=row[7] or "", text=row[8] or "", reply_to_comment_id=row[9],
            has_voice=bool(row[10]), media_type=row[11], raw_json=row[12] or ""
        )

    @staticmethod
    def _row_to_media(row) -> Media:
        return Media(
            id=row[0], comment_id=row[1], document_id=row[2], mime_type=row[3] or "",
            local_path=row[4] or "", size=row[5], duration=row[6],
            sha256=row[7] or "", download_status=row[8] or "pending"
        )

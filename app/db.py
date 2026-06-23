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

CREATE TABLE IF NOT EXISTS parse_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_url      TEXT NOT NULL,
    target_type     TEXT NOT NULL,
    channel         TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'queued',
    started_at      TEXT DEFAULT '',
    finished_at     TEXT DEFAULT '',
    error           TEXT DEFAULT '',
    save_path       TEXT DEFAULT '',
    posts_count     INTEGER DEFAULT 0,
    comments_count  INTEGER DEFAULT 0,
    processed_posts INTEGER DEFAULT 0,
    total_posts     INTEGER DEFAULT 0,
    download_media  INTEGER DEFAULT 0,
    media_types_json TEXT DEFAULT '[]',
    media_files_count INTEGER DEFAULT 0,
    warnings_json   TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS parsed_posts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    channel         TEXT NOT NULL,
    channel_title   TEXT DEFAULT '',
    post_id         INTEGER NOT NULL,
    publication_number INTEGER,
    date            TEXT DEFAULT '',
    text            TEXT DEFAULT '',
    views           INTEGER,
    forwards        INTEGER,
    has_media       INTEGER DEFAULT 0,
    media_type      TEXT,
    raw_json        TEXT DEFAULT '{}',
    last_run_id     INTEGER REFERENCES parse_runs(id),
    updated_at      TEXT DEFAULT '',
    UNIQUE(channel, post_id)
);

CREATE TABLE IF NOT EXISTS parsed_comments (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    channel             TEXT NOT NULL,
    post_id             INTEGER NOT NULL,
    comment_id          INTEGER NOT NULL,
    date                TEXT DEFAULT '',
    text                TEXT DEFAULT '',
    sender_id           INTEGER,
    sender_username     TEXT,
    sender_name         TEXT DEFAULT '',
    reply_to_comment_id INTEGER,
    has_media           INTEGER DEFAULT 0,
    media_type          TEXT,
    raw_json            TEXT DEFAULT '{}',
    last_run_id         INTEGER REFERENCES parse_runs(id),
    updated_at          TEXT DEFAULT '',
    UNIQUE(channel, post_id, comment_id)
);

CREATE TABLE IF NOT EXISTS parse_run_posts (
    run_id          INTEGER NOT NULL REFERENCES parse_runs(id) ON DELETE CASCADE,
    channel         TEXT NOT NULL,
    post_id         INTEGER NOT NULL,
    error           TEXT DEFAULT '',
    PRIMARY KEY(run_id, channel, post_id)
);

CREATE TABLE IF NOT EXISTS parse_run_queue (
    run_id          INTEGER NOT NULL REFERENCES parse_runs(id) ON DELETE CASCADE,
    position        INTEGER NOT NULL,
    post_id         INTEGER NOT NULL,
    PRIMARY KEY(run_id, position),
    UNIQUE(run_id, post_id)
);

CREATE INDEX IF NOT EXISTS idx_parse_runs_started ON parse_runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_parsed_posts_channel ON parsed_posts(channel, post_id DESC);
CREATE INDEX IF NOT EXISTS idx_parsed_comments_post ON parsed_comments(channel, post_id);
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
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA_SQL)
        self._ensure_column("parse_runs", "download_media", "INTEGER DEFAULT 0")
        self._ensure_column(
            "parse_runs", "media_types_json", "TEXT DEFAULT '[]'"
        )
        self._ensure_column(
            "parse_runs", "media_files_count", "INTEGER DEFAULT 0"
        )
        self._ensure_column(
            "parsed_posts", "publication_number", "INTEGER"
        )
        self.conn.commit()

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        columns = {
            row["name"]
            for row in self.conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            self.conn.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )

    # ── Web parse history ───────────────────────────────────────────────

    def create_parse_run(self, source_url: str, target_type: str, channel: str,
                         total_posts: int = 0,
                         download_media: bool = False,
                         media_types: list[str] | tuple[str, ...] = ()) -> int:
        cur = self.conn.execute("""
            INSERT INTO parse_runs (
                source_url, target_type, channel, status, started_at,
                total_posts, download_media, media_types_json
            ) VALUES (?, ?, ?, 'queued', ?, ?, ?, ?)
        """, (
            source_url, target_type, channel, now_iso(), total_posts,
            int(download_media), json.dumps(list(media_types)),
        ))
        self.conn.commit()
        return int(cur.lastrowid)

    def update_parse_run(self, run_id: int, **values) -> None:
        allowed = {
            "status", "finished_at", "error", "save_path", "posts_count",
            "comments_count", "processed_posts", "total_posts", "warnings_json",
            "media_files_count",
        }
        updates = {key: value for key, value in values.items() if key in allowed}
        if not updates:
            return
        sql = ", ".join(f"{key} = ?" for key in updates)
        self.conn.execute(
            f"UPDATE parse_runs SET {sql} WHERE id = ?",
            [*updates.values(), run_id],
        )
        self.conn.commit()

    def get_parse_run_status(self, run_id: int) -> Optional[str]:
        row = self.conn.execute(
            "SELECT status FROM parse_runs WHERE id = ?", (run_id,)
        ).fetchone()
        return str(row["status"]) if row else None

    def get_parse_run_post_ids(self, run_id: int) -> set[int]:
        return {
            int(row["post_id"])
            for row in self.conn.execute(
                "SELECT post_id FROM parse_run_posts WHERE run_id = ?",
                (run_id,),
            ).fetchall()
        }

    def save_parse_run_queue(self, run_id: int, post_ids: list[int]) -> None:
        self.conn.execute(
            "DELETE FROM parse_run_queue WHERE run_id = ?", (run_id,)
        )
        self.conn.executemany(
            """
            INSERT INTO parse_run_queue (run_id, position, post_id)
            VALUES (?, ?, ?)
            """,
            [
                (run_id, position, int(post_id))
                for position, post_id in enumerate(post_ids, start=1)
            ],
        )
        self.conn.commit()

    def get_parse_run_queue(self, run_id: int) -> list[int]:
        return [
            int(row["post_id"])
            for row in self.conn.execute(
                """
                SELECT post_id FROM parse_run_queue
                WHERE run_id = ?
                ORDER BY position
                """,
                (run_id,),
            ).fetchall()
        ]

    def pause_interrupted_runs(self) -> int:
        cursor = self.conn.execute("""
            UPDATE parse_runs
            SET status = 'paused',
                error = 'Приложение было остановлено. Продолжите парсинг с сохранённого места.'
            WHERE status IN ('queued', 'running')
        """)
        self.conn.commit()
        return int(cursor.rowcount)

    def get_parse_run(self, run_id: int) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM parse_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["warnings"] = json.loads(result.pop("warnings_json") or "[]")
        result["media_types"] = json.loads(
            result.pop("media_types_json", "[]") or "[]"
        )
        result["posts"] = []
        for item in self.conn.execute("""
                SELECT rp.channel, rp.post_id, rp.error, p.date, p.text,
                       p.channel_title, p.publication_number,
                       p.has_media, p.media_type, p.raw_json,
                       (SELECT COUNT(*) FROM parsed_comments c
                        WHERE c.channel = rp.channel AND c.post_id = rp.post_id) AS comments_count
                FROM parse_run_posts rp
                LEFT JOIN parsed_posts p
                  ON p.channel = rp.channel AND p.post_id = rp.post_id
                WHERE rp.run_id = ?
                ORDER BY rp.post_id DESC
            """, (run_id,)).fetchall():
            post = dict(item)
            try:
                raw_post = json.loads(post.pop("raw_json") or "{}")
            except (TypeError, ValueError):
                raw_post = {}
            post["media"] = raw_post.get("media")
            result["posts"].append(post)
        result["observed_processed_posts"] = len(result["posts"])
        return result

    def list_parse_runs(self, limit: int = 30) -> list[dict]:
        rows = self.conn.execute("""
            SELECT * FROM parse_runs ORDER BY id DESC LIMIT ?
        """, (limit,)).fetchall()
        results = []
        for row in rows:
            result = dict(row)
            result["media_types"] = json.loads(
                result.pop("media_types_json", "[]") or "[]"
            )
            results.append(result)
        return results

    def upsert_parsed_post(self, data: dict, run_id: int) -> None:
        self.conn.execute("""
            INSERT INTO parsed_posts (
                channel, channel_title, post_id, publication_number, date,
                text, views, forwards, has_media, media_type, raw_json,
                last_run_id, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(channel, post_id) DO UPDATE SET
                channel_title = excluded.channel_title,
                publication_number = excluded.publication_number,
                date = excluded.date,
                text = excluded.text,
                views = excluded.views,
                forwards = excluded.forwards,
                has_media = excluded.has_media,
                media_type = excluded.media_type,
                raw_json = excluded.raw_json,
                last_run_id = excluded.last_run_id,
                updated_at = excluded.updated_at
        """, (
            data["channel"], data.get("channel_title", ""), data["post_id"],
            data.get("publication_number"), data.get("date", ""),
            data.get("text", ""), data.get("views"), data.get("forwards"),
            int(bool(data.get("has_media"))), data.get("media_type"),
            json.dumps(data, ensure_ascii=False, default=str), run_id, now_iso(),
        ))
        self.conn.execute("""
            INSERT INTO parse_run_posts (run_id, channel, post_id, error)
            VALUES (?, ?, ?, '')
            ON CONFLICT(run_id, channel, post_id) DO UPDATE SET error = ''
        """, (run_id, data["channel"], data["post_id"]))
        self.conn.commit()

    def replace_parsed_comments(self, channel: str, post_id: int,
                                comments: list[dict], run_id: int) -> None:
        self.conn.execute(
            "DELETE FROM parsed_comments WHERE channel = ? AND post_id = ?",
            (channel, post_id),
        )
        for data in comments:
            self.conn.execute("""
                INSERT INTO parsed_comments (
                    channel, post_id, comment_id, date, text, sender_id,
                    sender_username, sender_name, reply_to_comment_id,
                    has_media, media_type, raw_json, last_run_id, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                channel, post_id, data["id"], data.get("date", ""),
                data.get("text", ""), data.get("sender_id"),
                data.get("sender_username"), data.get("sender_name", ""),
                data.get("reply_to"), int(bool(data.get("has_media"))),
                data.get("media_type"),
                json.dumps(data, ensure_ascii=False, default=str),
                run_id, now_iso(),
            ))
        self.conn.commit()

    def add_run_post_error(self, run_id: int, channel: str,
                           post_id: int, error: str) -> None:
        self.conn.execute("""
            INSERT INTO parse_run_posts (run_id, channel, post_id, error)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(run_id, channel, post_id) DO UPDATE SET error = excluded.error
        """, (run_id, channel, post_id, error))
        self.conn.commit()

    def get_parsed_post(self, channel: str, post_id: int) -> Optional[dict]:
        row = self.conn.execute("""
            SELECT *, (
                SELECT COUNT(*) FROM parsed_comments c
                WHERE c.channel = parsed_posts.channel
                  AND c.post_id = parsed_posts.post_id
            ) AS comments_count
            FROM parsed_posts WHERE channel = ? AND post_id = ?
        """, (channel, post_id)).fetchone()
        if not row:
            return None
        result = dict(row)
        try:
            raw_post = json.loads(result.get("raw_json") or "{}")
        except (TypeError, ValueError):
            raw_post = {}
        for key in (
            "media",
            "media_directory",
            "media_download_requested",
            "media_download_all",
            "media_download_types",
            "url",
        ):
            if key in raw_post:
                result[key] = raw_post[key]
        result["comments"] = [
            dict(item) for item in self.conn.execute("""
                SELECT * FROM parsed_comments
                WHERE channel = ? AND post_id = ?
                ORDER BY date, comment_id
            """, (channel, post_id)).fetchall()
        ]
        for comment in result["comments"]:
            try:
                raw_comment = json.loads(comment.get("raw_json") or "{}")
            except (TypeError, ValueError):
                raw_comment = {}
            if "media" in raw_comment:
                comment["media"] = raw_comment["media"]
        return result

    def list_parsed_posts(self, channel: Optional[str] = None,
                          limit: int = 100) -> list[dict]:
        params: list = []
        where = ""
        if channel:
            where = "WHERE p.channel = ?"
            params.append(channel)
        params.append(limit)
        rows = self.conn.execute(f"""
            SELECT p.*, COUNT(c.id) AS comments_count
            FROM parsed_posts p
            LEFT JOIN parsed_comments c
              ON c.channel = p.channel AND c.post_id = p.post_id
            {where}
            GROUP BY p.id
            ORDER BY p.updated_at DESC
            LIMIT ?
        """, params).fetchall()
        results = []
        for row in rows:
            post = dict(row)
            try:
                raw_post = json.loads(post.get("raw_json") or "{}")
            except (TypeError, ValueError):
                raw_post = {}
            post["media"] = raw_post.get("media")
            results.append(post)
        return results

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

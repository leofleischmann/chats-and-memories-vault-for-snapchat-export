from __future__ import annotations

import sqlite3
from typing import Iterable, Optional

from .importer import Message, Snap


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS chats (
  chat_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  text_message_count INTEGER NOT NULL DEFAULT 0,
  message_count INTEGER NOT NULL DEFAULT 0,
  first_ts TEXT,
  last_ts TEXT
);

CREATE TABLE IF NOT EXISTS messages (
  message_id TEXT PRIMARY KEY,
  chat_id TEXT NOT NULL,
  ts_utc TEXT,
  sender TEXT,
  is_sender INTEGER NOT NULL DEFAULT 0,
  type TEXT NOT NULL,
  text TEXT NOT NULL,
  ordinal_in_chat INTEGER NOT NULL,
  is_saved INTEGER NOT NULL DEFAULT 0,
  media_id TEXT,
  media_filename TEXT,
  FOREIGN KEY(chat_id) REFERENCES chats(chat_id)
);

CREATE INDEX IF NOT EXISTS idx_messages_chat_ordinal ON messages(chat_id, ordinal_in_chat);

CREATE TABLE IF NOT EXISTS snaps (
  snap_id TEXT PRIMARY KEY,
  thread_id TEXT NOT NULL,
  thread_title TEXT,
  sender TEXT,
  is_sender INTEGER NOT NULL DEFAULT 0,
  type TEXT NOT NULL,
  ts_utc TEXT
);

CREATE INDEX IF NOT EXISTS idx_snaps_thread_ts ON snaps(thread_id, ts_utc);

CREATE TABLE IF NOT EXISTS media_files (
  filename TEXT PRIMARY KEY,
  file_date TEXT,
  extension TEXT NOT NULL,
  media_type TEXT NOT NULL,
  media_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_media_files_date ON media_files(file_date);
CREATE INDEX IF NOT EXISTS idx_media_files_media_id ON media_files(media_id);
CREATE INDEX IF NOT EXISTS idx_media_files_type_date ON media_files(media_type, file_date);

CREATE TABLE IF NOT EXISTS message_media_ids (
  media_id TEXT NOT NULL,
  message_id TEXT NOT NULL,
  chat_id TEXT NOT NULL,
  PRIMARY KEY(media_id, message_id)
);

CREATE INDEX IF NOT EXISTS idx_mmi_media_id ON message_media_ids(media_id);
CREATE INDEX IF NOT EXISTS idx_mmi_chat_id ON message_media_ids(chat_id);
CREATE INDEX IF NOT EXISTS idx_messages_ts ON messages(ts_utc);

-- ---------------------------------------------------------------------------
-- Insights (Snapshot from various snapchat export JSON files)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS insights_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS insights_engagement (
  event TEXT PRIMARY KEY,
  occurrences INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS insights_time_spent (
  area TEXT PRIMARY KEY,
  percent REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS insights_interest (
  category TEXT NOT NULL,
  kind TEXT NOT NULL,
  PRIMARY KEY(category, kind)
);

CREATE TABLE IF NOT EXISTS insights_web_interactions (
  domain TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS insights_ranking (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS insights_device_history (
  start_ts TEXT,
  make TEXT,
  model TEXT,
  device_type TEXT
);

CREATE TABLE IF NOT EXISTS insights_login_history (
  created_ts TEXT,
  ip TEXT,
  country TEXT,
  status TEXT,
  device TEXT
);

CREATE TABLE IF NOT EXISTS insights_account_history (
  section TEXT NOT NULL,
  created_ts TEXT,
  value TEXT NOT NULL
);

-- Immich upload cache lives in a separate DB (immich_upload_cache.sqlite)
-- so it survives reset-app and unpack+import.
"""


MSG_COLUMNS = "message_id, chat_id, ts_utc, sender, is_sender, type, text, ordinal_in_chat, is_saved, media_id, media_filename"


class Storage:
    def __init__(self, sqlite_path: str):
        self.sqlite_path = sqlite_path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.sqlite_path,
            timeout=30,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)

    # ------------------------------------------------------------------
    # Chats
    # ------------------------------------------------------------------

    def upsert_chat(
        self,
        chat_id: str,
        title: str,
        text_message_count: int,
        message_count: int,
        first_ts: Optional[str],
        last_ts: Optional[str],
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO chats(chat_id, title, text_message_count, message_count, first_ts, last_ts)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                  title=excluded.title,
                  text_message_count=excluded.text_message_count,
                  message_count=excluded.message_count,
                  first_ts=excluded.first_ts,
                  last_ts=excluded.last_ts
                """,
                (chat_id, title, text_message_count, message_count, first_ts, last_ts),
            )

    def list_chats(self) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT chat_id, title, text_message_count, message_count, first_ts, last_ts FROM chats ORDER BY text_message_count DESC, message_count DESC, title ASC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_chat(self, chat_id: str) -> Optional[dict]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT chat_id, title, text_message_count, message_count, first_ts, last_ts FROM chats WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_media(raw_media_id: str | None, lookup: dict[str, str]) -> tuple[str | None, str | None]:
        """Split pipe-separated Media IDs and return (first_matched_id, filename)."""
        if not raw_media_id:
            return None, None
        for part in raw_media_id.split(" | "):
            part = part.strip()
            if part and part in lookup:
                return part, lookup[part]
        return raw_media_id.split(" | ")[0].strip() or None, None

    def insert_messages(self, messages: Iterable[Message], media_lookup: dict[str, str] | None = None) -> None:
        if media_lookup is None:
            media_lookup = {}

        msg_rows = []
        mmi_rows = []
        for m in messages:
            mid, mfn = self._resolve_media(m.media_id, media_lookup)
            msg_rows.append((
                m.message_id, m.chat_id, m.ts_utc, m.sender,
                1 if m.is_sender else 0, m.type, m.text,
                m.ordinal_in_chat, 1 if m.is_saved else 0,
                mid, mfn,
            ))
            if m.media_id:
                for part in m.media_id.split(" | "):
                    part = part.strip()
                    if part:
                        mmi_rows.append((part, m.message_id, m.chat_id))

        with self.connect() as conn:
            conn.executemany(
                f"""
                INSERT OR REPLACE INTO messages({MSG_COLUMNS})
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                msg_rows,
            )
            if mmi_rows:
                conn.executemany(
                    "INSERT OR IGNORE INTO message_media_ids(media_id, message_id, chat_id) VALUES (?, ?, ?)",
                    mmi_rows,
                )

    def get_messages(self, chat_id: str, offset: int, limit: int) -> list[dict]:
        """Return messages ordered oldest-first (ASC). offset=0 means newest page."""
        with self.connect() as conn:
            total_row = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE chat_id = ?", (chat_id,)
            ).fetchone()
            total = total_row[0] if total_row else 0
            asc_offset = max(0, total - offset - limit)
            actual_limit = min(limit, total - offset)
            if actual_limit <= 0:
                return []
            rows = conn.execute(
                f"SELECT {MSG_COLUMNS} FROM messages WHERE chat_id = ? ORDER BY ordinal_in_chat ASC LIMIT ? OFFSET ?",
                (chat_id, actual_limit, asc_offset),
            ).fetchall()
        return [dict(r) for r in rows]


    # ------------------------------------------------------------------
    # Snaps
    # ------------------------------------------------------------------

    def insert_snaps(self, snaps: Iterable[Snap]) -> None:
        with self.connect() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO snaps(snap_id, thread_id, thread_title, sender, is_sender, type, ts_utc) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    (s.snap_id, s.thread_id, s.thread_title, s.sender, 1 if s.is_sender else 0, s.type, s.ts_utc)
                    for s in snaps
                ),
            )

    def list_snap_threads(self) -> list[dict]:
        with self.connect() as conn:
            try:
                # Pro thread_id eine Zeile; Titel = erster nicht-leerer Titel, sonst thread_id
                rows = conn.execute(
                    """
                    SELECT thread_id,
                           COALESCE(NULLIF(trim(MAX(CASE WHEN trim(COALESCE(thread_title, '')) <> '' THEN thread_title END)), ''), thread_id) AS thread_title,
                           COUNT(*) AS snap_count
                    FROM snaps
                    GROUP BY thread_id
                    ORDER BY snap_count DESC, thread_title
                    """
                ).fetchall()
            except sqlite3.OperationalError:
                return []
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Media files
    # ------------------------------------------------------------------

    def insert_media_files(self, files: list[dict]) -> None:
        with self.connect() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO media_files(filename, file_date, extension, media_type, media_id) VALUES (?, ?, ?, ?, ?)",
                ((f["filename"], f["file_date"], f["extension"], f["media_type"], f.get("media_id")) for f in files),
            )

    def list_media_files(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        media_type: str | None = None,
        chat_id: str | None = None,
        assigned_only: bool = True,
        unassigned_only: bool = False,
        include_audio: bool = True,
        offset: int = 0,
        limit: int = 60,
    ) -> dict:
        where_parts: list[str] = []
        params: list = []
        if date_from:
            where_parts.append("mf.file_date >= ?")
            params.append(date_from)
        if date_to:
            where_parts.append("mf.file_date <= ?")
            params.append(date_to)
        if media_type:
            if media_type == "audio":
                where_parts.append("(mf.media_type = 'audio' OR link.msg_type = 'NOTE')")
            elif media_type == "video":
                where_parts.append("(mf.media_type = 'video' AND (link.msg_type IS NULL OR link.msg_type != 'NOTE'))")
            else:
                where_parts.append("mf.media_type = ?")
                params.append(media_type)
        if not include_audio:
            where_parts.append("(mf.media_type != 'audio' AND (link.msg_type IS NULL OR link.msg_type != 'NOTE'))")
        if chat_id:
            where_parts.append("link.chat_id = ?")
            params.append(chat_id)
        if unassigned_only:
            where_parts.append("link.chat_id IS NULL")
        elif assigned_only:
            where_parts.append("link.chat_id IS NOT NULL")

        link_join = """LEFT JOIN (
            SELECT mmi.media_id AS link_media_id, mmi.chat_id, mmi.message_id,
                   m.sender, m.ts_utc, m.type AS msg_type,
                   ROW_NUMBER() OVER (PARTITION BY mmi.media_id ORDER BY m.ts_utc DESC) AS rn
            FROM message_media_ids mmi
            JOIN messages m ON m.message_id = mmi.message_id
        ) link ON link.link_media_id = mf.media_id AND link.rn = 1"""

        where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
        with self.connect() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) FROM media_files mf {link_join} {where_sql}",
                params,
            ).fetchone()
            total = row[0] if row else 0
            rows = conn.execute(
                f"""SELECT mf.filename, mf.file_date, mf.extension, mf.media_type,
                           link.chat_id, c.title AS chat_title, link.message_id, link.sender, link.ts_utc,
                           link.msg_type
                    FROM media_files mf
                    {link_join}
                    LEFT JOIN chats c ON c.chat_id = link.chat_id
                    {where_sql}
                    ORDER BY COALESCE(link.ts_utc, mf.file_date) DESC, mf.filename
                    LIMIT ? OFFSET ?""",
                params + [limit, offset],
            ).fetchall()
        return {"total": total, "files": [dict(r) for r in rows]}

    def list_chats_with_media(self) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT mmi.chat_id, c.title, COUNT(DISTINCT mf.filename) AS media_count
                   FROM message_media_ids mmi
                   JOIN media_files mf ON mf.media_id = mmi.media_id
                   JOIN chats c ON c.chat_id = mmi.chat_id
                   GROUP BY mmi.chat_id, c.title
                   ORDER BY media_count DESC"""
            ).fetchall()
        return [dict(r) for r in rows]

    def get_media_by_date(self, date: str) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT filename, file_date, extension, media_type FROM media_files WHERE file_date = ? ORDER BY filename",
                (date,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_stats(
        self,
        chat_id: Optional[str] = None,
        thread_id: Optional[str] = None,
        from_ts: Optional[str] = None,
        to_ts: Optional[str] = None,
        group_by: str = "day",
    ) -> dict:
        with self.connect() as conn:
            where_parts: list[str] = ["ts_utc IS NOT NULL AND ts_utc != ''"]
            params: list = []
            if chat_id:
                where_parts.append("chat_id = ?")
                params.append(chat_id)
            if from_ts:
                where_parts.append("ts_utc >= ?")
                params.append(from_ts)
            if to_ts:
                where_parts.append("ts_utc <= ?")
                params.append(to_ts)
            where_sql = " AND ".join(where_parts)

            if group_by == "month":
                date_expr = "substr(ts_utc, 1, 7)"
            else:
                date_expr = "substr(ts_utc, 1, 10)"

            rows = conn.execute(f"SELECT {date_expr} AS period, COUNT(*) AS count FROM messages WHERE {where_sql} GROUP BY period ORDER BY period", params).fetchall()
            messages_over_time = [{"period": r[0], "count": r[1]} for r in rows]

            rows = conn.execute(f"SELECT {date_expr} AS period, COUNT(*) AS count FROM messages WHERE {where_sql} AND type != 'TEXT' GROUP BY period ORDER BY period", list(params)).fetchall()
            chat_media_over_time = [{"period": r[0], "count": r[1]} for r in rows]

            rows = conn.execute(f"SELECT type, COUNT(*) AS count FROM messages WHERE {where_sql} GROUP BY type ORDER BY count DESC", params).fetchall()
            by_type = [{"type": r[0], "count": r[1]} for r in rows]

            rows = conn.execute(f"SELECT COALESCE(sender, '(unbekannt)') AS sender, COUNT(*) AS count FROM messages WHERE {where_sql} GROUP BY sender ORDER BY count DESC LIMIT 30", params).fetchall()
            by_sender = [{"sender": r[0], "count": r[1]} for r in rows]

            row = conn.execute(f"SELECT COUNT(*) FROM messages WHERE {where_sql}", params).fetchone()
            total_messages = row[0] if row else 0
            row = conn.execute(f"SELECT COUNT(*) FROM messages WHERE {where_sql} AND type != 'TEXT'", params).fetchone()
            total_chat_media = row[0] if row else 0

            rows = conn.execute(f"SELECT CAST(strftime('%H', ts_utc) AS INTEGER) AS hour, COUNT(*) AS count FROM messages WHERE {where_sql} GROUP BY hour ORDER BY hour", params).fetchall()
            by_hour = [{"hour": r[0], "count": r[1]} for r in rows]

            rows = conn.execute(f"SELECT CAST(strftime('%w', ts_utc) AS INTEGER) AS weekday, COUNT(*) AS count FROM messages WHERE {where_sql} GROUP BY weekday ORDER BY weekday", params).fetchall()
            by_weekday = [{"weekday": r[0], "count": r[1]} for r in rows]

            rows = conn.execute(f"SELECT substr(ts_utc, 1, 10) AS day, COUNT(*) AS count FROM messages WHERE {where_sql} GROUP BY day ORDER BY count DESC LIMIT 20", params).fetchall()
            top_days = [{"day": r[0], "count": r[1]} for r in rows]

            row = conn.execute(f"SELECT AVG(LENGTH(COALESCE(text, ''))) FROM messages WHERE {where_sql} AND type = 'TEXT' AND (text IS NOT NULL AND text != '')", params).fetchone()
            avg_message_length = round(row[0], 1) if row and row[0] is not None else None

            snap_where: list[str] = ["ts_utc IS NOT NULL AND ts_utc != ''"]
            snap_params: list = []
            if thread_id:
                snap_where.append("thread_id = ?")
                snap_params.append(thread_id)
            if from_ts:
                snap_where.append("ts_utc >= ?")
                snap_params.append(from_ts)
            if to_ts:
                snap_where.append("ts_utc <= ?")
                snap_params.append(to_ts)
            snap_where_sql = " AND ".join(snap_where)
            try:
                rows = conn.execute(f"SELECT {date_expr} AS period, COUNT(*) AS count FROM snaps WHERE {snap_where_sql} GROUP BY period ORDER BY period", snap_params).fetchall()
                snaps_over_time = [{"period": r[0], "count": r[1]} for r in rows]
                row = conn.execute(f"SELECT COUNT(*) FROM snaps WHERE {snap_where_sql}", snap_params).fetchone()
                total_snaps = row[0] if row else 0
            except sqlite3.OperationalError:
                snaps_over_time = []
                total_snaps = 0

        return {
            "messages_over_time": messages_over_time,
            "chat_media_over_time": chat_media_over_time,
            "snaps_over_time": snaps_over_time,
            "by_type": by_type,
            "by_sender": by_sender,
            "total_messages": total_messages,
            "total_chat_media": total_chat_media,
            "total_snaps": total_snaps,
            "by_hour": by_hour,
            "by_weekday": by_weekday,
            "top_days": top_days,
            "avg_message_length": avg_message_length,
        }

    # ------------------------------------------------------------------
    # Insights
    # ------------------------------------------------------------------

    def replace_insights_snapshot(self, snapshot: dict) -> None:
        """Replace the whole insights snapshot in one transaction."""
        meta: dict[str, str] = snapshot.get("meta", {}) or {}
        engagement: list[dict] = snapshot.get("engagement", []) or []
        time_spent: list[dict] = snapshot.get("time_spent", []) or []
        interests: list[dict] = snapshot.get("interests", []) or []
        web_interactions: list[str] = snapshot.get("web_interactions", []) or []
        ranking: dict[str, str] = snapshot.get("ranking", {}) or {}
        device_history: list[dict] = snapshot.get("device_history", []) or []
        login_history: list[dict] = snapshot.get("login_history", []) or []
        account_history: list[dict] = snapshot.get("account_history", []) or []

        with self.connect() as conn:
            conn.execute("BEGIN")
            for tbl in (
                "insights_meta",
                "insights_engagement",
                "insights_time_spent",
                "insights_interest",
                "insights_web_interactions",
                "insights_ranking",
                "insights_device_history",
                "insights_login_history",
                "insights_account_history",
            ):
                conn.execute(f"DELETE FROM {tbl}")

            if meta:
                conn.executemany(
                    "INSERT INTO insights_meta(key, value) VALUES (?, ?)",
                    list(meta.items()),
                )
            if engagement:
                conn.executemany(
                    "INSERT INTO insights_engagement(event, occurrences) VALUES (?, ?)",
                    [(e.get("event"), int(e.get("occurrences") or 0)) for e in engagement if e.get("event")],
                )
            if time_spent:
                conn.executemany(
                    "INSERT INTO insights_time_spent(area, percent) VALUES (?, ?)",
                    [
                        (t.get("area"), float(t.get("percent")))
                        for t in time_spent
                        if t.get("area") and t.get("percent") is not None
                    ],
                )
            if interests:
                conn.executemany(
                    "INSERT OR IGNORE INTO insights_interest(category, kind) VALUES (?, ?)",
                    [(i.get("category"), i.get("kind")) for i in interests if i.get("category") and i.get("kind")],
                )
            if web_interactions:
                conn.executemany(
                    "INSERT OR IGNORE INTO insights_web_interactions(domain) VALUES (?)",
                    [(d,) for d in web_interactions if d],
                )
            if ranking:
                conn.executemany(
                    "INSERT INTO insights_ranking(key, value) VALUES (?, ?)",
                    list(ranking.items()),
                )
            if device_history:
                conn.executemany(
                    "INSERT INTO insights_device_history(start_ts, make, model, device_type) VALUES (?, ?, ?, ?)",
                    [
                        (d.get("start_ts"), d.get("make"), d.get("model"), d.get("device_type"))
                        for d in device_history
                    ],
                )
            if login_history:
                conn.executemany(
                    "INSERT INTO insights_login_history(created_ts, ip, country, status, device) VALUES (?, ?, ?, ?, ?)",
                    [
                        (l.get("created_ts"), l.get("ip"), l.get("country"), l.get("status"), l.get("device"))
                        for l in login_history
                    ],
                )
            if account_history:
                conn.executemany(
                    "INSERT INTO insights_account_history(section, created_ts, value) VALUES (?, ?, ?)",
                    [
                        (a.get("section"), a.get("created_ts"), a.get("value"))
                        for a in account_history
                        if a.get("section") and a.get("value") is not None
                    ],
                )
            conn.commit()

    def get_insights(self) -> dict:
        with self.connect() as conn:
            meta_rows = conn.execute("SELECT key, value FROM insights_meta ORDER BY key").fetchall()
            meta = {r["key"]: r["value"] for r in meta_rows}

            engagement_rows = conn.execute(
                "SELECT event, occurrences FROM insights_engagement ORDER BY occurrences DESC, event ASC"
            ).fetchall()
            engagement = [dict(r) for r in engagement_rows]

            time_rows = conn.execute(
                "SELECT area, percent FROM insights_time_spent ORDER BY percent DESC, area ASC"
            ).fetchall()
            time_spent = [dict(r) for r in time_rows]

            interest_rows = conn.execute(
                "SELECT category, kind FROM insights_interest ORDER BY kind ASC, category ASC"
            ).fetchall()
            interests = [dict(r) for r in interest_rows]

            web_rows = conn.execute(
                "SELECT domain FROM insights_web_interactions ORDER BY domain ASC"
            ).fetchall()
            web_interactions = [r["domain"] for r in web_rows]

            ranking_rows = conn.execute("SELECT key, value FROM insights_ranking ORDER BY key ASC").fetchall()
            ranking = {r["key"]: r["value"] for r in ranking_rows}

            device_rows = conn.execute(
                "SELECT start_ts, make, model, device_type FROM insights_device_history ORDER BY start_ts DESC"
            ).fetchall()
            device_history = [dict(r) for r in device_rows]

            login_rows = conn.execute(
                "SELECT created_ts, ip, country, status, device FROM insights_login_history ORDER BY created_ts DESC"
            ).fetchall()
            login_history = [dict(r) for r in login_rows]

            account_rows = conn.execute(
                "SELECT section, created_ts, value FROM insights_account_history ORDER BY section ASC, created_ts DESC"
            ).fetchall()
            account_history = [dict(r) for r in account_rows]

        return {
            "meta": meta,
            "engagement": engagement,
            "time_spent": time_spent,
            "interests": interests,
            "web_interactions": web_interactions,
            "ranking": ranking,
            "device_history": device_history,
            "login_history": login_history,
            "account_history": account_history,
        }

"""Immich upload cache (SQLite) for skip-on-reupload."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone

IMMICH_CACHE_META_KEY_API_KEY_SHA1 = "immich_api_key_sha1"


def _ensure_cache_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS immich_upload_cache_meta (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS immich_upload_cache (
          scope TEXT NOT NULL,
          rel_path TEXT NOT NULL,
          size_bytes INTEGER NOT NULL,
          mtime_ns INTEGER NOT NULL,
          sha256 TEXT,
          status TEXT,
          immich_asset_id TEXT,
          created_at TEXT NOT NULL,
          PRIMARY KEY(scope, rel_path, size_bytes, mtime_ns)
        );
        CREATE INDEX IF NOT EXISTS idx_immich_upload_cache_sha ON immich_upload_cache(scope, sha256, size_bytes);
        """
    )


def _get_cache_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM immich_upload_cache_meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def _set_cache_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO immich_upload_cache_meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def _invalidate_cache_if_needed(conn: sqlite3.Connection, *, api_key: str) -> None:
    api_key_sha1 = hashlib.sha1(api_key.encode("utf-8")).hexdigest()
    old = _get_cache_meta(conn, IMMICH_CACHE_META_KEY_API_KEY_SHA1)
    if old and old == api_key_sha1:
        return
    conn.execute("DELETE FROM immich_upload_cache")
    _set_cache_meta(conn, IMMICH_CACHE_META_KEY_API_KEY_SHA1, api_key_sha1)


def _cache_hit(conn: sqlite3.Connection, *, scope: str, rel_path: str, size_bytes: int, mtime_ns: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM immich_upload_cache WHERE scope=? AND rel_path=? AND size_bytes=? AND mtime_ns=? LIMIT 1",
        (scope, rel_path, size_bytes, mtime_ns),
    ).fetchone()
    return bool(row)


def _cache_get_asset_id(conn: sqlite3.Connection, *, scope: str, rel_path: str, size_bytes: int, mtime_ns: int) -> str | None:
    row = conn.execute(
        "SELECT immich_asset_id FROM immich_upload_cache WHERE scope=? AND rel_path=? AND size_bytes=? AND mtime_ns=? LIMIT 1",
        (scope, rel_path, size_bytes, mtime_ns),
    ).fetchone()
    if not row:
        return None
    v = row[0]
    return str(v) if v else None


def _cache_get_sha256(conn: sqlite3.Connection, *, scope: str, rel_path: str, size_bytes: int, mtime_ns: int) -> str | None:
    """Return cached sha256 for the given fingerprint key without re-hashing.

    Note: If sha256 is stored as NULL/empty in the cache, returns None.
    """
    row = conn.execute(
        "SELECT sha256 FROM immich_upload_cache WHERE scope=? AND rel_path=? AND size_bytes=? AND mtime_ns=? LIMIT 1",
        (scope, rel_path, size_bytes, mtime_ns),
    ).fetchone()
    if not row:
        return None
    v = row[0]
    return str(v) if v else None


def _cache_hit_by_sha(conn: sqlite3.Connection, *, scope: str, sha256: str, size_bytes: int) -> bool:
    if not sha256:
        return False
    row = conn.execute(
        "SELECT 1 FROM immich_upload_cache WHERE scope=? AND sha256=? AND size_bytes=? LIMIT 1",
        (scope, sha256, size_bytes),
    ).fetchone()
    return bool(row)


def _cache_get_asset_id_by_sha(conn: sqlite3.Connection, *, scope: str, sha256: str, size_bytes: int) -> str | None:
    if not sha256:
        return None
    row = conn.execute(
        "SELECT immich_asset_id FROM immich_upload_cache WHERE scope=? AND sha256=? AND size_bytes=? LIMIT 1",
        (scope, sha256, size_bytes),
    ).fetchone()
    if not row:
        return None
    v = row[0]
    return str(v) if v else None


def _cache_put(
    conn: sqlite3.Connection,
    *,
    scope: str,
    rel_path: str,
    size_bytes: int,
    mtime_ns: int,
    sha256: str | None,
    status: str,
    immich_asset_id: str | None,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO immich_upload_cache(scope, rel_path, size_bytes, mtime_ns, sha256, status, immich_asset_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            scope,
            rel_path,
            size_bytes,
            mtime_ns,
            sha256,
            status,
            immich_asset_id,
            datetime.now(timezone.utc).isoformat(),
        ),
    )

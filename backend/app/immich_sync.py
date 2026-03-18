"""Sync chat media and memories to Immich via its API."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

MEMORY_MAIN_RE = re.compile(r"-main\.\w+$")
MEMORY_OVERLAY_RE = re.compile(r"-overlay\.\w+$", re.IGNORECASE)
DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")
DEVICE_ID = "snapchat-export"
TIMEOUT = httpx.Timeout(60.0, connect=15.0)

ADMIN_EMAIL = "admin@snapchats.local"
ADMIN_PASSWORD = "snapchats-admin-2026"
CONFIG_FILENAME = "immich_config.json"
COMBINED_MEMORIES_DIRNAME = "immich_combined_memories"
CONFIG_KEY_COMBINE_OVERLAY = "combine_memories_overlay"
CONFIG_KEY_MEMORIES_OVERLAY_LOCKED = "memories_overlay_mode_locked"

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
    # API key changed (typical after Immich reset) -> cache is unsafe; clear it.
    conn.execute("DELETE FROM immich_upload_cache")
    _set_cache_meta(conn, IMMICH_CACHE_META_KEY_API_KEY_SHA1, api_key_sha1)


def _file_fingerprint(path: str) -> tuple[int, int]:
    st = os.stat(path)
    # mtime_ns exists on all modern python; fallback just in case.
    mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000))
    return int(st.st_size), int(mtime_ns)


def _sha256_file(path: str, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


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


@dataclass
class SyncResult:
    memories_uploaded: int = 0
    memories_skipped: int = 0
    memories_cache_skipped: int = 0
    memories_unsupported_mime: int = 0
    memories_upload_errors: int = 0
    shared_story_uploaded: int = 0
    shared_story_skipped: int = 0
    shared_story_cache_skipped: int = 0
    shared_story_unsupported_mime: int = 0
    shared_story_upload_errors: int = 0
    chat_media_uploaded: int = 0
    chat_media_skipped: int = 0
    chat_media_cache_skipped: int = 0
    chat_media_unsupported_mime: int = 0
    chat_media_upload_errors: int = 0
    albums_created: int = 0
    errors: list[str] = field(default_factory=list)


class ImmichClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.client = httpx.Client(
            base_url=self.base_url,
            headers={"x-api-key": self.api_key},
            timeout=TIMEOUT,
        )

    def check_connection(self) -> bool:
        try:
            r = self.client.get("/api/server/ping")
            return r.status_code == 200
        except Exception:
            return False

    def upload_asset(
        self,
        file_path: str,
        device_asset_id: str,
        created_at: str | None = None,
    ) -> dict | None:
        """
        Upload a single file.

        Returns:
          - Immich asset dict (uploaded or duplicate)
          - or an error dict: {"status": "error", "error_type": "...", "message": "..."}
        """
        if not created_at:
            created_at = datetime.now(timezone.utc).isoformat()

        fname = os.path.basename(file_path)
        mime = _guess_mime(fname)

        with open(file_path, "rb") as f:
            r = self.client.post(
                "/api/assets",
                data={
                    "deviceAssetId": device_asset_id,
                    "deviceId": DEVICE_ID,
                    "fileCreatedAt": created_at,
                    "fileModifiedAt": created_at,
                },
                files={"assetData": (fname, f, mime)},
            )

        if r.status_code == 201:
            return r.json()
        if r.status_code == 200:
            body = r.json()
            if body.get("status") == "duplicate":
                return body
            return body
        # Non-2xx: return structured error so the sync can count categories.
        try:
            body = r.json()
            message = str(body.get("message") or body.get("error") or r.text)[:300]
        except Exception:
            message = str(r.text)[:300]

        error_type = "upload-error"
        if "Unsupported file type" in message or "unsupported file type" in message:
            error_type = "unsupported-mime"

        logger.warning("Upload failed %s: %s %s", fname, r.status_code, message[:200])
        return {"status": "error", "error_type": error_type, "message": message}

    def update_asset_metadata(
        self,
        asset_id: str,
        description: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        date_time_original: str | None = None,
    ) -> bool:
        body: dict = {}
        if description is not None:
            body["description"] = description
        if latitude is not None:
            body["latitude"] = latitude
        if longitude is not None:
            body["longitude"] = longitude
        if date_time_original is not None:
            body["dateTimeOriginal"] = date_time_original
        if not body:
            return True

        r = self.client.put(f"/api/assets/{asset_id}", json=body)
        if r.status_code == 200:
            return True
        logger.warning("Update metadata failed %s: %s", asset_id, r.text[:200])
        return False

    def get_or_create_album(self, name: str) -> str:
        """Returns album ID, creating it if it doesn't exist."""
        r = self.client.get("/api/albums")
        if r.status_code == 200:
            for album in r.json():
                if album.get("albumName") == name:
                    return album["id"]

        r = self.client.post("/api/albums", json={"albumName": name})
        if r.status_code == 201:
            return r.json()["id"]
        raise RuntimeError(f"Failed to create album '{name}': {r.status_code} {r.text[:200]}")

    def add_assets_to_album(self, album_id: str, asset_ids: list[str]) -> None:
        if not asset_ids:
            return
        for i in range(0, len(asset_ids), 100):
            batch = asset_ids[i : i + 100]
            self.client.put(
                f"/api/albums/{album_id}/assets",
                json={"ids": batch},
            )

    def close(self):
        self.client.close()


def _load_config(data_dir: str) -> dict:
    path = os.path.join(data_dir, CONFIG_FILENAME)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_config(data_dir: str, config: dict) -> None:
    path = os.path.join(data_dir, CONFIG_FILENAME)
    os.makedirs(data_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def get_sync_preferences(data_dir: str) -> dict:
    """Return persisted sync preferences (defaults applied)."""
    cfg = _load_config(data_dir)
    return {
        "combine_memories_overlay": bool(cfg.get(CONFIG_KEY_COMBINE_OVERLAY, False)),
        "memories_overlay_mode_locked": bool(cfg.get(CONFIG_KEY_MEMORIES_OVERLAY_LOCKED, False)),
    }


def set_sync_preferences(data_dir: str, *, combine_memories_overlay: bool) -> dict:
    """Persist sync preferences (kept alongside Immich bootstrap config)."""
    cfg = _load_config(data_dir)
    # Once a mode was chosen, keep it fixed to avoid mixing plain + combined uploads
    # across incremental sync runs.
    if bool(cfg.get(CONFIG_KEY_MEMORIES_OVERLAY_LOCKED, False)):
        return get_sync_preferences(data_dir)

    cfg[CONFIG_KEY_COMBINE_OVERLAY] = bool(combine_memories_overlay)
    cfg[CONFIG_KEY_MEMORIES_OVERLAY_LOCKED] = True
    _save_config(data_dir, cfg)
    return get_sync_preferences(data_dir)


def _wait_for_immich(base_url: str, max_wait: int = 90) -> bool:
    """Poll Immich /api/server/ping until it responds or timeout."""
    deadline = time.time() + max_wait
    interval = 2
    while time.time() < deadline:
        try:
            r = httpx.get(f"{base_url}/api/server/ping", timeout=5)
            if r.status_code == 200:
                logger.info("Immich erreichbar unter %s", base_url)
                return True
        except Exception:
            pass
        time.sleep(interval)
        interval = min(interval * 1.5, 10)
    return False


def _validate_api_key(base_url: str, api_key: str) -> bool:
    """Check whether an API key is still valid."""
    try:
        r = httpx.get(
            f"{base_url}/api/users/me",
            headers={"x-api-key": api_key},
            timeout=10,
        )
        return r.status_code == 200
    except Exception:
        return False


def _bootstrap_immich(base_url: str) -> dict:
    """Create admin, login, generate API key. Returns config dict."""
    c = httpx.Client(base_url=base_url, timeout=TIMEOUT)
    try:
        signup = c.post("/api/auth/admin-sign-up", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD,
            "name": "Admin",
        })
        if signup.status_code == 201:
            logger.info("Immich Admin-Account erstellt")
        elif signup.status_code == 400:
            logger.info("Immich Admin existiert bereits")
        else:
            logger.warning("Admin sign-up: %s %s", signup.status_code, signup.text[:200])

        login = c.post("/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD,
        })
        if login.status_code != 201:
            raise RuntimeError(
                f"Immich Login fehlgeschlagen ({login.status_code}): {login.text[:200]}"
            )
        token = login.json()["accessToken"]

        key_resp = c.post(
            "/api/api-keys",
            json={"name": "snapchat-sync", "permissions": ["all"]},
            headers={"Authorization": f"Bearer {token}"},
        )
        if key_resp.status_code != 201:
            raise RuntimeError(
                f"API-Key Erstellung fehlgeschlagen ({key_resp.status_code}): {key_resp.text[:200]}"
            )
        api_key = key_resp.json()["secret"]
        logger.info("Immich API-Key automatisch erstellt")

        return {
            "admin_email": ADMIN_EMAIL,
            "admin_password": ADMIN_PASSWORD,
            "api_key": api_key,
        }
    finally:
        c.close()


def ensure_immich_ready(immich_url: str, data_dir: str) -> str:
    """Ensure Immich is running and configured. Returns a valid API key.

    1. Wait for Immich to be reachable
    2. Load saved config (if any)
    3. Validate saved API key
    4. If invalid or missing: bootstrap admin + new key
    5. Save config for next run
    """
    if not _wait_for_immich(immich_url):
        raise RuntimeError(
            f"Immich nicht erreichbar unter {immich_url} nach 90s Wartezeit."
        )

    config = _load_config(data_dir)
    api_key = config.get("api_key", "")

    if api_key and _validate_api_key(immich_url, api_key):
        logger.info("Gespeicherter Immich API-Key ist gueltig")
        return api_key

    # Important: if we need to (re-)bootstrap Immich, we must not lose persisted
    # sync preferences (overlay mode lock). Otherwise the UI checkbox can
    # become editable again unexpectedly.
    persisted_prefs: dict = {}
    for k in (CONFIG_KEY_COMBINE_OVERLAY, CONFIG_KEY_MEMORIES_OVERLAY_LOCKED):
        if k in config:
            persisted_prefs[k] = config.get(k)

    logger.info("Kein gueltiger API-Key vorhanden, starte Immich-Bootstrap...")
    config = _bootstrap_immich(immich_url)
    if persisted_prefs:
        config.update(persisted_prefs)
    _save_config(data_dir, config)
    return config["api_key"]


def get_immich_credentials(data_dir: str) -> dict | None:
    """Return saved Immich credentials, or None."""
    config = _load_config(data_dir)
    if config.get("api_key"):
        return {
            "admin_email": config.get("admin_email", ADMIN_EMAIL),
            "admin_password": config.get("admin_password", ADMIN_PASSWORD),
            "configured": True,
        }
    return None


def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()


def _guess_mime(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    return {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".gif": "image/gif",
        ".webp": "image/webp", ".heif": "image/heif",
        ".mp4": "video/mp4", ".mov": "video/quicktime",
        ".avi": "video/x-msvideo", ".mkv": "video/x-matroska",
        ".webm": "video/webm",
    }.get(ext, "application/octet-stream")


def _parse_date_from_filename(filename: str) -> str | None:
    m = DATE_PREFIX_RE.match(filename)
    if m:
        return m.group(1) + "T12:00:00Z"
    return None


def _parse_memory_location(loc_str: str) -> tuple[float | None, float | None]:
    """Parse 'Latitude, Longitude: 47.504, 9.746' format."""
    if not loc_str or "Latitude" not in loc_str:
        return None, None
    try:
        parts = loc_str.split(":")[1].strip().split(",")
        return float(parts[0].strip()), float(parts[1].strip())
    except (IndexError, ValueError):
        return None, None


def _find_overlay_for_main(memories_dir: str, main_fname: str) -> str | None:
    """Try to find a matching overlay file for a given main memory filename."""
    base = os.path.splitext(main_fname)[0]
    # Most exports use ...-main.ext and ...-overlay.ext (sometimes different ext).
    prefix = base[:-5] if base.lower().endswith("-main") else base

    try:
        candidates = [
            f
            for f in os.listdir(memories_dir)
            if os.path.isfile(os.path.join(memories_dir, f))
            and f.lower().startswith(prefix.lower())
            and MEMORY_OVERLAY_RE.search(f)
        ]
    except Exception:
        return None

    if not candidates:
        return None
    # Prefer same extension as main, otherwise first by name.
    main_ext = os.path.splitext(main_fname)[1].lower()
    same_ext = [c for c in candidates if os.path.splitext(c)[1].lower() == main_ext]
    pick = sorted(same_ext or candidates)[0]
    return os.path.join(memories_dir, pick)


def _build_overlay_index(memories_dir: str) -> dict[str, list[str]]:
    """
    Pre-index overlays in the memories directory.

    _find_overlay_for_main() does an os.listdir() for every memory. With large exports
    this becomes very slow. Building a single index makes lookups O(1).
    """
    idx: dict[str, list[str]] = {}
    try:
        for f in os.listdir(memories_dir):
            if not MEMORY_OVERLAY_RE.search(f):
                continue
            if not os.path.isfile(os.path.join(memories_dir, f)):
                continue
            base = os.path.splitext(f)[0]
            prefix = base[:-8] if base.lower().endswith("-overlay") else base
            idx.setdefault(prefix.lower(), []).append(f)
    except Exception:
        return {}

    for k in list(idx.keys()):
        idx[k] = sorted(idx[k])
    return idx


def _find_overlay_for_main_indexed(
    memories_dir: str, main_fname: str, overlay_idx: dict[str, list[str]]
) -> str | None:
    """Same matching logic as _find_overlay_for_main(), but via pre-built index."""
    base = os.path.splitext(main_fname)[0]
    prefix = base[:-5] if base.lower().endswith("-main") else base
    candidates = overlay_idx.get(prefix.lower(), [])
    if not candidates:
        return None
    main_ext = os.path.splitext(main_fname)[1].lower()
    same_ext = [c for c in candidates if os.path.splitext(c)[1].lower() == main_ext]
    pick = sorted(same_ext or candidates)[0]
    return os.path.join(memories_dir, pick)


def _combine_main_and_overlay_image(
    *,
    data_dir: str,
    main_path: str,
    overlay_path: str,
) -> str | None:
    """Create (or reuse) a cached combined image file and return its path."""
    try:
        from PIL import Image  # type: ignore
    except Exception as e:
        logger.warning("Pillow not available, cannot combine overlay: %s", e)
        return None

    try:
        main_stat = os.stat(main_path)
        overlay_stat = os.stat(overlay_path)
    except OSError:
        return None

    main_name = os.path.basename(main_path)
    overlay_name = os.path.basename(overlay_path)
    out_dir = os.path.join(data_dir, COMBINED_MEMORIES_DIRNAME)
    os.makedirs(out_dir, exist_ok=True)

    out_ext = os.path.splitext(main_name)[1].lower() or ".jpg"
    key = _sha1(
        f"combine:{main_name}:{main_stat.st_size}:{int(main_stat.st_mtime)}:"
        f"{overlay_name}:{overlay_stat.st_size}:{int(overlay_stat.st_mtime)}"
    )
    out_path = os.path.join(out_dir, f"{key}{out_ext}")

    if os.path.exists(out_path):
        return out_path

    try:
        with Image.open(main_path) as im_main:
            main_rgba = im_main.convert("RGBA")
            with Image.open(overlay_path) as im_ov:
                ov_rgba = im_ov.convert("RGBA")
                if ov_rgba.size != main_rgba.size:
                    ov_rgba = ov_rgba.resize(main_rgba.size, Image.Resampling.LANCZOS)
                combined = Image.alpha_composite(main_rgba, ov_rgba).convert("RGB")

        # Write to a temp file then rename (avoid partial files).
        # Keep a real image extension on the temp file so Pillow can infer the format.
        tmp_path = out_path + ".tmp" + out_ext
        combined.save(tmp_path, quality=95)
        os.replace(tmp_path, out_path)
        return out_path
    except Exception as e:
        logger.warning("Failed to combine overlay for %s: %s", main_name, e)
        try:
            if os.path.exists(out_path + ".tmp" + out_ext):
                os.remove(out_path + ".tmp" + out_ext)
        except Exception:
            pass
        return None


def sync_memories(
    client: ImmichClient,
    data_dir: str,
    memories_dir: str,
    memories_json_path: str,
    cache_sqlite_path: str,
    result: SyncResult,
    progress_callback=None,
    *,
    combine_overlay: bool = False,
) -> None:
    """Upload memories to Immich with date and GPS from memories_history.json."""
    if not os.path.isdir(memories_dir):
        logger.info("No memories directory found at %s", memories_dir)
        return

    main_files = sorted(
        f for f in os.listdir(memories_dir)
        if os.path.isfile(os.path.join(memories_dir, f))
        and MEMORY_MAIN_RE.search(f)
        and not MEMORY_OVERLAY_RE.search(f)
    )
    if not main_files:
        return

    logger.info("Found %d memory files to process", len(main_files))

    history_by_date: dict[str, list[dict]] = {}
    if os.path.exists(memories_json_path):
        with open(memories_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for item in data.get("Saved Media", []):
            date_str = (item.get("Date") or "")[:10]
            if date_str:
                history_by_date.setdefault(date_str, []).append(item)
        for entries in history_by_date.values():
            entries.sort(key=lambda x: x.get("Date", ""))

    conn = sqlite3.connect(cache_sqlite_path)
    try:
        _ensure_cache_tables(conn)
        _invalidate_cache_if_needed(conn, api_key=client.api_key)

        album_id = client.get_or_create_album("Snapchat Memories")
        result.albums_created += 1
        uploaded_ids: list[str] = []

        overlay_idx = _build_overlay_index(memories_dir) if combine_overlay else None

        for idx, fname in enumerate(main_files):
            file_path = os.path.join(memories_dir, fname)
            try:
                size_bytes, mtime_ns = _file_fingerprint(file_path)
            except OSError:
                continue

            overlay_path_for_cache = None
            overlay_fingerprint = None
            if combine_overlay:
                overlay_path_for_cache = (
                    _find_overlay_for_main_indexed(memories_dir, fname, overlay_idx)
                    if overlay_idx is not None
                    else _find_overlay_for_main(memories_dir, fname)
                )
                if overlay_path_for_cache:
                    try:
                        ov_size, ov_mtime_ns = _file_fingerprint(overlay_path_for_cache)
                        overlay_fingerprint = (os.path.basename(overlay_path_for_cache), ov_size, ov_mtime_ns)
                    except OSError:
                        overlay_path_for_cache = None
                        overlay_fingerprint = None

            # In overlay mode, include overlay fingerprint in the cache key so changes can't be skipped incorrectly.
            rel_cache_key = fname
            if overlay_fingerprint is not None:
                ov_name, ov_size, ov_mtime_ns = overlay_fingerprint
                rel_cache_key = f"{fname}|ov={ov_name}|ov_size={ov_size}|ov_mtime_ns={ov_mtime_ns}"

            if _cache_hit(conn, scope="memories", rel_path=rel_cache_key, size_bytes=size_bytes, mtime_ns=mtime_ns):
                asset_id = _cache_get_asset_id(
                    conn, scope="memories", rel_path=rel_cache_key, size_bytes=size_bytes, mtime_ns=mtime_ns
                )
                if asset_id:
                    uploaded_ids.append(asset_id)
                result.memories_skipped += 1
                result.memories_cache_skipped += 1
                continue

            variant = "combined" if combine_overlay else "plain"
            device_id = _sha1(f"memory:{variant}:{fname}")
            file_date = _parse_date_from_filename(fname)

            lat, lon = None, None
            description = "Snapchat Memory"
            history_ts = None

            date_key = fname[:10] if len(fname) >= 10 else ""
            entries = history_by_date.get(date_key, [])
            if entries:
                entry = entries.pop(0)
                raw_date = entry.get("Date", "")
                if raw_date:
                    history_ts = raw_date.replace(" UTC", "Z").replace(" ", "T")
                loc = entry.get("Location", "")
                entry_lat, entry_lon = _parse_memory_location(loc)
                if entry_lat is not None:
                    lat, lon = entry_lat, entry_lon
                media_type = entry.get("Media Type", "")
                description = f"Snapchat Memory ({media_type})"

            created_at = history_ts or file_date or datetime.now(timezone.utc).isoformat()

            upload_path = file_path
            if combine_overlay:
                overlay_path = overlay_path_for_cache
                if overlay_path:
                    combined = _combine_main_and_overlay_image(
                        data_dir=data_dir,
                        main_path=file_path,
                        overlay_path=overlay_path,
                    )
                    if combined:
                        upload_path = combined

            sha256 = None
            try:
                sha256 = _sha256_file(upload_path)
            except Exception:
                sha256 = None

            if sha256 and _cache_hit_by_sha(conn, scope="memories", sha256=sha256, size_bytes=size_bytes):
                cached_id = _cache_get_asset_id_by_sha(conn, scope="memories", sha256=sha256, size_bytes=size_bytes)
                _cache_put(
                    conn,
                    scope="memories",
                    rel_path=rel_cache_key,
                    size_bytes=size_bytes,
                    mtime_ns=mtime_ns,
                    sha256=sha256,
                    status="skipped",
                    immich_asset_id=cached_id,
                )
                conn.commit()
                result.memories_skipped += 1
                result.memories_cache_skipped += 1
                if cached_id:
                    uploaded_ids.append(cached_id)
                continue

            asset = client.upload_asset(upload_path, device_id, created_at)
            if asset is None:
                result.memories_upload_errors += 1
                result.errors.append(f"Memory upload failed: {fname}")
                continue
            if asset.get("status") == "error":
                et = asset.get("error_type", "upload-error")
                if et == "unsupported-mime":
                    result.memories_unsupported_mime += 1
                else:
                    result.memories_upload_errors += 1
                result.errors.append(f"Memory upload failed ({et}): {fname}")
                continue

            asset_id = asset.get("id")
            if asset.get("status") == "duplicate":
                result.memories_skipped += 1
                if asset_id:
                    uploaded_ids.append(asset_id)
                _cache_put(
                    conn,
                    scope="memories",
                    rel_path=rel_cache_key,
                    size_bytes=size_bytes,
                    mtime_ns=mtime_ns,
                    sha256=sha256,
                    status="duplicate",
                    immich_asset_id=asset_id,
                )
            else:
                result.memories_uploaded += 1
                if asset_id:
                    uploaded_ids.append(asset_id)
                    client.update_asset_metadata(
                        asset_id,
                        description=description,
                        latitude=lat,
                        longitude=lon,
                        date_time_original=created_at,
                    )
                _cache_put(
                    conn,
                    scope="memories",
                    rel_path=rel_cache_key,
                    size_bytes=size_bytes,
                    mtime_ns=mtime_ns,
                    sha256=sha256,
                    status="uploaded",
                    immich_asset_id=asset_id,
                )
            conn.commit()

            if progress_callback and (idx + 1) % 50 == 0:
                progress_callback(idx + 1, len(main_files), "memories")

        if uploaded_ids:
            client.add_assets_to_album(album_id, uploaded_ids)

        logger.info(
            "Memories sync done: %d uploaded, %d skipped, %d errors",
            result.memories_uploaded, result.memories_skipped, len(result.errors),
        )
    finally:
        conn.close()


def sync_shared_story(
    client: ImmichClient,
    shared_story_dir: str,
    shared_story_json_path: str,
    cache_sqlite_path: str,
    result: SyncResult,
    progress_callback=None,
) -> None:
    """Upload shared story media to Immich (best-effort pairing with shared_story.json)."""
    if not os.path.isdir(shared_story_dir):
        logger.info("No shared_story directory found at %s", shared_story_dir)
        return

    files = sorted(
        f
        for f in os.listdir(shared_story_dir)
        if os.path.isfile(os.path.join(shared_story_dir, f))
    )
    if not files:
        return

    meta_entries: list[dict] = []
    if os.path.exists(shared_story_json_path):
        try:
            with open(shared_story_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            raw = data.get("Shared Story", [])
            if isinstance(raw, list):
                meta_entries = [e for e in raw if isinstance(e, dict)]
                meta_entries.sort(key=lambda x: x.get("Created", ""))
        except Exception as e:
            logger.warning("Failed to read shared_story.json: %s", e)

    conn = sqlite3.connect(cache_sqlite_path)
    try:
        _ensure_cache_tables(conn)
        _invalidate_cache_if_needed(conn, api_key=client.api_key)

        album_id = client.get_or_create_album("Snapchat Shared Story")
        result.albums_created += 1

        uploaded_ids: list[str] = []
        total = len(files)
        for idx, fname in enumerate(files):
            file_path = os.path.join(shared_story_dir, fname)
            try:
                size_bytes, mtime_ns = _file_fingerprint(file_path)
            except OSError:
                continue
            if _cache_hit(conn, scope="shared_story", rel_path=fname, size_bytes=size_bytes, mtime_ns=mtime_ns):
                asset_id = _cache_get_asset_id(conn, scope="shared_story", rel_path=fname, size_bytes=size_bytes, mtime_ns=mtime_ns)
                if asset_id:
                    uploaded_ids.append(asset_id)
                result.shared_story_skipped += 1
                result.shared_story_cache_skipped += 1
                continue

            device_id = _sha1(f"sharedstory:{fname}")

            created_at = _parse_date_from_filename(fname) or datetime.now(timezone.utc).isoformat()
            description = "Snapchat Shared Story"

            if idx < len(meta_entries):
                entry = meta_entries[idx]
                raw_created = (entry.get("Created") or "").strip()
                if raw_created:
                    created_at = raw_created.replace(" UTC", "Z").replace(" ", "T")
                content = (entry.get("Content") or "").strip()
                if content:
                    description = f"Snapchat Shared Story ({content})"

            sha256 = None
            try:
                sha256 = _sha256_file(file_path)
            except Exception:
                sha256 = None
            if sha256 and _cache_hit_by_sha(conn, scope="shared_story", sha256=sha256, size_bytes=size_bytes):
                cached_id = _cache_get_asset_id_by_sha(conn, scope="shared_story", sha256=sha256, size_bytes=size_bytes)
                _cache_put(
                    conn,
                    scope="shared_story",
                    rel_path=fname,
                    size_bytes=size_bytes,
                    mtime_ns=mtime_ns,
                    sha256=sha256,
                    status="skipped",
                    immich_asset_id=cached_id,
                )
                conn.commit()
                result.shared_story_skipped += 1
                result.shared_story_cache_skipped += 1
                if cached_id:
                    uploaded_ids.append(cached_id)
                continue

            asset = client.upload_asset(file_path, device_id, created_at)
            if asset is None:
                result.shared_story_upload_errors += 1
                result.errors.append(f"Shared Story upload failed: {fname}")
                continue
            if asset.get("status") == "error":
                et = asset.get("error_type", "upload-error")
                if et == "unsupported-mime":
                    result.shared_story_unsupported_mime += 1
                else:
                    result.shared_story_upload_errors += 1
                result.errors.append(f"Shared Story upload failed ({et}): {fname}")
                continue

            asset_id = asset.get("id")
            if asset.get("status") == "duplicate":
                result.shared_story_skipped += 1
                if asset_id:
                    uploaded_ids.append(asset_id)
                _cache_put(
                    conn,
                    scope="shared_story",
                    rel_path=fname,
                    size_bytes=size_bytes,
                    mtime_ns=mtime_ns,
                    sha256=sha256,
                    status="duplicate",
                    immich_asset_id=asset_id,
                )
            else:
                result.shared_story_uploaded += 1
                if asset_id:
                    uploaded_ids.append(asset_id)
                    client.update_asset_metadata(
                        asset_id,
                        description=description,
                        date_time_original=created_at,
                    )
                _cache_put(
                    conn,
                    scope="shared_story",
                    rel_path=fname,
                    size_bytes=size_bytes,
                    mtime_ns=mtime_ns,
                    sha256=sha256,
                    status="uploaded",
                    immich_asset_id=asset_id,
                )
            conn.commit()

            if progress_callback and (idx + 1) % 50 == 0:
                progress_callback(idx + 1, total, "shared_story")

        if uploaded_ids:
            client.add_assets_to_album(album_id, uploaded_ids)

        logger.info(
            "Shared story sync done: %d uploaded, %d skipped, %d errors",
            result.shared_story_uploaded, result.shared_story_skipped, len(result.errors),
        )
    finally:
        conn.close()


def sync_chat_media(
    client: ImmichClient,
    chat_media_dir: str,
    app_sqlite_path: str,
    cache_sqlite_path: str,
    result: SyncResult,
    progress_callback=None,
) -> None:
    """Upload chat media to Immich with chat context from SQLite."""
    if not os.path.isdir(chat_media_dir):
        logger.info("No chat_media directory found at %s", chat_media_dir)
        return

    app_conn = sqlite3.connect(app_sqlite_path)
    app_conn.row_factory = sqlite3.Row
    cache_conn = sqlite3.connect(cache_sqlite_path)
    try:
        _ensure_cache_tables(cache_conn)
        _invalidate_cache_if_needed(cache_conn, api_key=client.api_key)

        rows = app_conn.execute("""
        SELECT mf.filename, mf.media_id, mf.media_type,
               link.chat_id, c.title AS chat_title, link.sender, link.ts_utc, link.msg_type
        FROM media_files mf
        LEFT JOIN (
            SELECT mmi.media_id AS link_media_id, mmi.chat_id, mmi.message_id,
                   m.sender, m.ts_utc, m.type AS msg_type,
                   ROW_NUMBER() OVER (PARTITION BY mmi.media_id ORDER BY m.ts_utc DESC) AS rn
            FROM message_media_ids mmi
            JOIN messages m ON m.message_id = mmi.message_id
        ) link ON link.link_media_id = mf.media_id AND link.rn = 1
        LEFT JOIN chats c ON c.chat_id = link.chat_id
        ORDER BY COALESCE(link.ts_utc, mf.file_date) DESC
    """).fetchall()

        logger.info("Found %d chat media files to process", len(rows))

        chat_assets: dict[str, list[str]] = {}
        unassigned_ids: list[str] = []

        for idx, row in enumerate(rows):
            fname = row["filename"]
            # Skip audio / voice notes for Immich (user preference)
            if (row["media_type"] == "audio") or (row["msg_type"] == "NOTE"):
                result.chat_media_skipped += 1
                continue
            file_path = os.path.join(chat_media_dir, fname)
            if not os.path.isfile(file_path):
                continue

            try:
                size_bytes, mtime_ns = _file_fingerprint(file_path)
            except OSError:
                continue

            if _cache_hit(cache_conn, scope="chat_media", rel_path=fname, size_bytes=size_bytes, mtime_ns=mtime_ns):
                cached_id = _cache_get_asset_id(cache_conn, scope="chat_media", rel_path=fname, size_bytes=size_bytes, mtime_ns=mtime_ns)
                if cached_id and row["chat_id"]:
                    chat_assets.setdefault(row["chat_id"], []).append(cached_id)
                elif cached_id:
                    unassigned_ids.append(cached_id)
                result.chat_media_skipped += 1
                result.chat_media_cache_skipped += 1
                continue

            device_id = _sha1(f"chatmedia:{fname}")
            ts = row["ts_utc"] or _parse_date_from_filename(fname) or datetime.now(timezone.utc).isoformat()

            sha256 = None
            try:
                sha256 = _sha256_file(file_path)
            except Exception:
                sha256 = None
            if sha256 and _cache_hit_by_sha(cache_conn, scope="chat_media", sha256=sha256, size_bytes=size_bytes):
                cached_id = _cache_get_asset_id_by_sha(cache_conn, scope="chat_media", sha256=sha256, size_bytes=size_bytes)
                _cache_put(
                    cache_conn,
                    scope="chat_media",
                    rel_path=fname,
                    size_bytes=size_bytes,
                    mtime_ns=mtime_ns,
                    sha256=sha256,
                    status="skipped",
                    immich_asset_id=cached_id,
                )
                cache_conn.commit()
                if cached_id and row["chat_id"]:
                    chat_assets.setdefault(row["chat_id"], []).append(cached_id)
                elif cached_id:
                    unassigned_ids.append(cached_id)
                result.chat_media_skipped += 1
                result.chat_media_cache_skipped += 1
                continue

            asset = client.upload_asset(file_path, device_id, ts)
            if asset is None:
                result.chat_media_upload_errors += 1
                result.errors.append(f"Chat media upload failed: {fname}")
                continue
            if asset.get("status") == "error":
                et = asset.get("error_type", "upload-error")
                if et == "unsupported-mime":
                    result.chat_media_unsupported_mime += 1
                else:
                    result.chat_media_upload_errors += 1
                result.errors.append(f"Chat media upload failed ({et}): {fname}")
                continue

            asset_id = asset.get("id")
            if asset.get("status") == "duplicate":
                result.chat_media_skipped += 1
                if asset_id and row["chat_id"]:
                    chat_assets.setdefault(row["chat_id"], []).append(asset_id)
                elif asset_id:
                    unassigned_ids.append(asset_id)
                _cache_put(
                    cache_conn,
                    scope="chat_media",
                    rel_path=fname,
                    size_bytes=size_bytes,
                    mtime_ns=mtime_ns,
                    sha256=sha256,
                    status="duplicate",
                    immich_asset_id=asset_id,
                )
            else:
                result.chat_media_uploaded += 1
                if asset_id:
                    chat_title = row["chat_title"] or row["chat_id"] or "Unbekannt"
                    sender = row["sender"] or ""
                    msg_type = row["msg_type"] or ""

                    desc_parts = [f"Chat: {chat_title}"]
                    if sender:
                        desc_parts.append(f"Von: {sender}")
                    if msg_type and msg_type != "TEXT":
                        desc_parts.append(f"Typ: {msg_type}")
                    description = " | ".join(desc_parts)

                    client.update_asset_metadata(
                        asset_id,
                        description=description,
                        date_time_original=ts,
                    )

                    if row["chat_id"]:
                        chat_assets.setdefault(row["chat_id"], []).append(asset_id)
                    else:
                        unassigned_ids.append(asset_id)
                _cache_put(
                    cache_conn,
                    scope="chat_media",
                    rel_path=fname,
                    size_bytes=size_bytes,
                    mtime_ns=mtime_ns,
                    sha256=sha256,
                    status="uploaded",
                    immich_asset_id=asset_id,
                )
            cache_conn.commit()

            if progress_callback and (idx + 1) % 50 == 0:
                progress_callback(idx + 1, len(rows), "chat_media")

        for chat_id, asset_ids in chat_assets.items():
            chat_title = None
            r = app_conn.execute("SELECT title FROM chats WHERE chat_id = ?", (chat_id,)).fetchone()
            if r:
                chat_title = r["title"]
            album_name = f"Chat: {chat_title or chat_id}"
            try:
                album_id = client.get_or_create_album(album_name)
                client.add_assets_to_album(album_id, asset_ids)
                result.albums_created += 1
            except Exception as e:
                result.errors.append(f"Album '{album_name}': {e}")

        if unassigned_ids:
            try:
                album_id = client.get_or_create_album("Chat-Medien (ohne Zuordnung)")
                client.add_assets_to_album(album_id, unassigned_ids)
                result.albums_created += 1
            except Exception as e:
                result.errors.append(f"Unassigned album: {e}")

    finally:
        app_conn.close()
        cache_conn.close()
    logger.info(
        "Chat media sync done: %d uploaded, %d skipped, %d errors",
        result.chat_media_uploaded, result.chat_media_skipped, len(result.errors),
    )


def run_full_sync(
    immich_url: str,
    data_dir: str,
    export_root: str,
    sqlite_path: str,
    cache_sqlite_path: str,
    progress_callback=None,
    *,
    combine_memories_overlay: bool = False,
) -> SyncResult:
    """Run the complete sync: auto-bootstrap Immich, then upload memories + chat media."""
    result = SyncResult()

    try:
        api_key = ensure_immich_ready(immich_url, data_dir)
    except RuntimeError as e:
        result.errors.append(str(e))
        return result

    client = ImmichClient(immich_url, api_key)
    try:
        memories_dir = os.path.join(export_root, "memories")
        memories_json = os.path.join(export_root, "json", "memories_history.json")
        sync_memories(
            client,
            data_dir=data_dir,
            memories_dir=memories_dir,
            memories_json_path=memories_json,
            cache_sqlite_path=cache_sqlite_path,
            result=result,
            progress_callback=progress_callback,
            combine_overlay=combine_memories_overlay,
        )

        shared_story_dir = os.path.join(export_root, "shared_story")
        shared_story_json = os.path.join(export_root, "json", "shared_story.json")
        sync_shared_story(
            client,
            shared_story_dir=shared_story_dir,
            shared_story_json_path=shared_story_json,
            cache_sqlite_path=cache_sqlite_path,
            result=result,
            progress_callback=progress_callback,
        )

        chat_media_dir = os.path.join(export_root, "chat_media")
        sync_chat_media(
            client, chat_media_dir, sqlite_path, cache_sqlite_path, result, progress_callback
        )
    finally:
        client.close()

    return result

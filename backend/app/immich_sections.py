"""Sync sections: memories, shared_story, chat_media."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone

from .immich_cache import (
    _cache_get_asset_id,
    _cache_get_asset_id_by_sha,
    _cache_hit,
    _cache_hit_by_sha,
    _cache_put,
    _ensure_cache_tables,
    _invalidate_cache_if_needed,
)
from .immich_client import ImmichClient
from .immich_heic import HEIC_CONVERTED_DIRNAME, _convert_heic_to_jpeg, _is_heic_heif
from .immich_overlay import (
    MEMORY_MAIN_RE,
    MEMORY_OVERLAY_RE,
    _build_overlay_index,
    _combine_main_and_overlay_image,
    _find_overlay_for_main,
    _find_overlay_for_main_indexed,
)
from .immich_models import SyncResult
from .immich_util import (
    _file_fingerprint,
    _parse_date_from_filename,
    _parse_memory_location,
    _sha1,
    _sha256_file,
)

logger = logging.getLogger(__name__)


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

            if _is_heic_heif(upload_path):
                heic_out_dir = os.path.join(data_dir, HEIC_CONVERTED_DIRNAME)
                converted = _convert_heic_to_jpeg(
                    upload_path,
                    heic_out_dir,
                    scope="memories",
                    rel_path=rel_cache_key,
                    size_bytes=size_bytes,
                    mtime_ns=mtime_ns,
                )
                if converted:
                    upload_path = converted

            try:
                upload_size_bytes, upload_mtime_ns = _file_fingerprint(upload_path)
            except OSError:
                upload_size_bytes, upload_mtime_ns = size_bytes, mtime_ns

            sha256 = None
            try:
                sha256 = _sha256_file(upload_path)
            except Exception:
                sha256 = None

            device_id = _sha1(f"memory:{variant}:{sha256 or fname}")

            if sha256 and _cache_hit_by_sha(conn, scope="memories", sha256=sha256, size_bytes=upload_size_bytes):
                cached_id = _cache_get_asset_id_by_sha(conn, scope="memories", sha256=sha256, size_bytes=upload_size_bytes)
                _cache_put(
                    conn,
                    scope="memories",
                    rel_path=rel_cache_key,
                    size_bytes=upload_size_bytes,
                    mtime_ns=upload_mtime_ns,
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
                    size_bytes=upload_size_bytes,
                    mtime_ns=upload_mtime_ns,
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
                    size_bytes=upload_size_bytes,
                    mtime_ns=upload_mtime_ns,
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
    data_dir: str,
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

            upload_path = file_path
            if _is_heic_heif(upload_path):
                heic_out_dir = os.path.join(data_dir, HEIC_CONVERTED_DIRNAME)
                converted = _convert_heic_to_jpeg(
                    upload_path,
                    heic_out_dir,
                    scope="shared_story",
                    rel_path=fname,
                    size_bytes=size_bytes,
                    mtime_ns=mtime_ns,
                )
                if converted:
                    upload_path = converted

            try:
                upload_size_bytes, upload_mtime_ns = _file_fingerprint(upload_path)
            except OSError:
                upload_size_bytes, upload_mtime_ns = size_bytes, mtime_ns

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
                sha256 = _sha256_file(upload_path)
            except Exception:
                sha256 = None

            device_id = _sha1(f"sharedstory:{sha256 or fname}")

            if sha256 and _cache_hit_by_sha(conn, scope="shared_story", sha256=sha256, size_bytes=upload_size_bytes):
                cached_id = _cache_get_asset_id_by_sha(conn, scope="shared_story", sha256=sha256, size_bytes=upload_size_bytes)
                _cache_put(
                    conn,
                    scope="shared_story",
                    rel_path=fname,
                    size_bytes=upload_size_bytes,
                    mtime_ns=upload_mtime_ns,
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

            asset = client.upload_asset(upload_path, device_id, created_at)
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
                    client.update_asset_metadata(
                        asset_id,
                        description=description,
                        date_time_original=created_at,
                    )
                _cache_put(
                    conn,
                    scope="shared_story",
                    rel_path=fname,
                    size_bytes=upload_size_bytes,
                    mtime_ns=upload_mtime_ns,
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
                    size_bytes=upload_size_bytes,
                    mtime_ns=upload_mtime_ns,
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
    data_dir: str,
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

            upload_path = file_path
            if _is_heic_heif(upload_path):
                heic_out_dir = os.path.join(data_dir, HEIC_CONVERTED_DIRNAME)
                converted = _convert_heic_to_jpeg(
                    upload_path,
                    heic_out_dir,
                    scope="chat_media",
                    rel_path=fname,
                    size_bytes=size_bytes,
                    mtime_ns=mtime_ns,
                )
                if converted:
                    upload_path = converted

            try:
                upload_size_bytes, upload_mtime_ns = _file_fingerprint(upload_path)
            except OSError:
                upload_size_bytes, upload_mtime_ns = size_bytes, mtime_ns

            ts = row["ts_utc"] or _parse_date_from_filename(fname) or datetime.now(timezone.utc).isoformat()

            sha256 = None
            try:
                sha256 = _sha256_file(upload_path)
            except Exception:
                sha256 = None

            device_id = _sha1(f"chatmedia:{sha256 or fname}")

            if sha256 and _cache_hit_by_sha(cache_conn, scope="chat_media", sha256=sha256, size_bytes=upload_size_bytes):
                cached_id = _cache_get_asset_id_by_sha(cache_conn, scope="chat_media", sha256=sha256, size_bytes=upload_size_bytes)
                _cache_put(
                    cache_conn,
                    scope="chat_media",
                    rel_path=fname,
                    size_bytes=upload_size_bytes,
                    mtime_ns=upload_mtime_ns,
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

            asset = client.upload_asset(upload_path, device_id, ts)
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
            chat_title = row["chat_title"] or row["chat_id"] or "Unbekannt"
            sender = row["sender"] or ""
            msg_type = row["msg_type"] or ""
            desc_parts = [f"Chat: {chat_title}"]
            if sender:
                desc_parts.append(f"Von: {sender}")
            if msg_type and msg_type != "TEXT":
                desc_parts.append(f"Typ: {msg_type}")
            description = " | ".join(desc_parts)

            if asset.get("status") == "duplicate":
                result.chat_media_skipped += 1
                if asset_id and row["chat_id"]:
                    chat_assets.setdefault(row["chat_id"], []).append(asset_id)
                elif asset_id:
                    unassigned_ids.append(asset_id)
                if asset_id:
                    client.update_asset_metadata(
                        asset_id,
                        description=description,
                        date_time_original=ts,
                    )
                _cache_put(
                    cache_conn,
                    scope="chat_media",
                    rel_path=fname,
                    size_bytes=upload_size_bytes,
                    mtime_ns=upload_mtime_ns,
                    sha256=sha256,
                    status="duplicate",
                    immich_asset_id=asset_id,
                )
            else:
                result.chat_media_uploaded += 1
                if asset_id:
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
                    size_bytes=upload_size_bytes,
                    mtime_ns=upload_mtime_ns,
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

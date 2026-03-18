from __future__ import annotations

import asyncio
import os
import shutil
import threading
import time
import zipfile
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .config import settings
from .logging_setup import setup_logging
from .immich_sync import (
    MEMORY_MAIN_RE,
    get_immich_credentials,
    get_sync_preferences,
    run_full_sync,
    set_sync_preferences,
)
from .insights_import import build_insights_snapshot
from .importer import (
    build_media_id_lookup,
    iter_messages_for_chat_json,
    iter_snaps_for_thread_json,
    load_chats_from_json,
    load_friend_display_names,
    load_snaps_from_json,
    scan_chat_media,
)
from .meili import MeiliClient
from .storage import Storage


setup_logging()

app = FastAPI(title="Snapchat Chat Search")
store = Storage(settings.sqlite_path)
meili = MeiliClient(settings.meili_url, settings.meili_api_key, settings.meili_index)


@app.on_event("startup")
def _startup() -> None:
    os.makedirs(settings.data_dir, exist_ok=True)
    store.init()


class ImportResponse(BaseModel):
    chat_count: int
    message_count: int
    snap_count: int
    media_file_count: int


class AdminActionResponse(BaseModel):
    ok: bool
    message: str
    details: dict = Field(default_factory=dict)


class UnpackRequest(BaseModel):
    wipe_input: bool = True


def _safe_extract_zip(zip_path: str, dest_dir: str) -> int:
    """Extract zip into dest_dir, preventing path traversal. Returns extracted file count."""
    extracted = 0
    with zipfile.ZipFile(zip_path, "r") as z:
        for info in z.infolist():
            name = info.filename
            if not name or name.endswith("/"):
                continue
            # Normalize and prevent path traversal
            normalized = os.path.normpath(name).lstrip("\\/")  # remove absolute prefixes
            if normalized.startswith("..") or os.path.isabs(normalized):
                continue
            out_path = os.path.join(dest_dir, normalized)
            out_dir = os.path.dirname(out_path)
            os.makedirs(out_dir, exist_ok=True)
            with z.open(info, "r") as src, open(out_path, "wb") as dst:
                shutil.copyfileobj(src, dst)
            extracted += 1
    return extracted


def _delete_path(path: str) -> tuple[bool, str]:
    """Best-effort delete file or directory. Returns (deleted, error_msg)."""
    try:
        if os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.exists(path):
            os.remove(path)
        return True, ""
    except Exception as e:
        return False, str(e)


# ------------------------------------------------------------------
# Unpack + Import (mit Fortschrittsanzeige, bleibt bei Reload sichtbar)
# ------------------------------------------------------------------

_unpack_import_state: dict = {
    "phase": "idle",  # idle | unpack | import | done | error
    "current": 0,
    "total": 0,
    "message": "",
    "error": None,
    "result": None,
}
_unpack_import_lock = threading.Lock()


def _set_unpack_import_state(*, phase: str, current: int = 0, total: int = 0, message: str = "", error: str | None = None, result: dict | None = None) -> None:
    with _unpack_import_lock:
        _unpack_import_state["phase"] = phase
        _unpack_import_state["current"] = current
        _unpack_import_state["total"] = total
        _unpack_import_state["message"] = message
        _unpack_import_state["error"] = error
        _unpack_import_state["result"] = result


def _do_unpack(*, wipe_input: bool) -> dict:
    zip_dir = "/data/input_zip"
    dest = settings.export_root
    if not os.path.isdir(zip_dir):
        raise RuntimeError("ZIP directory not mounted (/data/input_zip)")

    zips = sorted(
        os.path.join(zip_dir, f)
        for f in os.listdir(zip_dir)
        if f.lower().endswith(".zip") and os.path.isfile(os.path.join(zip_dir, f))
    )
    if not zips:
        raise RuntimeError("Keine ZIP-Dateien in 'input zip' gefunden.")

    if wipe_input:
        os.makedirs(dest, exist_ok=True)
        for name in os.listdir(dest):
            _delete_path(os.path.join(dest, name))
        os.makedirs(dest, exist_ok=True)

    total_extracted = 0
    per_zip: list[dict] = []
    total = len(zips)
    for i, zp in enumerate(zips, start=1):
        _set_unpack_import_state(
            phase="unpack",
            current=i - 1,
            total=total,
            message=f"Entpacke ZIP {i}/{total}: {os.path.basename(zp)}",
        )
        cnt = _safe_extract_zip(zp, dest)
        per_zip.append({"zip": os.path.basename(zp), "extracted": cnt})
        total_extracted += cnt
        _set_unpack_import_state(
            phase="unpack",
            current=i,
            total=total,
            message=f"ZIP entpackt ({i}/{total}): {os.path.basename(zp)}",
        )

    _invalidate_memory_count_cache()
    return {"zip_count": len(zips), "files_extracted": total_extracted, "per_zip": per_zip, "dest": dest}


async def _do_import(*, progress_callback=None) -> ImportResponse:
    export_root = settings.export_root

    chat_media_dir = os.path.join(export_root, "chat_media")
    media_lookup = build_media_id_lookup(chat_media_dir)

    friends_path = os.path.join(export_root, "json", "friends.json")
    display_names = load_friend_display_names(friends_path)

    chat_json_path = os.path.join(export_root, "json", "chat_history.json")
    if not os.path.exists(chat_json_path):
        raise RuntimeError(f"Missing {chat_json_path}")

    chats_data = load_chats_from_json(chat_json_path)
    total_est = sum(len(v or []) for v in chats_data.values())
    processed = 0

    def _progress(msg: str) -> None:
        if progress_callback:
            progress_callback(processed, total_est, msg)

    await meili.ensure_index()
    batch: list[dict] = []
    batch_size = 2000
    total_messages = 0

    for chat_id, raw_msgs in chats_data.items():
        msg_count = 0
        text_count = 0
        first_ts: str | None = None
        last_ts: str | None = None
        title = ""

        chunk: list = []
        for m in iter_messages_for_chat_json(chat_id, raw_msgs):
            if not title:
                title = m.chat_title
            msg_count += 1
            total_messages += 1
            processed += 1
            if m.type == "TEXT" and m.text:
                text_count += 1
            if m.ts_utc:
                first_ts = min(first_ts, m.ts_utc) if first_ts else m.ts_utc
                last_ts = max(last_ts, m.ts_utc) if last_ts else m.ts_utc

            chunk.append(m)
            batch.append({
                "message_id": m.message_id,
                "chat_id": m.chat_id,
                "chat_title": m.chat_title,
                "ts_utc": m.ts_utc,
                "sender": m.sender,
                "type": m.type,
                "text": m.text,
                "ordinal_in_chat": m.ordinal_in_chat,
                "is_saved": m.is_saved,
            })

            if len(chunk) >= 2000:
                store.insert_messages(chunk, media_lookup)
                chunk = []
                _progress("Importiere Nachrichten…")
            if len(batch) >= batch_size:
                await meili.add_documents(batch)
                batch = []
                _progress("Indexiere Suche…")

        if chunk:
            store.insert_messages(chunk, media_lookup)
        if batch:
            await meili.add_documents(batch)
            batch = []

        display_title = title
        if title == chat_id and chat_id in display_names:
            display_title = display_names[chat_id]
        store.upsert_chat(
            chat_id=chat_id,
            title=display_title,
            text_message_count=text_count,
            message_count=msg_count,
            first_ts=first_ts,
            last_ts=last_ts,
        )

    if batch:
        await meili.add_documents(batch)

    total_snaps = 0
    snap_json_path = os.path.join(export_root, "json", "snap_history.json")
    if os.path.exists(snap_json_path):
        snaps_data = load_snaps_from_json(snap_json_path)
        for thread_id, raw_snaps in snaps_data.items():
            chunk_s = list(iter_snaps_for_thread_json(thread_id, raw_snaps))
            if chunk_s:
                store.insert_snaps(chunk_s)
                total_snaps += len(chunk_s)

    media_files = scan_chat_media(chat_media_dir)
    media_file_count = len(media_files)
    if media_files:
        for i in range(0, len(media_files), 2000):
            store.insert_media_files(media_files[i : i + 2000])

    # --- Insights snapshot import (does not affect core import) ---
    try:
        store.replace_insights_snapshot(build_insights_snapshot(export_root))
    except Exception:
        # Keep import resilient; insights can be re-imported with the next full import.
        pass

    return ImportResponse(
        chat_count=len(chats_data),
        message_count=total_messages,
        snap_count=total_snaps,
        media_file_count=media_file_count,
    )


def _unpack_import_progress_callback(current: int, total: int, message: str) -> None:
    _set_unpack_import_state(
        phase="import",
        current=current,
        total=total,
        message=message,
        error=None,
        result=None,
    )


def _run_unpack_and_import_in_background(*, wipe_input: bool) -> None:
    _set_unpack_import_state(phase="unpack", current=0, total=0, message="Starte Entpacken…", error=None, result=None)
    try:
        unpack_details = _do_unpack(wipe_input=wipe_input)
        _set_unpack_import_state(phase="import", current=0, total=0, message="Starte Import…", error=None, result=None)
        import_result = asyncio.run(_do_import(progress_callback=_unpack_import_progress_callback))
        _set_unpack_import_state(
            phase="done",
            current=1,
            total=1,
            message="Entpacken + Import abgeschlossen.",
            error=None,
            result={
                "unpack": unpack_details,
                "import": import_result.model_dump(),
            },
        )
    except Exception as e:
        _set_unpack_import_state(
            phase="error",
            current=_unpack_import_state.get("current", 0),
            total=_unpack_import_state.get("total", 0),
            message="Fehler",
            error=str(e),
            result=None,
        )


@app.get("/api/admin/unpack-import-progress")
def unpack_import_progress():
    with _unpack_import_lock:
        return dict(_unpack_import_state)


@app.post("/api/admin/unpack-import")
def unpack_import_start(req: UnpackRequest) -> dict:
    with _unpack_import_lock:
        if _unpack_import_state["phase"] in ("unpack", "import"):
            raise HTTPException(status_code=409, detail="Entpacken/Import läuft bereits.")
        _unpack_import_state["phase"] = "starting"
        _unpack_import_state["error"] = None
        _unpack_import_state["result"] = None
        _unpack_import_state["message"] = "Job gestartet."
        _unpack_import_state["current"] = 0
        _unpack_import_state["total"] = 0

    t = threading.Thread(
        target=_run_unpack_and_import_in_background,
        kwargs={"wipe_input": bool(req.wipe_input)},
        daemon=True,
    )
    t.start()
    return {"started": True, "message": "Entpacken + Import gestartet."}


@app.post("/api/admin/unpack", response_model=AdminActionResponse)
def admin_unpack(req: UnpackRequest) -> AdminActionResponse:
    """Unpack all ZIPs from /data/input_zip into EXPORT_ROOT (/data/raw_export)."""
    zip_dir = "/data/input_zip"
    dest = settings.export_root
    if not os.path.isdir(zip_dir):
        raise HTTPException(status_code=400, detail="ZIP directory not mounted (/data/input_zip)")

    zips = sorted(
        os.path.join(zip_dir, f)
        for f in os.listdir(zip_dir)
        if f.lower().endswith(".zip") and os.path.isfile(os.path.join(zip_dir, f))
    )
    if not zips:
        raise HTTPException(status_code=400, detail="Keine ZIP-Dateien in 'input zip' gefunden.")

    if req.wipe_input:
        os.makedirs(dest, exist_ok=True)
        # Wipe everything in EXPORT_ROOT
        for name in os.listdir(dest):
            p = os.path.join(dest, name)
            _delete_path(p)
        os.makedirs(dest, exist_ok=True)

    total_extracted = 0
    per_zip: list[dict] = []
    for zp in zips:
        cnt = _safe_extract_zip(zp, dest)
        per_zip.append({"zip": os.path.basename(zp), "extracted": cnt})
        total_extracted += cnt

    _invalidate_memory_count_cache()
    return AdminActionResponse(
        ok=True,
        message="ZIPs entpackt.",
        details={"zip_count": len(zips), "files_extracted": total_extracted, "per_zip": per_zip, "dest": dest},
    )


@app.post("/api/admin/reset-app", response_model=AdminActionResponse)
def admin_reset_app() -> AdminActionResponse:
    """Reset local app state: SQLite + normalized files + Meilisearch index."""
    deleted: list[dict] = []
    for rel in ("app.sqlite", "app.sqlite-shm", "app.sqlite-wal", os.path.join("normalized", "chats.json"), os.path.join("normalized", "messages.jsonl")):
        p = os.path.join(settings.data_dir, rel)
        ok, err = _delete_path(p)
        if ok:
            deleted.append({"path": p, "deleted": True})
        else:
            deleted.append({"path": p, "deleted": False, "error": err})

    # Recreate SQLite schema immediately (backend keeps running after reset).
    db_init_ok = True
    db_init_err = ""
    try:
        store.init()
    except Exception as e:
        db_init_ok = False
        db_init_err = str(e)

    # Reset Meilisearch index
    meili_ok = True
    meili_err = ""
    try:
        import httpx

        r = httpx.delete(
            f"{settings.meili_url}/indexes/{settings.meili_index}",
            headers={"Authorization": f"Bearer {settings.meili_api_key}"},
            timeout=10,
        )
        # 200/202/204 success, 404 also fine
        if r.status_code not in (200, 202, 204, 404):
            meili_ok = False
            meili_err = f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as e:
        meili_ok = False
        meili_err = str(e)

    return AdminActionResponse(
        ok=db_init_ok and meili_ok,
        message="App reset abgeschlossen." if (db_init_ok and meili_ok) else "App reset unvollstaendig.",
        details={"deleted": deleted, "db_init_ok": db_init_ok, "db_init_error": db_init_err, "meili_ok": meili_ok, "meili_error": meili_err},
    )


@app.post("/api/admin/reset-immich", response_model=AdminActionResponse)
def admin_reset_immich() -> AdminActionResponse:
    """Delete host immich-data, local immich_config.json and Immich upload cache (requires volume mount)."""
    immich_host = "/data/immich_host"
    if not os.path.exists(immich_host):
        raise HTTPException(status_code=400, detail="immich-data ist nicht ins Backend gemountet (/data/immich_host).")

    # Delete bootstrap config used by auto setup
    cfg = os.path.join(settings.data_dir, "immich_config.json")
    cfg_ok, cfg_err = _delete_path(cfg)

    # Delete Immich upload cache (stale after full reset; only deleted here, not on reset-app)
    cache_path = settings.immich_cache_sqlite_path
    cache_ok, cache_err = _delete_path(cache_path)
    for suffix in ("-shm", "-wal"):
        _delete_path(cache_path + suffix)

    # Delete everything in immich-data (library + postgres)
    errors: list[str] = []
    if os.path.isdir(immich_host):
        for name in os.listdir(immich_host):
            ok, err = _delete_path(os.path.join(immich_host, name))
            if not ok and err:
                errors.append(f"{name}: {err}")

    still_there = os.listdir(immich_host) if os.path.isdir(immich_host) else []
    ok = (not still_there) and (cfg_ok or not os.path.exists(cfg))

    return AdminActionResponse(
        ok=ok,
        message="Immich reset abgeschlossen." if ok else "Immich reset unvollstaendig (Dateien evtl. gesperrt).",
        details={
            "cfg_deleted": cfg_ok,
            "cfg_error": cfg_err,
            "cache_deleted": cache_ok,
            "cache_error": cache_err,
            "remaining": still_there,
            "errors": errors,
        },
    )


@app.post("/api/import", response_model=ImportResponse)
async def import_export() -> ImportResponse:
    try:
        return await _do_import()
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/insights")
def insights():
    """Extra export insights snapshot (stored in SQLite)."""
    return store.get_insights()


# Cache für memory_count (TTL 60 s), damit das Dashboard nicht bei jedem Aufruf
# tausende Dateien im gemounteten memories-Ordner durchzählt.
_dashboard_memory_count_cache: tuple[float, int] = (0.0, 0)
MEMORY_COUNT_CACHE_TTL = 60.0


def _get_memory_count() -> int:
    global _dashboard_memory_count_cache
    now = time.monotonic()
    cached_ts, cached_count = _dashboard_memory_count_cache
    if now - cached_ts < MEMORY_COUNT_CACHE_TTL:
        return cached_count
    count = 0
    try:
        memories_dir = os.path.join(settings.export_root, "memories")
        if os.path.isdir(memories_dir):
            # Nur Namen prüfen (Regex), kein isfile pro Datei – spart tausende Stat-Calls
            count = sum(1 for f in os.listdir(memories_dir) if MEMORY_MAIN_RE.search(f))
        _dashboard_memory_count_cache = (now, count)
    except Exception:
        pass
    return count


def _invalidate_memory_count_cache() -> None:
    global _dashboard_memory_count_cache
    _dashboard_memory_count_cache = (0.0, 0)


@app.get("/api/dashboard")
def dashboard():
    """Quick summary stats for the dashboard page. Gibt bei leerer/fehlender DB immer 200 mit Nullen zurück."""
    default = {
        "chat_count": 0,
        "message_count": 0,
        "media_message_count": 0,
        "media_file_count": 0,
        "assigned_media": 0,
        "unassigned_media": 0,
        "snap_count": 0,
        "memory_count": 0,
        "first_message": None,
        "last_message": None,
    }
    try:
        chats = store.list_chats()
        with store.connect() as conn:
            msg_count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            media_msg_count = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE type != 'TEXT'"
            ).fetchone()[0]
            media_file_count = conn.execute("SELECT COUNT(*) FROM media_files").fetchone()[0]
            assigned_media = conn.execute(
                "SELECT COUNT(DISTINCT mf.filename) FROM media_files mf "
                "JOIN message_media_ids mmi ON mf.media_id = mmi.media_id"
            ).fetchone()[0]
            unassigned_media = media_file_count - assigned_media
            try:
                snap_count = conn.execute("SELECT COUNT(*) FROM snaps").fetchone()[0]
            except Exception:
                snap_count = 0
            first_msg = conn.execute(
                "SELECT MIN(ts_utc) FROM messages WHERE ts_utc IS NOT NULL AND ts_utc != ''"
            ).fetchone()[0]
            last_msg = conn.execute(
                "SELECT MAX(ts_utc) FROM messages WHERE ts_utc IS NOT NULL AND ts_utc != ''"
            ).fetchone()[0]

        memory_count = _get_memory_count()

        return {
            "chat_count": len(chats),
            "message_count": msg_count,
            "media_message_count": media_msg_count,
            "media_file_count": media_file_count,
            "assigned_media": assigned_media,
            "unassigned_media": unassigned_media,
            "snap_count": snap_count,
            "memory_count": memory_count,
            "first_message": first_msg,
            "last_message": last_msg,
        }
    except Exception:
        return default


@app.get("/api/chats")
def list_chats():
    return {"chats": store.list_chats()}


@app.get("/api/chats/{chat_id}")
def get_chat(chat_id: str):
    chat = store.get_chat(chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat


@app.get("/api/chats/{chat_id}/messages")
def get_messages(chat_id: str, offset: int = 0, limit: int = 100):
    if limit > 100_000:
        limit = 100_000
    chat = store.get_chat(chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"messages": store.get_messages(chat_id, offset=offset, limit=limit), "chat": chat}


class SearchRequest(BaseModel):
    q: str = Field(min_length=1)
    chat_id: Optional[str] = None
    limit: int = 20
    offset: int = 0


@app.post("/api/search")
async def search(req: SearchRequest):
    limit = max(1, min(req.limit, 50))
    offset = max(0, req.offset)
    result = await meili.search(q=req.q, chat_id=req.chat_id, limit=limit, offset=offset)
    return result


@app.get("/api/message/{message_id}")
def get_message(message_id: str):
    m = store.get_message(message_id)
    if not m:
        raise HTTPException(status_code=404, detail="Message not found")
    return m


@app.get("/api/chats/{chat_id}/context")
def get_context(chat_id: str, center_ordinal: int, before: int = 30, after: int = 30):
    chat = store.get_chat(chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {
        "chat": chat,
        "messages": store.get_context_by_ordinal(chat_id=chat_id, center_ordinal=center_ordinal, before=before, after=after),
        "center_ordinal": center_ordinal,
    }


@app.get("/api/snap_threads")
def list_snap_threads():
    return {"threads": store.list_snap_threads()}


# ------------------------------------------------------------------
# Media endpoints
# ------------------------------------------------------------------

MEDIA_CONTENT_TYPES = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "gif": "image/gif", "webp": "image/webp", "mp4": "video/mp4",
    "mov": "video/quicktime", "avi": "video/x-msvideo",
    "mkv": "video/x-matroska", "webm": "video/webm",
}


@app.get("/api/media/files/{filename:path}")
def serve_media_file(filename: str):
    safe_name = os.path.basename(filename)
    file_path = os.path.join(settings.export_root, "chat_media", safe_name)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    ext = os.path.splitext(safe_name)[1].lstrip(".").lower()
    content_type = MEDIA_CONTENT_TYPES.get(ext, "application/octet-stream")
    return FileResponse(file_path, media_type=content_type)


@app.get("/api/media")
def list_media(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    media_type: Optional[str] = None,
    chat_id: Optional[str] = None,
    assigned_only: bool = True,
    unassigned_only: bool = False,
    offset: int = 0,
    limit: int = 60,
):
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    return store.list_media_files(
        date_from=date_from,
        date_to=date_to,
        media_type=media_type,
        chat_id=chat_id,
        assigned_only=assigned_only,
        unassigned_only=unassigned_only,
        offset=offset,
        limit=limit,
    )


@app.get("/api/media/chats")
def list_media_chats():
    return {"chats": store.list_chats_with_media()}


@app.get("/api/media/by-date/{date}")
def get_media_by_date(date: str):
    return {"files": store.get_media_by_date(date)}


# ------------------------------------------------------------------
# Immich Sync (mit Fortschrittsanzeige)
# ------------------------------------------------------------------

_sync_state: dict = {
    "phase": "idle",  # idle | memories | shared_story | chat_media | done | error
    "current": 0,
    "total": 0,
    "message": "",
    "result": None,
    "error": None,
    "combine_memories_overlay": False,
}
_sync_lock = threading.Lock()


def _immich_progress_callback(current: int, total: int, phase: str) -> None:
    with _sync_lock:
        _sync_state["phase"] = phase
        _sync_state["current"] = current
        _sync_state["total"] = total
        _sync_state["message"] = f"{phase}: {current} / {total}"
        _sync_state["error"] = None


def _run_sync_in_background(*, combine_memories_overlay: bool) -> None:
    with _sync_lock:
        _sync_state["phase"] = "memories"
        _sync_state["current"] = 0
        _sync_state["total"] = 0
        _sync_state["message"] = "Starte Sync..."
        _sync_state["result"] = None
        _sync_state["error"] = None
        _sync_state["combine_memories_overlay"] = combine_memories_overlay
    try:
        result = run_full_sync(
            immich_url=settings.immich_url,
            data_dir=settings.data_dir,
            export_root=settings.export_root,
            sqlite_path=settings.sqlite_path,
            cache_sqlite_path=settings.immich_cache_sqlite_path,
            progress_callback=_immich_progress_callback,
            combine_memories_overlay=combine_memories_overlay,
        )
        with _sync_lock:
            _sync_state["phase"] = "done"
            _sync_state["result"] = {
                "memories_uploaded": result.memories_uploaded,
                "memories_skipped": result.memories_skipped,
                "memories_cache_skipped": getattr(result, "memories_cache_skipped", 0),
                "memories_unsupported_mime": getattr(result, "memories_unsupported_mime", 0),
                "memories_upload_errors": getattr(result, "memories_upload_errors", 0),
                "shared_story_uploaded": getattr(result, "shared_story_uploaded", 0),
                "shared_story_skipped": getattr(result, "shared_story_skipped", 0),
                "shared_story_cache_skipped": getattr(result, "shared_story_cache_skipped", 0),
                "shared_story_unsupported_mime": getattr(result, "shared_story_unsupported_mime", 0),
                "shared_story_upload_errors": getattr(result, "shared_story_upload_errors", 0),
                "chat_media_uploaded": result.chat_media_uploaded,
                "chat_media_skipped": result.chat_media_skipped,
                "chat_media_cache_skipped": getattr(result, "chat_media_cache_skipped", 0),
                "chat_media_unsupported_mime": getattr(result, "chat_media_unsupported_mime", 0),
                "chat_media_upload_errors": getattr(result, "chat_media_upload_errors", 0),
                "albums_created": result.albums_created,
                "errors": result.errors,
            }
    except Exception as e:
        with _sync_lock:
            _sync_state["phase"] = "error"
            _sync_state["error"] = str(e)


class ImmichSyncResponse(BaseModel):
    started: bool = False
    message: Optional[str] = None
    memories_uploaded: int = 0
    memories_skipped: int = 0
    memories_cache_skipped: int = 0
    shared_story_uploaded: int = 0
    shared_story_skipped: int = 0
    shared_story_cache_skipped: int = 0
    chat_media_uploaded: int = 0
    chat_media_skipped: int = 0
    chat_media_cache_skipped: int = 0
    albums_created: int = 0
    errors: list[str] = []


class ImmichSyncRequest(BaseModel):
    combine_memories_overlay: Optional[bool] = None


@app.get("/api/immich/sync-progress")
def immich_sync_progress():
    """Aktueller Sync-Fortschritt (für Polling während des Syncs)."""
    with _sync_lock:
        out = {
            "phase": _sync_state["phase"],
            "current": _sync_state["current"],
            "total": _sync_state["total"],
            "message": _sync_state["message"],
            "error": _sync_state["error"],
            "combine_memories_overlay": _sync_state.get("combine_memories_overlay", False),
        }
        if _sync_state["phase"] == "done" and _sync_state["result"]:
            out["result"] = _sync_state["result"]
    return out


@app.get("/api/immich/sync-settings")
def immich_sync_settings():
    """Persisted sync settings (used by UI)."""
    return get_sync_preferences(settings.data_dir)


@app.post("/api/immich/sync")
def sync_to_immich(req: ImmichSyncRequest | None = None):
    """Startet den Immich-Sync im Hintergrund. Fortschritt per GET /api/immich/sync-progress."""
    prefs = get_sync_preferences(settings.data_dir)
    combine = prefs.get("combine_memories_overlay", False)
    locked = bool(prefs.get("memories_overlay_mode_locked", False))
    if req and (req.combine_memories_overlay is not None) and not locked:
        combine = bool(req.combine_memories_overlay)
        set_sync_preferences(settings.data_dir, combine_memories_overlay=combine)

    with _sync_lock:
        if _sync_state["phase"] not in ("idle", "done", "error"):
            raise HTTPException(status_code=409, detail="Sync läuft bereits.")
        _sync_state["phase"] = "starting"
        _sync_state["result"] = None
        _sync_state["error"] = None
    thread = threading.Thread(
        target=_run_sync_in_background,
        kwargs={"combine_memories_overlay": combine},
        daemon=True,
    )
    thread.start()
    return {"started": True, "message": "Sync gestartet."}


@app.get("/api/immich/status")
def immich_status():
    """Check if Immich is auto-configured and reachable."""
    from .immich_sync import ImmichClient, _load_config, _validate_api_key

    config = _load_config(settings.data_dir)
    api_key = config.get("api_key", "")
    configured = bool(api_key)

    reachable = False
    try:
        import httpx as _httpx
        r = _httpx.get(f"{settings.immich_url}/api/server/ping", timeout=5)
        reachable = r.status_code == 200
    except Exception:
        pass

    key_valid = False
    if configured and reachable:
        key_valid = _validate_api_key(settings.immich_url, api_key)

    return {
        "configured": configured,
        "reachable": reachable,
        "key_valid": key_valid,
        "url": settings.immich_url,
    }


@app.get("/api/immich/credentials")
def immich_credentials():
    """Return auto-generated Immich login credentials."""
    creds = get_immich_credentials(settings.data_dir)
    if not creds:
        return {"configured": False}
    return creds


# ------------------------------------------------------------------
# Stats
# ------------------------------------------------------------------

@app.get("/api/stats")
def get_stats(
    chat_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    from_ts: Optional[str] = None,
    to_ts: Optional[str] = None,
    group_by: str = "day",
):
    if group_by not in ("day", "month"):
        group_by = "day"
    if chat_id and not store.get_chat(chat_id):
        raise HTTPException(status_code=404, detail="Chat not found")
    return store.get_stats(chat_id=chat_id, thread_id=thread_id, from_ts=from_ts, to_ts=to_ts, group_by=group_by)

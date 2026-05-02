"""Immich bootstrap and full sync orchestration."""

from __future__ import annotations

import logging
import os
import time

import httpx

from .immich_client import ImmichClient, TIMEOUT
from .config import settings as app_settings
from .immich_config import (
    CONFIG_KEY_COMBINE_OVERLAY,
    CONFIG_KEY_COMBINE_OVERLAY_VIDEOS,
    CONFIG_KEY_EXTERNAL_API_KEY,
    CONFIG_KEY_EXTERNAL_ENABLED,
    CONFIG_KEY_EXTERNAL_URL,
    CONFIG_KEY_MEMORIES_OVERLAY_LOCKED,
    _external_immich_active,
    _load_config,
    _save_config,
    get_effective_immich_url,
)
from .immich_models import SyncResult
from .immich_sections import sync_chat_media, sync_memories, sync_shared_story

logger = logging.getLogger(__name__)


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


def _bootstrap_immich(base_url: str, admin_email: str, admin_password: str) -> dict:
    """Create admin, login, generate API key. Returns config dict."""
    c = httpx.Client(base_url=base_url, timeout=TIMEOUT)
    try:
        signup = c.post("/api/auth/admin-sign-up", json={
            "email": admin_email,
            "password": admin_password,
            "name": "Admin",
        })
        if signup.status_code == 201:
            logger.info("Immich Admin-Account erstellt")
        elif signup.status_code == 400:
            logger.info("Immich Admin existiert bereits")
        else:
            logger.warning("Admin sign-up: %s %s", signup.status_code, signup.text[:200])

        login = c.post("/api/auth/login", json={
            "email": admin_email,
            "password": admin_password,
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
            "admin_email": admin_email,
            "admin_password": admin_password,
            "api_key": api_key,
        }
    finally:
        c.close()


def ensure_immich_ready(data_dir: str) -> tuple[str, str]:
    """
    Ensure Immich is reachable and we have a valid API key.
    Returns (base_url, api_key).

    External mode: uses saved URL + API key only (no auto-bootstrap).
    Bundled mode: auto-creates admin + key when missing.
    """
    immich_url = get_effective_immich_url(data_dir)
    if not _wait_for_immich(immich_url):
        raise RuntimeError(
            f"Immich nicht erreichbar unter {immich_url} nach 90s Wartezeit."
        )

    config = _load_config(data_dir)

    if _external_immich_active(config):
        api_key = (config.get(CONFIG_KEY_EXTERNAL_API_KEY) or "").strip()
        if not api_key:
            raise RuntimeError(
                "Externe Immich-Instanz: kein API-Key gespeichert. Bitte unter Erweitert speichern."
            )
        if not _validate_api_key(immich_url, api_key):
            raise RuntimeError(
                f"Externer Immich API-Key ungültig oder abgelaufen (URL: {immich_url})."
            )
        logger.info("Externe Immich-Instanz: API-Key gueltig (%s)", immich_url)
        return immich_url, api_key

    api_key = config.get("api_key", "")

    if api_key and _validate_api_key(immich_url, api_key):
        logger.info("Gespeicherter Immich API-Key ist gueltig")
        return immich_url, api_key

    old_cfg = dict(config)
    logger.info("Kein gueltiger API-Key vorhanden, starte Immich-Bootstrap...")
    config = _bootstrap_immich(
        immich_url,
        app_settings.immich_admin_email,
        app_settings.immich_admin_password,
    )
    preserve_keys = (
        CONFIG_KEY_COMBINE_OVERLAY,
        CONFIG_KEY_COMBINE_OVERLAY_VIDEOS,
        CONFIG_KEY_MEMORIES_OVERLAY_LOCKED,
        CONFIG_KEY_EXTERNAL_ENABLED,
        CONFIG_KEY_EXTERNAL_URL,
        CONFIG_KEY_EXTERNAL_API_KEY,
    )
    for k in preserve_keys:
        if k in old_cfg:
            config[k] = old_cfg[k]
    _save_config(data_dir, config)
    return immich_url, config["api_key"]


def run_full_sync(
    data_dir: str,
    export_root: str,
    sqlite_path: str,
    cache_sqlite_path: str,
    progress_callback=None,
    *,
    combine_memories_overlay: bool = False,
    combine_memories_overlay_videos: bool = False,
) -> SyncResult:
    """Run the complete sync: auto-bootstrap Immich (unless external mode), then upload."""
    result = SyncResult()
    eff_url = get_effective_immich_url(data_dir)
    logger.info(
        "Immich full sync started (combine_memories_overlay=%s, combine_memories_overlay_videos=%s, immich_url=%s)",
        combine_memories_overlay,
        combine_memories_overlay_videos,
        eff_url,
    )

    try:
        immich_url, api_key = ensure_immich_ready(data_dir)
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
            combine_overlay_videos=combine_memories_overlay_videos,
        )

        shared_story_dir = os.path.join(export_root, "shared_story")
        shared_story_json = os.path.join(export_root, "json", "shared_story.json")
        sync_shared_story(
            client,
            data_dir=data_dir,
            shared_story_dir=shared_story_dir,
            shared_story_json_path=shared_story_json,
            cache_sqlite_path=cache_sqlite_path,
            result=result,
            progress_callback=progress_callback,
        )

        chat_media_dir = os.path.join(export_root, "chat_media")
        sync_chat_media(
            client,
            data_dir=data_dir,
            chat_media_dir=chat_media_dir,
            app_sqlite_path=sqlite_path,
            cache_sqlite_path=cache_sqlite_path,
            result=result,
            progress_callback=progress_callback,
        )
    finally:
        client.close()

    logger.info(
        "Immich full sync finished (memories: uploaded=%d skipped=%d errors=%d, shared_story: uploaded=%d skipped=%d, chat_media: uploaded=%d skipped=%d, albums_created=%d, errors=%d)",
        result.memories_uploaded,
        result.memories_skipped,
        result.memories_upload_errors,
        result.shared_story_uploaded,
        result.shared_story_skipped,
        result.chat_media_uploaded,
        result.chat_media_skipped,
        result.albums_created,
        len(result.errors),
    )
    return result

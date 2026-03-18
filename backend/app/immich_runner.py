"""Immich bootstrap and full sync orchestration."""

from __future__ import annotations

import logging
import os
import time

import httpx

from .immich_client import ImmichClient, TIMEOUT
from .immich_config import (
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    CONFIG_KEY_COMBINE_OVERLAY,
    CONFIG_KEY_MEMORIES_OVERLAY_LOCKED,
    _load_config,
    _save_config,
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
    """Ensure Immich is running and configured. Returns a valid API key."""
    if not _wait_for_immich(immich_url):
        raise RuntimeError(
            f"Immich nicht erreichbar unter {immich_url} nach 90s Wartezeit."
        )

    config = _load_config(data_dir)
    api_key = config.get("api_key", "")

    if api_key and _validate_api_key(immich_url, api_key):
        logger.info("Gespeicherter Immich API-Key ist gueltig")
        return api_key

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
    logger.info(
        "Immich full sync started (combine_memories_overlay=%s, immich_url=%s)",
        combine_memories_overlay,
        immich_url,
    )

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

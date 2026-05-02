"""Immich config and sync preferences."""

from __future__ import annotations

import json
import os

from .config import settings

CONFIG_FILENAME = "immich_config.json"
CONFIG_KEY_COMBINE_OVERLAY = "combine_memories_overlay"
CONFIG_KEY_COMBINE_OVERLAY_VIDEOS = "combine_memories_overlay_videos"
CONFIG_KEY_MEMORIES_OVERLAY_LOCKED = "memories_overlay_mode_locked"
CONFIG_KEY_EXTERNAL_ENABLED = "external_immich_enabled"
CONFIG_KEY_EXTERNAL_URL = "external_immich_url"
CONFIG_KEY_EXTERNAL_API_KEY = "external_immich_api_key"


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
    combine_overlay = bool(cfg.get(CONFIG_KEY_COMBINE_OVERLAY, False))
    combine_overlay_videos_raw = cfg.get(CONFIG_KEY_COMBINE_OVERLAY_VIDEOS, None)
    locked = bool(cfg.get(CONFIG_KEY_MEMORIES_OVERLAY_LOCKED, False))

    # Backward-compat migration:
    # Older configs can be locked already but may not contain the new video-overlay flag.
    # Use False as safe default (video overlay should remain opt-in), then persist once.
    if combine_overlay_videos_raw is None and locked:
        cfg[CONFIG_KEY_COMBINE_OVERLAY_VIDEOS] = False
        _save_config(data_dir, cfg)
        combine_overlay_videos = bool(cfg[CONFIG_KEY_COMBINE_OVERLAY_VIDEOS])
    else:
        combine_overlay_videos = bool(combine_overlay_videos_raw)

    return {
        "combine_memories_overlay": combine_overlay,
        "combine_memories_overlay_videos": combine_overlay_videos,
        "memories_overlay_mode_locked": locked,
    }


def set_sync_preferences(
    data_dir: str,
    *,
    combine_memories_overlay: bool,
    combine_memories_overlay_videos: bool = False,
) -> dict:
    """Persist sync preferences (kept alongside Immich bootstrap config)."""
    cfg = _load_config(data_dir)
    if bool(cfg.get(CONFIG_KEY_MEMORIES_OVERLAY_LOCKED, False)):
        return get_sync_preferences(data_dir)

    cfg[CONFIG_KEY_COMBINE_OVERLAY] = bool(combine_memories_overlay)
    cfg[CONFIG_KEY_COMBINE_OVERLAY_VIDEOS] = bool(combine_memories_overlay_videos and combine_memories_overlay)
    cfg[CONFIG_KEY_MEMORIES_OVERLAY_LOCKED] = True
    _save_config(data_dir, cfg)
    return get_sync_preferences(data_dir)


def _external_immich_active(cfg: dict) -> bool:
    """True when UI/API treat external Immich as selected (enabled flag + non-empty URL)."""
    return bool(cfg.get(CONFIG_KEY_EXTERNAL_ENABLED)) and bool(
        (cfg.get(CONFIG_KEY_EXTERNAL_URL) or "").strip()
    )


def external_immich_enabled(data_dir: str) -> bool:
    return _external_immich_active(_load_config(data_dir))


def get_effective_immich_url(data_dir: str) -> str:
    """Bundled IMMICH_URL from env, or user-configured external base URL."""
    cfg = _load_config(data_dir)
    if _external_immich_active(cfg):
        return (cfg.get(CONFIG_KEY_EXTERNAL_URL) or "").strip().rstrip("/")
    return settings.immich_url.rstrip("/")


def get_external_settings_public(data_dir: str) -> dict:
    """Safe fields for the UI (no API key)."""
    cfg = _load_config(data_dir)
    enabled = bool(cfg.get(CONFIG_KEY_EXTERNAL_ENABLED))
    url = (cfg.get(CONFIG_KEY_EXTERNAL_URL) or "").strip()
    key_present = bool((cfg.get(CONFIG_KEY_EXTERNAL_API_KEY) or "").strip())
    return {
        "external_immich_enabled": enabled and bool(url),
        "external_immich_url": url,
        "api_key_configured": key_present,
    }


def save_external_immich_settings(
    data_dir: str,
    *,
    enabled: bool,
    external_immich_url: str | None,
    external_immich_api_key: str | None,
) -> dict:
    """
    Persist external Immich target. If api_key is None or blank, keep the stored key.
    """
    cfg = _load_config(data_dir)
    url = (external_immich_url or "").strip().rstrip("/")

    if not enabled:
        cfg[CONFIG_KEY_EXTERNAL_ENABLED] = False
        cfg[CONFIG_KEY_EXTERNAL_URL] = ""
        cfg.pop(CONFIG_KEY_EXTERNAL_API_KEY, None)
        _save_config(data_dir, cfg)
        return get_external_settings_public(data_dir)

    if not url:
        raise ValueError("external_immich_url ist erforderlich, wenn die externe Immich-Instanz aktiv ist.")

    cfg[CONFIG_KEY_EXTERNAL_ENABLED] = True
    cfg[CONFIG_KEY_EXTERNAL_URL] = url

    key_in = external_immich_api_key
    if key_in is not None and str(key_in).strip():
        cfg[CONFIG_KEY_EXTERNAL_API_KEY] = str(key_in).strip()
    elif not (cfg.get(CONFIG_KEY_EXTERNAL_API_KEY) or "").strip():
        raise ValueError(
            "API-Key ist erforderlich. Erstelle einen Schlüssel in Immich (Konto → API-Schlüssel)."
        )

    _save_config(data_dir, cfg)
    return get_external_settings_public(data_dir)


def get_immich_credentials(data_dir: str) -> dict | None:
    """Return saved Immich credentials, or None."""
    config = _load_config(data_dir)
    if _external_immich_active(config):
        return {
            "configured": True,
            "external": True,
            "external_url": (config.get(CONFIG_KEY_EXTERNAL_URL) or "").strip(),
        }
    if config.get("api_key"):
        return {
            "admin_email": config.get("admin_email", settings.immich_admin_email),
            "admin_password": config.get("admin_password", settings.immich_admin_password),
            "configured": True,
            "external": False,
        }
    return None

"""Immich config and sync preferences."""

from __future__ import annotations

import json
import os

ADMIN_EMAIL = "admin@snapchats.local"
ADMIN_PASSWORD = "snapchats-admin-2026"
CONFIG_FILENAME = "immich_config.json"
CONFIG_KEY_COMBINE_OVERLAY = "combine_memories_overlay"
CONFIG_KEY_MEMORIES_OVERLAY_LOCKED = "memories_overlay_mode_locked"


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
    if bool(cfg.get(CONFIG_KEY_MEMORIES_OVERLAY_LOCKED, False)):
        return get_sync_preferences(data_dir)

    cfg[CONFIG_KEY_COMBINE_OVERLAY] = bool(combine_memories_overlay)
    cfg[CONFIG_KEY_MEMORIES_OVERLAY_LOCKED] = True
    _save_config(data_dir, cfg)
    return get_sync_preferences(data_dir)


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

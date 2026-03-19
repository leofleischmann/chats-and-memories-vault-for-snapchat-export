"""Immich config and sync preferences."""

from __future__ import annotations

import json
import os

from .config import settings

CONFIG_FILENAME = "immich_config.json"
CONFIG_KEY_COMBINE_OVERLAY = "combine_memories_overlay"
CONFIG_KEY_COMBINE_OVERLAY_VIDEOS = "combine_memories_overlay_videos"
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


def get_immich_credentials(data_dir: str) -> dict | None:
    """Return saved Immich credentials, or None."""
    config = _load_config(data_dir)
    if config.get("api_key"):
        return {
            "admin_email": config.get("admin_email", settings.immich_admin_email),
            "admin_password": config.get("admin_password", settings.immich_admin_password),
            "configured": True,
        }
    return None

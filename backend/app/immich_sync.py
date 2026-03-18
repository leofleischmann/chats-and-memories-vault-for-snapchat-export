"""Sync chat media and memories to Immich via its API.

Facade: re-exports from modular subpackages for backward compatibility.
"""

from __future__ import annotations

from .immich_client import ImmichClient
from .immich_config import _load_config, get_immich_credentials, get_sync_preferences, set_sync_preferences
from .immich_overlay import MEMORY_MAIN_RE, MEMORY_OVERLAY_RE, _combine_main_and_overlay_image
from .immich_runner import ensure_immich_ready, run_full_sync, _validate_api_key

__all__ = [
    "MEMORY_MAIN_RE",
    "MEMORY_OVERLAY_RE",
    "ImmichClient",
    "_combine_main_and_overlay_image",
    "_load_config",
    "_validate_api_key",
    "ensure_immich_ready",
    "get_immich_credentials",
    "get_sync_preferences",
    "run_full_sync",
    "set_sync_preferences",
]

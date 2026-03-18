"""Data models for Immich sync."""

from __future__ import annotations

from dataclasses import dataclass, field


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

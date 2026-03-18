from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator, Optional


UTC_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC$")
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heif"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
AUDIO_EXTS = {".aac", ".m4a", ".mp3", ".ogg", ".wav", ".opus"}
MEDIA_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def parse_utc_timestamp(text: str) -> Optional[str]:
    text = (text or "").strip()
    if not text:
        return None
    if not UTC_TS_RE.match(text):
        return None
    dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Message:
    message_id: str
    chat_id: str
    chat_title: str
    ts_utc: Optional[str]
    sender: Optional[str]
    is_sender: bool
    type: str
    text: str
    ordinal_in_chat: int
    is_saved: bool
    media_id: Optional[str]


@dataclass(frozen=True)
class Snap:
    snap_id: str
    thread_id: str
    thread_title: Optional[str]
    sender: Optional[str]
    is_sender: bool
    type: str
    ts_utc: Optional[str]


# ---------------------------------------------------------------------------
# JSON-based chat import
# ---------------------------------------------------------------------------

def load_chats_from_json(json_path: str) -> dict[str, list[dict]]:
    """Load chat_history.json: keys are chat UUIDs, values are message lists."""
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def iter_messages_for_chat_json(
    chat_id: str,
    raw_messages: list[dict],
) -> Iterator[Message]:
    """Yields Message objects from a JSON chat message list.

    Messages in the JSON are ordered newest-first, so we reverse for
    chronological ordinal assignment.
    """
    title = ""
    if raw_messages:
        title = raw_messages[0].get("Conversation Title") or ""
    if not title:
        title = chat_id

    sorted_msgs = list(reversed(raw_messages))

    for ordinal, m in enumerate(sorted_msgs):
        sender = m.get("From") or None
        is_sender = bool(m.get("IsSender", False))
        msg_type = (m.get("Media Type") or "UNKNOWN").strip()
        text = m.get("Content") or ""
        ts_raw = m.get("Created") or ""
        ts_utc = parse_utc_timestamp(ts_raw)
        is_saved = bool(m.get("IsSaved", False))
        media_id = (m.get("Media IDs") or "").strip() or None

        msg_key = json.dumps(
            {
                "chat_id": chat_id,
                "ts_utc": ts_utc,
                "sender": sender,
                "type": msg_type,
                "text": text,
                "ordinal": ordinal,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        message_id = _sha1(msg_key)

        yield Message(
            message_id=message_id,
            chat_id=chat_id,
            chat_title=title,
            ts_utc=ts_utc,
            sender=sender,
            is_sender=is_sender,
            type=msg_type,
            text=text,
            ordinal_in_chat=ordinal,
            is_saved=is_saved,
            media_id=media_id,
        )


# ---------------------------------------------------------------------------
# JSON-based snap import
# ---------------------------------------------------------------------------

def load_snaps_from_json(json_path: str) -> dict[str, list[dict]]:
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def iter_snaps_for_thread_json(
    thread_id: str,
    raw_snaps: list[dict],
) -> Iterator[Snap]:
    sorted_snaps = list(reversed(raw_snaps))

    for ordinal, s in enumerate(sorted_snaps):
        sender = s.get("From") or None
        is_sender = bool(s.get("IsSender", False))
        snap_type = (s.get("Media Type") or "UNKNOWN").strip().upper()
        ts_raw = s.get("Created") or ""
        ts_utc = parse_utc_timestamp(ts_raw)
        title = s.get("Conversation Title") or None

        snap_key = json.dumps(
            {
                "thread_id": thread_id,
                "ts_utc": ts_utc,
                "sender": sender,
                "type": snap_type,
                "ordinal": ordinal,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        snap_id = _sha1(snap_key)

        yield Snap(
            snap_id=snap_id,
            thread_id=thread_id,
            thread_title=title,
            sender=sender,
            is_sender=is_sender,
            type=snap_type,
            ts_utc=ts_utc,
        )


# ---------------------------------------------------------------------------
# Media file scanning + lookup index
# ---------------------------------------------------------------------------

def scan_chat_media(chat_media_dir: str) -> list[dict]:
    """Scan only real chat media files (those with a b~ media_id)."""
    if not os.path.isdir(chat_media_dir):
        return []
    results: list[dict] = []
    for name in os.listdir(chat_media_dir):
        path = os.path.join(chat_media_dir, name)
        if not os.path.isfile(path):
            continue
        media_id = _extract_media_id_from_filename(name)
        if not media_id:
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext in IMAGE_EXTS:
            media_type = "image"
        elif ext in AUDIO_EXTS:
            media_type = "audio"
        elif ext in VIDEO_EXTS:
            media_type = "video"
        else:
            media_type = "other"
        date_match = MEDIA_DATE_RE.match(name)
        file_date = date_match.group(1) if date_match else None

        results.append({
            "filename": name,
            "file_date": file_date,
            "extension": ext.lstrip("."),
            "media_type": media_type,
            "media_id": media_id,
        })
    return results


HASH_ID_RE = re.compile(r"^[0-9a-f]{32}$")
MEMORY_PREFIXES = ("media~", "overlay~", "thumbnail~", "metadata~")


def _extract_media_id_from_filename(filename: str) -> Optional[str]:
    """Extract the media identifier from a chat_media filename.

    Supports two formats:
    - b~ IDs:   DATE_b~BASE64ENCODED...EXT
    - Hash IDs: DATE_HEXHASH.EXT  (32-char lowercase hex)
    """
    stem = os.path.splitext(filename)[0]
    idx = stem.find("_b~")
    if idx != -1:
        return stem[idx + 1:]
    parts = stem.split("_", 1)
    if len(parts) == 2:
        candidate = parts[1]
        if any(candidate.startswith(p) for p in MEMORY_PREFIXES):
            return None
        if HASH_ID_RE.match(candidate):
            return candidate
    return None


def build_media_id_lookup(chat_media_dir: str) -> dict[str, str]:
    """Returns {media_id: filename} for quick lookup."""
    lookup: dict[str, str] = {}
    if not os.path.isdir(chat_media_dir):
        return lookup
    for name in os.listdir(chat_media_dir):
        mid = _extract_media_id_from_filename(name)
        if mid:
            lookup[mid] = name
    return lookup


def load_friend_display_names(json_path: str) -> dict[str, str]:
    """Load friends.json and return {username: display_name} lookup."""
    if not os.path.exists(json_path):
        return {}
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    lookup: dict[str, str] = {}
    for list_key in ("Friends", "Friend Requests Sent", "Blocked Users", "Deleted Friends"):
        for entry in data.get(list_key, []):
            username = (entry.get("Username") or "").strip()
            display = (entry.get("Display Name") or "").strip()
            if username and display and username not in lookup:
                lookup[username] = display
    return lookup

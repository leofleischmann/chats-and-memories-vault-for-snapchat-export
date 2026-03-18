"""Shared utilities for Immich sync."""

from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone

DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()


def _file_fingerprint(path: str) -> tuple[int, int]:
    st = os.stat(path)
    mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000))
    return int(st.st_size), int(mtime_ns)


def _sha256_file(path: str, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _parse_date_from_filename(filename: str) -> str | None:
    m = DATE_PREFIX_RE.match(filename)
    if m:
        return m.group(1) + "T12:00:00Z"
    return None


def _parse_memory_location(loc_str: str) -> tuple[float | None, float | None]:
    """Parse 'Latitude, Longitude: 47.504, 9.746' format."""
    if not loc_str or "Latitude" not in loc_str:
        return None, None
    try:
        parts = loc_str.split(":")[1].strip().split(",")
        return float(parts[0].strip()), float(parts[1].strip())
    except (IndexError, ValueError):
        return None, None

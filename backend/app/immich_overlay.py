"""Overlay indexing and main+overlay image combining for Memories."""

from __future__ import annotations

import logging
import os
import re

from .immich_heic import _maybe_register_heif_plugin
from .immich_util import _sha1

logger = logging.getLogger(__name__)

MEMORY_MAIN_RE = re.compile(r"-main\.\w+$")
MEMORY_OVERLAY_RE = re.compile(r"-overlay\.\w+$", re.IGNORECASE)
COMBINED_MEMORIES_DIRNAME = "immich_combined_memories"


def _find_overlay_for_main(memories_dir: str, main_fname: str) -> str | None:
    """Try to find a matching overlay file for a given main memory filename."""
    base = os.path.splitext(main_fname)[0]
    prefix = base[:-5] if base.lower().endswith("-main") else base

    try:
        candidates = [
            f
            for f in os.listdir(memories_dir)
            if os.path.isfile(os.path.join(memories_dir, f))
            and f.lower().startswith(prefix.lower())
            and MEMORY_OVERLAY_RE.search(f)
        ]
    except Exception:
        return None

    if not candidates:
        return None
    main_ext = os.path.splitext(main_fname)[1].lower()
    same_ext = [c for c in candidates if os.path.splitext(c)[1].lower() == main_ext]
    pick = sorted(same_ext or candidates)[0]
    return os.path.join(memories_dir, pick)


def _build_overlay_index(memories_dir: str) -> dict[str, list[str]]:
    """Pre-index overlays in the memories directory for O(1) lookups."""
    idx: dict[str, list[str]] = {}
    try:
        for f in os.listdir(memories_dir):
            if not MEMORY_OVERLAY_RE.search(f):
                continue
            if not os.path.isfile(os.path.join(memories_dir, f)):
                continue
            base = os.path.splitext(f)[0]
            prefix = base[:-8] if base.lower().endswith("-overlay") else base
            idx.setdefault(prefix.lower(), []).append(f)
    except Exception:
        return {}

    for k in list(idx.keys()):
        idx[k] = sorted(idx[k])
    return idx


def _find_overlay_for_main_indexed(
    memories_dir: str, main_fname: str, overlay_idx: dict[str, list[str]]
) -> str | None:
    """Same matching logic as _find_overlay_for_main(), but via pre-built index."""
    base = os.path.splitext(main_fname)[0]
    prefix = base[:-5] if base.lower().endswith("-main") else base
    candidates = overlay_idx.get(prefix.lower(), [])
    if not candidates:
        return None
    main_ext = os.path.splitext(main_fname)[1].lower()
    same_ext = [c for c in candidates if os.path.splitext(c)[1].lower() == main_ext]
    pick = sorted(same_ext or candidates)[0]
    return os.path.join(memories_dir, pick)


def _combine_main_and_overlay_image(
    *,
    data_dir: str,
    main_path: str,
    overlay_path: str,
) -> str | None:
    """Create (or reuse) a cached combined image file and return its path. Always outputs JPEG."""
    try:
        from PIL import Image  # type: ignore
    except Exception as e:
        logger.warning("Pillow not available, cannot combine overlay: %s", e)
        return None

    try:
        main_stat = os.stat(main_path)
        overlay_stat = os.stat(overlay_path)
    except OSError:
        return None

    main_name = os.path.basename(main_path)
    overlay_name = os.path.basename(overlay_path)
    out_dir = os.path.join(data_dir, COMBINED_MEMORIES_DIRNAME)
    os.makedirs(out_dir, exist_ok=True)

    key = _sha1(
        f"combine:{main_name}:{main_stat.st_size}:{int(main_stat.st_mtime)}:"
        f"{overlay_name}:{overlay_stat.st_size}:{int(overlay_stat.st_mtime)}"
    )
    out_path = os.path.join(out_dir, f"{key}.jpg")

    if os.path.exists(out_path):
        return out_path

    if not _maybe_register_heif_plugin():
        pass  # Proceed anyway; Pillow may still open non-HEIC files

    try:
        with Image.open(main_path) as im_main:
            main_rgba = im_main.convert("RGBA")
            with Image.open(overlay_path) as im_ov:
                ov_rgba = im_ov.convert("RGBA")
                if ov_rgba.size != main_rgba.size:
                    ov_rgba = ov_rgba.resize(main_rgba.size, Image.Resampling.LANCZOS)
                combined = Image.alpha_composite(main_rgba, ov_rgba).convert("RGB")

        tmp_path = out_path + ".tmp.jpg"
        combined.save(tmp_path, "JPEG", quality=95)
        os.replace(tmp_path, out_path)
        return out_path
    except Exception as e:
        logger.warning("Failed to combine overlay for %s: %s", main_name, e)
        try:
            if os.path.exists(out_path + ".tmp.jpg"):
                os.remove(out_path + ".tmp.jpg")
        except Exception:
            pass
        return None

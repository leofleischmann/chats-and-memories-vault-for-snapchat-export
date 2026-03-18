"""HEIC/HEIF conversion to JPEG for Immich upload."""

from __future__ import annotations

import logging
import os

from .immich_util import _sha1

logger = logging.getLogger(__name__)

HEIC_CONVERTED_DIRNAME = "immich_heic_converted"

_HEIF_PLUGIN_REGISTERED = False


def _maybe_register_heif_plugin() -> bool:
    """Lazy register pillow-heif so Pillow can open HEIC/HEIF. Returns True if successful."""
    global _HEIF_PLUGIN_REGISTERED
    if _HEIF_PLUGIN_REGISTERED:
        return True
    try:
        from pillow_heif import register_heif_opener

        register_heif_opener()
        _HEIF_PLUGIN_REGISTERED = True
        return True
    except Exception as e:
        logger.debug("pillow-heif not available, HEIC/HEIF conversion disabled: %s", e)
        return False


def _is_heic_heif(path: str) -> bool:
    """Return True if the file has .heic or .heif extension."""
    ext = os.path.splitext(path)[1].lower()
    return ext in (".heic", ".heif")


def _convert_heic_to_jpeg(
    src_path: str,
    out_dir: str,
    *,
    scope: str,
    rel_path: str,
    size_bytes: int,
    mtime_ns: int,
) -> str | None:
    """
    Convert HEIC/HEIF to JPEG. Returns path to converted file, or None on failure (fallback to original).
    Output path is deterministic and cached for reuse.
    """
    if not _maybe_register_heif_plugin():
        return None
    try:
        from PIL import Image  # type: ignore
    except Exception as e:
        logger.warning("Pillow not available for HEIC conversion: %s", e)
        return None

    try:
        st = os.stat(src_path)
    except OSError:
        return None

    key = _sha1(
        f"heic2jpeg:{src_path}:{st.st_size}:{int(st.st_mtime)}:"
        f"{scope}:{rel_path}:{size_bytes}:{mtime_ns}"
    )
    out_path = os.path.join(out_dir, f"{key}.jpg")
    logger.debug(
        "HEIC/HEIF conversion attempt (scope=%s, src=%s, out=%s)",
        scope,
        os.path.basename(src_path),
        os.path.basename(out_path),
    )
    if os.path.exists(out_path):
        return out_path

    os.makedirs(out_dir, exist_ok=True)
    try:
        with Image.open(src_path) as im:
            rgb = im.convert("RGB")
        tmp_path = out_path + ".tmp.jpg"
        rgb.save(tmp_path, "JPEG", quality=95)
        os.replace(tmp_path, out_path)
        logger.debug(
            "HEIC/HEIF conversion done (scope=%s, out=%s)",
            scope,
            os.path.basename(out_path),
        )
        return out_path
    except Exception as e:
        logger.warning("Failed to convert HEIC/HEIF to JPEG %s: %s", src_path, e)
        try:
            if os.path.exists(out_path + ".tmp.jpg"):
                os.remove(out_path + ".tmp.jpg")
        except Exception:
            pass
        return None

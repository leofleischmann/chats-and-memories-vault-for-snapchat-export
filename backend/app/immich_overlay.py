"""Overlay indexing and main+overlay image combining for Memories."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from functools import lru_cache

from .immich_heic import _maybe_register_heif_plugin
from .immich_util import _sha1

logger = logging.getLogger(__name__)

MEMORY_MAIN_RE = re.compile(r"-main\.\w+$")
MEMORY_OVERLAY_RE = re.compile(r"-overlay\.\w+$", re.IGNORECASE)
COMBINED_MEMORIES_DIRNAME = "immich_combined_memories"

# Basic file type heuristics for overlay combining.
_VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif"}


def _is_video_path(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in _VIDEO_EXTS


def _is_image_path(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in _IMAGE_EXTS


@lru_cache(maxsize=1)
def _has_nvenc_support() -> bool:
    """Best-effort check whether ffmpeg can encode with h264_nvenc."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    if not (
        os.path.exists("/dev/nvidia0")
        or os.path.exists("/dev/dri/renderD128")
        or os.path.exists("/dev/dxg")
    ):
        return False
    try:
        proc = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], check=False, capture_output=True, text=True)
        text = (proc.stdout or "") + "\n" + (proc.stderr or "")
        return "h264_nvenc" in text
    except Exception:
        return False


def _video_encode_args() -> list[str]:
    """Return video encoder args. Prefer GPU (NVENC) when available."""
    if _has_nvenc_support():
        # cq is the NVENC quality-style control (lower = higher quality).
        return ["-c:v", "h264_nvenc", "-preset", "p1", "-cq", "23"]
    return ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "23"]


def _probe_media_size(path: str) -> tuple[int, int] | None:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        proc = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=p=0:s=x",
                path,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            return None
        txt = (proc.stdout or "").strip()
        if "x" not in txt:
            return None
        w_s, h_s = txt.split("x", 1)
        return int(w_s), int(h_s)
    except Exception:
        return None


def _combine_main_and_overlay_video(
    *,
    data_dir: str,
    main_path: str,
    overlay_path: str,
    main_sha256: str | None = None,
    overlay_sha256: str | None = None,
) -> str | None:
    """
    Combine overlay into a main *video*.

    Notes:
    - Uses ffmpeg overlay filter (fastest generic approach).
    - Supports overlay images (single PNG/WebP/etc) and (best-effort) overlay videos.
    - Always outputs .mp4.
    - If ffmpeg is missing or conversion fails, returns None (caller falls back to plain main).
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        logger.warning("ffmpeg not available; cannot combine overlay for video %s", os.path.basename(main_path))
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

    # Prefer content-based keys (stable across incremental runs).
    if main_sha256 and overlay_sha256:
        overlay_is_image = _is_image_path(overlay_path) and not _is_video_path(overlay_path)
        key = _sha1(
            f"combine_video_sha:{main_sha256}:{overlay_sha256}:"
            f"{os.path.splitext(main_name)[1].lower()}:{os.path.splitext(overlay_name)[1].lower()}:"
            f"{'img' if overlay_is_image else 'vid'}"
        )
    else:
        # Fallback: old behavior (mtime/size-based).
        key = _sha1(
            f"combine_video:{main_name}:{main_stat.st_size}:{int(main_stat.st_mtime)}:"
            f"{overlay_name}:{overlay_stat.st_size}:{int(overlay_stat.st_mtime)}"
        )
    out_path = os.path.join(out_dir, f"{key}.mp4")
    if os.path.exists(out_path):
        return out_path

    # Single-frame fast path for video overlays:
    # - Extract one frame from overlay video (prefer frame #1, fallback frame #0)
    # - Loop that image over the full main video duration
    # This avoids processing full overlay video frame-by-frame.
    overlay_filter_fast = (
        "[1:v]format=rgba,colorchannelmixer=aa=1.0[ovrgba];"
        "[0:v][ovrgba]overlay=x=0:y=0:format=auto:shortest=1"
    )
    # Fallback when dimensions differ or fast filter fails.
    overlay_filter_scaled = (
        "[1:v][0:v]scale2ref=w=iw:h=ih[ov][main];"
        "[ov]format=rgba,colorchannelmixer=aa=1.0[ovrgba];"
        "[main][ovrgba]overlay=x=0:y=0:format=auto:shortest=1"
    )

    overlay_is_image = _is_image_path(overlay_path) and not _is_video_path(overlay_path)
    temp_overlay_image_path: str | None = None

    try:
        if not overlay_is_image:
            temp_base = _sha1(
                f"single_frame_overlay:{main_name}:{overlay_name}:{main_stat.st_size}:{overlay_stat.st_size}"
            )
            temp_overlay_image_path = os.path.join(out_dir, f".tmp_overlay_frame_{temp_base}.png")

            def _extract_frame(frame_idx: int) -> bool:
                extract_cmd = [
                    ffmpeg, "-y",
                    "-i", overlay_path,
                    "-vf", f"select=eq(n\\,{frame_idx})",
                    "-vframes", "1",
                    temp_overlay_image_path,
                ]
                proc_extract = subprocess.run(extract_cmd, check=False, capture_output=True, text=True)
                return proc_extract.returncode == 0 and os.path.exists(temp_overlay_image_path)

            # Prefer 2nd frame, fallback to 1st frame if too short/cannot decode frame 1.
            if not _extract_frame(1):
                try:
                    if os.path.exists(temp_overlay_image_path):
                        os.remove(temp_overlay_image_path)
                except Exception:
                    pass
                if not _extract_frame(0):
                    logger.warning(
                        "Failed to extract single-frame overlay for %s from %s",
                        main_name,
                        overlay_name,
                    )
                    return None

            logger.info(
                "Using single-frame fast overlay for video %s (overlay source %s)",
                main_name,
                overlay_name,
            )

        overlay_input = overlay_path if overlay_is_image else temp_overlay_image_path
        if not overlay_input:
            return None

        base_cmd: list[str] = [ffmpeg, "-y", "-i", main_path, "-loop", "1", "-i", overlay_input]
        encode_args = _video_encode_args()
        if encode_args[1] == "h264_nvenc":
            logger.info("Using GPU encoder h264_nvenc for overlay video combine (%s)", main_name)

        def _run_overlay_cmd(filter_expr: str) -> subprocess.CompletedProcess[str]:
            cmd = base_cmd + [
                "-filter_complex",
                filter_expr,
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
            ] + encode_args + [
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "copy",
                out_path,
            ]
            return subprocess.run(cmd, check=False, capture_output=True, text=True)

        # Prevent clipping/offset artifacts: if dimensions differ, use scaled filter directly.
        main_size = _probe_media_size(main_path)
        overlay_size = _probe_media_size(overlay_input)
        prefer_scaled = bool(main_size and overlay_size and main_size != overlay_size)

        if prefer_scaled:
            logger.info(
                "Overlay size differs for %s (main=%s, overlay=%s), using scaled overlay path",
                main_name,
                main_size,
                overlay_size,
            )
            proc = _run_overlay_cmd(overlay_filter_scaled)
        else:
            proc = _run_overlay_cmd(overlay_filter_fast)
            if proc.returncode != 0:
                # Fast filter can still fail for edge-cases. Retry with explicit scale2ref.
                proc = _run_overlay_cmd(overlay_filter_scaled)

        if proc.returncode != 0:
            msg = (proc.stderr or proc.stdout or "").strip()
            logger.warning(
                "Failed to combine overlay video for %s: ffmpeg exit=%s: %s",
                main_name,
                proc.returncode,
                msg[:300],
            )
            try:
                if os.path.exists(out_path):
                    os.remove(out_path)
            except Exception:
                pass
            return None
        return out_path
    except Exception as e:
        logger.warning("Failed to combine overlay video for %s: %s", main_name, e)
        return None
    finally:
        if temp_overlay_image_path:
            try:
                if os.path.exists(temp_overlay_image_path):
                    os.remove(temp_overlay_image_path)
            except Exception:
                pass


def _combine_main_and_overlay_media(
    *,
    data_dir: str,
    main_path: str,
    overlay_path: str,
    main_sha256: str | None = None,
    overlay_sha256: str | None = None,
) -> str | None:
    """Combine main+overlay for either images or videos (fast-path)."""
    if _is_video_path(main_path):
        # Handle video main files via ffmpeg overlay.
        if not _is_video_path(overlay_path) and not _is_image_path(overlay_path):
            return None
        return _combine_main_and_overlay_video(
            data_dir=data_dir,
            main_path=main_path,
            overlay_path=overlay_path,
            main_sha256=main_sha256,
            overlay_sha256=overlay_sha256,
        )
    # Fallback: images (existing codepath)
    return _combine_main_and_overlay_image(
        data_dir=data_dir,
        main_path=main_path,
        overlay_path=overlay_path,
        main_sha256=main_sha256,
        overlay_sha256=overlay_sha256,
    )


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
    main_sha256: str | None = None,
    overlay_sha256: str | None = None,
) -> str | None:
    """Create (or reuse) a cached combined image file and return its path. Always outputs JPEG."""
    # Guard: if main is a video we should never try PIL composite.
    if _is_video_path(main_path):
        return None

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

    if main_sha256 and overlay_sha256:
        key = _sha1(
            f"combine_image_sha:{main_sha256}:{overlay_sha256}:"
            f"{os.path.splitext(main_name)[1].lower()}:{os.path.splitext(overlay_name)[1].lower()}"
        )
    else:
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

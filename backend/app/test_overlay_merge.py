from __future__ import annotations

import os
import sys
from pathlib import Path

# Import helpers from immich_sync; this is a standalone test module and not used by the app.
from .immich_sync import MEMORY_OVERLAY_RE, _combine_main_and_overlay_image


def _pick_first_n_main_files(memories_dir: Path, n: int) -> list[Path]:
    if not memories_dir.is_dir():
        return []
    files: list[Path] = []
    for p in sorted(memories_dir.iterdir(), key=lambda x: x.name.lower()):
        if not p.is_file():
            continue
        name = p.name.lower()
        if "-main." in name and "-overlay." not in name:
            files.append(p)
        if len(files) >= n:
            break
    return files


def _pick_first_n_main_files_with_overlay(memories_dir: Path, n: int, overlay_idx: dict[str, list[str]]) -> list[Path]:
    if not memories_dir.is_dir():
        return []
    files: list[Path] = []
    for p in sorted(memories_dir.iterdir(), key=lambda x: x.name.lower()):
        if not p.is_file():
            continue
        name = p.name
        lower = name.lower()
        if "-main." not in lower or "-overlay." in lower:
            continue
        base = os.path.splitext(name)[0]
        prefix = base[:-5] if base.lower().endswith("-main") else base
        if prefix.lower() not in overlay_idx:
            continue
        files.append(p)
        if len(files) >= n:
            break
    return files


def _index_overlays(memories_dir: Path) -> dict[str, list[str]]:
    """
    Build an index from overlay "prefix" -> list of overlay filenames.
    The prefix logic mirrors immich_sync._find_overlay_for_main:
    - base without extension
    - strip trailing "-overlay" if present (should be)
    """
    idx: dict[str, list[str]] = {}
    if not memories_dir.is_dir():
        return idx
    for p in memories_dir.iterdir():
        if not p.is_file():
            continue
        if not MEMORY_OVERLAY_RE.search(p.name):
            continue
        base = os.path.splitext(p.name)[0]
        prefix = base[:-8] if base.lower().endswith("-overlay") else base
        idx.setdefault(prefix.lower(), []).append(p.name)
    for k in list(idx.keys()):
        idx[k] = sorted(idx[k], key=lambda x: x.lower())
    return idx


def _find_overlay_from_index(memories_dir: Path, main_fname: str, idx: dict[str, list[str]]) -> str | None:
    base = os.path.splitext(main_fname)[0]
    prefix = base[:-5] if base.lower().endswith("-main") else base
    candidates = idx.get(prefix.lower(), [])
    if not candidates:
        return None
    main_ext = os.path.splitext(main_fname)[1].lower()
    same_ext = [c for c in candidates if os.path.splitext(c)[1].lower() == main_ext]
    pick = (same_ext or candidates)[0]
    return str(memories_dir / pick)


def main() -> int:
    export_root = Path(os.getenv("EXPORT_ROOT", "/data/raw_export"))
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    memories_dir = export_root / "memories"

    n = 10
    if len(sys.argv) >= 2:
        try:
            n = max(1, min(200, int(sys.argv[1])))
        except Exception:
            pass

    print(f"[INFO] export_root={export_root}")
    print(f"[INFO] data_dir={data_dir}")
    print(f"[INFO] memories_dir={memories_dir}")

    overlay_idx = _index_overlays(memories_dir)
    print(f"[INFO] indexed overlays: {sum(len(v) for v in overlay_idx.values())}")

    mode = "any"
    if len(sys.argv) >= 3 and sys.argv[2].strip().lower() in {"with-overlay", "with_overlay", "overlay"}:
        mode = "with-overlay"

    if mode == "with-overlay":
        mains = _pick_first_n_main_files_with_overlay(memories_dir, n, overlay_idx)
        print(f"[INFO] testing first {len(mains)} main files (WITH overlay)")
    else:
        mains = _pick_first_n_main_files(memories_dir, n)
        print(f"[INFO] testing first {len(mains)} main files")

    if not mains:
        print(f"[FAIL] no matching main files found in {memories_dir} (mode={mode})")
        return 3

    ok_combined = 0
    ok_no_overlay = 0
    failed = 0

    for i, main_path in enumerate(mains, start=1):
        overlay = _find_overlay_from_index(memories_dir, main_path.name, overlay_idx)
        if not overlay:
            ok_no_overlay += 1
            print(f"[{i:02d}] main={main_path.name}  overlay=NONE  -> OK (no overlay)")
            continue

        out = _combine_main_and_overlay_image(
            data_dir=str(data_dir),
            main_path=str(main_path),
            overlay_path=str(overlay),
        )
        if out and os.path.isfile(out):
            ok_combined += 1
            out_name = os.path.basename(out)
            print(f"[{i:02d}] main={main_path.name}  overlay={os.path.basename(overlay)}  -> OK combined={out_name}")
        else:
            failed += 1
            print(f"[{i:02d}] main={main_path.name}  overlay={os.path.basename(overlay)}  -> FAIL (combine returned None)")

    print("")
    print("[SUMMARY]")
    print(f"- combined_ok: {ok_combined}")
    print(f"- no_overlay_ok: {ok_no_overlay}")
    print(f"- failed: {failed}")
    print(f"- output_dir: {data_dir / 'immich_combined_memories'}")

    return 0 if failed == 0 else 4


if __name__ == "__main__":
    raise SystemExit(main())


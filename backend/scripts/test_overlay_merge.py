from __future__ import annotations

import os
import sys
from pathlib import Path


def _pick_first_n_main_files(memories_dir: Path, n: int) -> list[Path]:
    if not memories_dir.is_dir():
        return []
    files = []
    for p in sorted(memories_dir.iterdir(), key=lambda x: x.name.lower()):
        if not p.is_file():
            continue
        name = p.name.lower()
        if "-main." in name and not "-overlay." in name:
            files.append(p)
        if len(files) >= n:
            break
    return files


def main() -> int:
    # Use same defaults as backend container
    export_root = Path(os.getenv("EXPORT_ROOT", "/data/raw_export"))
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    memories_dir = export_root / "memories"

    n = 10
    if len(sys.argv) >= 2:
        try:
            n = max(1, min(200, int(sys.argv[1])))
        except Exception:
            pass

    try:
        from app.immich_sync import _find_overlay_for_main, _combine_main_and_overlay_image
    except Exception as e:
        print(f"[FAIL] cannot import overlay helpers: {e}")
        return 2

    mains = _pick_first_n_main_files(memories_dir, n)
    if not mains:
        print(f"[FAIL] no main files found in {memories_dir}")
        return 3

    print(f"[INFO] export_root={export_root}")
    print(f"[INFO] data_dir={data_dir}")
    print(f"[INFO] memories_dir={memories_dir}")
    print(f"[INFO] testing first {len(mains)} main files")

    ok_combined = 0
    ok_no_overlay = 0
    failed = 0

    for i, main_path in enumerate(mains, start=1):
        overlay = _find_overlay_for_main(str(memories_dir), main_path.name)
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


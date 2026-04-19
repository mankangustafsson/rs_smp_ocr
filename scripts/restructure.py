"""
Folder restructuring for SMP OCR project.
Renames the 6 raw MinerU output folders into the SMP/sources/<volume>/ tree
expected by scripts/build_*.py.
"""

import argparse
import shutil
from pathlib import Path

MOVES = {
    "SMP-1036.5015.24-04-Band-1": "band-1",
    "SMP-1036.5015.24-04-Band-2": "band-2",
    "SMP-1036.5015.24-04-Band-3": "band-3",
    "SMP-1036.5015.24-04-Band-4": "band-4",
    "smp_08_e": "user-manual",
    "SMP_dat_en": "datasheet",
}

# MinerU writes its results into a backend-specific subfolder. The pipeline
# backend uses `auto/`; the recommended hybrid-auto-engine uses `hybrid_auto/`;
# the pure vlm-auto-engine uses `vlm/`. Downstream build scripts expect
# `auto/`, so any non-`auto/` folder is renamed to `auto/` at the destination.
# Keep in sync with scripts/cleanup_mineru.py:AUTO_SUBDIRS.
AUTO_SUBDIRS = ("auto", "hybrid_auto", "vlm")


def main() -> bool:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--input-dir",
        default="output",
        help="Directory containing the 6 raw MinerU output folders (default: output)",
    )
    ap.add_argument(
        "--output-dir",
        default="sources",
        help="Target directory for the renamed volume folders (default: sources)",
    )
    ap.add_argument(
        "--copy",
        action="store_true",
        help="Copy instead of move (default: move).",
    )
    args = ap.parse_args()

    input_dir = Path(args.input_dir).resolve()
    output_dir = Path(args.output_dir).resolve()

    # 1. Verify all source folders exist
    print("=== Discovery phase ===")
    print(f"input-dir : {input_dir}")
    print(f"output-dir: {output_dir}")
    missing = []
    found_sub: dict[str, str] = {}
    for src_name in MOVES:
        src = input_dir / src_name
        if not src.is_dir():
            print(f"ERROR: Expected folder not found: {src}")
            missing.append(src_name)
            continue
        sub = next((s for s in AUTO_SUBDIRS if (src / s).is_dir()), None)
        if sub is None:
            print(f"ERROR: Missing {'/'.join(AUTO_SUBDIRS)} subfolder in {src}")
            missing.append(src_name)
            continue
        found_sub[src_name] = sub
        print(f"  ok  {src_name}/{sub}/")
    if missing:
        return False
    print(f"\nAll {len(MOVES)} source folders verified")

    # 2. Create target structure
    print("\n=== Creating target structure ===")
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"  ok  {output_dir}")

    # 3. Move (or copy) each folder
    op = "Copying" if args.copy else "Moving"
    print(f"\n=== {op} folders ===")
    for src_name, dst_name in MOVES.items():
        src = input_dir / src_name
        dst = output_dir / dst_name

        if dst.exists():
            print(f"  skip  {dst_name} already exists at destination")
            continue

        print(f"  {op.lower()}  {src_name} -> {dst}")
        if args.copy:
            shutil.copytree(src, dst)
        else:
            shutil.move(src, dst)

        sub = found_sub[src_name]
        if sub != "auto":
            src_sub = dst / sub
            dst_sub = dst / "auto"
            print(f"        rename {sub}/ -> auto/")
            src_sub.rename(dst_sub)

    # 4. Verify final structure
    print("\n=== Verification ===")
    ok = True
    for dst_name in MOVES.values():
        auto_path = output_dir / dst_name / "auto"
        if auto_path.is_dir():
            n = sum(1 for _ in auto_path.iterdir())
            print(f"  ok  {output_dir / dst_name}/auto/ ({n} items)")
        else:
            print(f"  MISSING: {auto_path}")
            ok = False

    print(
        "\n=== Restructuring complete ==="
        if ok
        else "\n=== Restructuring incomplete ==="
    )
    return ok


if __name__ == "__main__":
    try:
        success = main()
        raise SystemExit(0 if success else 1)
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback

        traceback.print_exc()
        raise SystemExit(1) from e

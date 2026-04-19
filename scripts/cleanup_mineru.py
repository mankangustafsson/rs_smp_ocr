"""
Remove MinerU output files that the build pipeline does not need.

Walks <root>/<volume>/<sub>/ and deletes the debug / intermediate artifacts:
  *_middle.json, *_model.json, *_origin.pdf, *_layout.pdf, *_span.pdf,
  *_content_list_v2.json

Keeps:
  *_content_list.json   - sole input to scripts/build_*.py
  images/               - copied into rs_smp_corpus/volumes/<volume>/figures/ by build_figures.py
  *.md                  - MinerU's flat markdown render, useful for spot-checks
                          (pass --strip-md to remove these too)

Works on any of the backend-specific subfolders MinerU emits:
  output/<pdf-stem>/auto/...           (pipeline backend)
  output/<pdf-stem>/hybrid_auto/...    (hybrid-auto-engine backend, recommended)
  output/<pdf-stem>/vlm/...            (vlm-auto-engine backend)
  SMP/sources/<volume>/auto/...        (after scripts/restructure.py)

Defaults to dry-run; pass --apply to actually delete.
"""

import argparse
from collections.abc import Iterator
from pathlib import Path

DISCARD_PATTERNS = [
    "*_middle.json",
    "*_model.json",
    "*_origin.pdf",
    "*_layout.pdf",
    "*_span.pdf",
    "*_content_list_v2.json",
]

OPTIONAL_MD_PATTERN = "*.md"

# MinerU writes its per-volume results into a backend-specific subfolder.
# Keep this in sync with scripts/restructure.py:AUTO_SUBDIRS.
AUTO_SUBDIRS = ("auto", "hybrid_auto", "vlm")


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def find_auto_dirs(root: Path) -> Iterator[Path]:
    """Yield every <volume>/<auto-like>/ directory under root."""
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        for sub_name in AUTO_SUBDIRS:
            sub = child / sub_name
            if sub.is_dir():
                yield sub


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--input-dir",
        default="output",
        help=(
            "Directory containing <volume>/{auto,hybrid_auto,vlm_auto}/ "
            "subtrees (default: output)"
        ),
    )
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete files. Without this flag the script only reports.",
    )
    ap.add_argument(
        "--strip-md",
        action="store_true",
        help="Also remove MinerU's flat <stem>.md render (kept by default).",
    )
    args = ap.parse_args()

    root = Path(args.input_dir).resolve()
    if not root.is_dir():
        print(f"ERROR: not a directory: {root}")
        raise SystemExit(1)

    patterns = list(DISCARD_PATTERNS)
    if args.strip_md:
        patterns.append(OPTIONAL_MD_PATTERN)

    print(f"input-dir : {root}")
    print(f"mode      : {'APPLY (deleting)' if args.apply else 'dry-run'}")
    print(f"patterns  : {', '.join(patterns)}")
    print()

    auto_dirs = list(find_auto_dirs(root))
    if not auto_dirs:
        joined = "/".join(AUTO_SUBDIRS)
        print(f"No <volume>/{{{joined}}}/ subdirectories found under {root}")
        raise SystemExit(1)

    grand_total = 0
    grand_count = 0
    for auto in auto_dirs:
        vol_total = 0
        vol_files = []
        for pat in patterns:
            for f in auto.glob(pat):
                if f.is_file():
                    vol_files.append(f)
                    vol_total += f.stat().st_size

        rel = auto.relative_to(root.parent) if root.parent in auto.parents else auto
        if not vol_files:
            print(f"  --   {rel}  (nothing to remove)")
            continue

        print(f"  {len(vol_files):3d} files, {human_size(vol_total):>9s}   {rel}")
        for f in vol_files:
            print(f"        - {f.name}  ({human_size(f.stat().st_size)})")
            if args.apply:
                f.unlink()

        grand_total += vol_total
        grand_count += len(vol_files)

    print()
    verb = "Deleted" if args.apply else "Would delete"
    print(f"{verb} {grand_count} files, {human_size(grand_total)} total")
    if not args.apply and grand_count:
        print("Re-run with --apply to actually delete.")


if __name__ == "__main__":
    main()

"""
Dump every xy-list-titleblock front matter (stock_number + assembly + page)
for all bands, sorted by (volume, chapter, page). Writes a Markdown table
to rs_smp_corpus/index/_titleblocks_dump.md for manual module-name review.
"""

import re
from pathlib import Path
from typing import Any

import yaml

FM_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)


def read_front_matter(path: Path) -> dict[str, Any]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    m = FM_RE.match(content)
    if not m:
        return {}
    try:
        data: dict[str, Any] = yaml.safe_load(m.group(1)) or {}
        return data
    except yaml.YAMLError:
        return {}


def load_toc_overrides(base_path: Path) -> dict[str, Any]:
    path = base_path / "scripts" / "toc_overrides.yaml"
    with open(path, encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}
        return data


def chapter_for_page(chapters: list[dict[str, Any]], page: int) -> dict[str, Any]:
    for ch in chapters:
        ps = ch.get("page_start")
        pe = ch.get("page_end")
        if ps is None:
            continue
        if page < ps:
            continue
        if pe is not None and page > pe:
            continue
        return ch
    return {}


def main() -> None:
    base_path = Path(__file__).parent.parent.parent
    overrides = load_toc_overrides(base_path)

    lines = ["# XY-list Titleblock Dump", ""]
    lines.append(
        "Assembly names are what the OCR extracted from the title "
        "block cartouche. Useful for filling in real module names "
        "in toc_overrides.yaml."
    )
    lines.append("")

    for volume_dir in sorted((base_path / "rs_smp_corpus" / "volumes").glob("band-*")):
        volume_id = volume_dir.name
        chapters = (overrides.get(volume_id) or {}).get("chapters", [])

        lines.append(f"## {volume_id}")
        lines.append("")
        lines.append("| Ch | Page | Stock Number | Assembly (OCR) | File |")
        lines.append("|----|------|--------------|----------------|------|")

        tables_dir = volume_dir / "tables"
        if not tables_dir.exists():
            lines.append("(no tables)\n")
            continue

        rows = []
        for f in sorted(tables_dir.glob("p*_xy-list-titleblock_*.md")):
            m = re.match(r"p(\d+)_", f.name)
            if not m:
                continue
            page = int(m.group(1))
            fm = read_front_matter(f)
            stock = fm.get("stock_number", "")
            assembly = fm.get("assembly", "")
            ch = chapter_for_page(chapters, page)
            ch_num = ch.get("number", "")
            rows.append((ch_num, page, stock, assembly, f.name))

        for ch_num, page, stock, assembly, fname in rows:
            lines.append(f"| {ch_num} | {page} | {stock} | {assembly} | {fname} |")
        lines.append("")

    out_path = base_path / "rs_smp_corpus" / "index" / "_titleblocks_dump.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\u2713 Wrote {out_path}")


if __name__ == "__main__":
    main()

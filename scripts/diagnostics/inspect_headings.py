"""
Diagnostic tool: dump all headings from each volume with page numbers.

Use this to identify real chapter boundaries before filling in toc_overrides.yaml.

Writes to rs_smp_corpus/index/_headings_dump.md for manual review.

Usage:
    python inspect_headings.py
"""

import json
from pathlib import Path
from typing import Any

import yaml


def load_config() -> dict[str, Any]:
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path, encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f)
        return data


def load_content_list(volume_path: Path) -> list[dict[str, Any]]:
    auto_dir = volume_path / "auto"
    json_files = list(auto_dir.glob("*_content_list.json"))
    json_files = [f for f in json_files if "_v2" not in f.name]

    if not json_files:
        return []

    with open(json_files[0], encoding="utf-8") as f:
        data: list[dict[str, Any]] = json.load(f)
        return data


def extract_headings(content_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract all entries with text_level."""
    headings: list[dict[str, Any]] = []
    for entry in content_list:
        if entry.get("text_level"):
            headings.append(
                {
                    "text": entry.get("text", ""),
                    "level": entry.get("text_level"),
                    "page": entry.get("page_idx", 0),
                }
            )
    return headings


def extract_first_text_per_page(
    content_list: list[dict[str, Any]],
) -> dict[int, str]:
    """Get first non-trivial text entry per page (may be a heading MinerU missed)."""
    page_first: dict[int, str] = {}
    for entry in content_list:
        if entry.get("type") != "text":
            continue
        text = (entry.get("text") or "").strip()
        if len(text) < 3:
            continue
        page_idx = entry.get("page_idx", 0)
        if page_idx not in page_first:
            page_first[page_idx] = text[:100]
    return page_first


def main() -> None:
    base_path = Path(__file__).parent.parent.parent
    config = load_config()

    output_path = base_path / "rs_smp_corpus" / "index" / "_headings_dump.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("# Headings Inspection Report\n\n")
        f.write(
            "Use this to identify real chapter boundaries for `toc_overrides.yaml`.\n\n"
        )
        f.write("For each volume, two tables are shown:\n")
        f.write("1. **MinerU-detected headings** (entries with `text_level`)\n")
        f.write("2. **First text per page** (useful when MinerU missed a heading)\n\n")

        for volume_config in config["volumes"]:
            volume_id = volume_config["id"]
            volume_folder = volume_config["folder"]

            print(f"Inspecting {volume_id}...")

            f.write(f"\n---\n\n## {volume_id}\n\n")

            volume_path = base_path / volume_folder
            content_list = load_content_list(volume_path)

            if not content_list:
                f.write("*(No content_list.json found)*\n\n")
                continue

            # Total pages
            page_indices: set[int] = {
                e["page_idx"] for e in content_list if e.get("page_idx") is not None
            }
            total_pages = max(page_indices) + 1 if page_indices else 0
            f.write(f"**Total pages:** {total_pages}\n\n")

            # Detected headings
            headings = extract_headings(content_list)
            f.write(f"### MinerU headings ({len(headings)})\n\n")

            if headings:
                f.write("| Page | Level | Text |\n")
                f.write("|------|-------|------|\n")
                for h in headings:
                    safe_text = h["text"].replace("|", "\\|").replace("\n", " ")[:120]
                    f.write(f"| {h['page']} | {h['level']} | {safe_text} |\n")
            else:
                f.write("*(No headings detected)*\n")

            f.write("\n")

            # First text per page (first 40 pages as a sample)
            page_first = extract_first_text_per_page(content_list)
            f.write("### First text per page (sample first 40)\n\n")
            f.write("| Page | First text |\n")
            f.write("|------|-----------|\n")
            for page in sorted(page_first.keys())[:40]:
                safe_text = page_first[page].replace("|", "\\|").replace("\n", " ")
                f.write(f"| {page} | {safe_text} |\n")
            f.write("\n")

    print(f"\n✓ Wrote {output_path}")
    print("  Open this file and identify chapter start pages for each volume")
    print("  Then fill in page_start/page_end in scripts/toc_overrides.yaml")


if __name__ == "__main__":
    main()

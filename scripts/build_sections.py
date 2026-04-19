"""
Build section/chapter files by aggregating pages.

Generates:
- rs_smp_corpus/volumes/<vol>/sections/<NN>_<slug>.md for each chapter

Detection strategy:
1. Extract headings from content_list.json (text_level: 1 or 2)
2. Build hierarchical TOC
3. Apply overrides from toc_overrides.yaml
4. Aggregate pages in each chapter range
5. For bilingual volumes, create English-primary merged sections

Usage:
    python build_sections.py
"""

import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

# Add scripts directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))


def load_config() -> dict[str, Any]:
    """Load configuration from config.yaml."""
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path, encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f)
        return data


def load_toc_overrides() -> dict[str, Any]:
    """Load TOC overrides from toc_overrides.yaml."""
    overrides_path = Path(__file__).parent / "toc_overrides.yaml"
    with open(overrides_path, encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f)
        return data


def load_content_list(volume_path: Path) -> list[dict[str, Any]]:
    """Load content_list.json for a volume."""
    auto_dir = volume_path / "auto"
    json_files = list(auto_dir.glob("*_content_list.json"))
    json_files = [f for f in json_files if "_v2" not in f.name]

    if not json_files:
        raise FileNotFoundError(f"No content_list.json found in {auto_dir}")

    with open(json_files[0], encoding="utf-8") as f:
        data: list[dict[str, Any]] = json.load(f)
        return data


def generate_slug(text: str, max_length: int = 40) -> str:
    """Generate a URL-safe slug from text."""
    if not text:
        return "section"

    slug = text.lower()
    slug = (
        slug.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    )
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = slug[:max_length].strip("-")

    return slug if slug else "section"


def extract_headings(content_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Extract headings with their page numbers from content_list.

    Returns list of dicts: {text, level, page}
    """
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


# English-section start markers inside a bilingual chapter. Matched against
# text_level:2 entries (case-insensitive).
EN_START_RE = re.compile(
    r"^\s*(7\.\s*TESTING\s+AND\s+REPAIR\s+OF\s+THE\s+(BOARD|MODULE)"
    r"|7\.1\s+FUNCTION(AL)?\s+DESCRIPTION"
    r"|CHECKING\s+AND\s+REPAIR\s+OF\s+THE\s+MODULE)",
    re.IGNORECASE,
)


def detect_en_start_page(
    content_list: list[dict[str, Any]], page_start: int, page_end: int | None
) -> int | None:
    """Return the earliest page within [page_start, page_end] that carries an
    English chapter/section heading at text_level:2. None if no such heading."""
    best: int | None = None
    for entry in content_list:
        if entry.get("text_level") != 2:
            continue
        page = entry.get("page_idx", 0)
        if page < page_start:
            continue
        if page_end is not None and page > page_end:
            continue
        text = (entry.get("text") or "").strip()
        if EN_START_RE.match(text) and (best is None or page < best):
            best = page
    return best


def apply_chapter_template(
    volume_id: str, overrides: dict[str, Any]
) -> list[dict[str, Any]]:
    """
    Apply chapter template from toc_overrides.yaml.

    Returns list of chapter definitions.
    """
    volume_overrides = overrides.get(volume_id, {})
    chapters = volume_overrides.get("chapters", [])

    # Filter out chapters with null page ranges (not yet filled in)
    valid_chapters: list[dict[str, Any]] = []
    for chapter in chapters:
        if chapter.get("page_start") is not None:
            valid_chapters.append(chapter)

    return valid_chapters


def auto_detect_chapters(headings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Auto-detect chapter boundaries from headings.

    Returns list of chapter definitions with page ranges.
    """
    if not headings:
        return []

    chapters: list[dict[str, Any]] = []

    # Use level-1 headings as primary chapter markers
    level1_headings = [h for h in headings if h["level"] == 1]

    for i, heading in enumerate(level1_headings):
        chapter: dict[str, Any] = {
            "number": i + 1,
            "title_en": heading["text"],  # May need translation detection
            "title_de": heading["text"],
            "page_start": heading["page"],
        }

        # End page is start of next chapter minus 1
        if i + 1 < len(level1_headings):
            chapter["page_end"] = level1_headings[i + 1]["page"] - 1
        else:
            # Last chapter extends to end
            chapter["page_end"] = None

        chapters.append(chapter)

    return chapters


def load_page_files(
    volume_id: str, base_path: Path, page_start: int, page_end: int | None
) -> list[Path]:
    """Load all page files in a given range."""
    pages_dir = base_path / "rs_smp_corpus" / "volumes" / volume_id / "pages"

    if not pages_dir.exists():
        return []

    page_files = []

    for page_file in sorted(pages_dir.glob("p*.md")):
        # Extract page number from filename (p0042_...)
        match = re.match(r"p(\d+)_", page_file.name)
        if match:
            page_num = int(match.group(1))
            if page_num >= page_start and (page_end is None or page_num <= page_end):
                page_files.append(page_file)

    return page_files


def concatenate_pages(page_files: list[Path], language: str) -> str:
    """Concatenate multiple page files into one section."""
    lines = []

    for page_file in page_files:
        # Read the page file
        with open(page_file, encoding="utf-8") as f:
            content = f.read()

        # Skip front matter (between --- markers)
        parts = content.split("---")
        if len(parts) >= 3:
            # Content after second ---
            page_content = "---".join(parts[2:]).strip()
        else:
            page_content = content.strip()

        # Extract page number from filename for anchor
        match = re.match(r"p(\d+)_", page_file.name)
        page_num = int(match.group(1)) if match else 0

        # Add page anchor
        lines.append(f"[p.{page_num}]\n\n")
        lines.append(page_content)
        lines.append("\n\n---\n\n")

    return "\n".join(lines)


def build_sections_for_volume(
    volume_config: dict[str, Any],
    base_path: Path,
    overrides: dict[str, Any],
) -> None:
    """Build section files for a single volume."""
    volume_id = volume_config["id"]
    volume_folder = volume_config["folder"]
    language = volume_config["language"]
    apply_template = volume_config.get("apply_chapter_template", False)
    bilingual = language == "de+en"

    print(f"\nProcessing {volume_id}...")

    # For bilingual volumes, load content_list up front so we can detect the
    # DE/EN split page inside each chapter.
    content_list: list[dict[str, Any]] = []
    if bilingual:
        volume_path = base_path / volume_folder
        try:
            content_list = load_content_list(volume_path)
        except FileNotFoundError:
            print("  Warning: content_list.json not found; bilingual split disabled")
            bilingual = False

    # Determine chapter structure
    if apply_template:
        chapters = apply_chapter_template(volume_id, overrides)
        if chapters:
            print(f"  Using TOC overrides: {len(chapters)} chapters")
        else:
            print(
                "  TOC overrides defined but page ranges not filled, using auto-detection"
            )
            # Fall back to auto-detection
            if not content_list:
                volume_path = base_path / volume_folder
                content_list = load_content_list(volume_path)
            headings = extract_headings(content_list)
            chapters = auto_detect_chapters(headings)
            print(f"  Auto-detected: {len(chapters)} chapters")
    else:
        # Auto-detect for user-manual and datasheet
        volume_path = base_path / volume_folder
        content_list = load_content_list(volume_path)
        headings = extract_headings(content_list)
        chapters = auto_detect_chapters(headings)
        print(f"  Auto-detected: {len(chapters)} chapters")

    if not chapters:
        # Flat volume (datasheet): create a single section covering all pages
        print("  No chapters detected, creating single-section volume")
        chapters = [
            {
                "number": 1,
                "title_en": volume_config["title_en"],
                "title_de": volume_config.get("title_de"),
                "page_start": 0,
                "page_end": None,
            }
        ]

    # Drop empty ranges (e.g. two level-1 headings on the same page)
    filtered = []
    for ch in chapters:
        ps = ch.get("page_start")
        pe = ch.get("page_end")
        if ps is None:
            continue
        if pe is not None and pe < ps:
            print(
                f"    Note: dropping chapter {ch.get('number')} (empty page range {ps}..{pe})"
            )
            continue
        filtered.append(ch)
    chapters = filtered

    # Create output directory (clear existing section files for idempotent re-runs)
    output_dir = base_path / "rs_smp_corpus" / "volumes" / volume_id / "sections"
    output_dir.mkdir(parents=True, exist_ok=True)
    for existing in output_dir.glob("*.md"):
        existing.unlink()

    # Process each chapter
    total_files = 0
    for chapter in chapters:
        chapter_num = chapter["number"]
        title_en = chapter.get("title_en", f"Chapter {chapter_num}")
        title_de = chapter.get("title_de", title_en)
        page_start = chapter["page_start"]
        page_end = chapter.get("page_end")

        all_pages = load_page_files(volume_id, base_path, page_start, page_end)
        if not all_pages:
            print(f"    Warning: No pages found for chapter {chapter_num}")
            continue

        # Attempt bilingual split: only when volume is de+en AND we have both
        # a DE title and an EN title AND we can find an EN-start page marker.
        # The chapter override may pin the EN start page explicitly when the
        # OCR'd heading isn't at text_level:2 and autodetection fails.
        en_start = None
        if bilingual and title_de and title_de != title_en:
            en_start = chapter.get("en_start_page")
            if en_start is None:
                en_start = detect_en_start_page(content_list, page_start, page_end)

        if en_start is not None and page_start < en_start:
            # Produce a paired DE/EN section.
            def _page_num(p: Path) -> int:
                m = re.match(r"p(\d+)_", p.name)
                return int(m.group(1)) if m else 0

            de_pages = [p for p in all_pages if _page_num(p) < en_start]
            en_pages = [p for p in all_pages if _page_num(p) >= en_start]

            slug_de = generate_slug(title_de)
            slug_en = generate_slug(title_en)
            de_name = f"{chapter_num:02d}_de_{slug_de}.md"
            en_name = f"{chapter_num:02d}_en_{slug_en}.md"
            de_sibling_ref = f"sections/{en_name}"
            en_sibling_ref = f"sections/{de_name}"

            _write_section_file(
                filepath=output_dir / de_name,
                volume_id=volume_id,
                chapter_num=chapter_num,
                title_en=title_en,
                title_de=title_de,
                language="de",
                page_start=page_start,
                page_end=en_start - 1,
                page_files=de_pages,
                bilingual_sibling=de_sibling_ref,
            )
            _write_section_file(
                filepath=output_dir / en_name,
                volume_id=volume_id,
                chapter_num=chapter_num,
                title_en=title_en,
                title_de=title_de,
                language="en",
                page_start=en_start,
                page_end=page_end,
                page_files=en_pages,
                bilingual_sibling=en_sibling_ref,
            )
            total_files += 2
            print(
                f"  ✓ Chapter {chapter_num}: {title_en} "
                f"(DE {len(de_pages)}p + EN {len(en_pages)}p)"
            )
        else:
            # Single combined section (monolingual volume, or bilingual
            # chapter with no detectable EN heading).
            slug = generate_slug(title_en)
            filename = f"{chapter_num:02d}_{slug}.md"
            _write_section_file(
                filepath=output_dir / filename,
                volume_id=volume_id,
                chapter_num=chapter_num,
                title_en=title_en,
                title_de=title_de,
                language=language,
                page_start=page_start,
                page_end=page_end,
                page_files=all_pages,
                bilingual_sibling=None,
            )
            total_files += 1
            print(f"  ✓ Chapter {chapter_num}: {title_en} ({len(all_pages)} pages)")

    print(f"  ✓ Created {total_files} section files in {output_dir}")


def _write_section_file(
    filepath: Path,
    volume_id: str,
    chapter_num: int,
    title_en: str,
    title_de: str | None,
    language: str,
    page_start: int,
    page_end: int | None,
    page_files: list[Path],
    bilingual_sibling: str | None,
) -> None:
    """Emit one section file with front matter + concatenated page content."""
    content = concatenate_pages(page_files, language)

    front_matter: dict[str, Any] = {
        "volume": volume_id,
        "chapter": chapter_num,
        "title_en": title_en,
        "language": language,
        "page_start": page_start,
        "page_end": page_end if page_end else "end",
        "n_pages": len(page_files),
    }
    if title_de and title_de != title_en:
        front_matter["title_de"] = title_de
        front_matter["authoritative_language"] = "de"
    if bilingual_sibling:
        front_matter["bilingual_sibling"] = bilingual_sibling

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("---\n")
        yaml.dump(front_matter, f, allow_unicode=True, default_flow_style=False)
        f.write("---\n\n")
        # Heading: show only the language this file carries. Monolingual
        # bilingual-title sections still get both titles joined.
        if language == "de" and title_de:
            f.write(f"# {title_de}\n\n")
        elif language == "en":
            f.write(f"# {title_en}\n\n")
        elif title_de and title_de != title_en:
            f.write(f"# {title_en} / {title_de}\n\n")
        else:
            f.write(f"# {title_en}\n\n")
        f.write(content)


def main() -> None:
    """Main entry point."""
    print("Building section files from pages...")

    # Find project root
    base_path = Path(__file__).parent.parent

    # Load configuration
    config = load_config()
    overrides = load_toc_overrides()

    # Process each volume
    for volume_config in config["volumes"]:
        try:
            build_sections_for_volume(volume_config, base_path, overrides)
        except Exception as e:
            print(f"  ✗ Error processing {volume_config['id']}: {e}")
            import traceback

            traceback.print_exc()

    print("\n✓ Section building complete!")


if __name__ == "__main__":
    main()

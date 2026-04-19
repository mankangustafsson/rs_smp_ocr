"""
Build individual page markdown files from MinerU content_list.json.

Reads content_list.json from each volume and generates:
- rs_smp_corpus/volumes/<vol>/pages/p<NNNN>_<slug>_<lang>.md for each page

Each page file includes:
- YAML front matter with metadata
- Normalized text content
- References to tables and figures on that page

Usage:
    python build_pages.py
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

# Add scripts directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))
from normalize import NormalizationLog, normalize_text

STOCK_NUMBER_RE = re.compile(r"^\d{4}\.\d{4}(?:\.\d{2})?$")
PRINTED_LOCATOR_RE = re.compile(r"^[A-Z]-\d+$")


def collect_header_footer_meta(
    entries: list[dict[str, Any]],
    language: str,
    log: NormalizationLog,
    context: str,
) -> dict[str, Any]:
    """Classify ``header`` / ``footer`` entries into structured front-matter
    fields so the rendered body stays clean while the data remains available
    to downstream scripts and search.

    - Every ``header`` text joins ``running_header`` in page order.
    - A ``footer`` matching ``NNNN.NNNN[.NN]`` populates ``stock_number``.
    - A ``footer`` matching ``[A-Z]-N`` populates ``printed_locator``.
    - Anything else lands in ``source_footers`` as a fallback list.
    """
    headers: list[str] = []
    stock: str | None = None
    locator: str | None = None
    other: list[str] = []
    for entry in entries:
        etype = entry.get("type")
        text = (entry.get("text") or "").strip()
        if not text or etype not in ("header", "footer"):
            continue
        value = normalize_text(text, language, log, context).strip()
        if not value:
            continue
        if etype == "header":
            headers.append(value)
        elif STOCK_NUMBER_RE.match(value):
            stock = stock or value
        elif PRINTED_LOCATOR_RE.match(value):
            locator = locator or value
        else:
            other.append(value)
    meta: dict[str, Any] = {}
    if headers:
        meta["running_header"] = " / ".join(headers)
    if stock:
        meta["stock_number"] = stock
    if locator:
        meta["printed_locator"] = locator
    if other:
        meta["source_footers"] = other
    return meta


def load_config() -> dict[str, Any]:
    """Load configuration from config.yaml."""
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path, encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f)
        return data


def load_content_list(volume_path: Path) -> list[dict[str, Any]]:
    """Load content_list.json for a volume."""
    # Find the content_list.json file
    auto_dir = volume_path / "auto"
    json_files = list(auto_dir.glob("*_content_list.json"))

    # Exclude v2 version
    json_files = [f for f in json_files if "_v2" not in f.name]

    if not json_files:
        raise FileNotFoundError(f"No content_list.json found in {auto_dir}")

    content_list_path = json_files[0]
    print(f"  Loading {content_list_path.name}...")

    with open(content_list_path, encoding="utf-8") as f:
        data: list[dict[str, Any]] = json.load(f)
        return data


def detect_language(text: str) -> str:
    """
    Detect language from text content.

    Returns: 'de', 'en', 'fr', or 'unknown'
    """
    if not text:
        return "unknown"

    text_lower = text.lower()

    # German indicators
    de_indicators = [
        "der",
        "die",
        "das",
        "und",
        "für",
        "mit",
        "von",
        "auf",
        "bei",
        "nach",
        "über",
        "durch",
        "schaltung",
        "funktion",
        "messung",
        "prüfung",
        "abgleich",
        "einstellung",
    ]
    de_count = sum(1 for word in de_indicators if word in text_lower)

    # English indicators
    en_indicators = [
        "the",
        "and",
        "for",
        "with",
        "from",
        "this",
        "that",
        "circuit",
        "function",
        "test",
        "adjustment",
        "measurement",
        "setting",
        "output",
        "input",
    ]
    en_count = sum(1 for word in en_indicators if word in text_lower)

    # French indicators (minimal, mostly boilerplate)
    fr_indicators = ["le", "la", "les", "et", "pour", "avec", "dans"]
    fr_count = sum(1 for word in fr_indicators if word in text_lower)

    if de_count > en_count and de_count > fr_count:
        return "de"
    elif en_count > de_count and en_count > fr_count:
        return "en"
    elif fr_count > 0:
        return "fr"
    else:
        return "unknown"


def generate_slug(text: str, max_length: int = 40) -> str:
    """
    Generate a URL-safe slug from text.

    Examples:
        "Digital Synthesis" → "digital-synthesis"
        "Schaltpläne / Schematics" → "schaltplane-schematics"
    """
    if not text:
        return "page"

    # Remove special characters, convert to lowercase
    slug = text.lower()

    # Replace umlauts
    slug = slug.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    slug = slug.replace("ß", "ss")

    # Keep only alphanumeric and spaces
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)

    # Replace spaces with hyphens
    slug = re.sub(r"\s+", "-", slug)

    # Remove duplicate hyphens
    slug = re.sub(r"-+", "-", slug)

    # Trim to max length
    slug = slug[:max_length].strip("-")

    return slug if slug else "page"


def group_by_page(
    content_list: list[dict[str, Any]],
) -> dict[int, list[dict[str, Any]]]:
    """Group content entries by page_idx."""
    pages: defaultdict[int, list[dict[str, Any]]] = defaultdict(list)

    for entry in content_list:
        page_idx = entry.get("page_idx")
        if page_idx is not None:
            pages[page_idx].append(entry)

    return dict(pages)


def extract_page_heading(entries: list[dict[str, Any]]) -> str | None:
    """Extract the most significant heading from a page."""
    # Look for entries with text_level (headings)
    headings = [e for e in entries if e.get("text_level")]

    if headings:
        # Prefer higher level headings (smaller numbers)
        headings.sort(key=lambda e: e.get("text_level", 99))
        heading_text = headings[0].get("text", "")
        return heading_text if isinstance(heading_text, str) else None

    # Fall back to first substantial text entry
    text_entries = [e for e in entries if e.get("type") == "text" and e.get("text")]
    if text_entries:
        text = text_entries[0].get("text", "")
        if isinstance(text, str) and 10 < len(text) < 100:
            return text

    return None


def build_page_content(
    entries: list[dict[str, Any]],
    language: str,
    log: NormalizationLog,
    context: str,
) -> str:
    """Build the markdown content for a page."""
    lines = []

    for entry in entries:
        entry_type = entry.get("type")
        text = entry.get("text", "")

        if entry_type == "text":
            if text and text.strip():
                # Normalize the text
                normalized = normalize_text(text, language, log, context)
                lines.append(normalized)
                lines.append("")  # Blank line

        elif entry_type in ("header", "footer"):
            # Running page headers and printed footers (stock number,
            # printed-page locator) are captured in front matter by
            # collect_header_footer_meta(); drop them from the body.
            continue

        elif entry_type == "table":
            # Reference to table (actual table will be built by build_tables.py)
            lines.append("[TABLE: See tables/ directory]")
            lines.append("")

        elif entry_type == "image":
            # Reference to figure (actual figure will be built by build_figures.py)
            img_path = entry.get("img_path", "")
            if img_path:
                lines.append(f"[FIGURE: {img_path}]")
                lines.append("")

        elif entry_type == "list":
            # Emitted by the hybrid-auto-engine backend (MinerU 2.7+); a
            # structured list whose items live in `list_items`. Render as a
            # markdown bullet list so the content is not lost.
            items = entry.get("list_items") or []
            for item in items:
                if not isinstance(item, str):
                    continue
                stripped = item.strip()
                if not stripped:
                    continue
                # Drop any leading bullet character MinerU's VLM emitted
                # verbatim (`-`, `–`, `—`, `•`, `◆`, `*`, `·`) so we render  # noqa: RUF003
                # a consistent `- ` marker.
                while stripped and stripped[0] in "-–—•◆*·":  # noqa: RUF001
                    stripped = stripped[1:].lstrip()
                if not stripped:
                    continue
                normalized = normalize_text(stripped, language, log, context)
                lines.append(f"- {normalized}")
            if items:
                lines.append("")

    return "\n".join(lines).strip()


def build_pages_for_volume(
    volume_config: dict[str, Any],
    base_path: Path,
    global_log: NormalizationLog,
) -> None:
    """Build page files for a single volume."""
    volume_id = volume_config["id"]
    volume_folder = volume_config["folder"]
    language = volume_config["language"]
    kind = volume_config["kind"]

    print(f"\nProcessing {volume_id}...")

    # Load content list
    volume_path = base_path / volume_folder
    content_list = load_content_list(volume_path)

    print(f"  Total entries: {len(content_list)}")

    # Group by page
    pages = group_by_page(content_list)
    print(f"  Total pages: {len(pages)}")

    # Create output directory
    output_dir = base_path / "rs_smp_corpus" / "volumes" / volume_id / "pages"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Process each page
    for page_idx in sorted(pages.keys()):
        entries = pages[page_idx]

        # Determine page language (may differ from volume language for bilingual docs)
        page_text = " ".join(e.get("text", "") for e in entries if e.get("text"))
        page_language = detect_language(page_text)

        # If volume is bilingual but page is single-language, use page language
        if language == "de+en":
            if page_language in ["de", "en"]:
                effective_language = page_language
            else:
                effective_language = "de+en"
        else:
            effective_language = language

        # Extract heading for slug
        heading = extract_page_heading(entries)
        slug = generate_slug(heading) if heading else f"page{page_idx:04d}"

        # Build content
        context = f"{volume_id}/p{page_idx:04d}"
        content = build_page_content(entries, effective_language, global_log, context)

        # Count content types
        n_text = len([e for e in entries if e.get("type") == "text"])
        n_tables = len([e for e in entries if e.get("type") == "table"])
        n_images = len([e for e in entries if e.get("type") == "image"])
        n_lists = len([e for e in entries if e.get("type") == "list"])

        # Build front matter
        front_matter: dict[str, Any] = {
            "volume": volume_id,
            "page": page_idx,
            "language": effective_language,
            "kind": kind,
            "n_text": n_text,
            "n_tables": n_tables,
            "n_images": n_images,
        }
        if n_lists:
            front_matter["n_lists"] = n_lists

        if heading:
            front_matter["heading"] = heading

        # Hoist running header and printed-footer data into front matter so the
        # body renders without boilerplate while the data stays searchable.
        front_matter.update(
            collect_header_footer_meta(entries, effective_language, global_log, context)
        )

        # Generate filename
        lang_suffix = f"_{effective_language}" if effective_language != language else ""
        filename = f"p{page_idx:04d}_{slug}{lang_suffix}.md"
        filepath = output_dir / filename

        # Write file
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("---\n")
            yaml.dump(front_matter, f, allow_unicode=True, default_flow_style=False)
            f.write("---\n\n")

            # Title — the heading alone when present, else a minimal page
            # anchor. Volume and page number already live in front matter.
            title = heading if heading else f"Page {page_idx}"
            f.write(f"# {title}\n\n")

            # Content
            f.write(content)
            f.write("\n")

        if page_idx % 50 == 0:
            print(f"  Processed {page_idx} pages...")

    print(f"  ✓ Created {len(pages)} page files in {output_dir}")


def main() -> None:
    """Main entry point."""
    print("Building page files from content_list.json...")

    # Find project root (parent of scripts/)
    base_path = Path(__file__).parent.parent

    # Load configuration
    config = load_config()

    # Initialize global normalization log
    global_log = NormalizationLog()

    # Process each volume
    for volume_config in config["volumes"]:
        try:
            build_pages_for_volume(volume_config, base_path, global_log)
        except Exception as e:
            print(f"  ✗ Error processing {volume_config['id']}: {e}")
            import traceback

            traceback.print_exc()

    # Write normalization log
    log_path = base_path / "rs_smp_corpus" / "index" / "normalization_log.md"
    global_log.write_to_file(log_path)
    print(f"\n✓ Normalization log written to {log_path}")
    print(f"  Total normalizations: {len(global_log.entries)}")

    print("\n✓ Page building complete!")


if __name__ == "__main__":
    main()

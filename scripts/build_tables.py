"""
Build table markdown files from MinerU content_list.json.

Extracts tables and generates:
- rs_smp_corpus/volumes/<vol>/tables/p<NNNN>_<kind>_<slug>.md for each table

Each table file includes:
- YAML front matter with metadata
- Raw HTML table (preserved exactly as OCR'd)
- Normalized CSV for XY-lists and parts lists (when applicable)

Table kinds:
- xy-list: Component position tables (designator, board, x, y, square, page)
- parts-list: Parts/assembly lists
- spec: Specification tables
- other: General tables

Usage:
    python build_tables.py
"""

import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml
from bs4 import BeautifulSoup

# Add scripts directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))
from normalize import normalize_designator, normalize_stock_number, normalize_text


def load_config() -> dict[str, Any]:
    """Load configuration from config.yaml."""
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path, encoding="utf-8") as f:
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


def count_data_rows(html: str) -> int:
    """Count rows in the table that are likely data rows (not the R&S title block)."""
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.find_all("tr")
    data_rows = 0
    for tr in rows:
        text = tr.get_text().lower()
        if "rohde" in text and "schwarz" in text:
            continue
        if "datum" in text and "date" in text:
            continue
        if "sach-nummer" in text or "stock-nr" in text:
            continue
        if not tr.get_text().strip():
            continue
        data_rows += 1
    return data_rows


_XY_INDICATOR_RE = re.compile(
    r"\b(xy-liste|xy-list|part side x|designator)\b", re.IGNORECASE
)
_PARTS_INDICATOR_RE = re.compile(
    r"\b(bauelementeliste|parts list|schl\u00fcsselliste|key list|ersatzteile|spare parts)\b",
    re.IGNORECASE,
)
_SPEC_INDICATOR_RE = re.compile(
    r"\b(specification|spezifikation|parameter|characteristics|daten)\b", re.IGNORECASE
)


def detect_table_kind(html: str, caption: str = "") -> str:
    """
    Detect the kind of table from HTML content and caption.

    Returns: 'xy-list', 'xy-list-titleblock', 'parts-list', 'spec', or 'other'

    A table is only classified as 'xy-list' if it has the XY-list indicators
    AND more than 2 data rows. Otherwise it's a title-block-only cartouche
    (the component data lives in an associated image).

    Indicators use word boundaries to avoid false positives
    (e.g. "square" inside "squarewave").
    """
    combined = html + " " + caption

    if _XY_INDICATOR_RE.search(combined):
        # Real XY-lists always contain component designators; title-block
        # cartouches only contain logo/metadata rows.
        has_designators = bool(extract_designators_from_html(html))
        if has_designators and count_data_rows(html) > 2:
            return "xy-list"
        return "xy-list-titleblock"

    if _PARTS_INDICATOR_RE.search(combined):
        return "parts-list"

    if _SPEC_INDICATOR_RE.search(combined):
        return "spec"

    return "other"


def extract_stock_number_from_table(html: str) -> str | None:
    """Extract stock number from table HTML (often in footer row)."""
    # Pattern: NNNN.NNNN.NN
    pattern = r"(\d{4}\.\d{4}\.\d{2}(?:/\d{2})*)"
    matches = re.findall(pattern, html)

    if matches:
        # Return the first valid one
        for match in matches:
            normalized = normalize_stock_number(match)
            if normalized:
                return normalized

    return None


def extract_assembly_name(html: str) -> str | None:
    """Extract assembly name from table HTML."""
    # Look for patterns like "DIGITAL_SYNTHESIS" or "Digital Synthesis"
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text()

    # Assembly names often in all caps or title case
    # Look for multi-word technical names
    patterns = [
        r"([A-Z_]{5,})",  # ALL_CAPS_NAMES
        r"((?:[A-Z][a-z]+\s*){2,}(?:Assembly|Module|Board|Synthesis|Generator)?)",
    ]

    for pattern in patterns:
        matches = re.findall(pattern, text)
        if matches:
            result: str = matches[0].strip()
            return result

    return None


def clean_table_html(html: str) -> str:
    """
    Clean up table HTML by removing R&S title block rows.

    These are header/footer rows like:
    "ROHDE&SCHWARZ | Datum | XY-Liste für | Sach-Nummer | Blatt"
    """
    soup = BeautifulSoup(html, "html.parser")

    # Find and remove title block rows
    for row in soup.find_all("tr"):
        text = row.get_text().lower()
        if ("rohde" in text and "schwarz" in text) or (
            "datum" in text and "date" in text
        ):
            row.decompose()

    return str(soup)


# Common R&S component designator prefixes (matches "R117", "C42", "V3", "T1", etc.)
# Excludes standalone "A" and "B" which are board-side codes, not components.
_DESIGNATOR_PREFIXES = {
    "R",
    "C",
    "L",
    "V",
    "D",
    "T",
    "X",
    "Q",
    "U",
    "K",
    "P",
    "J",
    "F",
    "Y",
    "W",
    "IC",
    "TR",
    "CR",
    "FL",
    "BR",
}

_DES_RE = re.compile(r"\b([A-Z]{1,3}\d{1,4}(?:-[A-Z])?)\b")
_SQR_RE = re.compile(r"\b((?:[1-9L]|1\d)[A-FLc])\b")
_SIDE_RE = re.compile(r"^([AB])(?:\b|(?=[-\d]))")
_COORD_RE = re.compile(r"(-?\d{1,3}|\$+)")
_PAGE_RE = re.compile(r"^\s*[|\s]*(\d{1,2})\b")


def _is_real_designator(token: str) -> bool:
    m = re.match(r"^([A-Z]+)", token)
    return bool(m and m.group(1) in _DESIGNATOR_PREFIXES)


def parse_xy_list_slice(slice_text: str) -> dict[str, str]:
    """
    Parse the text between one designator and the next into the fields
    {side, x, y, square, page}. All fields are optional. The square code
    (e.g. '5D', '11A') is the strongest anchor when present; otherwise
    we assume the first two integers are X and Y.
    """
    rec = {"side": "", "x": "", "y": "", "square": "", "page": ""}
    s = slice_text.strip().lstrip("|").strip()
    if not s:
        return rec

    side_m = _SIDE_RE.match(s)
    if side_m:
        rec["side"] = side_m.group(1)
        s = s[side_m.end() :].lstrip(" |")

    sqr_m = _SQR_RE.search(s)
    if sqr_m:
        rec["square"] = sqr_m.group(1)
        before, after = s[: sqr_m.start()], s[sqr_m.end() :]
        coords = _COORD_RE.findall(before)
        if coords:
            rec["x"] = coords[0]
        if len(coords) >= 2:
            rec["y"] = coords[1]
        pg_m = _PAGE_RE.match(after)
        if pg_m:
            rec["page"] = pg_m.group(1)
    else:
        coords = _COORD_RE.findall(s)
        if coords:
            rec["x"] = coords[0]
        if len(coords) >= 2:
            rec["y"] = coords[1]
    return rec


def _has_spatial_data(rec: dict[str, str]) -> bool:
    return bool(rec["square"] or (rec["x"] and rec["y"]))


def _assess_confidence(rec: dict[str, str]) -> str:
    """Score each spatial record by how many clean (no-$$$ placeholder)
    fields it has. Returns 'high', 'medium', or 'low'."""
    fields = ("side", "x", "y", "square", "page")
    clean = sum(1 for f in fields if rec.get(f) and "$" not in rec[f])
    if clean >= 4:
        return "high"
    if clean >= 2:
        return "medium"
    return "low"


def extract_xy_list_data(html: str) -> tuple[list[dict[str, str]], list[str]]:
    """
    Extract structured XY-list data by anchoring on designator and square
    tokens rather than the (broken) table grid.

    Returns (spatial_records, designator_only) where:
      spatial_records   - list of dicts {designator, side, x, y, square,
                          page, confidence}, in document order
      designator_only   - list of designator strings whose row could not
                          be located spatially (fallback)
    """
    soup = BeautifulSoup(html, "html.parser")
    cell_texts = [td.get_text(" ", strip=True) for td in soup.find_all("td")]
    text = " | ".join(cell_texts)

    des_matches = [m for m in _DES_RE.finditer(text) if _is_real_designator(m.group(1))]

    spatial: list[dict[str, str]] = []
    designator_only: list[str] = []
    seen_spatial = set()
    seen_des = set()

    for i, des in enumerate(des_matches):
        des_token = normalize_designator(des.group(1)) or des.group(1)
        next_pos = des_matches[i + 1].start() if i + 1 < len(des_matches) else len(text)
        slice_text = text[des.end() : next_pos]
        rec = parse_xy_list_slice(slice_text)
        rec["designator"] = des_token
        if _has_spatial_data(rec):
            key = (
                des_token,
                rec["side"],
                rec["x"],
                rec["y"],
                rec["square"],
                rec["page"],
            )
            if key in seen_spatial:
                continue
            seen_spatial.add(key)
            rec["confidence"] = _assess_confidence(rec)
            spatial.append(rec)
        else:
            if des_token in seen_des:
                continue
            seen_des.add(des_token)
            designator_only.append(des_token)

    # Drop designators that already appear in the spatial list.
    spatial_set = {r["designator"] for r in spatial}
    designator_only = [d for d in designator_only if d not in spatial_set]

    return spatial, designator_only


def extract_designators_from_html(html: str) -> list[str]:
    """Backwards-compatible helper: just the unique designators."""
    spatial, designator_only = extract_xy_list_data(html)
    return sorted(set(r["designator"] for r in spatial) | set(designator_only))


def generate_table_slug(
    kind: str, assembly: str | None = None, stock: str | None = None
) -> str:
    """Generate slug for table filename."""
    parts = [kind]

    if assembly:
        clean = re.sub(r"[^a-z0-9-]", "-", assembly.lower())
        clean = re.sub(r"-+", "-", clean).strip("-")
        parts.append(clean[:30])

    if stock:
        parts.append(stock.replace(".", "-").replace("/", "-"))

    return "_".join(parts)


def build_tables_for_volume(volume_config: dict[str, Any], base_path: Path) -> None:
    """Build table files for a single volume."""
    volume_id = volume_config["id"]
    volume_folder = volume_config["folder"]
    language = volume_config["language"]

    print(f"\nProcessing {volume_id}...")

    # Load content list
    volume_path = base_path / volume_folder
    content_list = load_content_list(volume_path)

    # Filter to tables only
    tables = [entry for entry in content_list if entry.get("type") == "table"]
    print(f"  Total tables: {len(tables)}")

    if not tables:
        print("  No tables found, skipping")
        return

    # Create output directory (clear existing table files for idempotent re-runs)
    output_dir = base_path / "rs_smp_corpus" / "volumes" / volume_id / "tables"
    output_dir.mkdir(parents=True, exist_ok=True)
    for existing in output_dir.glob("*.md"):
        existing.unlink()

    # Process each table
    table_count = 0
    xy_list_count = 0
    xy_titleblock_count = 0
    # Track per-page position so finalize_pages.py can pair placeholders with
    # the correct table even when some entries on a page are empty and end up
    # rendered via render_table_fallbacks.py instead.
    page_position_counters: dict[int, int] = {}

    for entry in tables:
        page_idx = entry.get("page_idx", 0)
        page_position = page_position_counters.get(page_idx, 0)
        page_position_counters[page_idx] = page_position + 1
        html = entry.get("table_body", "")

        if not html:
            # Empty table, skip
            continue

        # Detect table kind
        caption = " ".join(entry.get("table_caption", []))
        caption = normalize_text(caption, language)
        kind = detect_table_kind(html, caption)

        # Extract metadata
        stock_number = extract_stock_number_from_table(html)
        assembly = extract_assembly_name(html)

        # Clean HTML
        cleaned_html = clean_table_html(html)

        # Generate slug and filename. The ``page_position`` prefix prevents
        # collisions when a page carries multiple tables of the same kind
        # (e.g. two ``xy-list-titleblock`` entries on a schematic sheet).
        slug = generate_table_slug(kind, assembly, stock_number)
        filename = f"p{page_idx:04d}_{page_position}_{slug}.md"
        filepath = output_dir / filename

        # Build front matter
        front_matter: dict[str, Any] = {
            "volume": volume_id,
            "page": page_idx,
            "page_position": page_position,
            "kind": kind,
            "language": language,
        }

        if stock_number:
            front_matter["stock_number"] = stock_number
        if assembly:
            front_matter["assembly"] = assembly
        if caption:
            front_matter["caption"] = caption

        # For XY-lists, extract normalized data (with designator-only fallback)
        normalized_data: list[dict[str, str]] = []
        designators_only: list[str] = []
        if kind == "xy-list":
            normalized_data, designators_only = extract_xy_list_data(html)
            xy_list_count += 1
            total = len(normalized_data) + len(designators_only)
            front_matter["n_components"] = total
            front_matter["n_components_spatial"] = len(normalized_data)
            if not normalized_data:
                front_matter["extraction_quality"] = "designators-only"
            elif designators_only:
                front_matter["extraction_quality"] = "partial"
            else:
                front_matter["extraction_quality"] = "full"
        elif kind == "xy-list-titleblock":
            xy_titleblock_count += 1
            img_path = entry.get("img_path")
            if img_path:
                front_matter["source_image"] = img_path

        # Write file
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("---\n")
            yaml.dump(front_matter, f, allow_unicode=True, default_flow_style=False)
            f.write("---\n\n")

            # Title
            title_parts = [volume_id, f"p.{page_idx}"]
            if assembly:
                title_parts.append(assembly)
            if kind:
                title_parts.append(f"({kind})")

            f.write(f"# {' — '.join(title_parts)}\n\n")

            # Description
            if kind == "xy-list":
                f.write("Component position list (XY-list) showing designator, ")
                f.write("board side, coordinates, and square grid reference.\n\n")
            elif kind == "xy-list-titleblock":
                f.write("Schematic sheet title block / cartouche for an XY-list. ")
                f.write(
                    "The actual component position data is in the associated image; "
                )
                f.write("see `source_image` in the front matter.\n\n")
            elif kind == "parts-list":
                f.write("Parts list / assembly list.\n\n")
            elif kind == "spec":
                f.write("Specification table.\n\n")

            # Raw HTML section
            f.write("## Raw OCR Table\n\n")
            f.write("```html\n")
            f.write(cleaned_html)
            f.write("\n```\n\n")

            # Normalized data section (for XY-lists)
            if normalized_data:
                f.write("## Normalized Component Data\n\n")
                f.write(
                    "Per-component records reconstructed from the OCR'd HTML "
                    "by anchoring on designator and square-grid tokens. "
                    "`Confidence` is `high` when at least 4 of "
                    "(side, X, Y, square, page) parsed cleanly, `medium` for "
                    "2-3, `low` otherwise. `$$$` placeholders mark digits "
                    "MinerU could not read.\n\n"
                )
                f.write("| Designator | Board | X | Y | Square | Page | Confidence |\n")
                f.write("|------------|-------|---|---|--------|------|------------|\n")
                for row in normalized_data:
                    f.write(
                        f"| {row['designator']} | {row['side']} | "
                        f"{row['x']} | {row['y']} | {row['square']} | "
                        f"{row['page']} | {row['confidence']} |\n"
                    )
                f.write("\n")
            if designators_only:
                f.write("## Component Designators (Partial Extraction)\n\n")
                f.write(
                    "Designators whose row could not be located spatially "
                    "(no square code and no parseable X/Y pair near the "
                    "designator in the OCR'd cell stream).\n\n"
                )
                f.write(", ".join(designators_only))
                f.write("\n")

        table_count += 1

    print(f"  ✓ Created {table_count} table files")
    print(f"    - {xy_list_count} XY-lists with component data")
    print(
        f"    - {xy_titleblock_count} XY-list title blocks (data in associated image)"
    )
    print(f"    - {table_count - xy_list_count - xy_titleblock_count} other tables")


def main() -> None:
    """Main entry point."""
    print("Building table files from content_list.json...")

    # Find project root
    base_path = Path(__file__).parent.parent

    # Load configuration
    config = load_config()

    # Process each volume
    for volume_config in config["volumes"]:
        try:
            build_tables_for_volume(volume_config, base_path)
        except Exception as e:
            print(f"  ✗ Error processing {volume_config['id']}: {e}")
            import traceback

            traceback.print_exc()

    print("\n✓ Table building complete!")


if __name__ == "__main__":
    main()

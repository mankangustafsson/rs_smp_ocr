"""
Detect chapter/module boundaries in MinerU content_list.json files.

Strategy by volume kind:
- service-manual (band-1..4):
  * Each module section is bounded by a heading
    "7.1 Funktionsbeschreibung" (German "Function Description"). MinerU
    consistently captures this even when it misses the parent "7. Pruefen
    und Instandsetzen" heading. Any `text_level` is accepted: the pipeline
    backend emits level 2, the hybrid/vlm backends collapse everything to
    level 1, and the regex below is specific enough to disambiguate.
  * For band-1 only, also detect the overview chapter "6. Instandsetzung
    des SMP" at top-of-page (no text_level marker).
  * Module name comes from the first stock-numbered XY-list table within
    the module's page range.
- user-manual: detect any `text_level` heading matching one of:
  * "<N> <Title>" pattern (e.g. "2 Operation"), first occurrence only
  * known number-stripped titles ("Preparation for Use")
  * Annex marker
  Strict sequential-number acceptance rejects all-caps button labels and
  intra-chapter section headers that the VLM backend also tags as headings.
- datasheet: no chapters (single section).

Output: writes toc_overrides.auto.yaml. Review, then merge into
toc_overrides.yaml.
"""

import json
import re
from pathlib import Path
from typing import Any

import yaml

MODULE_DE_RE = re.compile(r"^7\.1\s+Funktionsbeschreibun[gq]", re.IGNORECASE)
MODULE_EN_RE = re.compile(r"^7\.1\s+Function(al)?\s+Description", re.IGNORECASE)
CH6_DE_RE = re.compile(r"^6\.\s+Instandsetzung", re.IGNORECASE)
CH6_EN_RE = re.compile(r"^6\.\s+Repair", re.IGNORECASE)
STOCK_RE = re.compile(r"\b(\d{4}\.\d{4}\.\d{2})\b")
MODULE_ID_RE = re.compile(r"\b(A\d{1,3})\b")

UM_NUMBERED_RE = re.compile(r"^([1-9][0-9]?)\s+([A-Z][A-Za-z][\w\-/ ]{2,80})$")
UM_SUBSECTION_RE = re.compile(r"^[0-9]+\.[0-9]")
UM_KNOWN_TITLES = {
    "Preparation for Use": 1,
    "Annex A": 100,
}


def load_config() -> dict[str, Any]:
    with open(Path(__file__).parent.parent / "config.yaml", encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f)
        return data


def load_content_list(volume_path: Path) -> list[dict[str, Any]]:
    auto_dir = volume_path / "auto"
    json_files = [
        f for f in auto_dir.glob("*_content_list.json") if "_v2" not in f.name
    ]
    if not json_files:
        return []
    with open(json_files[0], encoding="utf-8") as f:
        data: list[dict[str, Any]] = json.load(f)
        return data


def is_top_of_page(entry: dict[str, Any], y_threshold: int = 200) -> bool:
    bbox = entry.get("bbox")
    return bool(bbox and len(bbox) >= 2 and bbox[1] < y_threshold)


def _read_titleblock_front_matter(table_path: Path) -> dict[str, Any]:
    """Return the YAML front matter of a generated table file (or {})."""
    try:
        with open(table_path, encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return {}
    if not content.startswith("---"):
        return {}
    end = content.find("\n---", 3)
    if end < 0:
        return {}
    try:
        data: dict[str, Any] = yaml.safe_load(content[3:end]) or {}
        return data
    except yaml.YAMLError:
        return {}


_FILENAME_STOCK_RE = re.compile(r"_(\d{4}-\d{4}-\d{2})\b")


def _collect_stocks_in_range(
    tables_dir: Path, page_start: int, page_end: int
) -> list[str]:
    """Return a list of stock numbers (with repeats) from table filenames
    in the given page range, including xy-list, parts-list, and other tables."""
    stocks = []
    for table_file in tables_dir.glob("p*.md"):
        m = re.match(r"p(\d+)_", table_file.name)
        if not m:
            continue
        page = int(m.group(1))
        if page < page_start or page > page_end:
            continue
        for fm in _FILENAME_STOCK_RE.finditer(table_file.name):
            stocks.append(fm.group(1).replace("-", "."))
    return stocks


def find_module_descriptor(
    entries: list[dict[str, Any]],
    page_start: int,
    page_end: int,
    tables_dir: Path | None = None,
    common_stocks: set[str] | None = None,
) -> str | None:
    """Find a useful module identifier within a page range.

    Preferred source: most-frequent stock number from table filenames in
    the range, excluding stocks that recur across multiple module ranges
    (those are typically shared parts-list cover sheets). Falls back to
    in-content text scanning.
    """
    common_stocks = common_stocks or set()

    if tables_dir and tables_dir.exists():
        stocks = _collect_stocks_in_range(tables_dir, page_start, page_end)
        from collections import Counter

        counts = Counter(s for s in stocks if s not in common_stocks)
        if not counts:
            counts = Counter(stocks)
        if counts:
            top_stock, _ = counts.most_common(1)[0]
            assembly = None
            for table_file in sorted(
                tables_dir.glob(
                    f"p*_xy-list-titleblock_*_{top_stock.replace('.', '-')}.md"
                )
            ):
                tb_match = re.match(r"p(\d+)_", table_file.name)
                if not tb_match:
                    continue
                tb_page = int(tb_match.group(1))
                if tb_page < page_start or tb_page > page_end:
                    continue
                fm = _read_titleblock_front_matter(table_file)
                a = fm.get("assembly")
                if a and a != "ROHDE":
                    assembly = a
                    break
            return f"{top_stock} {assembly}" if assembly else top_stock

    stock_numbers: list[str] = []
    module_ids: set[str] = set()
    assembly_names: set[str] = set()

    for entry in entries:
        page = entry.get("page_idx", 0)
        if page < page_start or page > page_end:
            continue
        text = ""
        if entry.get("type") == "table":
            text = entry.get("table_body", "") or ""
            text = re.sub(r"<[^>]+>", " ", text)
        elif entry.get("type") == "text":
            text = entry.get("text", "") or ""
        text = re.sub(r"\s+", " ", text)

        for m in STOCK_RE.finditer(text):
            stock_numbers.append(m.group(1))
        for m in MODULE_ID_RE.finditer(text):
            mid = m.group(1)
            if 1 <= int(mid[1:]) <= 200:
                module_ids.add(mid)

    for entry in entries:
        page = entry.get("page_idx", 0)
        if page < page_start or page > min(page_start + 3, page_end):
            continue
        if entry.get("type") != "text":
            continue
        text = (entry.get("text") or "").strip()
        if 5 < len(text) < 50 and re.search(r"^[A-Z][A-Z \-/]{4,}$", text):
            assembly_names.add(text)

    parts = []
    if stock_numbers:
        parts.append(stock_numbers[0])
    if assembly_names:
        parts.append(sorted(assembly_names)[0])
    elif module_ids:
        parts.append(sorted(module_ids)[0])

    return " ".join(parts) if parts else None


def _compute_common_stocks(
    tables_dir: Path | None, ranges: list[tuple[int, int | None]]
) -> set[str]:
    """Return stock numbers that appear in 2 or more module ranges (likely
    shared cover sheets, not module-specific)."""
    if not tables_dir or not tables_dir.exists():
        return set()
    per_range: list[set[str]] = []
    for ps, pe in ranges:
        per_range.append(
            set(
                _collect_stocks_in_range(
                    tables_dir, ps, pe if pe is not None else ps + 200
                )
            )
        )
    counts: dict[str, int] = {}
    for s in per_range:
        for stock in s:
            counts[stock] = counts.get(stock, 0) + 1
    return {stock for stock, c in counts.items() if c >= 2}


def detect_band_chapters(
    entries: list[dict[str, Any]],
    volume_id: str,
    tables_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Detect chapters/modules for service-manual bands."""
    markers: list[dict[str, Any]] = []

    if volume_id == "band-1":
        for entry in entries:
            if entry.get("type") != "text":
                continue
            text = (entry.get("text") or "").strip()
            if not text or len(text) > 60 or "\n" in text:
                continue
            if not is_top_of_page(entry):
                continue
            if CH6_DE_RE.match(text):
                markers.append(
                    {
                        "kind": "overview-de",
                        "page": entry.get("page_idx", 0),
                        "title": text,
                    }
                )
            elif CH6_EN_RE.match(text):
                markers.append(
                    {
                        "kind": "overview-en",
                        "page": entry.get("page_idx", 0),
                        "title": text,
                    }
                )

    seen_module_pages = set()
    for entry in entries:
        if not entry.get("text_level"):
            continue
        text = (entry.get("text") or "").strip()
        if not MODULE_DE_RE.match(text):
            continue
        page = entry.get("page_idx", 0)
        if page in seen_module_pages:
            continue
        seen_module_pages.add(page)
        markers.append({"kind": "module", "page": page, "title": None})

    markers.sort(key=lambda m: m["page"])

    module_ranges: list[tuple[int, int | None]] = []
    for i, m in enumerate(markers):
        if m["kind"] != "module":
            continue
        next_page = markers[i + 1]["page"] - 1 if i + 1 < len(markers) else None
        module_ranges.append((m["page"], next_page))
    common_stocks = _compute_common_stocks(tables_dir, module_ranges)

    chapters: list[dict[str, Any]] = []
    for i, m in enumerate(markers):
        next_page = markers[i + 1]["page"] - 1 if i + 1 < len(markers) else None

        if m["kind"] == "overview-de":
            ch: dict[str, Any] = {
                "number": i + 1,
                "page_start": m["page"],
                "page_end": next_page,
                "title_de": "Kap.6 Instandsetzung des SMP (\u00dcbersicht, DE)",
                "title_en": "Ch.6 Repair of the SMP (Overview, DE)",
            }
        elif m["kind"] == "overview-en":
            ch = {
                "number": i + 1,
                "page_start": m["page"],
                "page_end": next_page,
                "title_de": "Kap.6 Instandsetzung des SMP (\u00dcbersicht, EN)",
                "title_en": "Ch.6 Repair of the SMP (Overview, EN)",
            }
        else:
            descriptor = find_module_descriptor(
                entries,
                m["page"],
                next_page or m["page"] + 80,
                tables_dir=tables_dir,
                common_stocks=common_stocks,
            )
            label = descriptor if descriptor else f"Module @p.{m['page']}"
            ch = {
                "number": i + 1,
                "page_start": m["page"],
                "page_end": next_page,
                "title_de": f"Kap.7 Pr\u00fcfen und Instandsetzen \u2014 {label}",
                "title_en": f"Ch.7 Testing and Repair \u2014 {label}",
                "module": descriptor,
            }
        chapters.append(ch)
    return chapters


def _is_chapter_title(title: str) -> bool:
    """Reject all-caps strings and obvious noise."""
    if len(title) < 3:
        return False
    letters = [c for c in title if c.isalpha()]
    if not letters:
        return False
    return not all(c.isupper() for c in letters)


def detect_user_manual_chapters(
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Detect chapters in the user manual."""
    raw_candidates: list[dict[str, Any]] = []
    for entry in entries:
        if not entry.get("text_level"):
            continue
        text = (entry.get("text") or "").strip()
        if not text or UM_SUBSECTION_RE.match(text):
            continue
        page = entry.get("page_idx", 0)

        m = UM_NUMBERED_RE.match(text)
        if m:
            num = int(m.group(1))
            title = m.group(2).strip()
            if num > 12 or not _is_chapter_title(title):
                continue
            raw_candidates.append({"number": num, "page": page, "title": title})
            continue

        if text in UM_KNOWN_TITLES:
            raw_candidates.append(
                {
                    "number": UM_KNOWN_TITLES[text],
                    "page": page,
                    "title": text,
                }
            )

    raw_candidates.sort(key=lambda c: c["page"])

    annex_value = UM_KNOWN_TITLES.get("Annex A")
    accepted = []
    last_num = 0
    for c in raw_candidates:
        if c["number"] == annex_value:
            accepted.append(c)
            continue
        # Strict sequential: only accept the next expected chapter number.
        # This rejects all-caps button-labels like "9 Switching On/Off" that
        # appear inside earlier chapters.
        if c["number"] != last_num + 1:
            continue
        accepted.append(c)
        last_num = c["number"]

    chapters = []
    for i, c in enumerate(accepted):
        next_page = accepted[i + 1]["page"] - 1 if i + 1 < len(accepted) else None
        chapters.append(
            {
                "number": i + 1,
                "page_start": c["page"],
                "page_end": next_page,
                "title_en": c["title"],
                "title_de": None,
            }
        )
    return chapters


def main() -> None:
    base_path = Path(__file__).parent.parent.parent
    config = load_config()

    result: dict[str, dict[str, Any]] = {}
    for volume_config in config["volumes"]:
        volume_id = volume_config["id"]
        kind = volume_config["kind"]
        print(f"\n{volume_id} ({kind}):")
        entries = load_content_list(base_path / volume_config["folder"])
        if not entries:
            print("  (no content list)")
            continue

        if kind == "service-manual":
            tables_dir = base_path / "rs_smp_corpus" / "volumes" / volume_id / "tables"
            chapters = detect_band_chapters(entries, volume_id, tables_dir)
        elif kind == "user-manual":
            chapters = detect_user_manual_chapters(entries)
        else:
            chapters = []

        for ch in chapters:
            title = ch.get("title_en", "?")
            pe = ch.get("page_end")
            pe_s = str(pe) if pe is not None else "end"
            print(f"  {ch['number']:>2}. p.{ch['page_start']:<4}-{pe_s:<4} {title}")

        result[volume_id] = {"chapters": chapters}

    out_path = Path(__file__).parent / "toc_overrides.auto.yaml"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# Auto-generated by detect_chapters.py\n")
        f.write("# Review, then copy/merge into toc_overrides.yaml\n\n")
        yaml.dump(result, f, allow_unicode=True, sort_keys=False)

    print(f"\n\u2713 Wrote {out_path}")


if __name__ == "__main__":
    main()

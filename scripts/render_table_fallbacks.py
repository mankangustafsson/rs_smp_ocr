"""
Render PNG fallback images for tables MinerU detected but failed to extract
cleanly.

Two classes are handled:

1. ``empty``   — ``type: table`` with no ``table_body`` and no ``img_path``.
   The HTML can't be inlined at all, so the PNG replaces the placeholder.
2. ``mangled`` — ``type: table`` whose ``table_body`` is present but
   structurally broken (column-merged rows, giant single cells). The HTML
   is kept for search indexing; the PNG is rendered alongside it so the
   reader still sees the real table.

Outputs per volume under ``rs_smp_corpus/volumes/<vol>/figures/``:
- ``table_fallback_p<NNNN>_<pos>.png`` for each fallback target
- ``_table_fallbacks.json`` sidecar keyed by page index then position,
  recording ``{"file": <png>, "kind": "empty"|"mangled"}``

MinerU stores bboxes in a normalized 0..1000 coordinate system; we scale to
PDF points via ``x_pt = bbox_x / 1000 * page_width_pt``.

Usage:
    python render_table_fallbacks.py
"""

import json
import re
from pathlib import Path
from typing import Any

import fitz  # pymupdf
import yaml

RENDER_DPI = 150
BBOX_UNIT = 1000.0

# Mangling heuristic thresholds derived from the cross-band audit. A table
# qualifies as mangled when either (a) a large fraction of cells contain
# runs of text too long to be a real cell, or (b) row column counts are
# badly inconsistent (MinerU merged columns into a single cell on many
# rows). Tables smaller than ``MIN_CELLS_FOR_DETECTION`` cells are ignored
# so two-cell labels don't trip the ratio.
LONG_CELL_CHARS = 200
LONG_CELL_RATIO = 0.4
INCONSISTENCY_RATIO = 0.5
MIN_CELLS_FOR_DETECTION = 4

_ROW_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr\s*>", re.DOTALL | re.IGNORECASE)
_CELL_RE = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]\s*>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


def _cell_text_length(cell_html: str) -> int:
    return len(_TAG_RE.sub("", cell_html).strip())


def is_table_mangled(html: str) -> bool:
    """Return True if the HTML table is structurally broken enough that
    its inlined rendering is unreadable.

    Parses rows and cells with forgiving regexes (MinerU output is a
    reliable subset of HTML) and applies the long-cell / column-count
    heuristics documented at module top.
    """
    rows = _ROW_RE.findall(html)
    if not rows:
        return False
    row_cell_counts: list[int] = []
    long_cells = 0
    total_cells = 0
    for row_html in rows:
        cells = _CELL_RE.findall(row_html)
        if not cells:
            continue
        row_cell_counts.append(len(cells))
        for cell in cells:
            total_cells += 1
            if _cell_text_length(cell) >= LONG_CELL_CHARS:
                long_cells += 1
    if total_cells < MIN_CELLS_FOR_DETECTION or not row_cell_counts:
        return False
    max_cols = max(row_cell_counts)
    off_rows = sum(1 for c in row_cell_counts if c != max_cols)
    inconsistency = off_rows / len(row_cell_counts)
    long_ratio = long_cells / total_cells
    return long_ratio >= LONG_CELL_RATIO or inconsistency >= INCONSISTENCY_RATIO


def load_config() -> dict[str, Any]:
    """Load configuration from config.yaml."""
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path, encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f)
        return data


def resolve_pdf_path(base_path: Path, content_list_path: Path) -> Path | None:
    """Derive the source PDF location from the content_list filename.

    MinerU names ``<stem>_content_list.json`` alongside images; the
    corresponding PDF sits at the repo root as ``<stem>.pdf``.
    """
    stem = content_list_path.name.removesuffix("_content_list.json")
    candidate = base_path / f"{stem}.pdf"
    return candidate if candidate.is_file() else None


def find_content_list(volume_path: Path) -> Path | None:
    auto_dir = volume_path / "auto"
    if not auto_dir.is_dir():
        return None
    for p in sorted(auto_dir.glob("*_content_list.json")):
        if "_v2" not in p.name:
            return p
    return None


def render_for_volume(
    volume_config: dict[str, Any], base_path: Path
) -> tuple[int, int, int]:
    """Return (rendered, n_empty, n_mangled) for one volume."""
    volume_id = volume_config["id"]
    volume_path = base_path / volume_config["folder"]

    cl_path = find_content_list(volume_path)
    if cl_path is None:
        print(f"  {volume_id}: no content_list.json, skipping")
        return 0, 0, 0
    pdf_path = resolve_pdf_path(base_path, cl_path)
    if pdf_path is None:
        print(f"  {volume_id}: source PDF not found for {cl_path.name}, skipping")
        return 0, 0, 0

    with cl_path.open(encoding="utf-8") as f:
        content_list: list[dict[str, Any]] = json.load(f)

    # Assign a 0-based position within each page to every table entry (in
    # content_list order). Recoverable tables consume positions too so the
    # numbering stays aligned with build_tables.py / finalize_pages.py.
    page_counters: dict[int, int] = {}
    targets: list[tuple[int, int, list[float], str]] = []
    n_empty = 0
    n_mangled = 0
    for entry in content_list:
        if entry.get("type") != "table":
            continue
        page_idx = int(entry.get("page_idx", -1))
        if page_idx < 0:
            continue
        pos = page_counters.get(page_idx, 0)
        page_counters[page_idx] = pos + 1
        body = (entry.get("table_body") or "").strip()
        img = (entry.get("img_path") or "").strip()
        bbox = entry.get("bbox") or []
        if len(bbox) != 4:
            continue
        if not body and not img:
            kind = "empty"
            n_empty += 1
        elif body and is_table_mangled(body):
            kind = "mangled"
            n_mangled += 1
        else:
            continue
        targets.append((page_idx, pos, list(map(float, bbox)), kind))

    figures_dir = base_path / "rs_smp_corpus" / "volumes" / volume_id / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    # Clear previous fallback artefacts for idempotent re-runs.
    for old in figures_dir.glob("table_fallback_p*_*.png"):
        old.unlink()
    sidecar = figures_dir / "_table_fallbacks.json"
    if sidecar.is_file():
        sidecar.unlink()

    if not targets:
        print(f"  {volume_id}: 0 fallback tables")
        return 0, 0, 0

    index: dict[str, dict[str, dict[str, str]]] = {}
    rendered = 0
    with fitz.open(str(pdf_path)) as pdf:
        for page_idx, pos, bbox, kind in targets:
            if page_idx >= len(pdf):
                continue
            page = pdf[page_idx]
            w, h = page.rect.width, page.rect.height
            clip = fitz.Rect(
                bbox[0] / BBOX_UNIT * w,
                bbox[1] / BBOX_UNIT * h,
                bbox[2] / BBOX_UNIT * w,
                bbox[3] / BBOX_UNIT * h,
            )
            matrix = fitz.Matrix(RENDER_DPI / 72, RENDER_DPI / 72)
            pix = page.get_pixmap(matrix=matrix, clip=clip, alpha=False)
            filename = f"table_fallback_p{page_idx:04d}_{pos}.png"
            pix.save(str(figures_dir / filename))
            index.setdefault(str(page_idx), {})[str(pos)] = {
                "file": filename,
                "kind": kind,
            }
            rendered += 1

    with sidecar.open("w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, sort_keys=True)
        f.write("\n")
    print(
        f"  {volume_id}: rendered {rendered} fallback table images "
        f"({n_empty} empty, {n_mangled} mangled)"
    )
    return rendered, n_empty, n_mangled


def main() -> None:
    print("Rendering PDF-bbox fallbacks for empty/mangled tables...")
    base_path = Path(__file__).parent.parent
    config = load_config()
    total_rendered = 0
    total_empty = 0
    total_mangled = 0
    for volume_config in config["volumes"]:
        rendered, n_empty, n_mangled = render_for_volume(volume_config, base_path)
        total_rendered += rendered
        total_empty += n_empty
        total_mangled += n_mangled
    print(
        f"\n✓ Rendered {total_rendered} table fallbacks "
        f"({total_empty} empty, {total_mangled} mangled)"
    )


if __name__ == "__main__":
    main()

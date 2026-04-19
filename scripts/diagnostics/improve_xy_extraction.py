"""
Diagnostic re-parse of XY-list HTML tables from MinerU.

The original `build_tables.py` parser walked <tr>/<td> rows and required
strict "Designator Side X Y Sqr Pg" alignment in a single row. That fails
on most R&S XY-lists because MinerU shatters the multi-column page layout
across many <td> cells with mismatched colspan/rowspan, even though the
cell-internal text is essentially intact.

This script ignores the table grid entirely. It joins all cell text into
one stream and anchors on two unambiguous tokens:

  designator = [A-Z]{1,3}\\d{1,4}(-[A-Z])?    (R117, D201-A, X10A, K300-B)
  square     = [1-9L]\\d?[A-FL]               (5D, 7A, 11D, LA)

Algorithm (per table):
  1. Get all <td> text in DOM order, joined by " | ".
  2. Find all designator positions and all square positions.
  3. For each designator, take the first square that lies between it and
     the next designator. That bracket gives us a parsable record:
         designator | [side] [X] [Y] | square [page]
  4. Parse the small "middle" between designator and square as:
         optional [AB] side, optional signed integer X, optional integer Y.
     Each is permitted to be a $$$ placeholder.

The script writes a per-file report and prints aggregate stats.
"""

import re
from pathlib import Path
from typing import Any

import yaml

try:
    from bs4 import BeautifulSoup
except ImportError as exc:
    raise SystemExit("Missing dependency: pip install beautifulsoup4") from exc


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

DES_RE = re.compile(r"\b([A-Z]{1,3}\d{1,4}(?:-[A-Z])?)\b")
SQR_RE = re.compile(r"\b((?:[1-9L]|1\d)[A-FLc])\b")
SIDE_RE = re.compile(r"\b([AB])\b")
COORD_RE = re.compile(r"(-?\d{1,3}|\$+)")
PAGE_RE = re.compile(r"^\s*(\d{1,2})\b")

FM_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)
HTML_BLOCK_RE = re.compile(r"```html\s*(.*?)\s*```", re.DOTALL)


def is_real_designator(token: str) -> bool:
    m = re.match(r"^([A-Z]+)", token)
    if not m:
        return False
    return m.group(1) in _DESIGNATOR_PREFIXES


def parse_middle(middle: str) -> tuple[str | None, str | None, str | None]:
    """Pull out (side, x, y) from the text between a designator and its
    matching square. All three are optional. Order is fixed: side, then x,
    then y."""
    s = middle.strip()
    side = None
    side_match = SIDE_RE.match(s)
    if side_match:
        side = side_match.group(1)
        s = s[side_match.end() :].strip()
    elif s and s[0] in "AB" and len(s) > 1 and (s[1].isdigit() or s[1] == "-"):
        # side glued to a numeric X like "B229"
        side = s[0]
        s = s[1:].strip()
    coords = COORD_RE.findall(s)
    x = coords[0] if len(coords) >= 1 else None
    y = coords[1] if len(coords) >= 2 else None
    return side, x, y


def parse_slice(slice_text: str) -> dict[str, str]:
    """Parse the text between a designator and the next designator into
    {side, x, y, square, page}. All fields are optional. Strategy:
      1. Pull leading [AB] side (may be glued to a numeric X).
      2. If a square token (e.g. '5D', '11A') appears anywhere in the slice,
         use it as a strong anchor: numbers before it are X/Y, the first
         number after it is the page.
      3. Otherwise treat the slice as a flat sequence of numbers and assume
         the first two are X/Y. Page is left blank.
    """
    rec = {"side": "", "x": "", "y": "", "square": "", "page": ""}
    s = slice_text.strip()
    if not s:
        return rec

    side_m = re.match(r"^([AB])(?:\b|(?=[-\d]))", s)
    if side_m:
        rec["side"] = side_m.group(1)
        s = s[side_m.end() :].lstrip(" |")

    sqr_m = SQR_RE.search(s)
    if sqr_m:
        rec["square"] = sqr_m.group(1)
        before, after = s[: sqr_m.start()], s[sqr_m.end() :]
        coords = COORD_RE.findall(before)
        if coords:
            rec["x"] = coords[0]
        if len(coords) >= 2:
            rec["y"] = coords[1]
        pg_m = PAGE_RE.match(after.lstrip(" |"))
        if pg_m:
            rec["page"] = pg_m.group(1)
    else:
        coords = COORD_RE.findall(s)
        if coords:
            rec["x"] = coords[0]
        if len(coords) >= 2:
            rec["y"] = coords[1]
    return rec


def has_spatial_data(rec: dict[str, str]) -> bool:
    return bool(rec["square"] or (rec["x"] and rec["y"]))


def extract_records(html: str) -> tuple[list[dict[str, str]], list[str]]:
    """Return (full_records, designator_only_list).

    A record dict has keys: designator, side, x, y, square, page.
    'full' = has_spatial_data() returns True (square or X+Y present).
    Otherwise the designator is reported in `designator_only`.
    """
    soup = BeautifulSoup(html, "html.parser")
    cell_texts = [td.get_text(" ", strip=True) for td in soup.find_all("td")]
    text = " | ".join(cell_texts)

    des_matches = [m for m in DES_RE.finditer(text) if is_real_designator(m.group(1))]

    records: list[dict[str, str]] = []
    designator_only: list[str] = []

    for i, des in enumerate(des_matches):
        des_token = des.group(1)
        next_pos = des_matches[i + 1].start() if i + 1 < len(des_matches) else len(text)
        slice_text = text[des.end() : next_pos]
        rec = parse_slice(slice_text)
        rec["designator"] = des_token
        if has_spatial_data(rec):
            records.append(rec)
        else:
            designator_only.append(des_token)

    return records, designator_only


def read_md_file(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_text(encoding="utf-8")
    m = FM_RE.match(raw)
    if not m:
        return {}, ""
    fm: dict[str, Any] = yaml.safe_load(m.group(1)) or {}
    body = m.group(2)
    html_match = HTML_BLOCK_RE.search(body)
    return fm, html_match.group(1) if html_match else ""


def main() -> None:
    base = Path(__file__).parent.parent.parent
    files = sorted(
        f
        for f in (base / "rs_smp_corpus" / "volumes").glob("*/tables/*xy-list*.md")
        if "titleblock" not in f.name
    )

    total = len(files)
    sum_old = 0
    sum_new_full = 0
    sum_new_des_only = 0
    improved = 0
    rows_summary: list[str] = []

    for f in files:
        fm, html = read_md_file(f)
        if not html:
            continue
        old_n = int(fm.get("n_components", 0) or 0)
        old_quality = fm.get("extraction_quality", "unknown")
        records, des_only = extract_records(html)
        new_full = len(records)
        new_des_only = len(des_only)
        sum_old += old_n
        sum_new_full += new_full
        sum_new_des_only += new_des_only
        if new_full > old_n and old_quality != "full":
            improved += 1
        rows_summary.append(
            f"  {f.relative_to(base / 'rs_smp_corpus').as_posix():<60s} "
            f"old={old_n:>4d} ({old_quality:<17s}) "
            f"new_full={new_full:>4d}  new_des={new_des_only:>3d}"
        )

    print(f"Scanned {total} XY-list files.")
    print(f"  Old totals:   {sum_old:>5d} components (mostly designators-only)")
    print(f"  New 'full':   {sum_new_full:>5d} (designator + square + ...)")
    print(
        f"  New 'des'-only: {sum_new_des_only:>5d} (designator without locatable square)"
    )
    print(f"  Files improved (new_full > old_n): {improved}/{total}")
    print()
    print("Per-file detail:")
    for line in rows_summary:
        print(line)


if __name__ == "__main__":
    main()

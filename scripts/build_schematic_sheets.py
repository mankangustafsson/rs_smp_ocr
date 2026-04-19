"""
Build rs_smp_corpus/index/schematic_sheets.md — a cross-volume table of schematic sheets
extracted from XY-list titleblock cartouches.

For each xy-list-titleblock file we parse the HTML fragment and try to
recover:
  - the module title text (e.g., "ED RECHNER / PROCESSOR", "MICROWELLEN
    INTERFACE", "ALC VERSTAERKER")
  - the sheet number (e.g., "3", "5", "1") — usually the last non-empty
    cell on the last row, stored as "N+" or "N-".

The R&S cartouche layout across bands is only semi-consistent, so this is
best-effort: we record whatever we recognise and leave unparsed fields
blank. A readable Markdown table is produced for retrieval use.
"""

import re
from pathlib import Path
from typing import Any

import yaml

try:
    from bs4 import BeautifulSoup
except ImportError as exc:
    raise SystemExit("Missing dependency: pip install beautifulsoup4") from exc


FM_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)
SHEET_RE = re.compile(r"^\s*(\d{1,2})\s*[+\-]?\s*$")
STOCK_CELL_RE = re.compile(r"\d{4}\.\d{4}\.\d{2}\s*x[y]?", re.IGNORECASE)

# Tokens that appear in the cartouche header labels. A cell made up ENTIRELY
# of these tokens (after normalization) is discarded as boilerplate.
BOILERPLATE_TOKENS = {
    "ai",
    "al",
    "ed",
    "ee",
    "datum",
    "date",
    "datemdate",
    "datun",
    "bearbeitung",
    "bearb",
    "geproft",
    "gepruft",
    "geprueft",
    "name",
    "urspr",
    "ersatz",
    "fuer",
    "fur",
    "für",
    "sach",
    "nummer",
    "nr",
    "sachnummer",
    "sach-nummer",
    "sach-nr",
    "stock",
    "stock-nr",
    "stock-number",
    "stocknr",
    "blatt",
    "page",
    "sheet",
    "seite",
    "supplement",
    "xy",
    "xy-liste",
    "xyliste",
    "liste",
    "xy-list",
    "xylist",
    "list",
    "for",
    "from",
    "rohde",
    "schwarz",
    "part",
    "partside",
    "side",
    "sqr",
    "pg",
    "+",
    "-",
    "&",
    "amp;",
}

# Any date-looking substring disqualifies a cell from being picked as title.
DATE_SUBSTRING_RE = re.compile(
    r"\d{1,2}[.\|/]\d{1,2}[.\|/]\d{2,4}"
    r"|\d{4,6}[.\|/]\d{1,2}[.\|/]\d{2,4}"
)

# Minimum letters the cell must contain to be considered a module title.
MIN_TITLE_LETTERS = 5


def read_front_matter(path: Path) -> tuple[dict[str, Any], str]:
    content = path.read_text(encoding="utf-8")
    m = FM_RE.match(content)
    if not m:
        return {}, content
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        fm = {}
    return fm, content[m.end() :]


def extract_html_table(body: str) -> str | None:
    """Pull the first ```html block back out of the markdown body."""
    m = re.search(r"```html\s*(.*?)\s*```", body, re.DOTALL)
    return m.group(1) if m else None


def collect_cells(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    cells = []
    for td in soup.find_all("td"):
        text = td.get_text(separator=" ", strip=True)
        cells.append(text)
    return cells


def is_date(cell: str) -> bool:
    return bool(
        re.match(
            r"^\s*\d{1,2}[.\|/]?\d{0,2}\.?\d{0,2}\.\d{2,4}\s*$", cell.replace("|", ".")
        )
    )


def parse_sheet_number(cells: list[str], stock_cell_idx: int) -> int | None:
    """The sheet cell usually sits *just after* the stock-number cell.

    When that's not the case we fall back to "last short numeric cell on
    the row", scanning the tail of the cell list.
    """
    candidates = []
    # Prefer cells that follow the stock cell.
    if stock_cell_idx >= 0:
        candidates.extend(cells[stock_cell_idx + 1 :])
    # Then scan back from the end.
    for c in reversed(cells):
        if c not in candidates:
            candidates.append(c)
    for c in candidates:
        m = SHEET_RE.match(c)
        if m:
            val = int(m.group(1))
            if 0 < val < 30:
                return val
    return None


def _tokenize(cell: str) -> list[str]:
    return [t for t in re.split(r"[^A-Za-zÄÖÜäöüß]+", cell.lower()) if t]


def _is_only_boilerplate(cell: str) -> bool:
    tokens = _tokenize(cell)
    if not tokens:
        return True
    return all(t in BOILERPLATE_TOKENS for t in tokens)


def parse_module_title(cells: list[str]) -> str | None:
    """Pick the most module-like cell: has letters, is not purely made of
    cartouche header tokens, and contains no date substring or stock number."""
    best = None
    best_score = 0
    for cell in cells:
        stripped = cell.strip()
        if not stripped:
            continue
        if STOCK_CELL_RE.search(stripped):
            continue
        if DATE_SUBSTRING_RE.search(stripped):
            continue
        if re.fullmatch(r"[\d\s+\-|]+", stripped):
            continue
        letters = re.findall(r"[A-Za-zÄÖÜäöüß]", stripped)
        if len(letters) < MIN_TITLE_LETTERS:
            continue
        if _is_only_boilerplate(stripped):
            continue
        # Score on "non-boilerplate-letter density" so cells dominated by
        # the module name beat cells that are mostly header text.
        tokens = _tokenize(stripped)
        non_bp_letters = sum(len(t) for t in tokens if t not in BOILERPLATE_TOKENS)
        if non_bp_letters > best_score:
            best_score = non_bp_letters
            best = stripped
    return best


def find_stock_cell(cells: list[str]) -> int:
    for i, c in enumerate(cells):
        if STOCK_CELL_RE.search(c):
            return i
    return -1


def main() -> None:
    base = Path(__file__).parent.parent
    rows: list[dict[str, Any]] = []

    for tb_file in sorted(
        (base / "rs_smp_corpus" / "volumes").glob("*/tables/*xy-list-titleblock*.md")
    ):
        fm, body = read_front_matter(tb_file)
        html = extract_html_table(body)
        if html is None:
            continue
        cells = collect_cells(html)
        stock_idx = find_stock_cell(cells)
        sheet = parse_sheet_number(cells, stock_idx)
        title = parse_module_title(cells)
        rows.append(
            {
                "volume": fm.get("volume", ""),
                "page": fm.get("page", 0),
                "stock": fm.get("stock_number", ""),
                "sheet": sheet,
                "title": title or "",
                "file": tb_file.relative_to(base / "rs_smp_corpus").as_posix(),
            }
        )

    rows.sort(key=lambda r: (r["volume"], int(r["page"])))

    lines = [
        "# Schematic Sheets Index",
        "",
        "Cross-volume map of every XY-list schematic sheet recovered from "
        "titleblock cartouches. `sheet` is the sheet number printed in the "
        "R&S title block (often noisy due to OCR). `title` is the module "
        "name string from the same cartouche — typically bilingual and "
        "concatenated without spaces where the OCR lost the column split.",
        "",
        "Source: every `*_xy-list-titleblock_*.md` under `rs_smp_corpus/volumes/`.",
        "",
        "| Volume | Page | Stock Number | Sheet | Module Title (from cartouche) | File |",
        "|--------|-----:|--------------|------:|-------------------------------|------|",
    ]
    for r in rows:
        sheet_cell = str(r["sheet"]) if r["sheet"] is not None else ""
        # Escape pipes inside cell text.
        title = r["title"].replace("|", "/")
        lines.append(
            f"| {r['volume']} | {r['page']} | `{r['stock']}` | "
            f"{sheet_cell} | {title} | `{r['file']}` |"
        )

    lines.extend(
        [
            "",
            f"**Total titleblocks indexed:** {len(rows)}",
            f"**Sheets with parsed sheet-number:** "
            f"{sum(1 for r in rows if r['sheet'] is not None)}",
            f"**Sheets with parsed module title:** "
            f"{sum(1 for r in rows if r['title'])}",
        ]
    )

    out = base / "rs_smp_corpus" / "index" / "schematic_sheets.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\u2713 Wrote {out}")
    print(f"  Indexed {len(rows)} titleblocks.")


if __name__ == "__main__":
    main()

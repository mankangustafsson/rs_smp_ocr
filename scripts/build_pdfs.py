"""
Generate searchable A4 PDFs from the curated bilingual corpus.

For each band service-manual volume, produces one PDF:
- <band>.pdf  all pages (DE + EN)

Pipeline: YAML front matter filter -> markdown-it-py -> HTML ->
playwright / Chromium headless -> PDF. Chromium emits a /Outlines entry
per <h1..h3>, so headings become searchable bookmarks.

Usage:
    python scripts/build_pdfs.py
    python scripts/build_pdfs.py --volume band-1
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from markdown_it import MarkdownIt
from mdit_py_plugins.anchors import anchors_plugin
from playwright.sync_api import Browser, sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_ROOT = REPO_ROOT / "rs_smp_corpus"
CSS_PATH = REPO_ROOT / "assets" / "pdf.css"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "band_pdfs"
CONFIG_PATH = REPO_ROOT / "scripts" / "config.yaml"

FM_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
IMG_SRC_RE = re.compile(r'src="([^"]+)"')
SUBHEADING_RE = re.compile(
    r"^\s*(\d+\.\d+(?:\.\d+){0,3})\s+([A-Za-zÄÖÜäöüß][^\n]*?)\s*$"
)
H1_PAGE_PREFIX_RE = re.compile(
    r"^(#[ \t]+.+?)[ \t]*—[ \t]*p\.\d+[ \t]*—[ \t]+",
    re.MULTILINE,
)
H1_PAGE_SUFFIX_RE = re.compile(
    r"^(#[ \t]+.+?)[ \t]*—[ \t]*p\.\d+[ \t]*$",
    re.MULTILINE,
)
TABLE_PLACEHOLDER = "[TABLE: See tables/ directory]"
TABLE_HTML_RE = re.compile(r"```html\s*\n(.+?)\n```", re.DOTALL)
FIGURE_PLACEHOLDER_RE = re.compile(r"\[FIGURE:\s*images/([0-9a-f]+)\.(\w+)\]")
H1_LINE_RE = re.compile(r"^# +(.+?)[ \t]*$", re.MULTILINE)
INLINE_MATH_RE = re.compile(r"\$([^$\n]{1,200})\$")
MATH_FONT_RE = re.compile(
    r"\\(?:mathrm|mathsf|mathbf|mathit|text|operatorname)\s*\{\s*([^{}]*?)\s*\}"
)
MATH_SUBGROUP_RE = re.compile(r"_\s*\{\s*([^{}]*?)\s*\}")
MATH_SUPGROUP_RE = re.compile(r"\^\s*\{\s*([^{}]*?)\s*\}")
MATH_SUBCHAR_RE = re.compile(r"_([A-Za-z0-9])")
MATH_SUPCHAR_RE = re.compile(r"\^([A-Za-z0-9])")
TABLE_BLOCK_RE = re.compile(r"<table\b[^>]*>.*?</table>", re.DOTALL | re.IGNORECASE)
TR_OPEN_RE = re.compile(r"<tr\b", re.IGNORECASE)
TR_CONTENT_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
CELL_OPEN_RE = re.compile(r"<t[dh]\b", re.IGNORECASE)
ROWSPAN_ATTR_RE = re.compile(r'\s+rowspan="(\d+)"', re.IGNORECASE)
COLSPAN_ATTR_RE = re.compile(r'\s+colspan="(\d+)"', re.IGNORECASE)
CELL_BLOCK_RE = re.compile(
    r"(<t[dh]\b[^>]*>)(.*?)(</t[dh]>)", re.DOTALL | re.IGNORECASE
)
RUN_50_RE = re.compile(r"(.)\1{49,}")
ALNUM_RE = re.compile(r"[0-9A-Za-z]")

_HASH_MAP_CACHE: dict[Path, dict[str, str]] = {}

VARIANTS: dict[str, Callable[[str], bool]] = {
    "bilingual": lambda lang: True,
}


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open(encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f)
    return data


def read_front_matter(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    m = FM_RE.match(text)
    if not m:
        return {}, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        fm = {}
    if not isinstance(fm, dict):
        fm = {}
    return fm, text[m.end() :]


def make_renderer() -> MarkdownIt:
    md = MarkdownIt("commonmark", {"html": True, "breaks": False})
    md.enable(["table", "strikethrough"])
    md.use(anchors_plugin, min_level=1, max_level=4, permalink=False)
    return md


def rewrite_image_paths(html: str, page_dir: Path) -> str:
    def repl(m: re.Match[str]) -> str:
        src = m.group(1)
        if src.startswith(("http://", "https://", "file://", "data:")):
            return m.group(0)
        return f'src="{(page_dir / src).resolve().as_uri()}"'

    return IMG_SRC_RE.sub(repl, html)


def promote_subheadings(body: str) -> str:
    """Promote standalone ``N.N[.N...] Title`` paragraphs to ``### ...`` so that
    numbered service-manual subheadings (e.g. ``6.1.10 A21 Sampling Module``)
    render as bold headings rather than plain body text. Multi-line blocks
    such as table-of-contents lists are left untouched.
    """
    blocks = re.split(r"(\n[ \t]*\n)", body)
    for i, block in enumerate(blocks):
        core = block.strip("\n")
        if not core or "\n" in core.strip():
            continue
        m = SUBHEADING_RE.match(core)
        if not m:
            continue
        leading = block[: len(block) - len(block.lstrip("\n"))]
        trailing = block[len(block.rstrip("\n")) :]
        blocks[i] = f"{leading}### {m.group(1)} {m.group(2)}{trailing}"
    return "".join(blocks)


def strip_h1_page_prefix(body: str) -> str:
    """Drop the page-number fragment from per-page H1s in either position:
    ``— p.N —`` as a mid-title separator or ``— p.N`` at end of line. The
    page number is already encoded in the source filename and frontmatter.
    """
    body = H1_PAGE_PREFIX_RE.sub(r"\1 — ", body)
    body = H1_PAGE_SUFFIX_RE.sub(r"\1", body)
    return body


def strip_duplicate_h1_body(body: str) -> str:
    """Drop the first paragraph that repeats the H1 verbatim. OCR frequently
    emits the page title as both the heading and the opening body line.
    """
    m = H1_LINE_RE.search(body)
    if not m:
        return body
    title = m.group(1).strip()
    if not title:
        return body
    tail = body[m.end() :]
    lead = len(tail) - len(tail.lstrip("\n"))
    rest = tail[lead:]
    end = rest.find("\n\n")
    para_block = rest if end == -1 else rest[:end]
    if para_block.strip() == title:
        drop = lead + len(para_block) + (2 if end != -1 else 0)
        return body[: m.end()] + "\n\n" + tail[drop:]
    return body


def _render_math_inline(expr: str) -> str:
    """Convert a small LaTeX subset (``\\mathrm{X}``, ``_{X}``, ``^{X}``) to
    inline HTML. Anything that doesn't look like math (HTML tags inside,
    no sub/super/command markers) is returned with the ``$`` delimiters so
    it stays visible rather than silently dropped.
    """
    if "<" in expr or ">" in expr:
        return f"${expr}$"
    if not re.search(r"[_^\\]", expr):
        return f"${expr}$"
    s = MATH_FONT_RE.sub(r"\1", expr)
    s = MATH_SUBGROUP_RE.sub(r"<sub>\1</sub>", s)
    s = MATH_SUPGROUP_RE.sub(r"<sup>\1</sup>", s)
    s = MATH_SUBCHAR_RE.sub(r"<sub>\1</sub>", s)
    s = MATH_SUPCHAR_RE.sub(r"<sup>\1</sup>", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def render_inline_math(body: str) -> str:
    """Replace ``$…$`` spans with best-effort HTML. No MathJax is loaded in
    the PDF renderer, so raw LaTeX would otherwise show verbatim.
    """
    if "$" not in body:
        return body
    return INLINE_MATH_RE.sub(lambda m: _render_math_inline(m.group(1)), body)


def sanitize_table_spans(body: str) -> str:
    """Drop ``rowspan``/``colspan`` attributes whose value exceeds the actual
    row/column count of their table. OCR occasionally emits values like
    ``rowspan="791"`` that balloon the rendered table with empty rows.
    """
    if "<table" not in body.lower():
        return body

    def fix_table(match: re.Match[str]) -> str:
        block = match.group(0)
        n_rows = len(TR_OPEN_RE.findall(block))
        row_contents = TR_CONTENT_RE.findall(block)
        n_cols = max((len(CELL_OPEN_RE.findall(r)) for r in row_contents), default=1)
        max_rs = max(n_rows, 2)
        max_cs = max(n_cols, 2)
        block = ROWSPAN_ATTR_RE.sub(
            lambda mm: "" if int(mm.group(1)) > max_rs else mm.group(0), block
        )
        block = COLSPAN_ATTR_RE.sub(
            lambda mm: "" if int(mm.group(1)) > max_cs else mm.group(0), block
        )
        return block

    return TABLE_BLOCK_RE.sub(fix_table, body)


def _is_runaway(text: str) -> bool:
    """Heuristic: the cell is either a long run of the same character (e.g.
    ``0000\u2026``) or an ASCII-art ruler dominated by punctuation (e.g.
    ``+----+----+\u2026``). Legitimate prose has neither property.
    """
    stripped = re.sub(r"\s+", "", text)
    if len(stripped) < 200:
        return False
    if RUN_50_RE.search(stripped):
        return True
    alnum = len(ALNUM_RE.findall(stripped))
    return (len(stripped) - alnum) / len(stripped) >= 0.7


def truncate_runaway_cells(body: str) -> str:
    """Replace runaway cell contents (OCR artefacts such as ASCII-art rulers
    or multi-thousand-character digit runs) with a short elided marker so the
    table lays out at page width instead of overflowing.
    """
    if "<table" not in body.lower():
        return body

    def fix_cell(m: re.Match[str]) -> str:
        open_tag, inner, close_tag = m.group(1), m.group(2), m.group(3)
        if not _is_runaway(inner):
            return m.group(0)
        head = inner.lstrip()[:32]
        tail = inner.rstrip()[-8:]
        note = f"{head} \u2026 [{len(inner)} chars elided] \u2026 {tail}"
        return f"{open_tag}{note}{close_tag}"

    return CELL_BLOCK_RE.sub(fix_cell, body)


def _render_inlined_table(tfm: dict[str, Any], thtml: str) -> str:
    caption = str(tfm.get("caption", "")).strip()
    assembly = str(tfm.get("assembly", "")).strip()
    label = " — ".join(x for x in (assembly, caption) if x)
    cap_html = f"<figcaption>{label}</figcaption>" if label else ""
    return f'\n\n<figure class="inlined-table">{cap_html}{thtml}</figure>\n\n'


def inline_tables(body: str, page_file: Path, fm: dict[str, Any]) -> str:
    """Replace ``[TABLE: See tables/ directory]`` placeholders with the raw
    HTML from the matching per-page table files under ``../tables/``.
    Placeholders are paired with tables in filename-sorted order.
    """
    if TABLE_PLACEHOLDER not in body:
        return body
    page = fm.get("page")
    if not isinstance(page, int):
        return body
    tables_dir = page_file.parent.parent / "tables"
    if not tables_dir.is_dir():
        return body
    rendered: list[str] = []
    for tf in sorted(tables_dir.glob(f"p{page:04d}_*.md")):
        tfm, tbody = read_front_matter(tf)
        m = TABLE_HTML_RE.search(tbody)
        if not m:
            continue
        rendered.append(_render_inlined_table(tfm, m.group(1).strip()))
    if not rendered:
        return body
    it = iter(rendered)

    def _sub(_m: re.Match[str]) -> str:
        return next(it, "")

    return re.sub(re.escape(TABLE_PLACEHOLDER), _sub, body)


def _load_hash_map(figures_dir: Path) -> dict[str, str]:
    cached = _HASH_MAP_CACHE.get(figures_dir)
    if cached is not None:
        return cached
    path = figures_dir / "_hash_map.json"
    if not path.is_file():
        _HASH_MAP_CACHE[figures_dir] = {}
        return {}
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    mapping = (
        {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    )
    _HASH_MAP_CACHE[figures_dir] = mapping
    return mapping


def inline_figures(body: str, page_file: Path) -> str:
    """Replace ``[FIGURE: images/<hash>.<ext>]`` placeholders with an inline
    ``<img>`` pointing at the curated file under ``../figures/``.
    Unresolvable hashes are left as-is so the gap remains visible.
    """
    if "[FIGURE:" not in body:
        return body
    figures_dir = page_file.parent.parent / "figures"
    hash_map = _load_hash_map(figures_dir)
    if not hash_map:
        return body

    def _sub(m: re.Match[str]) -> str:
        curated = hash_map.get(m.group(1))
        if not curated:
            return m.group(0)
        rel = (figures_dir / curated).resolve().as_uri()
        return (
            f'\n\n<figure class="inlined-figure">'
            f'<img src="{rel}" alt="Figure"></figure>\n\n'
        )

    return FIGURE_PLACEHOLDER_RE.sub(_sub, body)


def render_page(md: MarkdownIt, page_file: Path, fm: dict[str, Any], body: str) -> str:
    processed = inline_tables(body, page_file, fm)
    processed = inline_figures(processed, page_file)
    processed = sanitize_table_spans(processed)
    processed = truncate_runaway_cells(processed)
    processed = strip_duplicate_h1_body(strip_h1_page_prefix(processed))
    processed = promote_subheadings(processed)
    processed = render_inline_math(processed)
    html = md.render(processed)
    return rewrite_image_paths(html, page_file.parent)


def filter_pages(
    pages_dir: Path, predicate: Callable[[str], bool]
) -> list[tuple[Path, dict[str, Any], str]]:
    selected: list[tuple[Path, dict[str, Any], str]] = []
    for md_file in sorted(pages_dir.glob("p*.md")):
        fm, body = read_front_matter(md_file)
        if predicate(str(fm.get("language", ""))):
            selected.append((md_file, fm, body))
    return selected


def build_document(
    pages: list[tuple[Path, dict[str, Any], str]],
    volume: dict[str, Any],
    variant: str,
    css: str,
) -> str:
    md = make_renderer()
    parts: list[str] = []
    for page_file, fm, body in pages:
        parts.append(
            f'<section class="page">\n{render_page(md, page_file, fm, body)}\n</section>'
        )
    title = str(volume.get("title_en") or volume["id"])
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{title}</title><style>{css}</style></head><body>"
        f'<section class="cover"><h1>{title}</h1></section>'
        + "".join(parts)
        + "</body></html>"
    )


def render_pdf(
    browser: Browser, html: str, output: Path, footer: str, html_path: Path
) -> None:
    # Chromium blocks file:// subresources when the document origin is
    # about:blank (what set_content produces). Write the HTML next to the
    # referenced figures and navigate to a file:// URL so <img> tags resolve.
    html_path.write_text(html, encoding="utf-8")
    page = browser.new_page()
    try:
        page.goto(html_path.resolve().as_uri(), wait_until="load")
        page.emulate_media(media="print")
        page.pdf(
            path=str(output),
            format="A4",
            margin={"top": "20mm", "right": "18mm", "bottom": "22mm", "left": "18mm"},
            print_background=True,
            display_header_footer=True,
            header_template="<div></div>",
            footer_template=footer,
            tagged=True,
            outline=True,
        )
    finally:
        page.close()


FOOTER_TEMPLATE = (
    '<div style="font-size:8pt; color:#666; width:100%; padding:0 18mm;'
    ' font-family:Arial,sans-serif; display:flex; justify-content:space-between;">'
    "<span>{title}</span>"
    '<span class="pageNumber"></span> / <span class="totalPages"></span>'
    "</div>"
)


def build_one(
    browser: Browser, volume: dict[str, Any], variant: str, css: str, output_dir: Path
) -> tuple[Path, int]:
    vol_id = str(volume["id"])
    vol_dir = CORPUS_ROOT / "volumes" / vol_id
    pages_dir = vol_dir / "pages"
    if not pages_dir.is_dir():
        raise FileNotFoundError(f"Pages dir missing: {pages_dir}")
    pages = filter_pages(pages_dir, VARIANTS[variant])
    html = build_document(pages, volume, variant, css)
    title = str(volume.get("title_en") or vol_id)
    footer = FOOTER_TEMPLATE.replace("{title}", title)
    out = output_dir / f"{vol_id}.pdf"
    html_tmp = vol_dir / f"_{vol_id}.pdf.html"
    try:
        render_pdf(browser, html, out, footer, html_tmp)
    finally:
        html_tmp.unlink(missing_ok=True)
    return out, len(pages)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--volume", choices=["band-1", "band-2", "band-3", "band-4"])
    ap.add_argument("--variant", choices=list(VARIANTS))
    ap.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = ap.parse_args()

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    css = CSS_PATH.read_text(encoding="utf-8")

    bands = {"band-1", "band-2", "band-3", "band-4"}
    volumes = [v for v in load_config()["volumes"] if v["id"] in bands]
    if args.volume:
        volumes = [v for v in volumes if v["id"] == args.volume]
    variants = [args.variant] if args.variant else list(VARIANTS)

    print(f"=== build_pdfs: {len(volumes)} volume(s) x {len(variants)} variant(s) ===")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for volume in volumes:
                for variant in variants:
                    out, n = build_one(browser, volume, variant, css, output_dir)
                    size_mb = out.stat().st_size / (1024 * 1024)
                    rel = out.relative_to(REPO_ROOT)
                    print(f"  \u2713 {rel}  ({n} pages, {size_mb:.1f} MB)")
        finally:
            browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

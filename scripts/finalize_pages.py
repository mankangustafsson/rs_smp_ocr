"""
Finalize page markdown files by inlining tables and figures.

Reads the generated artefacts from build_tables.py and build_figures.py and
rewrites the placeholders emitted by build_pages.py so each page under
rs_smp_corpus/volumes/<vol>/pages/p*.md renders with the real content in
any markdown viewer (GitHub, VSCode, ...).

- Replaces each ``[TABLE: See tables/ directory]`` with the matching HTML
  table pulled from ``../tables/p<NNNN>_*.md`` (filename-sorted pairing).
- Replaces each ``[FIGURE: images/<hash>.<ext>]`` with a markdown image
  reference resolved through ``../figures/_hash_map.json``.
- Idempotent: pages without placeholders are left untouched.

Usage:
    python finalize_pages.py
"""

import json
import re
from pathlib import Path
from typing import Any

import yaml

FM_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
TABLE_PLACEHOLDER = "[TABLE: See tables/ directory]"
TABLE_UNAVAILABLE = "*(Table omitted: OCR did not extract cell content.)*"
TABLE_FALLBACK_CAPTION = (
    "**Table (rendered from PDF; OCR did not extract cell content)**"
)
TABLE_MANGLED_CAPTION = (
    "**Table (rendered from PDF; OCR text retained below for search)**"
)
TABLE_HTML_RE = re.compile(r"```html\s*\n(.+?)\n```", re.DOTALL)
FIGURE_PLACEHOLDER_RE = re.compile(r"\[FIGURE:\s*images/([0-9a-f]+)\.(\w+)\]")
SUBHEADING_RE = re.compile(
    r"^\s*(\d+\.\d+(?:\.\d+){0,3})\s+([A-Za-zÄÖÜäöüß][^\n]*?)\s*$"
)


def split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    m = FM_RE.match(text)
    if not m:
        return {}, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        fm = {}
    return fm, text[m.end() :]


def read_front_matter(path: Path) -> tuple[dict[str, Any], str]:
    return split_front_matter(path.read_text(encoding="utf-8"))


def load_hash_map(figures_dir: Path) -> dict[str, str]:
    hm_path = figures_dir / "_hash_map.json"
    if not hm_path.is_file():
        return {}
    with hm_path.open(encoding="utf-8") as f:
        data: dict[str, str] = json.load(f)
    return data


def load_figure_captions(figures_dir: Path) -> dict[str, str]:
    """Return ``{curated_image_filename: caption}`` for every figure stub
    that carries a non-empty ``caption`` in front matter. Used to surface
    the caption next to the inlined image on the page body.
    """
    captions: dict[str, str] = {}
    if not figures_dir.is_dir():
        return captions
    for stub in figures_dir.glob("p*.md"):
        fm, _ = read_front_matter(stub)
        image_file = str(fm.get("image_file", "")).strip()
        caption = str(fm.get("caption", "")).strip()
        if image_file and caption:
            captions[image_file] = caption
    return captions


def load_table_fallbacks(
    figures_dir: Path,
) -> dict[int, dict[int, dict[str, str]]]:
    """Load the sidecar produced by render_table_fallbacks.py.

    Returns ``{page_idx: {position: {"file": png, "kind": empty|mangled}}}``.
    Missing file yields an empty mapping so callers degrade gracefully.
    """
    fb_path = figures_dir / "_table_fallbacks.json"
    if not fb_path.is_file():
        return {}
    with fb_path.open(encoding="utf-8") as f:
        raw: dict[str, dict[str, dict[str, str]]] = json.load(f)
    out: dict[int, dict[int, dict[str, str]]] = {}
    for page_key, positions in raw.items():
        try:
            pg = int(page_key)
        except ValueError:
            continue
        out[pg] = {int(p): dict(v) for p, v in positions.items()}
    return out


def render_inlined_table(fm: dict[str, Any], html: str) -> str:
    """HTML table wrapped with a bold caption line that renders in
    GitHub/VSCode markdown and keeps the raw OCR structure intact.

    The ``assembly`` field in ``build_tables.py`` front matter is a
    heuristic that produces noise (``RESET``, ``BASIC``, ``ROHDE``,
    column-header fragments, ...) and is not used here. Diagnostics and
    index builders still read it from front matter when they need it;
    the rendered page body only shows MinerU's explicit ``caption``.
    """
    caption = str(fm.get("caption", "")).strip()
    parts: list[str] = []
    if caption:
        parts.append(f"**{caption}**")
        parts.append("")
    parts.append(html.strip())
    return "\n".join(parts)


def inline_tables(
    body: str,
    page_file: Path,
    fm: dict[str, Any],
    fallbacks: dict[int, dict[int, dict[str, str]]],
) -> str:
    """Replace every ``[TABLE: ...]`` placeholder.

    Placeholders are paired positionally with the rendered tables in
    ``../tables/``: each table file carries its content-list position on the
    page via the ``page_position`` front-matter field.

    Fallback sidecar (``../figures/_table_fallbacks.json``) records PNG
    crops of the PDF region. Two kinds are handled:

    - ``empty``   — no HTML exists; the PNG replaces the placeholder.
    - ``mangled`` — HTML exists but is structurally broken; the PNG is
      emitted above the HTML so readers see the clean table while the OCR
      text stays in the file for search indexing (visual+text mode).

    If neither HTML nor fallback is present, ``TABLE_UNAVAILABLE`` is used
    so the page never renders with the literal placeholder string.
    """
    placeholder_count = body.count(TABLE_PLACEHOLDER)
    if placeholder_count == 0:
        return body
    page = fm.get("page")
    if not isinstance(page, int):
        return body
    tables_dir = page_file.parent.parent / "tables"
    by_pos: dict[int, str] = {}
    unpositioned: list[str] = []
    if tables_dir.is_dir():
        for tf in sorted(tables_dir.glob(f"p{page:04d}_*.md")):
            tfm, tbody = read_front_matter(tf)
            m = TABLE_HTML_RE.search(tbody)
            if not m:
                continue
            html = render_inlined_table(tfm, m.group(1).strip())
            pos = tfm.get("page_position")
            if isinstance(pos, int):
                by_pos[pos] = html
            else:
                unpositioned.append(html)
    fb_for_page = fallbacks.get(page, {})
    replacements: list[str] = []
    for i in range(placeholder_count):
        inlined = by_pos.get(i)
        fb = fb_for_page.get(i)
        if inlined and fb and fb.get("kind") == "mangled":
            img = f"![Table](../figures/{fb['file']})"
            replacements.append(f"{TABLE_MANGLED_CAPTION}\n\n{img}\n\n{inlined}")
        elif inlined:
            replacements.append(inlined)
        elif fb:
            replacements.append(
                f"{TABLE_FALLBACK_CAPTION}\n\n![Table](../figures/{fb['file']})"
            )
        elif unpositioned:
            replacements.append(unpositioned.pop(0))
        else:
            replacements.append(TABLE_UNAVAILABLE)
    it = iter(replacements)

    def _sub(_m: re.Match[str]) -> str:
        return next(it)

    return re.sub(re.escape(TABLE_PLACEHOLDER), _sub, body)


def inline_figures(
    body: str,
    page_file: Path,
    hash_map: dict[str, str],
    captions: dict[str, str],
) -> str:
    if "[FIGURE:" not in body or not hash_map:
        return body

    def _sub(m: re.Match[str]) -> str:
        curated = hash_map.get(m.group(1))
        if not curated:
            return m.group(0)
        caption = captions.get(curated, "").strip()
        image_md = f"![Figure](../figures/{curated})"
        if caption:
            return f"{image_md}\n*Figure: {caption}*"
        return image_md

    return FIGURE_PLACEHOLDER_RE.sub(_sub, body)


def promote_subheadings(body: str, page_heading: str | None = None) -> str:
    """Promote standalone ``N.N[.N...] Title`` paragraphs to ``### ...`` so
    numbered service-manual subheadings (e.g. ``6.1.24 Austauschteile``) are
    rendered as real headings. Multi-line blocks such as table-of-contents
    lists are left untouched. A match that is identical to the page's H1
    heading is dropped entirely to avoid printing the chapter title twice.
    """
    heading_norm = (page_heading or "").strip()
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
        candidate = f"{m.group(1)} {m.group(2)}"
        if heading_norm and candidate.strip() == heading_norm:
            blocks[i] = f"{leading.rstrip('\n')}{trailing.lstrip('\n')}"
            continue
        blocks[i] = f"{leading}### {candidate}{trailing}"
    return "".join(blocks)


def finalize_volume(pages_dir: Path) -> tuple[int, int]:
    """Return (changed, scanned)."""
    figures_dir = pages_dir.parent / "figures"
    hash_map = load_hash_map(figures_dir)
    captions = load_figure_captions(figures_dir)
    fallbacks = load_table_fallbacks(figures_dir)
    changed = 0
    scanned = 0
    for page_file in sorted(pages_dir.glob("p*.md")):
        scanned += 1
        original = page_file.read_text(encoding="utf-8")
        fm, body = split_front_matter(original)
        new_body = inline_tables(body, page_file, fm, fallbacks)
        new_body = inline_figures(new_body, page_file, hash_map, captions)
        new_body = promote_subheadings(new_body, fm.get("heading"))
        if new_body == body:
            continue
        prefix = original[: len(original) - len(body)]
        page_file.write_text(prefix + new_body, encoding="utf-8")
        changed += 1
    return changed, scanned


def main() -> None:
    base = Path(__file__).parent.parent
    volumes_root = base / "rs_smp_corpus" / "volumes"
    if not volumes_root.is_dir():
        print(f"No volumes directory at {volumes_root}")
        return
    total_changed = 0
    total_scanned = 0
    print("Finalizing page markdown (inlining tables and figures)...")
    for vol_dir in sorted(volumes_root.iterdir()):
        pages_dir = vol_dir / "pages"
        if not pages_dir.is_dir():
            continue
        changed, scanned = finalize_volume(pages_dir)
        total_changed += changed
        total_scanned += scanned
        print(f"  {vol_dir.name}: {changed}/{scanned} pages updated")
    print(f"\n✓ Finalized {total_changed}/{total_scanned} pages")


if __name__ == "__main__":
    main()

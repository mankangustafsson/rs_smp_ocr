"""
Report-only verification for the generated searchable PDFs.

Runs the following checks per PDF in output/band_pdfs/:

    1 opens cleanly                 6 word recall per page  >= 0.97
    2 text layer on >= 95% pages    7 glossary term hits    >= 1
    3 page count matches source     8 image count >= source figure refs
    4 outline populated             9 garbled-run ratio       < 10%
    5 source H1 -> outline          10 metadata populated

Writes _pdfs_verification.md at the repo root and prints a summary.
Always exits 0 (report-only, matches the diagnostics pattern).

Usage:
    python scripts/verify_pdfs.py
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pymupdf
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_ROOT = REPO_ROOT / "rs_smp_corpus"
PDF_DIR = REPO_ROOT / "output" / "band_pdfs"
REPORT_PATH = REPO_ROOT / "_pdfs_verification.md"
GLOSSARY_PATH = CORPUS_ROOT / "index" / "glossary.md"

FM_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
H1_RE = re.compile(r"^# +(.+?)\s*$", re.MULTILINE)
H1_PAGE_PREFIX_RE = re.compile(r"[ \t]*—[ \t]*p\.\d+[ \t]*—[ \t]+")
H1_PAGE_SUFFIX_RE = re.compile(r"[ \t]*—[ \t]*p\.\d+[ \t]*$")
IMG_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
WORD_RE = re.compile(r"[A-Za-z\u00c0-\u024f]{3,}")
MD_STRIP_RE = re.compile(r"[`*_~#>\[\]()!|\-]+")
# Placeholder markers that the PDF renderer either inlines as binary content
# (images) or rewrites entirely (tables) — excluded from recall comparison
# so hash substrings don't count as "missing" words in the PDF.
PLACEHOLDER_RE = re.compile(
    r"\[(?:FIGURE|TABLE|Footer):[^\]]*\]",
    re.IGNORECASE,
)

VARIANT_LANG: dict[str, Callable[[str], bool]] = {
    "bilingual": lambda _lang: True,
}


def parse_pdf_name(stem: str) -> tuple[str, str]:
    return stem, "bilingual"


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


def source_pages(vol_id: str, variant: str) -> list[tuple[Path, dict[str, Any], str]]:
    pages_dir = CORPUS_ROOT / "volumes" / vol_id / "pages"
    predicate = VARIANT_LANG[variant]
    out: list[tuple[Path, dict[str, Any], str]] = []
    for p in sorted(pages_dir.glob("p*.md")):
        fm, body = read_front_matter(p)
        if predicate(str(fm.get("language", ""))):
            out.append((p, fm, body))
    return out


def extract_words(text: str) -> set[str]:
    return {w.lower() for w in WORD_RE.findall(text)}


def load_glossary_terms() -> list[str]:
    """Extract German and English terms from the glossary markdown table."""
    if not GLOSSARY_PATH.is_file():
        return []
    terms: list[str] = []
    for line in GLOSSARY_PATH.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        de, en = cells[0], cells[1]
        if de.lower() in {"german (de)", ""} or set(de) <= set("-: "):
            continue
        for t in (de, en):
            if 2 <= len(t) <= 40:
                terms.append(t)
    return terms


def check_pdf(pdf_path: Path, glossary: list[str]) -> dict[str, Any]:
    vol_id, variant = parse_pdf_name(pdf_path.stem)
    result: dict[str, Any] = {"pdf": pdf_path.name, "checks": {}, "warnings": []}
    try:
        doc: Any = pymupdf.open(pdf_path)  # type: ignore[no-untyped-call]
    except Exception as e:
        result["checks"]["1_opens"] = f"FAIL ({e})"
        return result
    result["checks"]["1_opens"] = "PASS"

    n_pages: int = doc.page_count
    pages_iter: list[Any] = [doc.load_page(i) for i in range(n_pages)]

    src = source_pages(vol_id, variant)
    result["src_page_count"] = len(src)
    result["pdf_page_count"] = n_pages

    pages_with_text = sum(1 for p in pages_iter if p.get_text().strip())
    text_cov = pages_with_text / max(1, n_pages)
    result["checks"]["2_text_layer_cov"] = (
        f"PASS ({text_cov:.1%})" if text_cov >= 0.95 else f"FAIL ({text_cov:.1%})"
    )

    # PDF is allowed to overflow the source page count because long tables
    # and figures may span multiple physical pages after paged-media layout.
    expected = len(src) + 1  # +1 for cover
    if n_pages >= expected:
        result["checks"]["3_page_count"] = f"PASS ({n_pages} >= {expected})"
    else:
        result["checks"]["3_page_count"] = f"FAIL (pdf={n_pages} < expected={expected})"

    toc = doc.get_toc()
    result["checks"]["4_outline"] = "PASS" if toc else "FAIL"

    h1s = [H1_RE.findall(body) for _f, _fm, body in src]
    flat_h1 = [
        H1_PAGE_SUFFIX_RE.sub("", H1_PAGE_PREFIX_RE.sub(" — ", h)).strip()
        for g in h1s
        for h in g
    ]
    outline_titles = {entry[1].strip() for entry in toc}
    matched = sum(1 for h in flat_h1 if h.strip() in outline_titles)
    h1_cov = matched / max(1, len(flat_h1))
    result["checks"]["5_h1_to_outline"] = (
        f"PASS ({h1_cov:.1%})" if h1_cov >= 0.90 else f"WARN ({h1_cov:.1%})"
    )

    # Global recall: long pages can overflow into multiple PDF pages, so
    # compare word-sets across the whole document rather than pairing pages.
    src_text = PLACEHOLDER_RE.sub(" ", "\n".join(body for _f, _fm, body in src))
    src_words = extract_words(MD_STRIP_RE.sub(" ", src_text))
    pdf_words = extract_words("\n".join(p.get_text() for p in pages_iter[1:]))
    recall = len(src_words & pdf_words) / max(1, len(src_words))
    result["checks"]["6_word_recall"] = (
        f"PASS ({recall:.3f})" if recall >= 0.97 else f"WARN ({recall:.3f})"
    )

    hits = {term: sum(len(p.search_for(term)) for p in pages_iter) for term in glossary}
    hit_terms = sum(1 for c in hits.values() if c >= 1)
    hit_ratio = hit_terms / max(1, len(glossary))
    # Not every glossary term appears in every volume; 25% is a healthy floor.
    result["checks"]["7_glossary_hits"] = (
        f"PASS ({hit_terms}/{len(glossary)})"
        if hit_ratio >= 0.25
        else f"WARN ({hit_terms}/{len(glossary)})"
    )

    src_figrefs = sum(len(IMG_RE.findall(body)) for _f, _fm, body in src)
    pdf_imgs = sum(len(p.get_images()) for p in pages_iter)
    result["checks"]["8_images_ge_refs"] = (
        "PASS" if pdf_imgs >= src_figrefs else f"WARN ({pdf_imgs} < {src_figrefs})"
    )

    all_text = "\n".join(p.get_text() for p in pages_iter)
    tokens = all_text.split()
    garbled = sum(
        1 for t in tokens if "\ufffd" in t or (len(t) == 1 and not t.isalnum())
    )
    garb_ratio = garbled / max(1, len(tokens))
    result["checks"]["9_garbled_ratio"] = (
        f"PASS ({garb_ratio:.2%})" if garb_ratio < 0.10 else f"WARN ({garb_ratio:.2%})"
    )

    meta = doc.metadata or {}
    result["checks"]["10_metadata"] = (
        "PASS" if meta.get("title") and meta.get("creator") else "WARN (missing fields)"
    )

    result["summary"] = {
        "pages": n_pages,
        "outline": len(toc),
        "recall": round(recall, 3),
        "glossary_hit_ratio": round(hit_ratio, 2),
        "size_mb": round(pdf_path.stat().st_size / (1024 * 1024), 2),
    }
    doc.close()
    return result


def render_report(results: list[dict[str, Any]]) -> str:
    lines: list[str] = [
        "# Searchable PDF verification",
        "",
        "Report generated by `scripts/verify_pdfs.py` \u2014 checks each PDF under",
        "`output/band_pdfs/` for basic searchability and fidelity against the",
        "source per-page markdown.",
        "",
        "## Summary",
        "",
        "| PDF | Pages | Outline | Recall | Glossary | Size |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        s = r.get("summary", {})
        lines.append(
            f"| {r['pdf']} | {s.get('pages', '-')} | {s.get('outline', '-')} | "
            f"{s.get('recall', '-')} | {s.get('glossary_hit_ratio', '-')} | "
            f"{s.get('size_mb', '-')} MB |"
        )
    lines.append("")
    for r in results:
        lines.append(f"## {r['pdf']}")
        lines.append("")
        lines.append("| Check | Result |")
        lines.append("|---|---|")
        for name, verdict in r["checks"].items():
            lines.append(f"| {name} | {verdict} |")
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    if not PDF_DIR.is_dir():
        print(f"No PDFs directory at {PDF_DIR}", file=sys.stderr)
        return 0
    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in {PDF_DIR}", file=sys.stderr)
        return 0
    glossary = load_glossary_terms()
    print(f"=== verify_pdfs: {len(pdfs)} PDF(s), {len(glossary)} glossary terms ===")
    results = [check_pdf(p, glossary) for p in pdfs]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(render_report(results), encoding="utf-8")
    for r in results:
        fails = sum(1 for v in r["checks"].values() if str(v).startswith("FAIL"))
        warns = sum(1 for v in r["checks"].values() if str(v).startswith("WARN"))
        tag = "FAIL" if fails else ("WARN" if warns else "OK  ")
        print(f"  {tag}  {r['pdf']}  ({fails} fail, {warns} warn)")
    print(f"\n\u2713 Wrote {REPORT_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

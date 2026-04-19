"""
Spot-check bilingual section pairs.

For every section file with `bilingual_sibling` front matter, compute a
simple DE vs. EN score on the first ~40 content lines (skipping the page
anchor and front-matter) and flag any file whose declared language does
not match the detected dominant language.

Writes a readable summary table to rs_smp_corpus/index/_bilingual_spotcheck.md.
"""

import re
from pathlib import Path
from typing import Any

import yaml

FM_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)

# Language signature words. Order matters only for readability; the
# classifier counts case-insensitive token occurrences.
DE_MARKERS = {
    "und",
    "der",
    "die",
    "das",
    "mit",
    "nicht",
    "sind",
    "wird",
    "funktionsbeschreibung",
    "baugruppe",
    "messgeräte",
    "fehlersuche",
    "prüfen",
    "abgleich",
    "zerlegung",
    "schnittstelle",
    "stromlauf",
    "spannung",
    "einstellung",
    "überprüfung",
    "ausgang",
}
EN_MARKERS = {
    "and",
    "the",
    "with",
    "not",
    "are",
    "this",
    "that",
    "function",
    "description",
    "module",
    "board",
    "measuring",
    "troubleshooting",
    "testing",
    "adjustment",
    "disassembly",
    "interface",
    "diagram",
    "voltage",
    "setting",
    "checking",
    "output",
}

UMLAUT_RE = re.compile(r"[äöüÄÖÜß]")
WORD_RE = re.compile(r"[A-Za-zÄÖÜäöüß]{2,}")


def read_front_matter(path: Path) -> tuple[dict[str, Any], str]:
    content = path.read_text(encoding="utf-8")
    m = FM_RE.match(content)
    if not m:
        return {}, content
    try:
        fm: dict[str, Any] = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        fm = {}
    body = content[m.end() :]
    return fm, body


def extract_sample_text(body: str, max_chars: int = 4000) -> str:
    """Strip page anchors and HTML table markup; keep plain prose only."""
    lines = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("[p.") or stripped.startswith("#"):
            continue
        if stripped.startswith("<table") or stripped.startswith("</table"):
            continue
        if stripped.startswith("<tr") or stripped.startswith("</tr"):
            continue
        if stripped.startswith("<td") or stripped.startswith("</td"):
            continue
        if stripped.startswith("---"):
            continue
        lines.append(stripped)
        if sum(len(ln) for ln in lines) >= max_chars:
            break
    return " ".join(lines)


def score_language(sample: str) -> tuple[int, int, int]:
    """Return (de_score, en_score, umlaut_count)."""
    tokens = [w.lower() for w in WORD_RE.findall(sample)]
    de = sum(1 for t in tokens if t in DE_MARKERS)
    en = sum(1 for t in tokens if t in EN_MARKERS)
    umlauts = len(UMLAUT_RE.findall(sample))
    return de, en, umlauts


def classify(de_score: int, en_score: int, umlauts: int) -> str:
    # Umlauts are strong DE evidence; one umlaut beats 3 EN markers.
    adjusted_de = de_score + umlauts * 3
    if adjusted_de == 0 and en_score == 0:
        return "unknown"
    if adjusted_de > en_score * 1.5:
        return "de"
    if en_score > adjusted_de * 1.5:
        return "en"
    return "mixed"


def main() -> None:
    base = Path(__file__).parent.parent.parent
    lines = ["# Bilingual split spot-check", ""]
    lines.append(
        "Classifier inspects the first ~4000 chars of each section "
        "(after the front matter / page anchors / HTML table markup "
        "are stripped)."
    )
    lines.append("")
    lines.append("| Volume | Ch | Lang | Det. | DE | EN | Umlauts | Match | File |")
    lines.append("|--------|----|------|------|----|----|---------|-------|------|")

    total = 0
    mismatches = 0
    by_volume: dict[str, list[tuple[Any, ...]]] = {}

    for section_file in sorted(
        (base / "rs_smp_corpus" / "volumes").glob("*/sections/*.md")
    ):
        fm, body = read_front_matter(section_file)
        declared = fm.get("language")
        if declared not in ("de", "en"):
            continue  # skip monolingual / combined files
        total += 1
        sample = extract_sample_text(body)
        de, en, umlauts = score_language(sample)
        detected = classify(de, en, umlauts)
        match = (
            "✓"
            if detected == declared
            else ("~" if detected in ("mixed", "unknown") else "✗")
        )
        if match == "✗":
            mismatches += 1
        volume = fm.get("volume", "?")
        chapter = fm.get("chapter", "?")
        by_volume.setdefault(volume, []).append(
            (
                chapter,
                declared,
                detected,
                de,
                en,
                umlauts,
                match,
                section_file.name,
            )
        )

    for volume in sorted(by_volume):
        for row in by_volume[volume]:
            chapter, declared, detected, de, en, umlauts, match, fname = row
            lines.append(
                f"| {volume} | {chapter} | {declared} | {detected} "
                f"| {de} | {en} | {umlauts} | {match} | {fname} |"
            )

    lines.append("")
    lines.append(f"**Total bilingual files:** {total}")
    lines.append(f"**Mismatches (✗):** {mismatches}")

    out = base / "rs_smp_corpus" / "index" / "_bilingual_spotcheck.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\u2713 Wrote {out}")
    print(f"  {total} bilingual files checked; {mismatches} mismatches.")


if __name__ == "__main__":
    main()

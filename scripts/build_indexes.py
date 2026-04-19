"""
Build cross-volume index files.

Generates in rs_smp_corpus/index/:
- toc.md - Unified table of contents across all volumes
- assemblies.md - Stock number index with assembly names
- components.md - Component designator index (from XY-lists)
- signals.md - Signal/net name index
- glossary.md - DE/EN/FR terminology
- page_manifest.jsonl - Machine-readable page manifest

Usage:
    python build_indexes.py
"""

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml


def load_config() -> dict[str, Any]:
    """Load configuration from config.yaml."""
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path, encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f)
        return data


def build_toc(config: dict[str, Any], base_path: Path) -> None:
    """Build unified table of contents."""
    filepath = base_path / "rs_smp_corpus" / "index" / "toc.md"
    filepath.parent.mkdir(parents=True, exist_ok=True)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("# Table of Contents — SMP Documentation\n\n")
        f.write("Unified index across all 6 volumes.\n\n")

        for volume_config in config["volumes"]:
            volume_id = volume_config["id"]
            title_en = volume_config["title_en"]
            title_de = volume_config.get("title_de")

            f.write(f"## {title_en}")
            if title_de:
                f.write(f" / {title_de}")
            f.write(f" ({volume_id})\n\n")

            # List sections if they exist. Bilingual pairs (sharing the same
            # chapter number) are grouped under a single TOC entry with
            # DE/EN links side by side.
            sections_dir = (
                base_path / "rs_smp_corpus" / "volumes" / volume_id / "sections"
            )
            if sections_dir.exists():
                by_chapter: dict[Any, dict[str, Any]] = {}
                for section_file in sorted(sections_dir.glob("*.md")):
                    with open(section_file, encoding="utf-8") as sf:
                        content = sf.read()
                    if not content.startswith("---"):
                        continue
                    parts = content.split("---", 2)
                    if len(parts) < 3:
                        continue
                    try:
                        fm = yaml.safe_load(parts[1]) or {}
                    except yaml.YAMLError:
                        continue
                    chapter = fm.get("chapter", "?")
                    entry = by_chapter.setdefault(
                        chapter,
                        {
                            "title_en": fm.get("title_en", ""),
                            "title_de": fm.get("title_de"),
                            "files": {},
                        },
                    )
                    lang = fm.get("language", "en")
                    entry["files"][lang] = section_file

                for chapter in sorted(
                    by_chapter.keys(), key=lambda k: (isinstance(k, str), k)
                ):
                    entry = by_chapter[chapter]
                    sec_title_en = entry["title_en"]
                    sec_title_de = entry["title_de"]
                    f.write(f"  {chapter}. {sec_title_en}")
                    if sec_title_de and sec_title_de != sec_title_en:
                        f.write(f" / {sec_title_de}")
                    links = []
                    for lang in ("de", "en", "de+en"):
                        sf_path = entry["files"].get(lang)
                        if sf_path is not None:
                            rel = sf_path.relative_to(base_path / "rs_smp_corpus")
                            label = lang.upper() if lang != "de+en" else "DE+EN"
                            links.append(f"[{label}](`{rel}`)")
                    if links:
                        f.write(" → " + " · ".join(links))
                    f.write("\n")

            f.write("\n")

    print(f"  ✓ Created {filepath.name}")


def build_assemblies_index(base_path: Path) -> None:
    """Build assemblies/stock number index."""
    filepath = base_path / "rs_smp_corpus" / "index" / "assemblies.md"

    # Collect assembly info from all table files
    assemblies: defaultdict[str, dict[str, Any]] = defaultdict(
        lambda: {"volumes": set(), "pages": [], "names": set()}
    )

    for volume_dir in (base_path / "rs_smp_corpus" / "volumes").glob("*/tables"):
        volume_id = volume_dir.parent.name

        for table_file in volume_dir.glob("*.md"):
            with open(table_file, encoding="utf-8") as f:
                content = f.read()
                if content.startswith("---"):
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        try:
                            front_matter = yaml.safe_load(parts[1])
                            stock = front_matter.get("stock_number")
                            assembly = front_matter.get("assembly")
                            page = front_matter.get("page", 0)

                            if stock:
                                assemblies[stock]["volumes"].add(volume_id)
                                assemblies[stock]["pages"].append((volume_id, page))
                                if assembly:
                                    assemblies[stock]["names"].add(assembly)
                        except Exception:
                            pass

    # Write index
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("# Assemblies and Stock Numbers\n\n")
        f.write("Index of all assemblies by stock number.\n\n")

        for stock in sorted(assemblies.keys()):
            info = assemblies[stock]
            f.write(f"## {stock}\n\n")

            if info["names"]:
                f.write(f"**Names:** {', '.join(sorted(info['names']))}\n\n")

            f.write(f"**Volumes:** {', '.join(sorted(info['volumes']))}\n\n")

            f.write("**Pages:**\n")
            for vol, page in sorted(info["pages"]):
                f.write(f"- {vol}: p.{page}\n")
            f.write("\n")

    print(f"  ✓ Created {filepath.name} ({len(assemblies)} assemblies)")


def build_components_index(base_path: Path) -> None:
    """Build component designator index from XY-lists."""
    filepath = base_path / "rs_smp_corpus" / "index" / "components.md"

    # Collect component data from XY-list tables
    components: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)

    for volume_dir in (base_path / "rs_smp_corpus" / "volumes").glob("*/tables"):
        volume_id = volume_dir.parent.name

        for table_file in volume_dir.glob("*.md"):
            with open(table_file, encoding="utf-8") as f:
                content = f.read()

                # Extract page number from filename (p0198_...)
                page_match = re.match(r"p(\d+)_", table_file.name)
                file_page = int(page_match.group(1)) if page_match else 0

                # Full normalized data
                if "## Normalized Component Data" in content:
                    lines = content.split("\n")
                    in_table = False
                    for line in lines:
                        if line.startswith("| Designator"):
                            in_table = True
                            continue
                        if in_table and line.startswith("|"):
                            if "---" in line:
                                continue
                            parts = [p.strip() for p in line.split("|")]
                            if len(parts) >= 7:
                                designator = parts[1]
                                board = parts[2]
                                x = parts[3]
                                y = parts[4]
                                square = parts[5]
                                page = parts[6]

                                if designator and designator != "Designator":
                                    components[designator].append(
                                        {
                                            "volume": volume_id,
                                            "board": board,
                                            "x": x,
                                            "y": y,
                                            "square": square,
                                            "sheet": page,
                                            "pdf_page": file_page,
                                            "quality": "full",
                                        }
                                    )

                # Partial (designators-only) data — may co-exist with the
                # normalized table when extraction_quality is 'partial'.
                if "## Component Designators (Partial Extraction)" in content:
                    section = content.split(
                        "## Component Designators (Partial Extraction)", 1
                    )[1]
                    # Take everything up to the next heading or end
                    if "\n## " in section:
                        section = section.split("\n## ", 1)[0]
                    # Find the comma-separated designator list
                    for token in re.findall(r"\b[A-Z]{1,3}\d{1,4}[A-Z]?\b", section):
                        components[token].append(
                            {
                                "volume": volume_id,
                                "board": "",
                                "x": "",
                                "y": "",
                                "square": "",
                                "sheet": "",
                                "pdf_page": file_page,
                                "quality": "partial",
                            }
                        )

    # Write index grouped by prefix
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("# Component Index\n\n")
        f.write(
            "All components from XY-lists, grouped by prefix. "
            "`p.NNN` is the PDF page of the table; `sheet N` is the schematic "
            "sheet number printed in the R&S cartouche. Entries marked "
            "*(partial)* are from tables where OCR cell structure was too "
            "fragmented for full x/y extraction.\n\n"
        )

        # Group by prefix (R, C, V, etc.)
        by_prefix: defaultdict[str, list[str]] = defaultdict(list)
        for des in components:
            prefix = re.match(r"^([A-Z]+)", des)
            if prefix:
                by_prefix[prefix.group(1)].append(des)

        def _des_sort_key(x: str) -> tuple[str, int]:
            m = re.search(r"\d+", x)
            return (x, int(m.group()) if m else 0)

        for prefix_key in sorted(by_prefix.keys()):
            f.write(f"## {prefix_key}* Components\n\n")

            for designator in sorted(by_prefix[prefix_key], key=_des_sort_key):
                entries = components[designator]
                f.write(f"### {designator}\n\n")

                for entry in entries:
                    location_bits = []
                    if entry["board"]:
                        location_bits.append(f"Board {entry['board']}")
                    if entry["x"] and entry["y"]:
                        location_bits.append(f"({entry['x']}, {entry['y']})")
                    if entry["square"]:
                        location_bits.append(f"Square {entry['square']}")
                    if entry.get("sheet"):
                        location_bits.append(f"sheet {entry['sheet']}")

                    prefix_text = f"- **{entry['volume']}** p.{entry['pdf_page']}"
                    if entry["quality"] == "full" and location_bits:
                        f.write(f"{prefix_text}: {', '.join(location_bits)}\n")
                    elif entry["quality"] == "full":
                        f.write(f"{prefix_text} *(no location data)*\n")
                    else:
                        f.write(f"{prefix_text} *(partial)*\n")

                f.write("\n")

    print(f"  ✓ Created {filepath.name} ({len(components)} unique components)")


def build_glossary(base_path: Path) -> None:
    """Build DE/EN/FR glossary."""
    filepath = base_path / "rs_smp_corpus" / "index" / "glossary.md"

    # Common technical terms
    terms: list[tuple[str, str, str]] = [
        ("Abgleich", "Adjustment", "Ajustement"),
        ("Baugruppe", "Assembly", "Module"),
        ("Betriebsvorbereitung", "Preparation for Use", "Préparation"),
        ("Datenblatt", "Data Sheet", "Fiche technique"),
        ("Ersatzteile", "Spare Parts", "Pièces de rechange"),
        ("Funktionsprüfung", "Performance Test", "Test de performance"),
        ("Instandsetzung", "Repair", "Réparation"),
        ("Meßtechnik", "Measurement Technology", "Technologie de mesure"),
        ("Sachnummer", "Stock Number", "Numéro de stock"),
        ("Schaltplan", "Schematic", "Schéma"),
        ("Schaltungsbeschreibung", "Circuit Description", "Description du circuit"),
        ("Schlüsselliste", "Key List", "Liste"),
        ("Servicehandbuch", "Service Manual", "Manuel de service"),
        ("Signalgenerator", "Signal Generator", "Générateur de signal"),
    ]

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("# Glossary — DE / EN / FR\n\n")
        f.write("Technical terminology across languages.\n\n")

        f.write("| German (DE) | English (EN) | French (FR) |\n")
        f.write("|-------------|--------------|-------------|\n")

        for de, en, fr in terms:
            f.write(f"| {de} | {en} | {fr} |\n")

    print(f"  ✓ Created {filepath.name}")


def build_page_manifest(config: dict[str, Any], base_path: Path) -> None:
    """Build machine-readable page manifest."""
    filepath = base_path / "rs_smp_corpus" / "index" / "page_manifest.jsonl"

    count = 0
    with open(filepath, "w", encoding="utf-8") as f:
        for volume_config in config["volumes"]:
            volume_id = volume_config["id"]
            pages_dir = base_path / "rs_smp_corpus" / "volumes" / volume_id / "pages"

            if not pages_dir.exists():
                continue

            for page_file in sorted(pages_dir.glob("p*.md")):
                with open(page_file, encoding="utf-8") as pf:
                    content = pf.read()
                    if content.startswith("---"):
                        parts = content.split("---", 2)
                        if len(parts) >= 3:
                            try:
                                front_matter = yaml.safe_load(parts[1])
                                # Write as single JSON line
                                json.dump(front_matter, f)
                                f.write("\n")
                                count += 1
                            except Exception:
                                pass

    print(f"  ✓ Created {filepath.name} ({count} pages)")


def main() -> None:
    """Main entry point."""
    print("Building cross-volume indexes...")

    # Find project root
    base_path = Path(__file__).parent.parent

    # Load configuration
    config = load_config()

    # Build each index
    build_toc(config, base_path)
    build_assemblies_index(base_path)
    build_components_index(base_path)
    build_glossary(base_path)
    build_page_manifest(config, base_path)

    print("\n✓ Index building complete!")


if __name__ == "__main__":
    main()

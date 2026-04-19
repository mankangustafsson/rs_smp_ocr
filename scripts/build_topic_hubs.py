"""
Build topic hub routing documents.

Generates three routing hub files in rs_smp_corpus/index/:
- operator_topics.md - Common operator tasks with links to user manual and service procedures
- service_topics.md - Service/repair topics with links across service manual bands
- spec_topics.md - Specifications with links to all sources (datasheet, user manual, service manual)

These hubs help retrieval find the right content for broad queries.

Usage:
    python build_topic_hubs.py
"""

from pathlib import Path
from typing import Any

import yaml


def load_config() -> dict[str, Any]:
    """Load configuration from config.yaml."""
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path, encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f)
        return data


def create_operator_topics_hub(base_path: Path) -> None:
    """Create operator_topics.md routing hub."""
    filepath = base_path / "rs_smp_corpus" / "index" / "operator_topics.md"
    filepath.parent.mkdir(parents=True, exist_ok=True)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("# Operator Topics — SMP Signal Generator\n\n")
        f.write("Common operator tasks and procedures. Each topic links to relevant ")
        f.write("sections in the user manual and related service procedures.\n\n")

        # Define common operator tasks
        topics = [
            {
                "title": "Setting Frequency",
                "keywords": ["frequency", "RF", "carrier", "CW"],
                "user_manual_ref": "See user-manual sections on frequency setting",
                "service_ref": "Performance test procedures in band-2, band-3",
            },
            {
                "title": "Setting Output Level",
                "keywords": ["level", "power", "amplitude", "dBm", "attenuation"],
                "user_manual_ref": "See user-manual sections on level control",
                "service_ref": "Level accuracy tests and ALC adjustment in service bands",
            },
            {
                "title": "Modulation Setup",
                "keywords": ["AM", "FM", "PM", "pulse", "modulation"],
                "user_manual_ref": "See user-manual modulation chapter",
                "service_ref": "Modulation board adjustments in band-1, band-2",
            },
            {
                "title": "Sweep and List Mode",
                "keywords": ["sweep", "list", "step", "frequency sweep", "power sweep"],
                "user_manual_ref": "See user-manual sweep configuration",
                "service_ref": "Digital synthesis board testing",
            },
            {
                "title": "Remote Control",
                "keywords": ["GPIB", "RS-232", "remote", "interface", "programming"],
                "user_manual_ref": "See user-manual remote control chapter",
                "service_ref": "Interface board troubleshooting in band-2",
            },
            {
                "title": "Reference Oscillator",
                "keywords": ["reference", "OCXO", "10 MHz", "external reference"],
                "user_manual_ref": "See user-manual reference oscillator section",
                "service_ref": "Reference oscillator adjustment in band-1",
            },
        ]

        for topic in topics:
            f.write(f"## {topic['title']}\n\n")
            f.write(f"**Keywords:** {', '.join(topic['keywords'])}\n\n")
            f.write(f"**For Users:** {topic['user_manual_ref']}\n\n")
            f.write(f"**For Service:** {topic['service_ref']}\n\n")

    print(f"  ✓ Created {filepath}")


def create_service_topics_hub(base_path: Path) -> None:
    """Create service_topics.md routing hub."""
    filepath = base_path / "rs_smp_corpus" / "index" / "service_topics.md"
    filepath.parent.mkdir(parents=True, exist_ok=True)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("# Service Topics — SMP Signal Generator\n\n")
        f.write("Service, repair, and adjustment procedures. Links to relevant ")
        f.write("sections across all service manual bands.\n\n")

        topics = [
            {
                "title": "Performance Test",
                "assemblies": ["All main assemblies"],
                "bands": ["band-1", "band-2", "band-3", "band-4"],
                "chapter": "Chapter 4: Funktionsprüfung / Performance Test",
            },
            {
                "title": "Adjustment Procedures",
                "assemblies": [
                    "Reference oscillator",
                    "Digital synthesis",
                    "ALC amplifier",
                    "YIG PLL",
                ],
                "bands": ["band-1", "band-2", "band-3", "band-4"],
                "chapter": "Chapter 5: Abgleich / Adjustment",
            },
            {
                "title": "Circuit Descriptions",
                "assemblies": ["All assemblies with detailed circuit theory"],
                "bands": ["band-1", "band-2", "band-3", "band-4"],
                "chapter": "Chapter 7: Schaltungsbeschreibung / Circuit Descriptions",
            },
            {
                "title": "Schematics and XY-Lists",
                "assemblies": ["Component-level schematics with position data"],
                "bands": ["band-1", "band-2", "band-3", "band-4"],
                "chapter": "Chapter 8: Schaltpläne / Schematics",
            },
            {
                "title": "Parts and Assemblies",
                "assemblies": [
                    "Spare parts lists, stock numbers, assembly identification"
                ],
                "bands": ["band-1", "band-2", "band-3", "band-4"],
                "chapter": "Chapter 9: Ersatzteilliste / Spare Parts",
            },
            {
                "title": "Troubleshooting",
                "assemblies": ["Fault diagnosis and repair procedures"],
                "bands": ["band-1", "band-2", "band-3", "band-4"],
                "chapter": "Chapter 6: Instandsetzung / Repair",
            },
        ]

        for topic in topics:
            f.write(f"## {topic['title']}\n\n")
            f.write(f"**Assemblies:** {', '.join(topic['assemblies'])}\n\n")
            f.write(f"**Volumes:** {', '.join(topic['bands'])}\n\n")
            f.write(f"**Location:** {topic['chapter']}\n\n")

    print(f"  ✓ Created {filepath}")


def create_spec_topics_hub(base_path: Path) -> None:
    """Create spec_topics.md routing hub."""
    filepath = base_path / "rs_smp_corpus" / "index" / "spec_topics.md"
    filepath.parent.mkdir(parents=True, exist_ok=True)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("# Specification Topics — SMP Signal Generator\n\n")
        f.write("Technical specifications and performance characteristics. ")
        f.write(
            "Links to datasheet (authoritative), user manual specs, and service manual data.\n\n"
        )

        f.write("**Authoritative source:** The standalone datasheet is the primary ")
        f.write("reference for specifications. Where datasheet, user manual, and ")
        f.write("service manual disagree, datasheet takes precedence.\n\n")

        specs = [
            {
                "param": "Frequency Range",
                "smp02": "10 MHz to 20 GHz",
                "smp03": "10 MHz to 27 GHz",
                "smp04": "10 MHz to 40 GHz",
                "sources": ["datasheet", "user-manual Ch. 1", "service band-1 Ch. 1"],
            },
            {
                "param": "Output Level Range",
                "smp02": "-140 to +13 dBm (typical)",
                "smp03": "-140 to +13 dBm (typical)",
                "smp04": "-140 to +13 dBm (typical)",
                "sources": [
                    "datasheet",
                    "user-manual specs",
                    "service band-1 data sheet",
                ],
            },
            {
                "param": "SSB Phase Noise",
                "value": "See datasheet for detailed tables at various offset frequencies",
                "sources": ["datasheet (primary)", "service band-1 Ch. 1"],
            },
            {
                "param": "Frequency Resolution",
                "value": "0.1 Hz",
                "sources": ["datasheet", "user-manual"],
            },
            {
                "param": "Harmonics",
                "value": "See datasheet for level vs frequency",
                "sources": ["datasheet", "performance test in service bands"],
            },
            {
                "param": "Spurious (Non-Harmonic)",
                "value": "See datasheet",
                "sources": ["datasheet", "performance test procedures"],
            },
        ]

        for spec in specs:
            f.write(f"## {spec['param']}\n\n")

            if "smp02" in spec:
                f.write(f"- **SMP02:** {spec['smp02']}\n")
                f.write(f"- **SMP03:** {spec['smp03']}\n")
                f.write(f"- **SMP04:** {spec['smp04']}\n\n")
            elif "value" in spec:
                f.write(f"**Value:** {spec['value']}\n\n")

            f.write(f"**Sources:** {', '.join(spec['sources'])}\n\n")

    print(f"  ✓ Created {filepath}")


def main() -> None:
    """Main entry point."""
    print("Building topic hub files...")

    # Find project root
    base_path = Path(__file__).parent.parent

    # Create the three hubs
    create_operator_topics_hub(base_path)
    create_service_topics_hub(base_path)
    create_spec_topics_hub(base_path)

    print("\n✓ Topic hub building complete!")


if __name__ == "__main__":
    main()

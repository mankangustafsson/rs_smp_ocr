"""
Build figure files from MinerU content_list.json.

Processes images and generates:
- rs_smp_corpus/volumes/<vol>/figures/p<NNNN>_<slug>.jpg (renamed image)
- rs_smp_corpus/volumes/<vol>/figures/p<NNNN>_<slug>.md (stub with caption and context)
- rs_smp_corpus/volumes/<vol>/figures/_hash_map.json (hash → filename mapping)

Each figure stub includes:
- YAML front matter with metadata
- Image reference
- Caption (if available)
- Surrounding text context (5 blocks before and after)

Usage:
    python build_figures.py
"""

import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import yaml

# Add scripts directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))
from normalize import normalize_text


def load_config() -> dict[str, Any]:
    """Load configuration from config.yaml."""
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path, encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f)
        return data


def load_content_list(volume_path: Path) -> list[dict[str, Any]]:
    """Load content_list.json for a volume."""
    auto_dir = volume_path / "auto"
    json_files = list(auto_dir.glob("*_content_list.json"))
    json_files = [f for f in json_files if "_v2" not in f.name]

    if not json_files:
        raise FileNotFoundError(f"No content_list.json found in {auto_dir}")

    with open(json_files[0], encoding="utf-8") as f:
        data: list[dict[str, Any]] = json.load(f)
        return data


def generate_slug(text: str, max_length: int = 40) -> str:
    """Generate a URL-safe slug from text."""
    if not text:
        return "figure"

    slug = text.lower()
    slug = (
        slug.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    )
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = slug[:max_length].strip("-")

    return slug if slug else "figure"


def extract_context(
    content_list: list[dict[str, Any]],
    image_entry: dict[str, Any],
    context_lines: int = 5,
) -> tuple[list[str], list[str]]:
    """
    Extract surrounding text context for an image.

    Returns: (before_text, after_text)
    """
    page_idx = image_entry.get("page_idx")

    # Find the index of this image in the content list
    try:
        img_idx = content_list.index(image_entry)
    except ValueError:
        return ([], [])

    # Get text entries on the same page
    before: list[str] = []
    after: list[str] = []

    # Look backward for context
    for i in range(img_idx - 1, -1, -1):
        entry = content_list[i]
        if entry.get("page_idx") != page_idx:
            break  # Different page
        if entry.get("type") == "text" and entry.get("text"):
            before.insert(0, entry["text"])
            if len(before) >= context_lines:
                break

    # Look forward for context
    for i in range(img_idx + 1, len(content_list)):
        entry = content_list[i]
        if entry.get("page_idx") != page_idx:
            break  # Different page
        if entry.get("type") == "text" and entry.get("text"):
            after.append(entry["text"])
            if len(after) >= context_lines:
                break

    return (before, after)


def build_figures_for_volume(volume_config: dict[str, Any], base_path: Path) -> None:
    """Build figure files for a single volume."""
    volume_id = volume_config["id"]
    volume_folder = volume_config["folder"]
    language = volume_config["language"]

    print(f"\nProcessing {volume_id}...")

    # Load content list
    volume_path = base_path / volume_folder
    content_list = load_content_list(volume_path)

    # Filter to images only
    images = [entry for entry in content_list if entry.get("type") == "image"]
    print(f"  Total images: {len(images)}")

    if not images:
        print("  No images found, skipping")
        return

    # Create output directory
    output_dir = base_path / "rs_smp_corpus" / "volumes" / volume_id / "figures"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Source images directory
    source_images_dir = volume_path / "auto" / "images"

    # Hash map for tracking renamed files
    hash_map: dict[str, str] = {}

    # Process each image
    image_count = 0
    copied_count = 0

    for entry in images:
        page_idx = entry.get("page_idx", 0)
        img_path = entry.get("img_path", "")
        caption_list = entry.get("image_caption", [])

        if not img_path:
            continue

        # Source image path
        source_img = source_images_dir / img_path.replace("images/", "")

        if not source_img.exists():
            print(f"    Warning: Image not found: {img_path}")
            continue

        # Generate caption text
        caption = " ".join(caption_list) if caption_list else ""
        if caption:
            caption = normalize_text(caption, language)

        # Generate slug from caption or use generic name
        if caption:
            slug = generate_slug(caption)
        else:
            # Try to find nearby heading text for slug
            before_text, after_text = extract_context(content_list, entry, 2)
            context_text = " ".join(before_text + after_text)
            if context_text:
                slug = generate_slug(context_text[:50])
            else:
                slug = f"fig{image_count:03d}"

        # Target filename
        img_filename = f"p{page_idx:04d}_{slug}.jpg"
        target_img = output_dir / img_filename

        # Copy image file
        if not target_img.exists():
            shutil.copy2(source_img, target_img)
            copied_count += 1

        # Record hash mapping
        original_hash = source_img.stem  # The filename is already a hash
        hash_map[original_hash] = img_filename

        # Extract surrounding context
        before_context, after_context = extract_context(content_list, entry, 5)

        # Create markdown stub
        md_filename = f"p{page_idx:04d}_{slug}.md"
        md_filepath = output_dir / md_filename

        # Build front matter
        front_matter = {
            "volume": volume_id,
            "page": page_idx,
            "kind": "figure",
            "language": language,
            "image_file": img_filename,
        }

        if caption:
            front_matter["caption"] = caption

        # Write markdown stub
        with open(md_filepath, "w", encoding="utf-8") as f:
            f.write("---\n")
            yaml.dump(front_matter, f, allow_unicode=True, default_flow_style=False)
            f.write("---\n\n")

            # Title
            title = f"{volume_id} — p.{page_idx} — Figure"
            if caption:
                title += f": {caption[:50]}"
            f.write(f"# {title}\n\n")

            # Image reference
            f.write(f"![{caption if caption else 'Figure'}](./{img_filename})\n\n")

            # Caption (if available)
            if caption:
                f.write(f"**Caption:** {caption}\n\n")

            # Context section
            if before_context or after_context:
                f.write("## Context\n\n")

                if before_context:
                    f.write("**Text before figure:**\n\n")
                    for text in before_context:
                        normalized = normalize_text(text, language)
                        f.write(f"> {normalized}\n\n")

                if after_context:
                    f.write("**Text after figure:**\n\n")
                    for text in after_context:
                        normalized = normalize_text(text, language)
                        f.write(f"> {normalized}\n\n")

        image_count += 1

    # Write hash map
    hash_map_path = output_dir / "_hash_map.json"
    with open(hash_map_path, "w", encoding="utf-8") as f:
        json.dump(hash_map, f, indent=2)

    print(f"  ✓ Created {image_count} figure stubs")
    print(f"  ✓ Copied {copied_count} image files")
    print(f"  ✓ Hash map written to {hash_map_path.name}")


def main() -> None:
    """Main entry point."""
    print("Building figure files from content_list.json...")

    # Find project root
    base_path = Path(__file__).parent.parent

    # Load configuration
    config = load_config()

    # Process each volume
    for volume_config in config["volumes"]:
        try:
            build_figures_for_volume(volume_config, base_path)
        except Exception as e:
            print(f"  ✗ Error processing {volume_config['id']}: {e}")
            import traceback

            traceback.print_exc()

    print("\n✓ Figure building complete!")


if __name__ == "__main__":
    main()

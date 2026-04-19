"""
Master build script - runs all builders in sequence.

Usage:
    python build_all.py

Or run individual scripts:
    python build_pages.py
    python build_tables.py
    python build_figures.py
    python finalize_pages.py
    python build_sections.py
    python build_topic_hubs.py
    python build_indexes.py
    python verify.py
"""

import subprocess
import sys
import time
from pathlib import Path


def run_script(script_name: str) -> bool:
    """
    Run a build script and return success/failure.

    Returns True if successful, False otherwise.
    """
    script_path = Path(__file__).parent / script_name

    print(f"\n{'=' * 70}")
    print(f"Running {script_name}...")
    print(f"{'=' * 70}\n")

    start_time = time.time()

    try:
        subprocess.run(
            [sys.executable, str(script_path)],
            check=True,
            capture_output=False,
            text=True,
        )

        elapsed = time.time() - start_time
        print(f"\n✓ {script_name} completed in {elapsed:.1f}s")
        return True

    except subprocess.CalledProcessError as e:
        elapsed = time.time() - start_time
        print(f"\n✗ {script_name} failed after {elapsed:.1f}s")
        print(f"  Error code: {e.returncode}")
        return False
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"\n✗ {script_name} failed after {elapsed:.1f}s")
        print(f"  Error: {e}")
        return False


def main() -> int:
    """Run all build scripts in order."""
    print("=" * 70)
    print("SMP Documentation Build - Running all scripts")
    print("=" * 70)

    overall_start = time.time()

    # List of scripts to run in order
    scripts = [
        "build_pages.py",
        "build_tables.py",
        "build_figures.py",
        "render_table_fallbacks.py",
        "finalize_pages.py",
        "build_sections.py",
        "build_topic_hubs.py",
        "build_indexes.py",
        "verify.py",
    ]

    results = {}

    for script in scripts:
        success = run_script(script)
        results[script] = success

        if not success:
            print(f"\n⚠ Build stopped due to failure in {script}")
            print("You can fix the issue and re-run that script individually.")
            break

    # Summary
    overall_elapsed = time.time() - overall_start

    print(f"\n{'=' * 70}")
    print("Build Summary")
    print(f"{'=' * 70}\n")

    for script, success in results.items():
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"  {status}  {script}")

    print(f"\nTotal time: {overall_elapsed:.1f}s")

    all_passed = all(results.values())

    if all_passed:
        print("\n✓ All builds completed successfully!")
        print("\nNext steps:")
        print("  1. Review rs_smp_corpus/index/verification_report.md for any warnings")
        print("  2. Review rs_smp_corpus/index/toc.md to verify chapter detection")
        print("  3. Update scripts/toc_overrides.yaml if needed")
        print("  4. Re-run build_sections.py and build_indexes.py if you made changes")
        print("  5. Create .augmentignore file (see plan.md §14.7)")
        print("  6. Test retrieval quality with sample queries")
        return 0
    else:
        print("\n✗ Build incomplete - see errors above")
        return 1


if __name__ == "__main__":
    sys.exit(main())

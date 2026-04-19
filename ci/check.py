"""
Run the full set of Python static checks.

Used by:
- developers locally:       python ci/check.py [--fix]
- GitHub Actions:           .github/workflows/ci.yml
- pre-commit hook:          .pre-commit-config.yaml

Checks (in order):
  1. ruff check .          - lint
  2. ruff format --check . - formatting (or `ruff format .` with --fix)
  3. mypy scripts          - strict type-check

Exit code is 0 only if every step succeeds. With --fix, ruff is run in
auto-fix / format mode before the final verification pass.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run(label: str, cmd: list[str]) -> bool:
    """Run a check, print a banner, return True on success."""
    print(f"\n=== {label} ===")
    print("$ " + " ".join(cmd))
    start = time.perf_counter()
    result = subprocess.run(cmd, cwd=REPO_ROOT)
    elapsed = time.perf_counter() - start
    ok = result.returncode == 0
    status = "OK" if ok else f"FAIL (exit {result.returncode})"
    print(f"--- {label}: {status} in {elapsed:.1f}s")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Apply ruff auto-fixes and re-format before checking.",
    )
    args = parser.parse_args()

    # Use `python -m <tool>` so the checks work even if the tools are only
    # installed in the current interpreter's environment (not on PATH).
    py = sys.executable

    results: list[tuple[str, bool]] = []

    if args.fix:
        results.append(
            (
                "ruff check --fix",
                _run("ruff check --fix", [py, "-m", "ruff", "check", ".", "--fix"]),
            )
        )
        results.append(
            ("ruff format", _run("ruff format", [py, "-m", "ruff", "format", "."]))
        )
    else:
        results.append(
            ("ruff check", _run("ruff check", [py, "-m", "ruff", "check", "."]))
        )
        results.append(
            (
                "ruff format --check",
                _run(
                    "ruff format --check", [py, "-m", "ruff", "format", "--check", "."]
                ),
            )
        )

    results.append(
        ("mypy scripts", _run("mypy scripts", [py, "-m", "mypy", "scripts"]))
    )

    print("\n=== summary ===")
    for label, ok in results:
        print(f"  {'OK  ' if ok else 'FAIL'}  {label}")

    return 0 if all(ok for _, ok in results) else 1


if __name__ == "__main__":
    sys.exit(main())

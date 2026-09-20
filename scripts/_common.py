"""Shared plumbing for the contract-enforcement scripts.

Five scripts had resolved `ROOT` identically, re-read the same JSON files, and ended with three
near-identical failure epilogues that disagreed about the output stream. The divergence was the
problem: `check_schema.py` printed errors to stdout while the other two used stderr, so a CI log
filter that worked for one silently missed the other.

Underscore-prefixed so pytest never collects it and `pyrefly coverage --public-only` will not
count it as public API once W1 adopts that convention.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any, NoReturn

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_TIMEOUT = 120


def load_json(relative: str) -> Any:
    """Read a repository JSON file. Relative to the repository root, never to the caller."""
    return json.loads((ROOT / relative).read_text())


def load_toml(relative: str) -> dict[str, Any]:
    return tomllib.loads((ROOT / relative).read_text())


def run(*args: str, timeout: int = DEFAULT_TIMEOUT, capture: bool = False) -> str:
    """Run a command as an argument array from the repository root.

    Never a shell string, always a timeout: `rules/no-shell-invocation.yml` enforces the first
    structurally, and the second is what stops a hung vendor tool from consuming the CI budget.
    """
    result = subprocess.run(
        list(args),
        cwd=ROOT,
        timeout=timeout,
        capture_output=capture,
        text=True,
        check=True,
    )
    return result.stdout if capture else ""


def report(
    name: str,
    errors: list[str],
    warnings: list[str] | None = None,
    success: list[str] | None = None,
) -> NoReturn:
    """Emit warnings and errors to stderr, then exit.

    One epilogue for every check, so the failure shape is identical across the suite. Warnings
    are always shown, including on success: a warning that only appears when something else
    already failed is a warning nobody reads.
    """
    for warning in warnings or []:
        print(f"warning: {warning}", file=sys.stderr)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        raise SystemExit(f"{name} failed with {len(errors)} error(s)")
    for line in success or []:
        print(line)
    raise SystemExit(0)

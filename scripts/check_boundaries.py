"""Enforce the contract rules that have no syntax tree to match against.

Three tiers of contract enforcement, in order of preference:

  1. a parser for the format             -- uv.lock is TOML, so parse it (below);
  2. a syntax tree                       -- Python code, so `ast-grep scan` (see rules/);
  3. text                                -- prose and generated assets, so scan the text.

Tier three is last because it is the one that silently rots: a pattern nothing exercises is
indistinguishable from a pattern that matches nothing. Every check here therefore asserts a
known-bad example is caught, not only that the tree is clean.

Tracked files come from `git ls-files` rather than a directory walk, because the question these
checks ask is "is this committed?", and git is the authority on that.
"""

import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# DATA-36: Notion owns narrative and decisions; Git owns executable contracts. Private workspace
# URLs, sync-folder paths and developer home paths must never be committed.
PRIVATE_MARKERS = (
    re.compile(r"\bapp\.notion\.com\b"),
    re.compile(r"\bnotion\.so\b"),
    re.compile(r"\bdropbox\.com\b"),
    re.compile(r"/Users/[a-z]"),
    re.compile(r"/home/[a-z]"),
)

# DATA-33: no overlapping dataframe, database, orchestration or ORM layer. Checked against the
# resolved lock, not pyproject, so a transitive pull is caught too.
FORBIDDEN_PACKAGES = frozenset(
    {
        "pandas",
        "polars",
        "duckdb",
        "pyspark",
        "sqlalchemy",
        "django",
        "peewee",
        "tortoise-orm",
        "neo4j",
        "rdflib",
        "chromadb",
        "qdrant-client",
        "apache-airflow",
        "prefect",
        "dagster",
    }
)

SCANNABLE = {".md", ".py", ".json", ".yml", ".yaml", ".toml", ".dsl", ".puml", ".bpmn", ".cfg"}


def tracked_files() -> list[Path]:
    listing = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return [ROOT / name for name in listing.stdout.split("\0") if name]


def scan_text(text: str) -> list[str]:
    return [marker.pattern for marker in PRIVATE_MARKERS if marker.search(text)]


def check_private_content(files: list[Path]) -> list[str]:
    errors = []
    for path in files:
        if path.suffix not in SCANNABLE or not path.is_file():
            continue
        # .context.example.json documents the private-context keys without any real value.
        if path.name == ".context.example.json":
            continue
        for number, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            for pattern in scan_text(line):
                relative = path.relative_to(ROOT)
                errors.append(f"{relative}:{number}: tracked file carries private marker {pattern}")
    return errors


def check_forbidden_dependencies() -> list[str]:
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    resolved = {package["name"].lower() for package in lock["package"]}
    return [
        f"uv.lock resolves {name}, excluded by DATA-33"
        for name in sorted(resolved & FORBIDDEN_PACKAGES)
    ]


def self_test() -> list[str]:
    """A guard that cannot fail is not a guard. Prove each check catches a known-bad input."""
    errors = []
    # Assembled from fragments so this file does not trip its own scan once committed.
    samples = (
        "see https://app" + ".notion.com/p/abc",
        "local copy at /Users" + "/someone/architecture-toolkit",
        "shared via dropbox" + ".com/scl/fo/xyz",
    )
    for sample in samples:
        if not scan_text(sample):
            errors.append(f"private-content scan fails to catch {sample!r}")
    for benign in ("docs/contracts/data.md", "see the authorized Notion workspace"):
        if scan_text(benign):
            errors.append(f"private-content scan wrongly flags {benign!r}")
    if "pandas" not in FORBIDDEN_PACKAGES:
        errors.append("dependency deny-list lost its anchor entry")
    return errors


def main() -> int:
    files = tracked_files()
    errors = self_test() + check_private_content(files) + check_forbidden_dependencies()
    print(f"scanned {len(files)} tracked files and {len(FORBIDDEN_PACKAGES)} excluded packages")
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        raise SystemExit(f"Boundary check failed with {len(errors)} error(s)")
    print("no private workspace content committed; no excluded dependency resolved")
    return 0


if __name__ == "__main__":
    sys.exit(main())

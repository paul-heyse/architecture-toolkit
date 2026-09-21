"""`docs/cli.md` is generated, and this proves it has not drifted (DATA-38).

The CLI is a durable public surface — twenty-four verbs, and the wave plan calls verb naming a
thing that breaks consumers when it changes. A hand-written reference page would drift the first
time somebody added a flag, so the page is generated from the app object itself and this script is
the gate: it regenerates into a temporary file and refuses if the committed page differs.

Same shape as `scripts/check_schema.py`, deliberately. The JSON Schema contracts are generated and
drift-checked the same way, and a reader who understands one understands the other.
"""

import sys
import tempfile
from pathlib import Path

from _common import ROOT, run

PAGE = ROOT / "docs" / "cli.md"
COMMAND = (
    "typer",
    "architecture_toolkit.cli",
    "utils",
    "docs",
    "--name",
    "architecture",
    "--title",
    "CLI reference",
)


def generate(destination: Path) -> None:
    run(*COMMAND, "--output", str(destination), timeout=120)


def main() -> int:
    if not PAGE.is_file():
        print(f"{PAGE} is missing; run `uv run python scripts/check_cli_docs.py --write`")
        return 1
    if "--write" in sys.argv[1:]:
        generate(PAGE)
        print(f"wrote {PAGE.relative_to(ROOT)}")
        return 0
    with tempfile.TemporaryDirectory() as workspace:
        fresh = Path(workspace) / "cli.md"
        generate(fresh)
        if fresh.read_text(encoding="utf-8") != PAGE.read_text(encoding="utf-8"):
            print(
                f"{PAGE.relative_to(ROOT)}: stale; the CLI changed and the page did not. "
                f"Run `uv run python scripts/check_cli_docs.py --write`."
            )
            return 1
    print(f"{PAGE.relative_to(ROOT)} matches the command surface")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

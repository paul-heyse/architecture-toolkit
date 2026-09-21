"""Refuse a requirement whose evidence did not run.

A skipped test is green. `pytest` reports it, nothing fails on it, and the requirement it carries
still appears in `reference/requirements.json` as scheduled — so a requirement can go from
"evidenced" to "not evidenced" without a single red build.

That is not hypothetical. W7a shipped thirteen tests carrying CORE-40, CORE-41 and CORE-42 markers
that skip unless `.tools/` has been populated, and CI ran `pytest` twelve steps *before* it ran
`bootstrap_tools.py`. Every one of them skipped on both platforms, for two commits, while the build
stayed green and `docs/qualification.md` claimed the lxml layer was proven against both schema sets.
Two module docstrings asserted the ordering the workflow did not have.

This reads the evidence document the pytest plugin already writes and refuses a run in which a
requirement-marked test skipped. It is deliberately not a pytest hook: the plugin's job is to
*record* what happened, and a recorder that also judges is a recorder you cannot trust to record a
failure. The document is the interface between them.

Run after `pytest`. It needs `.runtime/qualification/requirement-evidence.json`, which pytest
writes on every run, so a missing document means pytest did not run at all — which is itself worth
refusing.
"""

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from _common import ROOT, report

EVIDENCE = Path(".runtime") / "qualification" / "requirement-evidence.json"

# A test may skip for a reason that is a fact about the platform rather than a hole in the
# evidence. `platform`-marked tests are the category `pyproject.toml` registers for exactly that —
# "behaviour that genuinely differs by platform" — and a skip there is the test working.
#
# Nothing is listed today. The constant exists so that the first genuine platform skip is added
# here, with a reason, rather than by loosening the check.
PERMITTED_SKIPS: frozenset[str] = frozenset()


def main() -> None:
    errors: list[str] = []
    warnings: list[str] = []
    success: list[str] = []

    document_path = ROOT / EVIDENCE
    if not document_path.is_file():
        report(
            "requirement evidence",
            [f"{EVIDENCE} is missing; run pytest before this check"],
        )

    document: dict[str, Any] = json.loads(document_path.read_text())
    tests: list[dict[str, Any]] = document["tests"]

    skipped: dict[str, list[str]] = defaultdict(list)
    for entry in tests:
        if entry["outcome"] != "skipped" or entry["node_id"] in PERMITTED_SKIPS:
            continue
        for requirement in entry["requirements"]:
            skipped[requirement].append(entry["node_id"])

    for requirement in sorted(skipped):
        nodes = sorted(skipped[requirement])
        errors.append(
            f"{requirement}: {len(nodes)} test(s) carrying this marker skipped, so the run is "
            f"green and the requirement is unevidenced — {nodes[0]}"
            + (f" (+{len(nodes) - 1} more)" if len(nodes) > 1 else "")
        )

    evidenced = {
        requirement
        for entry in tests
        if entry["outcome"] == "passed"
        for requirement in entry["requirements"]
    }
    if not evidenced:
        errors.append("no requirement-marked test passed; the evidence document proves nothing")

    success.append(
        f"{len(tests)} marked test(s) recorded on {document['platform']}; "
        f"{len(evidenced)} requirement(s) evidenced by a passing test"
    )
    report("requirement evidence", errors, warnings, success)


if __name__ == "__main__":
    main()

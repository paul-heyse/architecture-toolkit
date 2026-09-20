"""Emit machine-readable requirement evidence from a pytest run (CORE-49, CORE-50).

Requirement definitions are static contracts; test outcomes are generated evidence. This plugin
is the generator. It maps `@pytest.mark.requirement("CORE-49")` markers onto outcomes and writes
a document conforming to `schemas/qualification-evidence.schema.json`.

Two deliberate properties:

  * An unknown requirement ID fails collection. A report that silently accepted `CORE-99` would
    claim coverage of a requirement that does not exist, which is worse than no report at all.
  * JUnit remains the standard CI channel (CORE-50). This artifact is separate and additional,
    and nothing here depends on nonstandard JUnit properties.

The document is written under `.runtime/`, which is gitignored: evidence describes one run on one
platform, and a run is not a source artifact.
"""

from __future__ import annotations

import json
import platform
import subprocess
import tomllib
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from _pytest.config import Config
    from _pytest.config.argparsing import Parser
    from _pytest.reports import TestReport

ROOT = Path(__file__).resolve().parents[2]
INDEX = ROOT / "reference" / "requirements.json"
LOCK = ROOT / "uv.lock"
DEFAULT_OUTPUT = ROOT / ".runtime" / "qualification" / "requirement-evidence.json"

SCHEMA_VERSION = 1
MARKER = "requirement"


def pytest_addoption(parser: Parser) -> None:
    parser.getgroup("requirement evidence").addoption(
        "--requirement-evidence",
        action="store",
        default=None,
        metavar="PATH",
        help=f"Write the requirement-evidence document here (default: {DEFAULT_OUTPUT}).",
    )


def pytest_configure(config: Config) -> None:
    config.pluginmanager.register(RequirementEvidence(config), "requirement-evidence-collector")


class _Outcome:
    """One node's outcome and duration, accumulated across setup, call and teardown."""

    def __init__(self) -> None:
        self.outcome = "passed"
        self.duration = 0.0

    def absorb(self, report: TestReport) -> None:
        self.duration += report.duration
        if report.when in {"setup", "teardown"} and report.failed:
            self.outcome = "error"
        elif report.when == "call":
            if hasattr(report, "wasxfail"):
                self.outcome = "xpassed" if report.passed else "xfailed"
            elif report.failed:
                self.outcome = "failed"
            elif report.skipped:
                self.outcome = "skipped"
        elif report.when == "setup" and report.skipped and self.outcome == "passed":
            self.outcome = "skipped"


class RequirementEvidence:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._requirements: dict[str, list[str]] = {}
        self._outcomes: dict[str, _Outcome] = {}

    # -- collection -------------------------------------------------------------------------

    @staticmethod
    def _declared(item: pytest.Item) -> list[str]:
        found: list[str] = []
        for mark in item.iter_markers(name=MARKER):
            for value in mark.args:
                if not isinstance(value, str):
                    message = f"{item.nodeid}: requirement marker takes string IDs, got {value!r}"
                    raise TypeError(message)
                if value not in found:
                    found.append(value)
        return found

    def pytest_collection_modifyitems(self, items: list[pytest.Item]) -> None:
        known = frozenset(entry["id"] for entry in json.loads(INDEX.read_text())["requirements"])
        unknown: list[str] = []
        for item in items:
            declared = self._declared(item)
            if not declared:
                continue
            unknown += [
                f"{item.nodeid}: unknown requirement {r}" for r in declared if r not in known
            ]
            self._requirements[item.nodeid] = declared
        if unknown:
            message = "requirement markers must name an ID in reference/requirements.json:\n  "
            raise pytest.UsageError(message + "\n  ".join(unknown))

    # -- execution --------------------------------------------------------------------------

    def pytest_runtest_logreport(self, report: TestReport) -> None:
        if report.nodeid in self._requirements:
            self._outcomes.setdefault(report.nodeid, _Outcome()).absorb(report)

    # -- reporting --------------------------------------------------------------------------

    @staticmethod
    def _toolkit_commit() -> str:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return result.stdout.strip() or "unknown"

    @staticmethod
    def _dependencies() -> dict[str, str]:
        lock = tomllib.loads(LOCK.read_text())
        return {p["name"]: p["version"] for p in lock.get("package", []) if p.get("version")}

    def document(self) -> dict[str, object]:
        tests = [
            {
                "node_id": node_id,
                "requirements": ids,
                "outcome": self._outcomes[node_id].outcome,
                "duration_seconds": round(self._outcomes[node_id].duration, 6),
            }
            for node_id, ids in sorted(self._requirements.items())
            if node_id in self._outcomes
        ]
        return {
            "schema_version": SCHEMA_VERSION,
            "toolkit_commit": self._toolkit_commit(),
            "platform": f"{platform.system().lower()}-{platform.machine()}",
            "python": platform.python_version(),
            "lock_digest": sha256(LOCK.read_bytes()).hexdigest(),
            "generated_at": datetime.now(UTC).isoformat(),
            "dependencies": dict(sorted(self._dependencies().items())),
            "tests": tests,
        }

    def pytest_sessionfinish(self) -> None:
        if not self._requirements:
            return
        chosen = self._config.getoption("--requirement-evidence")
        output = Path(chosen) if chosen else DEFAULT_OUTPUT
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(self.document(), indent=2) + "\n")

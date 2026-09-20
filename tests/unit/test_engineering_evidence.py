"""Engineering evidence stays separate from architecture-model validation (CORE-66)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from architecture_toolkit.domain.engineering import (
    CheckResult,
    CheckType,
    EngineeringQualificationArtifact,
)

ROOT = Path(__file__).resolve().parents[2]
ENGINEERING = ROOT / "src" / "architecture_toolkit" / "domain" / "engineering.py"


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


@pytest.mark.unit
@pytest.mark.requirement("CORE-66")
def test_engineering_evidence_does_not_touch_model_validation() -> None:
    """Engineering evidence must not reach into the architecture diagnostic model.

    The reverse direction is guarded when W1 adds `validation/diagnostics.py`; until it exists
    there is nothing for it to import.
    """
    imported = _imported_modules(ENGINEERING)
    leaked = {m for m in imported if "validation" in m or "diagnostic" in m}
    assert not leaked, f"engineering evidence imports model validation: {leaked}"


@pytest.mark.unit
@pytest.mark.requirement("CORE-66")
def test_artifact_is_frozen_and_strict() -> None:
    artifact = EngineeringQualificationArtifact(
        artifact_id="eqa-0001",
        toolkit_commit="c7a7407",
        python_version="3.14.7",
        platform="darwin-arm64",
        lock_digest="f96b414c14af58b78869677e30bf1fea39fb1be04e7a28b8f9995dfaa5e819eb",
        check_type=CheckType.TYPE_CHECK,
        tool="pyrefly",
        tool_version="1.3.1",
        result=CheckResult.PASSED,
    )
    with pytest.raises(ValidationError):
        artifact.tool = "ty"  # type: ignore[misc]


@pytest.mark.unit
@pytest.mark.requirement("CORE-66")
def test_unqualified_is_distinct_from_failed() -> None:
    """A capability that was never qualified is not a failure; collapsing them overstates proof."""
    assert CheckResult.NOT_QUALIFIED != CheckResult.FAILED
    assert CheckResult.NOT_IMPLEMENTED != CheckResult.FAILED

"""Engineering qualification evidence (CORE-66).

This qualifies a *toolkit implementation revision* — a checker run, a lint run, a vendor tool
invocation — and is deliberately kept apart from architecture-model validation. A clean Pyrefly
run says nothing about whether a modelled architecture is correct, and `Diagnostic` must never
start carrying source-code quality signals.

The separation is enforced by `tests/unit/test_engineering_evidence.py`: these types share
nothing with the architecture diagnostic model and neither module imports the other.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["CheckResult", "CheckType", "EngineeringQualificationArtifact"]

Digest = Annotated[str, Field(min_length=7, max_length=64)]
NonEmpty = Annotated[str, Field(min_length=1)]


class CheckType(StrEnum):
    """What kind of engineering check produced this evidence."""

    TYPE_CHECK = "type_check"
    TYPE_COVERAGE = "type_coverage"
    LINT = "lint"
    FORMAT = "format"
    TEST_EVIDENCE = "test_evidence"
    DEPENDENCY_QUALIFICATION = "dependency_qualification"
    VENDOR_QUALIFICATION = "vendor_qualification"
    PLATFORM_CI = "platform_ci"


class CheckResult(StrEnum):
    """Outcome vocabulary.

    `not_qualified` and `not_implemented` are first-class: a vendor capability that has not been
    qualified is a distinct state from one that failed, and collapsing them would overstate
    what the toolkit has proven.
    """

    PASSED = "passed"
    FAILED = "failed"
    NOT_QUALIFIED = "not_qualified"
    NOT_IMPLEMENTED = "not_implemented"


class EngineeringQualificationArtifact(BaseModel):
    """One engineering check against one toolkit revision on one platform."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    artifact_id: NonEmpty
    toolkit_commit: Digest
    python_version: NonEmpty
    platform: NonEmpty
    lock_digest: Digest
    check_type: CheckType
    tool: NonEmpty
    tool_version: NonEmpty
    configuration_digest: Digest | None = None
    result: CheckResult
    report_locator: str | None = None
    report_digest: Digest | None = None

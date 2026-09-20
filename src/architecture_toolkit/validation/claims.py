"""What a validation run actually claims (DATA-31, PROJ-07).

The CLI used to print four hardcoded strings — `"structural_contract": "passed"`,
`"notation_validity": "not_checked"` and two more. They were honest, and they were unfalsifiable:
nothing connected them to what had run, so they would have kept saying `passed` after the rule
behind them was deleted.

This is the same honesty with a mechanism behind it. Two invariants do the work:

* a report answers for **every** claim, in enum order, so adding a seventh claim forces every
  report to say something about it rather than silently omitting it;
* a claim may only be `PASSED` if some rule actually checked it. You cannot claim success with
  an empty `checked_by`.

The second is the one that matters. It is what stops `SCHEMA_SYNTAX` quietly reading `passed`
because nobody looked.
"""

from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from architecture_toolkit.domain.base import CompiledRecord
from architecture_toolkit.domain.identifiers import ModelId, ProfileVersion, RuleId, SchemaVersion
from architecture_toolkit.validation.context import ValidationMode
from architecture_toolkit.validation.diagnostics import Diagnostic
from architecture_toolkit.validation.taxonomy import Disposition, Severity, ValidationClaim

__all__ = ["ClaimOutcome", "ClaimStatus", "ValidationClaimReport"]


class ClaimStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    NOT_CHECKED = "not_checked"
    NOT_FULLY_CHECKED = "not_fully_checked"
    NOT_ESTABLISHED = "not_established"
    NOT_IMPLEMENTED = "not_implemented"


class ClaimOutcome(CompiledRecord):
    claim: ValidationClaim
    status: ClaimStatus
    scope: str = Field(min_length=1)
    checked_by: tuple[RuleId, ...] = ()
    diagnostic_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def passing_requires_something_to_have_run(self) -> Self:
        if self.status is ClaimStatus.PASSED and not self.checked_by:
            message = (
                f"claim {self.claim.value!r} cannot be 'passed' with no rule behind it; "
                f"use 'not_checked'"
            )
            raise ValueError(message)
        return self


class ValidationClaimReport(CompiledRecord):
    model_id: ModelId
    schema_version: SchemaVersion
    profile_version: ProfileVersion
    validation_mode: ValidationMode
    claims: tuple[ClaimOutcome, ...]
    diagnostics: tuple[Diagnostic, ...] = ()

    @model_validator(mode="after")
    def every_claim_is_answered_once_in_order(self) -> Self:
        answered = tuple(outcome.claim for outcome in self.claims)
        if answered != tuple(ValidationClaim):
            message = (
                "a report must answer for every validation claim in enum order; got "
                f"{[c.value for c in answered]}"
            )
            raise ValueError(message)
        return self

    @property
    def hard_errors(self) -> tuple[Diagnostic, ...]:
        return tuple(
            diagnostic
            for diagnostic in self.diagnostics
            if diagnostic.disposition is Disposition.HARD_STRUCTURAL_ERROR
            and diagnostic.severity is Severity.ERROR
        )

    @property
    def evidence_gaps(self) -> tuple[Diagnostic, ...]:
        """Reported, never fatal. Failing on these is what drives authors to invent values."""
        return tuple(
            diagnostic
            for diagnostic in self.diagnostics
            if diagnostic.disposition is Disposition.EVIDENCE_GAP
        )

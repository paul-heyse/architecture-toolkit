"""The common Diagnostic (CORE-07, CORE-11).

Exactly the thirteen fields `core.md` specifies, and no more. `claim` and `disposition` are read
from the code registry rather than stored, because they are properties of a *rule* and not of an
occurrence: storing them would let two findings with the same code disagree about what kind of
claim they bear on, and would widen the shape W3 has to freeze into Arrow.

They are plain properties, deliberately not `computed_field`. A computed field appears in the
serialization schema and not the validation one, which is the only thing that makes those two
schemas differ — so keeping these off the model is what lets CORE-13's check assert the strongest
possible form: that the two modes are identical.

`source_location` is present and nullable now, and W1 never populates it. W2 owns the source map.
Adding the field later would mean replumbing every diagnostic W3 and W4 emit.

Identity is derived, not random. A uuid4 would make two runs of the same validation incomparable
and would defeat the golden-output tests the renderer needs.
"""

from hashlib import sha256
from typing import Self

from pydantic import Field, model_validator

from architecture_toolkit.domain.base import CompiledRecord
from architecture_toolkit.domain.identifiers import (
    NotationObjectId,
    RelationshipId,
    RuleId,
)
from architecture_toolkit.validation.codes import CODES
from architecture_toolkit.validation.taxonomy import (
    DiagnosticCategory,
    Disposition,
    Severity,
    ValidationClaim,
)

__all__ = ["Diagnostic", "SourceLocation", "build_diagnostic"]


class SourceLocation(CompiledRecord):
    """Where in the authored source a diagnostic came from. Populated at W2 (CORE-18)."""

    source_id: str = Field(min_length=1)
    document_id: str | None = None
    semantic_path: str | None = None
    line: int | None = Field(default=None, ge=1)
    column: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    end_column: int | None = Field(default=None, ge=1)


class Diagnostic(CompiledRecord):
    diagnostic_id: str = Field(min_length=1)
    code: str
    severity: Severity
    category: DiagnosticCategory
    message: str = Field(min_length=1)
    canonical_object_id: str | None = None
    relationship_id: RelationshipId | None = None
    field_path: str | None = None
    source_location: SourceLocation | None = None
    notation_object_id: NotationObjectId | None = None
    rule_id: RuleId | None = None
    # A tuple of pairs rather than a mapping, so the record stays hashable under the CORE-08
    # guard. Pydantic does not support `MappingProxyType`, and a `dict` field would make every
    # Diagnostic unhashable.
    context: tuple[tuple[str, str], ...] = ()
    remediation: str | None = None

    @model_validator(mode="after")
    def code_is_registered_and_agrees_with_its_category(self) -> Self:
        """An unregistered code cannot reach a report.

        This is what stops a rule inventing a code on the way out and a reader discovering it in
        production output. The category check keeps the registry authoritative rather than
        advisory.
        """
        spec = CODES.get(self.code)
        if spec is None:
            message = f"diagnostic code {self.code!r} is not registered in validation.codes"
            raise ValueError(message)
        if spec.category is not self.category:
            message = (
                f"diagnostic {self.code!r} declares category {self.category.value!r} but the "
                f"registry says {spec.category.value!r}"
            )
            raise ValueError(message)
        return self

    @property
    def claim(self) -> ValidationClaim:
        """What correctness this bears on. Registry-owned, so occurrences cannot disagree."""
        return CODES[self.code].claim

    @property
    def disposition(self) -> Disposition:
        """How to treat it. Separate from severity: a gap and a profile expectation both warn."""
        return CODES[self.code].disposition


def build_diagnostic(
    code: str,
    *,
    message: str,
    rule_id: RuleId | None = None,
    canonical_object_id: str | None = None,
    relationship_id: RelationshipId | None = None,
    field_path: str | None = None,
    notation_object_id: NotationObjectId | None = None,
    context: tuple[tuple[str, str], ...] = (),
    severity: Severity | None = None,
) -> Diagnostic:
    """Construct one, taking category, severity and remediation from the registry.

    The derived `diagnostic_id` is a digest of everything that identifies the finding. Two
    genuinely identical findings therefore share an id, which is correct — they are one finding
    reported twice, not two.
    """
    spec = CODES[code]
    identity = "|".join(
        (
            code,
            rule_id or "",
            canonical_object_id or "",
            relationship_id or "",
            field_path or "",
            ";".join(f"{key}={value}" for key, value in sorted(context)),
        )
    )
    return Diagnostic(
        diagnostic_id=f"diag-{sha256(identity.encode()).hexdigest()[:16]}",
        code=code,
        severity=severity or spec.default_severity,
        category=spec.category,
        message=message,
        canonical_object_id=canonical_object_id,
        relationship_id=relationship_id,
        field_path=field_path,
        notation_object_id=notation_object_id,
        rule_id=rule_id,
        context=tuple(sorted(context)),
        remediation=spec.remediation,
    )

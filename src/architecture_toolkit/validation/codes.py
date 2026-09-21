"""The diagnostic code registry (CORE-11).

`ARCH-TOOL-CORE-001` §3H fixes the namespace as `CORE.<AREA>.<REASON>` and names four codes.
The registry exists so the three taxonomy axes are set once per code rather than at every raise
site: two occurrences of `CORE.RELATION.UNRESOLVED_ENDPOINT` cannot disagree about whether they
are a hard structural error, because neither of them decides.

A code that is not registered cannot be put on a `Diagnostic`. That is the first of the guards
that make a new rule impossible to add without also declaring what it means.
"""

import re
from collections.abc import Mapping
from enum import StrEnum

from architecture_toolkit.domain.base import CompiledRecord
from architecture_toolkit.validation.taxonomy import (
    DiagnosticCategory,
    Disposition,
    Severity,
    ValidationClaim,
)

__all__ = ["CODES", "CODE_PATTERN", "CodeArea", "DiagnosticCodeSpec"]

CODE_PATTERN = r"^CORE\.[A-Z][A-Z0-9]*\.[A-Z][A-Z0-9_]*$"


class CodeArea(StrEnum):
    """Closed, so a typo'd area is a failure rather than a new area nobody agreed to."""

    DOMAIN = "DOMAIN"
    RELATION = "RELATION"
    CONTAINMENT = "CONTAINMENT"
    EVIDENCE = "EVIDENCE"
    INTERFACE = "INTERFACE"
    WORKFLOW = "WORKFLOW"
    VIEW = "VIEW"
    RELEASE = "RELEASE"
    SCHEMA = "SCHEMA"
    YAML = "YAML"


class DiagnosticCodeSpec(CompiledRecord):
    code: str
    area: CodeArea
    category: DiagnosticCategory
    claim: ValidationClaim
    disposition: Disposition
    default_severity: Severity
    summary: str
    remediation: str | None = None


def _spec(
    code: str,
    area: CodeArea,
    *,
    category: DiagnosticCategory = DiagnosticCategory.CROSS_RECORD_VALIDATION,
    claim: ValidationClaim = ValidationClaim.CANONICAL_STRUCTURE,
    disposition: Disposition = Disposition.HARD_STRUCTURAL_ERROR,
    severity: Severity = Severity.ERROR,
    summary: str,
    remediation: str | None = None,
) -> DiagnosticCodeSpec:
    return DiagnosticCodeSpec(
        code=code,
        area=area,
        category=category,
        claim=claim,
        disposition=disposition,
        default_severity=severity,
        summary=summary,
        remediation=remediation,
    )


_RECORD = DiagnosticCategory.RECORD_VALIDATION
_CROSS = DiagnosticCategory.CROSS_RECORD_VALIDATION
_AUTHORING = DiagnosticCategory.AUTHORING_PARSE
_SEMANTIC = ValidationClaim.CROSS_MODEL_SEMANTICS
_GAP = Disposition.EVIDENCE_GAP
_PROFILE = Disposition.PROFILE_EXPECTATION

_ALL: tuple[DiagnosticCodeSpec, ...] = (
    # -- the four `ARCH-TOOL-CORE-001` §3H names verbatim -------------------------------------
    _spec(
        "CORE.DOMAIN.INVALID_ID",
        CodeArea.DOMAIN,
        category=_RECORD,
        summary="An identifier does not match the constraint its semantic alias declares.",
        remediation="Use lowercase, start with a letter, 3 to 64 characters.",
    ),
    _spec(
        "CORE.DOMAIN.MUTUALLY_EXCLUSIVE_FIELDS",
        CodeArea.DOMAIN,
        category=_RECORD,
        summary="Two fields of one record were set that cannot both apply.",
    ),
    _spec(
        "CORE.DOMAIN.INVALID_VARIANT",
        CodeArea.DOMAIN,
        category=_RECORD,
        summary="A discriminated union tag names no known variant.",
    ),
    _spec(
        "CORE.RELATION.UNRESOLVED_ENDPOINT",
        CodeArea.RELATION,
        summary="A relationship names an element that does not exist in this model.",
        remediation="Add the element, or correct the endpoint identifier.",
    ),
    # -- record-local -------------------------------------------------------------------------
    _spec(
        "CORE.DOMAIN.MISSING_REQUIRED_FIELD",
        CodeArea.DOMAIN,
        category=_RECORD,
        summary="A required field was absent.",
    ),
    _spec(
        "CORE.DOMAIN.UNKNOWN_FIELD",
        CodeArea.DOMAIN,
        category=_RECORD,
        summary="An undeclared field was supplied to a closed record.",
    ),
    _spec(
        "CORE.DOMAIN.INVALID_FORMAT",
        CodeArea.DOMAIN,
        category=_RECORD,
        summary="A value did not match the format its field declares.",
    ),
    _spec(
        "CORE.DOMAIN.INVALID_TYPE",
        CodeArea.DOMAIN,
        category=_RECORD,
        summary="A value was of the wrong type under strict validation.",
    ),
    _spec(
        "CORE.DOMAIN.INVALID_VALUE",
        CodeArea.DOMAIN,
        category=_RECORD,
        summary="A value was well-typed but outside the range or vocabulary the field permits.",
    ),
    _spec(
        "CORE.DOMAIN.MISSING_VALIDATION_CONTEXT",
        CodeArea.DOMAIN,
        category=_RECORD,
        summary="A validator requiring an explicit ValidationContext was called without one.",
        remediation="Pass ValidationContext(...).as_pydantic_context() as the Pydantic context.",
    ),
    _spec(
        "CORE.DOMAIN.DUPLICATE_ID",
        CodeArea.DOMAIN,
        summary="Two records in one model claim the same identity.",
    ),
    # -- relationships ------------------------------------------------------------------------
    _spec(
        "CORE.RELATION.UNKNOWN_TYPE",
        CodeArea.RELATION,
        summary="A relationship names a type the active profile does not define.",
        remediation="Add the type to the profile, or use one the profile already declares.",
    ),
    _spec(
        "CORE.RELATION.ENDPOINT_KIND_NOT_PERMITTED",
        CodeArea.RELATION,
        claim=_SEMANTIC,
        summary="An endpoint's kind is not permitted for this relationship type.",
    ),
    _spec(
        "CORE.RELATION.SELF_LOOP",
        CodeArea.RELATION,
        claim=_SEMANTIC,
        summary="A relationship type that forbids self-loops joins an element to itself.",
    ),
    _spec(
        "CORE.RELATION.DUPLICATE_INVERSE",
        CodeArea.RELATION,
        claim=_SEMANTIC,
        summary="Both directions of a symmetric relationship were stored.",
        remediation="Store one canonical direction; the inverse is a derived view (DATA-06).",
    ),
    # -- containment --------------------------------------------------------------------------
    _spec(
        "CORE.CONTAINMENT.CYCLE",
        CodeArea.CONTAINMENT,
        claim=_SEMANTIC,
        summary="A relationship type declared acyclic forms a cycle.",
    ),
    _spec(
        "CORE.CONTAINMENT.MULTIPLE_PARENTS",
        CodeArea.CONTAINMENT,
        claim=_SEMANTIC,
        summary="An element is contained by more than one parent.",
    ),
    # -- evidence -----------------------------------------------------------------------------
    _spec(
        "CORE.EVIDENCE.UNRESOLVED_SUBJECT",
        CodeArea.EVIDENCE,
        summary="A reference link addresses an object that does not exist.",
    ),
    _spec(
        "CORE.EVIDENCE.UNRESOLVED_REFERENCE",
        CodeArea.EVIDENCE,
        summary="A reference link names a reference that does not exist.",
    ),
    _spec(
        "CORE.EVIDENCE.NO_SUPPORTING_REFERENCE",
        CodeArea.EVIDENCE,
        claim=_SEMANTIC,
        disposition=_GAP,
        severity=Severity.WARNING,
        summary="An assertion has no supporting reference.",
        remediation="Record the evidence, or leave the gap explicit. Do not invent a source.",
    ),
    _spec(
        "CORE.EVIDENCE.CONTRADICTED",
        CodeArea.EVIDENCE,
        claim=_SEMANTIC,
        disposition=Disposition.HUMAN_REVIEW,
        severity=Severity.WARNING,
        summary="A reference contradicts the assertion it is linked to.",
    ),
    # -- interfaces and schemas ---------------------------------------------------------------
    _spec(
        "CORE.INTERFACE.UNRESOLVED_SCHEMA",
        CodeArea.INTERFACE,
        summary="An interface names a request or response schema that does not exist.",
    ),
    _spec(
        "CORE.INTERFACE.DETAIL_NOT_PERMITTED",
        CodeArea.INTERFACE,
        claim=_SEMANTIC,
        disposition=_PROFILE,
        severity=Severity.WARNING,
        summary="An element carries a detail family its kind does not permit in this profile.",
    ),
    _spec(
        "CORE.INTERFACE.UNRESOLVED_FOREIGN_KEY",
        CodeArea.INTERFACE,
        summary="A schema field declares a foreign key to an element that does not exist.",
    ),
    # -- workflow -----------------------------------------------------------------------------
    _spec(
        "CORE.WORKFLOW.UNRESOLVED_PARTICIPANT",
        CodeArea.WORKFLOW,
        summary="A behaviour node or interaction names a participant that does not exist.",
    ),
    _spec(
        "CORE.WORKFLOW.NO_PARTICIPANT",
        CodeArea.WORKFLOW,
        claim=_SEMANTIC,
        disposition=_GAP,
        severity=Severity.INFO,
        summary="A behaviour node has no participating element.",
        remediation="Expected for a manual step. DATA-41: do not attach an application to "
        "complete a coverage matrix.",
    ),
    # -- release and profile ------------------------------------------------------------------
    _spec(
        "CORE.RELEASE.PROFILE_VERSION_UNSUPPORTED",
        CodeArea.RELEASE,
        category=DiagnosticCategory.RELEASE_COHERENCE,
        disposition=_PROFILE,
        summary="The model declares a profile version the active profile does not provide.",
    ),
    # W4: read-back coherence. These describe a *release*, not a model, so they are raised by
    # `validation/release.py` rather than registered as cross-record rules — a rule takes a model
    # candidate, and every registered rule needs a known-bad model fixture, which a manifest
    # mismatch cannot supply.
    _spec(
        "CORE.RELEASE.TABLE_NOT_PINNED",
        CodeArea.RELEASE,
        category=DiagnosticCategory.RELEASE_COHERENCE,
        summary="The manifest does not pin every table the storage schema declares.",
        remediation="Publish through the release protocol, which pins all eleven tables.",
    ),
    _spec(
        "CORE.RELEASE.DIGEST_MISMATCH",
        CodeArea.RELEASE,
        category=DiagnosticCategory.RELEASE_COHERENCE,
        summary="A staged table read back with a different semantic digest from the one pinned.",
        remediation=(
            "Do not publish. The staged version is orphaned and the current release is unchanged."
        ),
    ),
    _spec(
        "CORE.RELEASE.ROW_COUNT_MISMATCH",
        CodeArea.RELEASE,
        category=DiagnosticCategory.RELEASE_COHERENCE,
        summary="A staged table read back with a different row count from the one pinned.",
    ),
    _spec(
        "CORE.RELEASE.VERSION_UNREADABLE",
        CodeArea.RELEASE,
        category=DiagnosticCategory.RELEASE_COHERENCE,
        summary="A version a retained manifest pins can no longer be read.",
        remediation=(
            "Retention removed a version a release needs. Restore from a milestone archive; "
            "`releases/retention.py` computes the protected set so this cannot happen again."
        ),
    ),
    _spec(
        "CORE.RELEASE.PARENT_NOT_FOUND",
        CodeArea.RELEASE,
        category=DiagnosticCategory.RELEASE_COHERENCE,
        summary="A manifest names a parent release the store does not hold.",
        remediation=(
            "The chain is what makes a release history navigable; a missing link means a manifest "
            "was removed without its descendants, or copied out of another store."
        ),
    ),
    _spec(
        "CORE.RELEASE.CHAIN_CYCLE",
        CodeArea.RELEASE,
        category=DiagnosticCategory.RELEASE_COHERENCE,
        summary="Release parentage forms a cycle, so no release is the first.",
    ),
    _spec(
        "CORE.RELEASE.MULTIPLE_ROOTS",
        CodeArea.RELEASE,
        category=DiagnosticCategory.RELEASE_COHERENCE,
        summary="One model has more than one release with no parent.",
        remediation=(
            "Every release after the first names the one it was built against. Two roots means "
            "two histories in one store, which no reader can order."
        ),
    ),
    _spec(
        "CORE.RELEASE.STORAGE_SCHEMA_MISMATCH",
        CodeArea.RELEASE,
        category=DiagnosticCategory.RELEASE_COHERENCE,
        summary="The release was written against a different storage schema version.",
        remediation="Apply the declared migration for that version rather than merging schemas.",
    ),
    _spec(
        "CORE.VIEW.UNRESOLVED_MEMBER",
        CodeArea.VIEW,
        summary="A view names an object that does not exist. Reserved; views arrive at W7a.",
    ),
    # -- YAML authoring (CORE-15, CORE-16) ----------------------------------------------------
    # Raised by `domain/authoring/` as `AuthoringError` and normalized here. Parse failures never
    # enter a claim report — no model exists to report on — so each keeps the default claim and
    # disposition and the CLI renders them directly with exit code 3.
    _spec(
        "CORE.YAML.DUPLICATE_KEY",
        CodeArea.YAML,
        category=_AUTHORING,
        summary="A mapping key appears more than once.",
        remediation="Keys are unique within a mapping; there is no last-one-wins.",
    ),
    _spec(
        "CORE.YAML.ANCHOR",
        CodeArea.YAML,
        category=_AUTHORING,
        summary="A YAML anchor was declared.",
        remediation="Repeat the value. The baseline profile forbids anchors so a document means "
        "what it shows.",
    ),
    _spec(
        "CORE.YAML.ALIAS",
        CodeArea.YAML,
        category=_AUTHORING,
        summary="A YAML alias was used.",
        remediation="Repeat the value; hidden source inheritance defeats source diagnostics.",
    ),
    _spec(
        "CORE.YAML.MERGE_KEY",
        CodeArea.YAML,
        category=_AUTHORING,
        summary="A merge key (<<) was used.",
        remediation="Write the merged keys out in place.",
    ),
    _spec(
        "CORE.YAML.CUSTOM_TAG",
        CodeArea.YAML,
        category=_AUTHORING,
        summary="A tag outside the YAML 1.2 core schema was used.",
        remediation="Only the core schema (str, int, float, bool, null, map, seq) is authored; "
        "dates and binary values are strings.",
    ),
    _spec(
        "CORE.YAML.PYTHON_TAG",
        CodeArea.YAML,
        category=_AUTHORING,
        summary="A Python object tag was used.",
        remediation="Remove the tag. Authoring sources never construct Python objects.",
    ),
    _spec(
        "CORE.YAML.UNSUPPORTED_VERSION",
        CodeArea.YAML,
        category=_AUTHORING,
        summary="The document declares a YAML version other than 1.2.",
        remediation="Remove the %YAML directive or declare 1.2.",
    ),
    _spec(
        "CORE.YAML.DEPTH_EXCEEDED",
        CodeArea.YAML,
        category=_AUTHORING,
        summary="Collections are nested deeper than the profile permits.",
    ),
    _spec(
        "CORE.YAML.MULTIPLE_DOCUMENTS",
        CodeArea.YAML,
        category=_AUTHORING,
        summary="A source file holds more than one YAML document.",
        remediation="One model per file. Split the stream.",
    ),
    _spec(
        "CORE.YAML.SYNTAX",
        CodeArea.YAML,
        category=_AUTHORING,
        summary="The document is not well-formed under the authoring profile.",
    ),
    _spec(
        "CORE.YAML.NOT_A_MAPPING",
        CodeArea.YAML,
        category=_AUTHORING,
        summary="The document root is not a mapping.",
        remediation="A model is a mapping of `model_id`, `elements`, `relationships`, ...",
    ),
    # -- the toolkit's own failures -----------------------------------------------------------
    _spec(
        "CORE.SCHEMA.RULE_CRASHED",
        CodeArea.SCHEMA,
        category=DiagnosticCategory.SCHEMA_INTEROPERABILITY,
        summary="A validation rule raised. This is a toolkit defect, not a model defect.",
    ),
    _spec(
        "CORE.SCHEMA.UNCLASSIFIED",
        CodeArea.SCHEMA,
        category=_RECORD,
        summary="A validation failure the normalizer has no specific code for.",
    ),
)

CODES: Mapping[str, DiagnosticCodeSpec] = {spec.code: spec for spec in _ALL}


def _check_registry() -> None:
    """Fail at import rather than at the first raise site."""
    for spec in _ALL:
        if not re.fullmatch(CODE_PATTERN, spec.code):
            message = f"diagnostic code {spec.code!r} does not match {CODE_PATTERN}"
            raise ValueError(message)
        if spec.code.split(".")[1] != spec.area.value:
            message = f"diagnostic code {spec.code!r} disagrees with its declared area"
            raise ValueError(message)
    if len(CODES) != len(_ALL):
        raise ValueError("duplicate diagnostic code")


_check_registry()

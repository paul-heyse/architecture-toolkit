"""The diagnostic code registry (CORE-11)."""

import re

import pytest
from pydantic import ValidationError

from architecture_toolkit.validation.codes import CODE_PATTERN, CODES, CodeArea
from architecture_toolkit.validation.diagnostics import Diagnostic, build_diagnostic
from architecture_toolkit.validation.taxonomy import DiagnosticCategory, Severity

NAMED_BY_THE_CONTRACT = (
    "CORE.DOMAIN.INVALID_ID",
    "CORE.DOMAIN.MUTUALLY_EXCLUSIVE_FIELDS",
    "CORE.DOMAIN.INVALID_VARIANT",
    "CORE.RELATION.UNRESOLVED_ENDPOINT",
)


@pytest.mark.unit
@pytest.mark.requirement("CORE-11")
@pytest.mark.parametrize("code", NAMED_BY_THE_CONTRACT)
def test_the_codes_the_contract_names_exist_verbatim(code: str) -> None:
    assert code in CODES


@pytest.mark.unit
@pytest.mark.requirement("CORE-11")
def test_every_code_matches_the_namespace_and_agrees_with_its_area() -> None:
    for code, spec in CODES.items():
        assert re.fullmatch(CODE_PATTERN, code), code
        assert code.split(".")[1] == spec.area.value, code
        assert spec.area in CodeArea


@pytest.mark.unit
@pytest.mark.requirement("CORE-11")
def test_an_unregistered_code_cannot_reach_a_report() -> None:
    """The first guard against a rule inventing a code on its way out.

    Constructed with `Severity.ERROR` rather than `"error"`: under `strict=True`, Python-mode
    validation requires the enum member. Only JSON mode resolves the string.
    """
    with pytest.raises(ValidationError, match="not registered"):
        Diagnostic(
            diagnostic_id="diag-1",
            code="CORE.DOMAIN.MADE_UP",
            severity=Severity.ERROR,
            category=DiagnosticCategory.RECORD_VALIDATION,
            message="x",
        )


@pytest.mark.unit
@pytest.mark.requirement("CORE-11")
def test_a_diagnostic_cannot_disagree_with_the_registry_about_its_category() -> None:
    with pytest.raises(ValidationError, match="but the registry says"):
        Diagnostic(
            diagnostic_id="diag-1",
            code="CORE.RELATION.UNRESOLVED_ENDPOINT",
            severity=Severity.ERROR,
            category=DiagnosticCategory.RENDERING,
            message="x",
        )


@pytest.mark.unit
@pytest.mark.requirement("CORE-11")
def test_claim_and_disposition_are_registry_owned_not_stored() -> None:
    """Two occurrences of one code cannot disagree about what kind of finding they are.

    They are plain properties rather than `computed_field` on purpose: a computed field would
    appear in the serialization schema and not the validation one, which is the only thing that
    makes those two differ. Keeping them off the model is what lets CORE-13 assert the strongest
    form of its requirement.
    """
    assert len(Diagnostic.model_fields) == 13
    assert "claim" not in Diagnostic.model_fields
    assert "disposition" not in Diagnostic.model_fields
    one = build_diagnostic("CORE.RELATION.UNRESOLVED_ENDPOINT", message="a")
    assert one.claim is CODES[one.code].claim
    assert one.disposition is CODES[one.code].disposition


@pytest.mark.unit
@pytest.mark.requirement("CORE-11")
def test_diagnostic_identity_is_derived_so_two_runs_are_comparable() -> None:
    """A uuid4 would make every run's output differ and defeat golden rendering tests."""
    first = build_diagnostic(
        "CORE.RELATION.UNRESOLVED_ENDPOINT", message="a", relationship_id="rel-1"
    )
    again = build_diagnostic(
        "CORE.RELATION.UNRESOLVED_ENDPOINT", message="a", relationship_id="rel-1"
    )
    other = build_diagnostic(
        "CORE.RELATION.UNRESOLVED_ENDPOINT", message="a", relationship_id="rel-2"
    )
    assert first.diagnostic_id == again.diagnostic_id
    assert first.diagnostic_id != other.diagnostic_id


@pytest.mark.unit
@pytest.mark.requirement("CORE-08", "CORE-11")
def test_a_diagnostic_is_hashable() -> None:
    """`context` is a tuple of pairs, not a mapping, so the CORE-08 guard still holds."""
    assert isinstance(hash(build_diagnostic("CORE.DOMAIN.DUPLICATE_ID", message="a")), int)

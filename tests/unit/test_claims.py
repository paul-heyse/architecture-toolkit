"""What a validation run claims, and what it may not claim (DATA-31, PROJ-07)."""

import json
from typing import Any

import pytest
from pydantic import ValidationError

from architecture_toolkit.domain.model import Model
from architecture_toolkit.validation.claims import (
    ClaimOutcome,
    ClaimStatus,
    ValidationClaimReport,
)
from architecture_toolkit.validation.context import ValidationMode
from architecture_toolkit.validation.pipeline import validate_model
from architecture_toolkit.validation.render import render_report
from architecture_toolkit.validation.taxonomy import ValidationClaim


def _report(source: dict[str, Any]) -> ValidationClaimReport:
    return validate_model(Model.model_validate_json(json.dumps(source)))


@pytest.mark.unit
@pytest.mark.requirement("DATA-31")
def test_a_report_answers_for_every_claim_in_order(
    minimal_model_source: dict[str, Any],
) -> None:
    """Adding a seventh claim must force every report to say something about it."""
    report = _report(minimal_model_source)
    assert tuple(outcome.claim for outcome in report.claims) == tuple(ValidationClaim)


@pytest.mark.unit
@pytest.mark.requirement("DATA-31")
def test_a_partial_report_is_rejected() -> None:
    with pytest.raises(ValidationError, match="every validation claim"):
        ValidationClaimReport(
            model_id="m-1",
            schema_version="1.0.0",
            profile_version="1.0.0",
            validation_mode=ValidationMode.AUTHORING,
            claims=(
                ClaimOutcome(
                    claim=ValidationClaim.CANONICAL_STRUCTURE,
                    status=ClaimStatus.PASSED,
                    scope="one rule ran",
                    checked_by=("unique-identities",),
                ),
            ),
        )


@pytest.mark.unit
@pytest.mark.requirement("DATA-31", "PROJ-07")
def test_passed_requires_a_rule_to_have_run() -> None:
    """The single most useful invariant here.

    The CLI used to print `"structural_contract": "passed"` as a literal, which would have kept
    saying it after the check behind it was deleted. A claim can now only pass if something
    checked it.
    """
    with pytest.raises(ValidationError, match="cannot be 'passed' with no rule behind it"):
        ClaimOutcome(
            claim=ValidationClaim.SCHEMA_SYNTAX,
            status=ClaimStatus.PASSED,
            scope="nothing actually ran",
            checked_by=(),
        )


@pytest.mark.unit
@pytest.mark.requirement("DATA-31")
def test_unreachable_claims_say_so_rather_than_passing(
    minimal_model_source: dict[str, Any],
) -> None:
    """Honesty about what this wave cannot establish."""
    by_claim = {outcome.claim: outcome for outcome in _report(minimal_model_source).claims}
    assert by_claim[ValidationClaim.RENDERER].status is ClaimStatus.NOT_IMPLEMENTED
    assert by_claim[ValidationClaim.NOTATION_SEMANTICS].status is ClaimStatus.NOT_CHECKED
    real_world = by_claim[ValidationClaim.REAL_WORLD_CORRECTNESS]
    assert real_world.status is ClaimStatus.NOT_ESTABLISHED
    assert real_world.checked_by == ()


@pytest.mark.unit
@pytest.mark.requirement("DATA-31")
def test_a_deferred_rule_family_downgrades_the_claim_it_would_have_served(
    minimal_model_source: dict[str, Any],
) -> None:
    """Views are deferred to W7a, so cross-model semantics cannot be claimed complete."""
    by_claim = {outcome.claim: outcome for outcome in _report(minimal_model_source).claims}
    semantics = by_claim[ValidationClaim.CROSS_MODEL_SEMANTICS]
    assert semantics.status is ClaimStatus.NOT_FULLY_CHECKED
    assert "views deferred" in semantics.scope
    assert semantics.checked_by


@pytest.mark.unit
@pytest.mark.requirement("CORE-11")
def test_a_failing_rule_fails_the_claim_it_serves(minimal_model_source: dict[str, Any]) -> None:
    raw = minimal_model_source
    raw["relationships"][0]["target_element_id"] = "missing"
    by_claim = {outcome.claim: outcome for outcome in _report(raw).claims}
    assert by_claim[ValidationClaim.CANONICAL_STRUCTURE].status is ClaimStatus.FAILED


@pytest.mark.unit
@pytest.mark.requirement("CORE-11")
def test_the_human_rendering_matches_the_specified_four_line_form(
    minimal_model_source: dict[str, Any],
) -> None:
    """`ARCH-TOOL-CORE-001` §5E, degraded as specified where W1 has no source map."""
    raw = minimal_model_source
    raw["relationships"][0]["target_element_id"] = "missing"
    rendered = render_report(_report(raw), source="examples/minimal/model.yaml")
    block = rendered.split("\n\n")[0].splitlines()
    # Line one is the bare path: `source_location` is None until W2, and emitting `:0:0` would
    # teach every reader to accept a position that means "unknown".
    assert block[0] == "examples/minimal/model.yaml"
    assert block[1] == "ERROR CORE.RELATION.UNRESOLVED_ENDPOINT"
    assert block[2] == "relationships.rel-1.target_element_id"
    assert block[3] == "'missing' does not resolve."

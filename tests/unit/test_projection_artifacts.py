"""Projection provenance records (PROJ-04..PROJ-07).

None of these is produced yet — W7b generates projections, W7b or later renders them. They are
declared now for the reason W4 declared the manifest's artifact fields before filling them: adding
a record shape after releases exist is a DATA-56 migration on every one of them.
"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from architecture_toolkit.domain.notation import Notation
from architecture_toolkit.projections.artifacts import (
    LayoutArtifact,
    LayoutProfile,
    ProjectionArtifact,
    RenderArtifact,
    ValidationArtifact,
)
from architecture_toolkit.validation.taxonomy import Severity, ValidationClaim

DIGEST = "sha256:" + "a" * 64
OTHER = "sha256:" + "b" * 64
MOMENT = datetime(2026, 9, 21, 12, 0, 0, tzinfo=UTC)


def projection(**overrides: object) -> ProjectionArtifact:
    payload: dict[str, object] = {
        "projection_artifact_id": "proj-1",
        "release_id": "rel-0001",
        "view_id": "view-1",
        "notation": Notation.C4,
        "notation_version": "1.0",
        "generator_version": "0.1.0",
        "mapping_profile_version": "1.0.0",
        "semantic_input_digest": DIGEST,
        "generated_source_locator": "outputs/view-1.dsl",
        "generated_source_digest": OTHER,
    }
    return ProjectionArtifact.model_validate(payload | overrides)


@pytest.mark.unit
@pytest.mark.requirement("PROJ-07")
def test_validation_type_is_the_claim_vocabulary_that_already_exists() -> None:
    """PROJ-07's six dimensions and `ValidationClaim`'s six members are the same six.

    A parallel enum would be two lists to keep in step, and one of them would drift. This asserts
    the reuse rather than the equality of two vocabularies, because there is only one.
    """
    artifact = ValidationArtifact(
        validation_artifact_id="val-1",
        release_id="rel-0001",
        validation_type=ValidationClaim.SCHEMA_SYNTAX,
        validator="lxml",
        validator_version="6.1.3",
        passed=True,
        created_at=MOMENT,
    )
    assert artifact.validation_type in set(ValidationClaim)
    assert len(ValidationClaim) == 6
    assert artifact.is_clean


@pytest.mark.unit
@pytest.mark.requirement("PROJ-07")
def test_a_clean_result_is_not_the_same_as_a_passing_one() -> None:
    """A run can pass with warnings. Collapsing the two would lose the warnings."""
    artifact = ValidationArtifact(
        validation_artifact_id="val-1",
        release_id="rel-0001",
        validation_type=ValidationClaim.NOTATION_SEMANTICS,
        validator="bpmnlint",
        validator_version="11.0.0",
        severity_summary=((Severity.WARNING, 3),),
        passed=True,
        created_at=MOMENT,
    )
    assert artifact.passed
    assert not artifact.is_clean
    assert artifact.total_findings == 3


@pytest.mark.unit
@pytest.mark.requirement("PROJ-04", "DATA-31")
def test_layout_geometry_names_the_exact_view_digest_it_lays_out() -> None:
    """Geometry that did not say which version of a view it lays out would be applied to one
    whose membership had since changed — placing objects that are gone and omitting ones that
    are not."""
    artifact = LayoutArtifact(
        layout_artifact_id="layout-art-1",
        view_id="view-1",
        view_content_digest=DIGEST,
        layout_profile_id="layout-1",
        layout_version="1.0.0",
        geometry_locator="layouts/view-1.json",
        source_engine="bpmn-auto-layout",
        source_engine_version="0.5.0",
        content_hash=OTHER,
    )
    assert artifact.view_content_digest == DIGEST
    with pytest.raises(ValidationError):
        LayoutArtifact.model_validate(dict(artifact) | {"view_content_digest": "not-a-digest"})


@pytest.mark.unit
@pytest.mark.requirement("PROJ-05", "CORE-36")
def test_a_projection_records_the_template_bundle_as_well_as_the_generator() -> None:
    """The field `projections.md` does not name and CORE-36 requires.

    A macro edit changes generated output, and neither `generator_version` nor
    `mapping_profile_version` would move for it. Optional, because lxml builds standards XML
    structurally and CORE-38 forbids Jinja from generating it — so a BPMN artifact has no bundle
    by construction rather than by omission.
    """
    assert projection().template_bundle_digest is None
    assert projection(template_bundle_digest=DIGEST).template_bundle_digest == DIGEST


@pytest.mark.unit
@pytest.mark.requirement("PROJ-05", "PROJ-18")
def test_a_model_level_artifact_needs_no_view() -> None:
    """ArchiMate Exchange XML is generated per model, so requiring a view would invent one."""
    assert projection(view_id=None).view_id is None


@pytest.mark.unit
@pytest.mark.requirement("PROJ-05", "CORE-43")
def test_only_an_xml_artifact_carries_a_canonical_digest() -> None:
    """Text has no canonical form distinct from its bytes, so `None` is a fact, not a gap."""
    assert projection().canonical_source_digest is None
    assert projection(canonical_source_digest=DIGEST).canonical_source_digest == DIGEST


@pytest.mark.unit
@pytest.mark.requirement("PROJ-06", "PROJ-26")
def test_a_render_records_what_makes_its_bytes_differ_elsewhere() -> None:
    """PROJ-26 says byte-identical SVG across platforms is not a semantic requirement.

    So the record exists to make a difference explicable rather than to suppress it: each field
    here can change the output bytes with nothing about the architecture changing.
    """
    artifact = RenderArtifact(
        render_artifact_id="render-1",
        projection_artifact_id="proj-1",
        renderer="plantuml",
        renderer_version="1.2026.8",
        layout_engine="graphviz",
        layout_engine_version="12.2.1",
        platform="darwin-arm64",
        output_format="svg",
        output_locator="outputs/view-1.svg",
        output_digest=DIGEST,
    )
    assert {"renderer", "layout_engine", "platform", "font_profile"} <= set(
        RenderArtifact.model_fields
    )
    assert artifact.output_digest == DIGEST


@pytest.mark.unit
@pytest.mark.requirement("PROJ-04")
def test_a_layout_profile_is_configuration_and_carries_its_own_version() -> None:
    """Versioned separately from the semantic view, which is what PROJ-04 asks for."""
    profile = LayoutProfile(
        layout_profile_id="layout-1",
        notation=Notation.C4,
        renderer_family="structurizr",
        layout_engine="graphviz",
        direction="lr",
        rank_spacing=100,
        node_spacing=60,
        routing_policy="orthogonal",
        profile_version="1.0.0",
    )
    assert profile.profile_version == "1.0.0"
    assert profile.style_profile is None
    with pytest.raises(ValidationError):
        LayoutProfile.model_validate(dict(profile) | {"rank_spacing": -1})


@pytest.mark.unit
@pytest.mark.requirement("PROJ-01", "CORE-08")
def test_none_of_these_is_reachable_from_the_model() -> None:
    """The line `projections.md` draws, asserted rather than assumed.

    View membership is semantic governed content and lives on `Model`; renderer geometry, fonts
    and generated bytes are presentation provenance and are pinned by the manifest instead. If one
    of these ever became a `Model` field, `CHANGE_CLASSIFICATION` would demand a rule for every
    field of it — and the answer would have to be that a font change is an architectural change.
    """
    from architecture_toolkit.domain.model import Model

    reachable = {
        argument
        for field in Model.model_fields.values()
        for argument in getattr(field.annotation, "__args__", ())
    }
    for record in (LayoutProfile, LayoutArtifact, ProjectionArtifact, RenderArtifact):
        assert record not in reachable

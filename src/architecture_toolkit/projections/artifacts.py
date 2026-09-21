"""Projection provenance: what was generated, from what, by which tool (PROJ-04..PROJ-07).

Five records, all `ManifestRecord`, all pinned by digest from `ArchitectureRelease` and none
reachable from `Model`. That is the line `projections.md` draws and it is the whole design: view
membership is semantic governed content and lives on the model; coordinates, bendpoints, SVG
internals, fonts and renderer geometry are presentation provenance and live here.

**Not in `domain/`, and the reason is a rule.** `ValidationArtifact.validation_type` *is*
`ValidationClaim` — PROJ-07's six dimensions and the `ValidationClaim` enum are the same six, and
inventing a parallel vocabulary would mean two lists to keep in step. But `domain/` may not import
`validation/` at runtime, asserted by `tests/unit/test_layering.py`. `projections/` may import
both, so these live here and `domain/protocols.py` takes the same `TYPE_CHECKING` edge it already
takes for `Diagnostic`.

**Nothing here is generated yet.** W7b produces projections, W7b or later produces layouts and
renders. These are declared now for the reason W4 declared the manifest's artifact fields before
filling them: adding a record shape after releases exist is a DATA-56 migration on every one of
them, and adding it now is a line in a file.
"""

from datetime import datetime

from pydantic import AwareDatetime, Field

from architecture_toolkit.domain.base import ManifestRecord
from architecture_toolkit.domain.identifiers import (
    ArtifactId,
    Digest,
    LayoutDigest,
    LayoutProfileId,
    ProfileVersion,
    ReleaseId,
    SchemaVersion,
    ViewId,
)
from architecture_toolkit.domain.notation import Notation
from architecture_toolkit.validation.taxonomy import Severity, ValidationClaim

__all__ = [
    "LayoutArtifact",
    "LayoutProfile",
    "ProjectionArtifact",
    "RenderArtifact",
    "ValidationArtifact",
]


class LayoutProfile(ManifestRecord):
    """How a view should be laid out. Configuration, not content (PROJ-04).

    Versioned separately from the semantic view it lays out, which is the requirement: changing
    the spacing of a diagram is not an architectural decision, and a model digest that moved when
    somebody widened the gutters would make every such change look like one.

    `ViewDefinition.layout_profile_id` points here and is classified `LAYOUT_ONLY`, so swapping
    profiles produces no narrative record — the one place inside `Model` where that gate is
    demonstrable.
    """

    layout_profile_id: LayoutProfileId
    notation: Notation
    renderer_family: str = Field(min_length=1)
    layout_engine: str = Field(min_length=1)
    direction: str = Field(min_length=1)
    rank_spacing: int = Field(ge=0)
    node_spacing: int = Field(ge=0)
    routing_policy: str = Field(min_length=1)
    style_profile: str | None = None
    font_profile: str | None = None
    profile_version: ProfileVersion


class LayoutArtifact(ManifestRecord):
    """Geometry produced for one view at one exact semantic digest (PROJ-04).

    `view_content_digest` is the point of the record. Geometry that did not say which version of
    a view it lays out would be applied to a view whose membership had since changed, silently
    placing objects that are no longer there and omitting ones that are — which is why the field
    is a `LayoutDigest` rather than a `Digest`: DATA-31 keeps semantic and layout identity in
    separate types so one cannot be assigned where the other belongs. This is that alias's first
    use; it was declared at W1 and reserved for exactly this.
    """

    layout_artifact_id: ArtifactId
    view_id: ViewId
    view_content_digest: Digest
    layout_profile_id: LayoutProfileId
    layout_version: SchemaVersion
    geometry_locator: str = Field(min_length=1)
    """Where the geometry lives, relative to the store root. A locator rather than the geometry
    itself: coordinates are bulk presentation data and do not belong in a manifest."""

    source_engine: str = Field(min_length=1)
    source_engine_version: str = Field(min_length=1)
    content_hash: LayoutDigest


class ProjectionArtifact(ManifestRecord):
    """Generated notation source, and everything needed to explain where it came from (PROJ-05).

    The four provenance fields are what make a generated file explainable rather than merely
    present: `semantic_input_digest` says which model state it was generated from,
    `generator_version` and `mapping_profile_version` say which code and which mapping produced
    it, and `template_bundle_digest` says which templates — a field `projections.md` does not
    name and CORE-36 requires, because a macro edit changes generated output and neither of the
    other two versions would move.
    """

    projection_artifact_id: ArtifactId
    release_id: ReleaseId
    view_id: ViewId | None = None
    """`None` for a model-level artifact. ArchiMate Exchange XML is generated per model, not per
    view — PROJ-18 defers exchange diagram geometry — so requiring a view here would force every
    such generator to invent one."""

    notation: Notation
    notation_version: str = Field(min_length=1)
    generator_version: str = Field(min_length=1)
    mapping_profile_version: ProfileVersion
    template_bundle_digest: Digest | None = None
    """`None` for a generator that uses no template. lxml builds standards XML structurally, and
    CORE-38 forbids Jinja from generating it, so a BPMN artifact has no bundle by construction."""

    semantic_input_digest: Digest
    layout_artifact_id: ArtifactId | None = None
    generated_source_locator: str = Field(min_length=1)
    generated_source_digest: Digest
    canonical_source_digest: Digest | None = None
    """The C14N digest, for XML artifacts only (CORE-43). `None` for text, which has no
    canonical form distinct from its bytes."""

    warnings: tuple[str, ...] = ()


class RenderArtifact(ManifestRecord):
    """Rendered bytes, and the platform facts that explain why they differ elsewhere (PROJ-06).

    PROJ-26 says byte-identical SVG across platforms is not a semantic acceptance requirement, so
    this record exists to make the difference *explicable* rather than to suppress it. Renderer,
    engine, platform and font profile are recorded because each of them can change the bytes
    without anything about the architecture changing.
    """

    render_artifact_id: ArtifactId
    projection_artifact_id: ArtifactId
    renderer: str = Field(min_length=1)
    renderer_version: str = Field(min_length=1)
    layout_engine: str | None = None
    layout_engine_version: str | None = None
    platform: str = Field(min_length=1)
    font_profile: str | None = None
    render_options_digest: Digest | None = None
    output_format: str = Field(min_length=1)
    output_locator: str = Field(min_length=1)
    output_digest: Digest
    warnings: tuple[str, ...] = ()


class ValidationArtifact(ManifestRecord):
    """One validation run over one artifact, in one of the six dimensions (PROJ-07).

    `validation_type` is `ValidationClaim` rather than a new enum. PROJ-07's six dimensions —
    canonical structure, cross-model semantics, notation semantics, schema and syntax, renderer,
    and human real-world correctness — are exactly the six `ValidationClaim` already declares and
    `validation/pipeline.py` already reports over. A second vocabulary would be two lists to keep
    in step and one of them would drift.

    `findings` are digests of a report rather than the diagnostics themselves, for the same reason
    `LayoutArtifact` carries a locator: a manifest pins what was concluded, not the full text of
    every finding.
    """

    validation_artifact_id: ArtifactId
    release_id: ReleaseId
    projection_artifact_id: ArtifactId | None = None
    validation_type: ValidationClaim
    validator: str = Field(min_length=1)
    validator_version: str = Field(min_length=1)
    ruleset_version: str | None = None
    severity_summary: tuple[tuple[Severity, int], ...] = ()
    """Counts per severity, as pairs. A mapping would make the record unhashable, which
    `CompiledRecord`'s own guidance rules out and `ManifestRecord` follows."""

    findings_locator: str | None = None
    findings_digest: Digest | None = None
    passed: bool
    created_at: AwareDatetime
    """Injected by the caller's clock, never `now()` inline — the same discipline
    `ArchitectureRelease.published_at` follows, so a fault-injection test stays deterministic."""

    @property
    def is_clean(self) -> bool:
        return self.passed and not self.total_findings

    @property
    def total_findings(self) -> int:
        return sum(count for _, count in self.severity_summary)

    def created_before(self, moment: datetime) -> bool:
        return self.created_at < moment

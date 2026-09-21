"""The immutable ArchitectureRelease manifest (DATA-20, DATA-21).

**A Delta table version is not an architecture release.** That sentence is the whole reason this
module exists. Delta's transaction boundary is a single table, so writing `elements`,
`relationships` and `interface_details` is three commits, not one atomic architecture update. The
manifest is the coherent multi-table revision layered above them: it names an exact Delta version
per table, and a reader opens exactly those versions rather than assembling a model from twelve
independently resolved latest states.

Different tables are expected to sit at different versions. A revision that renames one element
moves `elements` and leaves the other ten where they were — which is DATA-22's reuse rule visible
in the data rather than asserted in prose.

**Everything here is a `ManifestRecord`**, the W1 base whose docstring reserved it for exactly this
("Declared here in W1 and populated in W4"). Frozen, strict, closed — a published manifest that
could be edited would make every digest it pins a claim about nothing.

**The four W8 fields are declared now and left empty on purpose.** `projection_artifact_digests`,
`render_artifact_digests`, `validation_reports` and `outputs` belong to PROJ-41 and arrive at W8.
Adding them then instead of now would change the manifest schema after releases exist, which is a
DATA-56 migration on every one of them. `reference/plan-waves.json` records this as an
`evidence_extension` rather than leaving it to be rediscovered.
"""

from datetime import datetime, timedelta
from typing import Self

from pydantic import AwareDatetime, Field, field_validator, model_validator

from architecture_toolkit.domain.base import ManifestRecord
from architecture_toolkit.domain.identifiers import (
    ArtifactId,
    ChangeSetId,
    Digest,
    ModelId,
    ProfileVersion,
    ReleaseId,
    ScenarioId,
    SchemaVersion,
    SemanticDigest,
    TableId,
)

__all__ = [
    "ArchitectureRelease",
    "GeneratorProvenance",
    "SourceBundle",
    "TableRef",
]


class TableRef(ManifestRecord):
    """One table pinned at one exact version.

    `uri` is stored **relative to the store root**, never absolute. An absolute path would make a
    manifest meaningless the moment the store is copied, archived or read on another machine, and
    a milestone archive that is supposed to be self-contained would be quietly host-bound.

    `row_count` is not required by DATA-21 and is carried anyway: it is the cheapest possible
    read-back assertion, and a table that reads back with the right digest and the wrong row count
    would otherwise be a silent impossibility nobody checks for.
    """

    table_id: TableId
    uri: str = Field(min_length=1)
    delta_version: int = Field(ge=0)
    semantic_digest: SemanticDigest
    row_count: int = Field(ge=0)

    @field_validator("uri")
    @classmethod
    def uri_is_relative(cls, value: str) -> str:
        if value.startswith("/") or ":" in value.split("/")[0]:
            message = f"table uri {value!r} must be relative to the store root"
            raise ValueError(message)
        return value


class SourceBundle(ManifestRecord):
    """What the model was authored from (DATA-37).

    DATA-37's point is that a mutable URL does not identify a version. Where a source has an
    immutable revision — a git commit — `revision` carries it. Where it does not, `digest` pins the
    bytes that were actually read and `snapshot_path` names the preserved copy, because "we read
    something at this URL once" is not a provenance claim anybody can check later.
    """

    source_id: str = Field(min_length=1)
    digest: Digest
    revision: str | None = None
    snapshot_path: str | None = None
    """Where the preserved copy lives, **relative to the store root**, or `None` if none was
    kept. Relative for the same reason `TableRef.uri` is: a milestone archive that is supposed to
    be self-contained would otherwise be quietly bound to the machine that wrote it."""

    @field_validator("snapshot_path")
    @classmethod
    def snapshot_path_is_relative(cls, value: str | None) -> str | None:
        if value is not None and (value.startswith("/") or ":" in value.split("/")[0]):
            message = f"snapshot_path {value!r} must be relative to the store root"
            raise ValueError(message)
        return value


class GeneratorProvenance(ManifestRecord):
    """Which toolkit produced this release, and under which durable conventions.

    The two version fields are not decoration. `storage_schema_version` says which physical schema
    the pinned tables were written against, and is the anchor a DATA-56 migration moves;
    `hash_algorithm_version` says which preimage produced every `semantic_digest` in the manifest.
    A release that recorded digests without saying how they were computed would be unverifiable
    the first time either changed.
    """

    toolkit_version: str = Field(min_length=1)
    toolkit_commit: str = Field(min_length=1)
    storage_schema_version: SchemaVersion
    hash_algorithm_version: str = Field(min_length=1)


class ArchitectureRelease(ManifestRecord):
    """One coherent, immutable multi-table architecture revision.

    Publication order matters and is visible here: this record is written to the store *before*
    the current pointer moves, so a manifest existing is not the same as a release being current.
    That is what makes the pointer move the commit point and a crash between the two harmless.
    """

    release_id: ReleaseId
    model_id: ModelId
    parent_release_id: ReleaseId | None = None
    change_set_id: ChangeSetId | None = None

    # -- DATA-28: an alternative is not a later revision ----------------------------------------
    scenario_id: ScenarioId | None = None
    """Which design alternative this release belongs to. `None` is the baseline line of work.

    A scenario is a separate line of releases derived from a common baseline, not a continuation
    of it. Its existence implies nothing about having superseded or been selected over the current
    design, which is why the two are distinguished by identity rather than by position: a
    position in a chain *is* a claim about succession.
    """

    baseline_release_id: ReleaseId | None = None
    """The release this alternative was derived from. Required on a scenario, refused off one.

    Explicit rather than inferred from `parent_release_id`, because those are different relations
    and DATA-28 exists to keep them apart: a parent is the revision this one supersedes, and a
    baseline is the design this one is an alternative to.
    """

    schema_version: SchemaVersion
    profile_version: ProfileVersion
    model_digest: SemanticDigest

    published_at: AwareDatetime
    """UTC microsecond instant (DATA-12). Injected by the publication clock, never `now()` inline,
    so a fault-injection test is deterministic (CORE-51)."""

    tables: tuple[TableRef, ...]
    source_bundle: SourceBundle
    generator: GeneratorProvenance

    validation_report_digest: Digest | None = None
    change_report_digest: Digest | None = None

    # -- reserved for W8 (PROJ-41); declared now so filling them is not a migration -------------
    projection_artifact_digests: tuple[tuple[ArtifactId, Digest], ...] = ()
    render_artifact_digests: tuple[tuple[ArtifactId, Digest], ...] = ()
    validation_reports: tuple[tuple[str, Digest], ...] = ()
    outputs: tuple[tuple[str, Digest], ...] = ()

    @field_validator("published_at")
    @classmethod
    def published_at_is_utc(cls, value: datetime) -> datetime:
        """An instant with an offset is still ambiguous to a reader a year later."""
        if value.utcoffset() != timedelta(0):
            message = f"published_at must be UTC, got offset {value.utcoffset()}"
            raise ValueError(message)
        return value

    @field_validator("tables")
    @classmethod
    def each_table_appears_once(cls, value: tuple[TableRef, ...]) -> tuple[TableRef, ...]:
        seen = [ref.table_id for ref in value]
        duplicates = sorted({name for name in seen if seen.count(name) > 1})
        if duplicates:
            message = f"manifest pins these tables more than once: {duplicates}"
            raise ValueError(message)
        return value

    @model_validator(mode="after")
    def an_alternative_declares_its_baseline_and_is_not_a_revision_of_it(self) -> Self:
        """DATA-28, in the three ways a release can get the relation wrong.

        A scenario without a baseline is an orphan nobody can interpret; a baseline reference on a
        release that is not a scenario is a claim with no subject; and a scenario whose *parent* is
        its baseline is precisely the sequential-release semantics the requirement forbids, because
        a parent is the revision this one supersedes.
        """
        if (self.scenario_id is None) is not (self.baseline_release_id is None):
            message = (
                f"release {self.release_id!r} sets one of scenario_id/baseline_release_id and not "
                f"the other; an alternative needs both and a baseline release needs neither"
            )
            raise ValueError(message)
        if self.baseline_release_id is not None and self.parent_release_id == (
            self.baseline_release_id
        ):
            message = (
                f"scenario release {self.release_id!r} names {self.baseline_release_id!r} as both "
                f"its parent and its baseline; an alternative is derived from a baseline, not a "
                f"later revision of it"
            )
            raise ValueError(message)
        return self

    @property
    def is_alternative(self) -> bool:
        """Whether this release is a design alternative rather than a revision."""
        return self.scenario_id is not None

    def table(self, table_id: str) -> TableRef:
        """The pin for one table, or `KeyError`. Readers open exactly what this names."""
        for ref in self.tables:
            if ref.table_id == table_id:
                return ref
        raise KeyError(table_id)

    @property
    def pinned_versions(self) -> tuple[tuple[str, int], ...]:
        """`(table_id, delta_version)` pairs. The retention computation's only input."""
        return tuple((ref.table_id, ref.delta_version) for ref in self.tables)

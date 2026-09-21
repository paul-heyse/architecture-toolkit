"""The immutable ArchitectureRelease manifest (DATA-20, DATA-21).

**A Delta table version is not an architecture release.** That sentence is the whole reason this
module exists. Delta's transaction boundary is a single table, so writing `elements`,
`relationships` and `interface_details` is three commits, not one atomic architecture update. The
manifest is the coherent multi-table revision layered above them: it names an exact Delta version
per table, and a reader opens exactly those versions rather than assembling a model from eleven
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

from pydantic import AwareDatetime, Field, field_validator

from architecture_toolkit.domain.base import ManifestRecord
from architecture_toolkit.domain.identifiers import (
    ArtifactId,
    ChangeSetId,
    Digest,
    ModelId,
    ProfileVersion,
    ReleaseId,
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

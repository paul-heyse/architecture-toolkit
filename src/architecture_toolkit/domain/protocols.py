"""Replaceable subsystem boundaries (CORE-58).

`docs/contracts/core.md` names eight boundaries. They are declared here together so the set is
reviewable in one place and a later wave cannot quietly invent a ninth informal seam.

Only the boundaries whose data types already exist are fully typed. The rest are declared with
their intended shape and completed by the wave that builds them, because a Protocol must exchange
typed DTOs rather than dictionaries, and those DTOs do not exist yet:

    SourceLoader        W2   authoring sources            typed at W2
    ValidatorAdapter    W1   diagnostics                  typed here
    SnapshotProvider    W3   Arrow tables at a version
    QueryExecutor       W5   release-scoped query results
    Publisher           W4   release manifests
    ProjectionGenerator W7a  projection artifacts
    Renderer            W7b  render artifacts
    ArtifactStore       W8   only if several stores exist

`tests/unit/test_protocols.py` asserts this module stays exhaustive against the contract list.
Concrete implementations do not inherit from these; structural typing is sufficient, and Pyrefly
checks conformance statically.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    # The only edge from `domain` to `validation`, and it exists only for the type checker.
    # `ValidatorAdapter` describes what a validator does, so it belongs here with the other
    # boundaries, but describing it honestly needs the diagnostic types. Protocols are
    # structural, so nothing is imported at runtime and the layering stays one-way — asserted
    # by `tests/unit/test_layering.py`.
    from architecture_toolkit.domain.authoring.loader import LoadedSource
    from architecture_toolkit.domain.model import Model
    from architecture_toolkit.projections.artifacts import ProjectionArtifact
    from architecture_toolkit.releases.candidate import ReleaseCandidate
    from architecture_toolkit.releases.manifest import ArchitectureRelease
    from architecture_toolkit.validation.context import ValidationContext
    from architecture_toolkit.validation.diagnostics import Diagnostic

from architecture_toolkit.domain.capsules import ArrowSchemaExportable, ArrowStreamExportable
from architecture_toolkit.domain.identifiers import ReleaseId, TableId, ViewId
from architecture_toolkit.domain.providers import SnapshotProviderDescription

__all__ = [
    "ArtifactStore",
    "ProjectionGenerator",
    "Publisher",
    "QueryExecutor",
    "Renderer",
    "SnapshotProvider",
    "SourceLoader",
    "ValidatorAdapter",
]


@runtime_checkable
class SourceLoader(Protocol):
    """Reads authoring source into plain data plus a source map (W2, CORE-14..CORE-19).

    Filled in at W2: `LoadedSource` carries the plain data and the `SourceMap` and contains no
    ruamel object, which is CORE-17 stated as a return type.
    """

    def load(self, source_id: str) -> LoadedSource: ...


@runtime_checkable
class ValidatorAdapter(Protocol):
    """Returns diagnostics for a candidate without mutating it (W1, CORE-07).

    Typed here in W1, as this module's header scheduled. The context parameter is not optional:
    CORE-06 requires validation to be explicit about the schema and profile versions it judged
    against, and a default would let a caller skip saying.
    """

    def validate(
        self, candidate: Model, *, context: ValidationContext
    ) -> tuple[Diagnostic, ...]: ...


@runtime_checkable
class SnapshotProvider(Protocol):
    """Opens one table at the exact version a manifest names (W3, DATA-34, DATA-51).

    Never resolves an implicit latest version; `rules/no-implicit-latest-delta-version.yml`
    enforces that structurally at every call site, and `version` is keyword-only with no default
    so a caller cannot omit it by accident.

    Typed at W3 against `domain/capsules.py` rather than pyarrow: a provider may hand back a
    pyarrow object, an arro3 object or anything else that exports the Arrow C data interface, and
    `domain/` may not import pyarrow at all. `storage/interchange.py` is where a capsule becomes
    a concrete pyarrow value.

    The remaining §11B obligations are behavioural and are expressed as tests rather than as
    signatures: an empty table keeps its schema, nested nullability survives, rows do not depend
    on batch boundaries, and `describe().native_ffi_enabled` is `False` under the current lock.
    """

    def describe(self) -> SnapshotProviderDescription: ...

    def schema_for(self, table_id: TableId, *, version: int) -> ArrowSchemaExportable: ...

    def open(self, table_id: TableId, *, version: int) -> ArrowStreamExportable: ...


@runtime_checkable
class QueryExecutor(Protocol):
    """Runs a versioned query recipe against one release (W5, DATA-48).

    Typed against `domain/capsules.py` for the same two reasons `SnapshotProvider` is: `domain/`
    may not import pyarrow, and the executor's caller should not have to care whether the rows
    arrive as a pyarrow table or anything else exporting the Arrow C data interface. The `object`
    this declared until W5.1 contradicted CORE-58's own "Protocols exchange typed DTOs rather than
    arbitrary dictionaries" — an untyped return is the widest dictionary of all.

    `release_id` is a parameter rather than a constructed context because the caller with a release
    id is the one that has a problem: `cli.py` had resolve-release-then-run written out three
    times. `queries/execution.py::ReleaseQueryExecutor` is the implementation, and it carries the
    provenance — recipe version, release ids, row count — on its own richer result for callers
    holding the concrete type.
    """

    def execute(self, recipe_id: str, *, release_id: str) -> ArrowStreamExportable: ...


@runtime_checkable
class Publisher(Protocol):
    """Publishes a coherent release manifest (W4, DATA-21..DATA-24).

    Typed at W4 against `ReleaseCandidate` and `ArchitectureRelease`, the typed DTOs CORE-58 asks
    a Protocol to exchange. `expected_parent` is required and may be `None`, which says "this is
    the first release" rather than "whatever is current" — a default would let a caller publish
    against a parent they never looked at, which is the stale-parent failure DATA-23 exists to
    prevent.

    Returning the published manifest rather than `None` is what lets a caller pin what it just
    made without re-reading the store and racing itself.
    """

    def publish(
        self, candidate: ReleaseCandidate, *, expected_parent: ReleaseId | None
    ) -> ArchitectureRelease: ...


@runtime_checkable
class ProjectionGenerator(Protocol):
    """Turns one view of one release into generated notation source (W7a, PROJ-05).

    Typed at W7a, which is the wave `reference/plan-waves.json` assigned the signature to. It
    declared `(view_id: str, *, release_id: str) -> object` from W0, and `object` contradicted
    CORE-58's own "Protocols exchange typed DTOs rather than arbitrary dictionaries" for the same
    reason `QueryExecutor`'s did until W5.1: an untyped return is the widest dictionary there is.

    Returning the artifact rather than the source text is the decision worth stating. A generator
    that returned a string would leave every caller to reconstruct the provenance —
    which model digest, which generator version, which mapping profile, which template bundle —
    and PROJ-05 exists precisely so that nobody has to. The generated bytes are named by
    `generated_source_locator`, because a manifest pins what was made, not the thing itself.

    `view_id` may be `None`: ArchiMate Exchange XML is generated per *model*, not per view, and
    requiring one would force that generator to invent it.
    """

    def generate(self, view_id: ViewId | None, *, release_id: ReleaseId) -> ProjectionArtifact: ...


@runtime_checkable
class Renderer(Protocol):
    """Invokes a bounded local renderer and records provenance (W7b, PROJ-06)."""

    def render(self, projection_artifact_id: str) -> object: ...


@runtime_checkable
class ArtifactStore(Protocol):
    """Locates stored artifacts (W8). Declared only; a second store must exist to justify it."""

    def locate(self, artifact_id: str) -> object: ...

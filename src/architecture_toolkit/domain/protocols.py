"""Replaceable subsystem boundaries (CORE-58).

`docs/contracts/core.md` names eight boundaries. They are declared here together so the set is
reviewable in one place and a later wave cannot quietly invent a ninth informal seam.

Only the boundaries whose data types already exist are fully typed. The rest are declared with
their intended shape and completed by the wave that builds them, because a Protocol must exchange
typed DTOs rather than dictionaries, and those DTOs do not exist yet:

    SourceLoader        W2   authoring sources            typed here
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
    from architecture_toolkit.domain.model import Model
    from architecture_toolkit.validation.context import ValidationContext
    from architecture_toolkit.validation.diagnostics import Diagnostic

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
    """Reads authoring source into plain data plus a source map (W2, CORE-14..CORE-19)."""

    def load(self, source_id: str) -> tuple[object, object]: ...


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
    """Opens one table at the exact version a manifest names (W3, DATA-51).

    Never resolves an implicit latest version; `rules/no-implicit-latest-delta-version.yml`
    enforces that structurally at every call site.
    """

    def schema_for(self, table: str, *, version: int) -> object: ...


@runtime_checkable
class QueryExecutor(Protocol):
    """Runs a versioned query recipe against one release (W5, DATA-48)."""

    def execute(self, recipe_id: str, *, release_id: str) -> object: ...


@runtime_checkable
class Publisher(Protocol):
    """Publishes a coherent release manifest (W4, DATA-21..DATA-24)."""

    def publish(self, candidate: object, *, expected_parent: str | None) -> object: ...


@runtime_checkable
class ProjectionGenerator(Protocol):
    """Turns a prepared DTO into notation source (W7a, PROJ-05)."""

    def generate(self, view_id: str, *, release_id: str) -> object: ...


@runtime_checkable
class Renderer(Protocol):
    """Invokes a bounded local renderer and records provenance (W7b, PROJ-06)."""

    def render(self, projection_artifact_id: str) -> object: ...


@runtime_checkable
class ArtifactStore(Protocol):
    """Locates stored artifacts (W8). Declared only; a second store must exist to justify it."""

    def locate(self, artifact_id: str) -> object: ...

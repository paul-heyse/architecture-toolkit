"""From a published release to a generated artifact on disk (PROJ-01, PROJ-05).

The pipeline `projections.md` §3 draws:

    ArchitectureRelease -> release-scoped model -> generator -> text + ProjectionArtifact

This module is the half that touches the world: it opens a release, hands the model to a generator
from `projections/generators.py`, and writes what comes back. The generators are pure — model in,
bytes and provenance out — which is what makes them testable without a store and what keeps a
generated artifact a function of the model rather than of the machine.

**Not a ninth lifecycle operation.** DATA-38 names exactly eight — baseline, change, validate,
diff, review, persist, publish, output — and `tests/integration/test_operations.py` is built
around that list being the list. Projecting a release is a different concern: `projections.md`
draws it hanging off a release rather than as a step in the change lifecycle, and a release can be
projected any number of times without the lifecycle advancing. So the CLI's `build` calls here
directly, the way `query` and `impact` call `ReleaseQueryExecutor`.
"""

from pathlib import Path

from architecture_toolkit.domain.identifiers import ViewId
from architecture_toolkit.projections.generators import (
    DEFAULT_GENERATOR,
    BuiltProjection,
    generator_named,
)
from architecture_toolkit.releases.manifest import ArchitectureRelease
from architecture_toolkit.releases.reader import read_model
from architecture_toolkit.releases.store import ReleaseStore

__all__ = ["build_projection", "write_projection"]


def build_projection(
    store: ReleaseStore,
    manifest: ArchitectureRelease,
    *,
    projection: str = DEFAULT_GENERATOR,
    view_id: ViewId | None = None,
    into: Path | None = None,
) -> BuiltProjection:
    """Generate one projection of one release, and write it if asked to.

    `into` is optional because the artifact is useful without the bytes: a caller pinning digests
    into a manifest needs the record, not the file. When it is given, the source lands at
    `into / artifact.generated_source_locator`, so two projections of the same release cannot
    collide and a whole release's output is one directory.
    """
    built = generator_named(projection).generate(
        read_model(store, manifest), release_id=manifest.release_id, view_id=view_id
    )
    if into is not None:
        write_projection(built, into)
    return built


def write_projection(built: BuiltProjection, into: Path) -> Path:
    """Write generated source under a root, and return where it landed."""
    written = into / built.locator
    written.parent.mkdir(parents=True, exist_ok=True)
    written.write_text(built.source, encoding="utf-8")
    return written

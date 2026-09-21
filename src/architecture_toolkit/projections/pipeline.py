"""From a published release to a generated artifact, with its provenance (PROJ-01, PROJ-05).

The pipeline `projections.md` §3 draws, for the one notation-neutral projection W7a ships:

    ArchitectureRelease -> release-scoped model -> typed DTO -> Jinja -> text + ProjectionArtifact

**Not a ninth lifecycle operation.** DATA-38 names exactly eight — baseline, change, validate,
diff, review, persist, publish, output — and `tests/integration/test_operations.py` is built
around that list being the list. Generating a projection is a different concern: `projections.md`
draws it hanging off a release rather than as a step in the change lifecycle, and a release can be
projected any number of times without the lifecycle advancing. So the CLI's `build` calls here
directly, the way `query` and `impact` call `ReleaseQueryExecutor` rather than routing through
`ArchitectureOperations`.

**Why the artifact and not just the text.** A caller that received a string would have to
reconstruct which model digest, which generator version and which template bundle produced it, and
PROJ-05 exists precisely so nobody has to. The bytes are named by `generated_source_locator`,
because a manifest pins what was made rather than the thing itself.
"""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Final

from architecture_toolkit import __version__
from architecture_toolkit.domain.identifiers import Digest, ReleaseId, ViewId
from architecture_toolkit.domain.model import Model
from architecture_toolkit.domain.semantics import model_digest
from architecture_toolkit.projections.artifacts import ProjectionArtifact
from architecture_toolkit.projections.errors import ProjectionError
from architecture_toolkit.projections.summary import summary_of
from architecture_toolkit.projections.text import bundle_for, environment, render
from architecture_toolkit.releases.manifest import ArchitectureRelease
from architecture_toolkit.releases.reader import read_model
from architecture_toolkit.releases.store import ReleaseStore

__all__ = ["SUMMARY_TEMPLATE", "BuiltProjection", "build_summary", "projection_digest"]

SUMMARY_TEMPLATE: Final[str] = "model-summary.md.j2"
"""The one projection W7a generates. Notation-neutral Markdown, so CORE-38 is untouched.

W7b adds the generators that produce ArchiMate, C4, BPMN, UML and ERD; this exists so the
environment, the contract check and the bundle digest are proven on a real artifact rather than on
a fixture, and so `build` has something to build.
"""

SOURCE_PREIMAGE: Final[str] = "architecture-toolkit/projection-source/v1\n"
"""Prefixed like every other digest here, so two digest kinds cannot collide."""

MAPPING_PROFILE_VERSION: Final[str] = "1.0.0"
"""The Markdown summary applies no notation mapping — there is no notation to map to. Recorded
anyway because `ProjectionArtifact` requires it, and a generated file that could not say which
mapping produced it would be the unexplainable artifact PROJ-01 exists to prevent."""


def projection_digest(source: str) -> Digest:
    """The digest of generated text. Bytes as written, UTF-8, no canonicalization.

    Markdown has no canonical form distinct from its bytes — unlike XML, where CORE-43 keeps a
    second digest — so `ProjectionArtifact.canonical_source_digest` stays `None` for this.
    """
    return f"sha256:{sha256(SOURCE_PREIMAGE.encode() + source.encode('utf-8')).hexdigest()}"


@dataclass(frozen=True, slots=True)
class BuiltProjection:
    """The generated text and the record that explains it."""

    artifact: ProjectionArtifact
    source: str

    @property
    def locator(self) -> str:
        return self.artifact.generated_source_locator


def build_summary(
    store: ReleaseStore,
    manifest: ArchitectureRelease,
    *,
    into: Path | None = None,
    view_id: ViewId | None = None,
) -> BuiltProjection:
    """Generate the model summary for one release, and record where it came from.

    `view_id` is accepted and unused by this generator, which is model-level. It is in the
    signature because `ProjectionGenerator` declares it and W7b's per-view generators need it;
    passing one here is refused rather than silently ignored, because a caller that named a view
    and got a whole-model artifact would have no way to notice.
    """
    if view_id is not None:
        message = (
            f"the model summary is a model-level projection and takes no view; {view_id!r} was "
            f"given. W7b adds the per-view generators."
        )
        raise ProjectionError(message)

    model = read_model(store, manifest)
    return _built(model, manifest.release_id, into)


def _built(model: Model, release_id: ReleaseId, into: Path | None) -> BuiltProjection:
    env = environment()
    bundle = bundle_for(env, SUMMARY_TEMPLATE)
    source = render(env, SUMMARY_TEMPLATE, summary_of(model))

    locator = f"projections/{release_id}/model-summary.md"
    if into is not None:
        written = into / locator
        written.parent.mkdir(parents=True, exist_ok=True)
        written.write_text(source, encoding="utf-8")

    return BuiltProjection(
        artifact=ProjectionArtifact(
            projection_artifact_id=f"proj-{release_id}-model-summary",
            release_id=release_id,
            view_id=None,
            # Markdown is a format, not a modelling language. See the field's docstring.
            notation=None,
            notation_version="commonmark",
            generator_version=__version__,
            mapping_profile_version=MAPPING_PROFILE_VERSION,
            template_bundle_digest=bundle.digest,
            semantic_input_digest=model_digest(model),
            generated_source_locator=locator,
            generated_source_digest=projection_digest(source),
        ),
        source=source,
    )

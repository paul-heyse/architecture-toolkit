"""The generators, and the registry a caller selects one from (CORE-58, PROJ-05).

The shape is `storage/snapshot.py`'s: a `Protocol` for the boundary, a frozen registry keyed by
the name a caller selects with, and a lookup that refuses an unknown name while listing the real
ones. W7b adds ArchiMate, Structurizr, BPMN, UML and ERD by appending to `GENERATORS`; nothing
else has to change, which is the point of landing this before there are five of them.

**A generator takes a model, not a store.** Reading a release is the pipeline's job, and a
generator that could reach a store could also reach anything in it — which is the same reasoning
that keeps the Jinja layer away from `queries` and `storage`. It makes every generator testable
from a `Model` alone, without publishing a release first.

**A generator returns bytes *and* provenance, and writes nothing.** `BuiltProjection` carries the
`ProjectionArtifact` and the source it describes. The caller decides where the bytes go — a
generator that wrote files itself would be a generator whose output depends on the filesystem,
which is exactly the determinism W7a spent a wave establishing.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType
from typing import Final

from architecture_toolkit import __version__
from architecture_toolkit.domain.identifiers import Digest, ReleaseId, ViewId
from architecture_toolkit.domain.model import Model
from architecture_toolkit.domain.protocols import ProjectionGenerator
from architecture_toolkit.domain.semantics import model_digest
from architecture_toolkit.projections.artifacts import ProjectionArtifact
from architecture_toolkit.projections.errors import ProjectionError
from architecture_toolkit.projections.summary import summary_of
from architecture_toolkit.projections.text import environment, prepare, render

__all__ = [
    "DEFAULT_GENERATOR",
    "GENERATORS",
    "SOURCE_PREIMAGE",
    "BuiltProjection",
    "ModelSummaryGenerator",
    "generator_named",
    "projection_digest",
]

SOURCE_PREIMAGE: Final[str] = "architecture-toolkit/projection-source/v1\n"
"""Prefixed like every other digest here, so two digest kinds cannot collide."""


def projection_digest(source: str) -> Digest:
    """The digest of generated text. Bytes as written, UTF-8, no canonicalization.

    Markdown has no canonical form distinct from its bytes — unlike XML, where CORE-43 keeps a
    second digest — so `ProjectionArtifact.canonical_source_digest` stays `None` for text.
    """
    return f"sha256:{sha256(SOURCE_PREIMAGE.encode() + source.encode('utf-8')).hexdigest()}"


@dataclass(frozen=True, slots=True)
class BuiltProjection:
    """Generated source and the record that explains where it came from."""

    artifact: ProjectionArtifact
    source: str

    @property
    def locator(self) -> str:
        """Where the caller should write `source`, relative to whatever root it chose."""
        return self.artifact.generated_source_locator


@dataclass(frozen=True, slots=True)
class ModelSummaryGenerator:
    """A notation-neutral Markdown summary of a whole release.

    The only generator W7a ships, and deliberately not a notation: `projections.md` §22 names
    generated Markdown as a Jinja output alongside Structurizr DSL and PlantUML, and Markdown maps
    to no modelling language. It exists so the environment, the contract check and the bundle
    digest are proven on a real artifact, and so `build` has something to build.
    """

    template: str = "model-summary.md.j2"
    mapping_profile_version: str = "1.0.0"
    """No notation mapping is applied — there is no notation to map to. Recorded anyway because
    `ProjectionArtifact` requires it, and a generated file that could not say which mapping
    produced it would be the unexplainable artifact PROJ-01 exists to prevent."""

    def generate(
        self, model: Model, *, release_id: ReleaseId, view_id: ViewId | None = None
    ) -> BuiltProjection:
        """Render the whole model. Refuses a view, because it does not project one.

        Refused rather than ignored: a caller that named a view and received a whole-model
        artifact would have no way to notice. W7b's per-view generators are what make the
        parameter live.
        """
        if view_id is not None:
            message = (
                f"{self.template} is a model-level projection and takes no view; {view_id!r} was "
                f"given. W7b adds the per-view generators."
            )
            raise ProjectionError(message)

        env = environment()
        summary = summary_of(model)
        bundle = prepare(env, self.template, type(summary))
        source = render(env, self.template, summary)

        return BuiltProjection(
            artifact=ProjectionArtifact(
                projection_artifact_id=f"proj-{release_id}-model-summary",
                release_id=release_id,
                view_id=None,
                notation=None,
                notation_version="commonmark",
                generator_version=__version__,
                mapping_profile_version=self.mapping_profile_version,
                template_bundle_digest=bundle.digest,
                semantic_input_digest=model_digest(model),
                generated_source_locator=f"projections/{release_id}/model-summary.md",
                generated_source_digest=projection_digest(source),
            ),
            source=source,
        )


GENERATORS: Final[Mapping[str, ProjectionGenerator]] = MappingProxyType(
    {"model-summary": ModelSummaryGenerator()}
)
"""Every generator, by the name a caller selects it with.

One today. W7b's five append here, and `architecture build --notation` reads this mapping, so
neither the CLI nor the pipeline changes when they arrive.
"""

DEFAULT_GENERATOR: Final[str] = "model-summary"
"""What `build` produces when asked for nothing in particular. The only one that exists."""


def generator_named(name: str) -> ProjectionGenerator:
    """One generator by name, or a refusal that lists the real ones."""
    try:
        return GENERATORS[name]
    except KeyError:
        message = f"unknown projection {name!r}; choose one of {sorted(GENERATORS)}"
        raise ProjectionError(message) from None


def _check_registry() -> None:
    """Run at import, like every other registry here.

    A default that is not in the mapping would make `build` fail on its own default, and the
    first caller to find out would be a user rather than a test.
    """
    if DEFAULT_GENERATOR not in GENERATORS:
        message = f"default projection {DEFAULT_GENERATOR!r} is not registered"
        raise ValueError(message)


_check_registry()

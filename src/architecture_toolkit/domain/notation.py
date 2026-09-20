"""Notation bindings — the sixth detail family (DATA-07, DATA-30, DATA-31).

DATA-07 lists six detail kinds and this is the one the W1 plan document dropped: "interface,
deployment, data-schema, behavior, requirement **and notation** details".

It is not an `ElementDetail` variant, for three reasons that each rule it out on their own. Its
subject is any canonical object — a relationship binds to a notation object as readily as an
element does. It has its own identity, because a projection artifact refers to the binding. And
there may be many per subject, one per notation.

**It is also where DATA-31's separation becomes concrete.** A binding names the notation object
and the mapping profile version, and nothing else about presentation. Coordinates, bendpoints,
fonts and renderer geometry are layout, excluded from semantic identity, and belong to W7a's
`LayoutArtifact`. Moving a diagram box must not read as an architectural redesign.

`Diagnostic.notation_object_id` joins to `notation_object_id` here, which is why the field exists
in W1 even though no generator does.
"""

from enum import StrEnum

from architecture_toolkit.domain.base import CompiledRecord
from architecture_toolkit.domain.identifiers import (
    ArtifactId,
    BindingId,
    Digest,
    ModelId,
    NotationObjectId,
    ProfileVersion,
    ViewId,
)
from architecture_toolkit.domain.references import ReferenceTarget

__all__ = ["Notation", "NotationBinding"]


class Notation(StrEnum):
    """The notations `projections.md` schedules. Declared now; generators arrive at W7b."""

    ARCHIMATE = "archimate"
    C4 = "c4"
    BPMN = "bpmn"
    UML = "uml"
    ERD = "erd"


class NotationBinding(CompiledRecord):
    binding_id: BindingId
    model_id: ModelId
    subject: ReferenceTarget
    notation: Notation
    # The notation's own type name — `bpmn:ExclusiveGateway`, `ArchiMate:ApplicationComponent`.
    # A free string because the notation owns that vocabulary and pinning it here would make a
    # profile upgrade in W7b a change to the domain.
    notation_type: str
    notation_object_id: NotationObjectId
    view_id: ViewId | None = None
    # Which mapping produced this binding. Without it a re-mapped model is indistinguishable
    # from a re-authored one, and DATA-31 requires those stay separable.
    mapping_profile_version: ProfileVersion
    projection_artifact_id: ArtifactId | None = None
    link_target: str | None = None
    content_hash: Digest | None = None

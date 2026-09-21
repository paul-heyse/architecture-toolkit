"""Canonical view definitions — what a diagram is *of*, separately from what it looks like.

PROJ-03. A `ViewDefinition` answers why a view exists, who it is for, which semantic objects it
contains and which perspective it applies. `projections.md` calls view membership "semantic
governed content", so this is canonical: it lives on `Model`, participates in the semantic digest,
and a membership change appears in `architecture diff`. Geometry does not — that is
`LayoutArtifact`, pinned by digest from the manifest, and the separation is the whole point.
Moving a box must not read as an architectural decision.

**`view_type` is a closed vocabulary, and `notation_type` is not.** The tempting precedent is
`NotationBinding.notation_type`, a free string because "the notation owns that vocabulary". That
reasoning does not transfer. `notation_type` is the *foreign* notation's type name, open by
nature; `view_type` is this toolkit's own classification and `projections.md` enumerates it. The
decisive point is that a closed enum makes "code-level C4 diagrams are excluded" *inexpressible*
rather than merely forbidden — the same argument `BehaviorNodeType` makes for the BPMN subset.

**`filter` is a tuple, not an optional record.** Storage decides this: the baseline persists no
nullable struct, so an optional nested record has no honest column. A tuple is a `list_of(struct)`
like `extensions`, needs no `OPTIONAL_RECORD_RULES` entry and so no new presence kinds, and
"empty means unfiltered" reads correctly.

**Record-local validators only.** `ARCH-TOOL-CORE-001` §3F puts foreign-key resolution outside a
Pydantic validator, so whether a member id resolves is `validation/rules/views.py`'s question.
What one record can answer about itself — that its type suits its notation, that it does not name
the same object twice, that its membership policy agrees with its filter — is answered here.
"""

from enum import StrEnum
from typing import Final, Self

from pydantic import Field, model_validator

from architecture_toolkit.domain.base import CompiledRecord
from architecture_toolkit.domain.identifiers import (
    Digest,
    ElementId,
    LayoutProfileId,
    ModelId,
    RelationshipId,
    ViewId,
)
from architecture_toolkit.domain.notation import Notation

__all__ = [
    "VIEW_TYPES_BY_NOTATION",
    "FilterDimension",
    "FilterMode",
    "MembershipPolicy",
    "PublicationState",
    "ViewDefinition",
    "ViewFilter",
    "ViewType",
]


class ViewType(StrEnum):
    """The view kinds `projections.md` schedules, and no others.

    C4's code-level diagram is absent deliberately: PROJ-08 excludes it as a maintained output,
    and a vocabulary that cannot name it cannot grow one by accident.
    """

    SYSTEM_LANDSCAPE = "system_landscape"
    SYSTEM_CONTEXT = "system_context"
    CONTAINER = "container"
    COMPONENT = "component"
    DEPLOYMENT = "deployment"
    DYNAMIC = "dynamic"
    ARCHIMATE_LAYERED = "archimate_layered"
    ARCHIMATE_VIEWPOINT = "archimate_viewpoint"
    BPMN_PROCESS = "bpmn_process"
    BPMN_COLLABORATION = "bpmn_collaboration"
    UML_SEQUENCE = "uml_sequence"
    UML_STATE = "uml_state"
    UML_CLASS = "uml_class"
    ERD = "erd"


class MembershipPolicy(StrEnum):
    """How the member lists were arrived at, which decides what a rule may check.

    Three members rather than two, because each buys a different check. `EXPLICIT` means both
    lists were authored and a rule only resolves them. `INDUCED` means the relationships are
    exactly those whose endpoints are both members, so a rule can verify completeness — the C4
    norm, and note that `!impliedRelationships false` forbids *inventing* a relationship, not
    including one that exists. `DERIVED` means both lists are the materialized answer to `filter`.
    Without the distinction an `INDUCED` view and a stale `EXPLICIT` one look identical.
    """

    EXPLICIT = "explicit"
    INDUCED = "induced"
    DERIVED = "derived"


class PublicationState(StrEnum):
    """Whether a release publishes this view. Not the same question as lifecycle."""

    DRAFT = "draft"
    PUBLISHED = "published"
    WITHDRAWN = "withdrawn"


class FilterMode(StrEnum):
    INCLUDE = "include"
    EXCLUDE = "exclude"


class FilterDimension(StrEnum):
    """What a filter may select on: exactly the dimensions the canonical model can answer.

    Closed so a filter cannot name something unanswerable. A filter on a dimension the model does
    not carry would be a view whose membership nobody can recompute, which is the opposite of
    "membership is semantic governed content".
    """

    KIND = "kind"
    RELATIONSHIP_TYPE = "relationship_type"
    LIFECYCLE_STATE = "lifecycle_state"
    CONTEXT = "context"


class ViewFilter(CompiledRecord):
    """One selection rule. Several compose by intersection, in declaration order."""

    filter_mode: FilterMode
    dimension: FilterDimension
    values: tuple[str, ...] = Field(min_length=1)


VIEW_TYPES_BY_NOTATION: Final[dict[Notation, frozenset[ViewType]]] = {
    Notation.C4: frozenset(
        {
            ViewType.SYSTEM_LANDSCAPE,
            ViewType.SYSTEM_CONTEXT,
            ViewType.CONTAINER,
            ViewType.COMPONENT,
            ViewType.DEPLOYMENT,
            ViewType.DYNAMIC,
        }
    ),
    Notation.ARCHIMATE: frozenset({ViewType.ARCHIMATE_LAYERED, ViewType.ARCHIMATE_VIEWPOINT}),
    Notation.BPMN: frozenset({ViewType.BPMN_PROCESS, ViewType.BPMN_COLLABORATION}),
    Notation.UML: frozenset({ViewType.UML_SEQUENCE, ViewType.UML_STATE, ViewType.UML_CLASS}),
    Notation.ERD: frozenset({ViewType.ERD}),
}
"""Which view types each notation can express. Total over `Notation` and over `ViewType`, by test.

A `c4` view of type `bpmn_process` is not a view somebody has to notice in review; it is a record
that cannot be constructed.
"""


class ViewDefinition(CompiledRecord):
    """One view: its purpose, its audience, its semantic membership and its layout profile."""

    view_id: ViewId
    model_id: ModelId
    view_type: ViewType
    notation: Notation

    scope: ElementId | None = None
    """The element this view is *of* — a container view is scoped to a system.

    An `ElementId` rather than a free string, because that is what it is: typing it loosely would
    discard the one fact that makes a container view generatable and the one thing a rule can
    check. `None` for a landscape view, which has no scope; DATA-41 makes that a fact rather than
    a gap.
    """

    audience: str | None = None
    title: str = Field(min_length=1)
    description: str | None = None

    membership_policy: MembershipPolicy = MembershipPolicy.EXPLICIT
    included_element_ids: tuple[ElementId, ...] = ()
    included_relationship_ids: tuple[RelationshipId, ...] = ()

    perspective: str | None = None
    """A named static overlay — ownership, risk, qualification state. Open on purpose: the
    perspectives a project uses come from its own metadata, and an enum here would be the toolkit
    inventing a vocabulary it has no source for."""

    filter: tuple[ViewFilter, ...] = ()
    layout_profile_id: LayoutProfileId | None = None
    """`None` is the baseline: `projections.md` makes automatic layout the default, so no pinned
    profile is a choice rather than an omission."""

    publication_state: PublicationState = PublicationState.DRAFT
    content_hash: Digest | None = None

    @model_validator(mode="after")
    def view_type_belongs_to_the_notation(self) -> Self:
        """A notation can only express the view types it has shapes for."""
        allowed = VIEW_TYPES_BY_NOTATION[self.notation]
        if self.view_type not in allowed:
            message = (
                f"view {self.view_id!r} is {self.notation.value} and {self.view_type.value}, "
                f"but {self.notation.value} expresses {sorted(t.value for t in allowed)}"
            )
            raise ValueError(message)
        return self

    @model_validator(mode="after")
    def members_are_named_once(self) -> Self:
        """A view listing an object twice is an authoring slip, not a view with a heavier edge."""
        for label, members in (
            ("element", self.included_element_ids),
            ("relationship", self.included_relationship_ids),
        ):
            repeated = sorted({item for item in members if members.count(item) > 1})
            if repeated:
                message = f"view {self.view_id!r} names {label}(s) {repeated} more than once"
                raise ValueError(message)
        return self

    @model_validator(mode="after")
    def membership_policy_agrees_with_the_filter(self) -> Self:
        """A derived view is derived *from* something, and an explicit one is not derived at all."""
        if self.membership_policy is MembershipPolicy.DERIVED and not self.filter:
            message = (
                f"view {self.view_id!r} says its membership is derived and declares no filter to "
                f"derive it from"
            )
            raise ValueError(message)
        if self.membership_policy is MembershipPolicy.EXPLICIT and self.filter:
            message = (
                f"view {self.view_id!r} says its membership is explicit and declares a filter; "
                f"use 'derived' if the filter decides membership, or drop the filter"
            )
            raise ValueError(message)
        return self

    @property
    def is_published(self) -> bool:
        return self.publication_state is PublicationState.PUBLISHED

    @property
    def member_count(self) -> int:
        return len(self.included_element_ids) + len(self.included_relationship_ids)

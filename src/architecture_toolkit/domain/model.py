"""The canonical typed architecture model (CORE-01, DATA-03, DATA-04, DATA-08).

DATA-03 asks for a typed relational core rather than a JSON node/edge bag, and the difference
shows up in what the records can refuse. The seven-field placeholder this replaces could say an
element was a `software.system`; it could not say whether a relationship between two elements was
a legal statement, which direction it was authored in, or what its inverse was called.

Column sets follow `ARCH-TOOL-DATA-001` §2A and §2B exactly — seven on elements and eight on
relationships, including the `model_id`, `description` and `content_hash` the wave plan omitted.
`model_id` is not bookkeeping: the toolkit's own architecture, a proposed client solution and a
portfolio company's operating model must not become one undifferentiated collection of nodes.

Owned value objects are nested, per data.md. `status` and `detail` are not columns in §2A because
that list is the *storage* projection; W3 flattens them into their own tables. Objects with
independent identity — references, interactions, notation bindings — are normalized instead.

`content_hash` is declared and always `None` here. W2 computes it (DATA-27), and the hash
primitive belongs in `domain/` because it is the canonical normal form of a validated record.
Reserving the field now means W3 and W4 are not replumbed to add it.
"""

from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from architecture_toolkit.domain.base import CompiledRecord
from architecture_toolkit.domain.details import ElementDetail
from architecture_toolkit.domain.extensions import (
    MAX_EXTENSIONS_PER_RECORD,
    Extension,
    duplicate_extension_key,
)
from architecture_toolkit.domain.identifiers import (
    ContextId,
    Digest,
    ElementId,
    InteractionId,
    ModelId,
    ProfileVersion,
    QualifiedKind,
    RelationshipId,
    RelationshipTypeId,
    SchemaVersion,
)
from architecture_toolkit.domain.notation import NotationBinding
from architecture_toolkit.domain.references import Reference, ReferenceLink
from architecture_toolkit.domain.registry import BASELINE_PROFILE_VERSION
from architecture_toolkit.domain.status import LifecycleState, StatusDimensions

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "Element",
    "Interaction",
    "InteractionKind",
    "InteractionParticipant",
    "Model",
    "ParticipantRole",
    "Relationship",
]

CURRENT_SCHEMA_VERSION = "1.0.0"


class ParticipantRole(StrEnum):
    """Why an element is in an interaction. DATA-08's worked example names these."""

    PRODUCER = "producer"
    CONSUMER = "consumer"
    SENDER = "sender"
    RECEIVER = "receiver"
    INTERFACE = "interface"
    EXCEPTION_HANDLER = "exception_handler"
    OBSERVER = "observer"


class InteractionKind(StrEnum):
    HANDOFF = "handoff"
    EXCHANGE = "exchange"
    COLLABORATION = "collaboration"


class Element(CompiledRecord):
    element_id: ElementId
    model_id: ModelId
    kind_id: QualifiedKind
    name: str = Field(min_length=1)
    description: str | None = None
    lifecycle_state: LifecycleState = LifecycleState.ACTIVE
    # DATA-04: stable identity is independent of display name, and readable aliases coexist with
    # it. Excluded from semantic identity — W2's hash ignores them, because renaming the label a
    # diagram shows is not an architectural change.
    aliases: tuple[str, ...] = ()
    status: StatusDimensions = StatusDimensions()
    detail: ElementDetail | None = None
    # DATA-13: a bounded namespaced annotation nobody queries. See `domain/extensions.py` for
    # why reading one anywhere in `queries/`, `projections/` or `validation/rules/` is the
    # signal that it should have been a typed field instead.
    extensions: tuple[Extension, ...] = Field(default=(), max_length=MAX_EXTENSIONS_PER_RECORD)
    content_hash: Digest | None = None

    @model_validator(mode="after")
    def extension_keys_are_unique(self) -> Self:
        duplicate = duplicate_extension_key(self.extensions)
        if duplicate is not None:
            namespace, key = duplicate
            message = f"element {self.element_id!r} repeats extension {namespace}.{key}"
            raise ValueError(message)
        return self

    @model_validator(mode="after")
    def detail_describes_this_element(self) -> Self:
        """Record-local discriminator consistency, explicitly allowed by §3F.

        Whether `kind_id` *permits* this detail family is a registry question and therefore
        cross-record; `validation/` owns it.
        """
        if self.detail is not None and self.detail.element_id != self.element_id:
            message = (
                f"detail on {self.element_id!r} declares element_id {self.detail.element_id!r}"
            )
            raise ValueError(message)
        return self


class Relationship(CompiledRecord):
    """Independently identified, because evidence and decisions attach to the relationship itself.

    Only one direction is stored. `registry.py` holds the canonical direction and the inverse
    label, and inverse views are derived — DATA-06 forbids persisting the duplicate.
    """

    relationship_id: RelationshipId
    model_id: ModelId
    relationship_type_id: RelationshipTypeId
    source_element_id: ElementId
    target_element_id: ElementId
    context_id: ContextId | None = None
    description: str | None = None
    extensions: tuple[Extension, ...] = Field(default=(), max_length=MAX_EXTENSIONS_PER_RECORD)
    content_hash: Digest | None = None

    @model_validator(mode="after")
    def extension_keys_are_unique(self) -> Self:
        duplicate = duplicate_extension_key(self.extensions)
        if duplicate is not None:
            namespace, key = duplicate
            message = f"relationship {self.relationship_id!r} repeats extension {namespace}.{key}"
            raise ValueError(message)
        return self


class InteractionParticipant(CompiledRecord):
    element_id: ElementId
    participant_role: ParticipantRole
    ordinal: int = Field(default=0, ge=0)


class Interaction(CompiledRecord):
    """A first-class multi-party handoff (DATA-08).

    A binary edge cannot carry a producing activity, a consuming activity, a sender role, a
    receiver role, an interface and the object being moved. Modelling it as one answers both
    questions §2D poses: which applications participate in this handoff, and which handoffs move
    this information object between roles.
    """

    interaction_id: InteractionId
    model_id: ModelId
    name: str = Field(min_length=1)
    interaction_kind: InteractionKind
    description: str | None = None
    participants: tuple[InteractionParticipant, ...] = ()
    moved_object_ids: tuple[ElementId, ...] = ()
    content_hash: Digest | None = None


class Model(CompiledRecord):
    """One canonical model. Frozen, hashable, and addressed by `model_id`.

    No cross-record validator lives here. Identity uniqueness and endpoint resolution used to be
    a `model_validator` on this class; `ARCH-TOOL-CORE-001` §3F puts foreign-key resolution
    outside record-local validators, and they now live in `validation/rules/structural.py` as
    rules that return diagnostics.

    That is a behaviour change worth stating plainly: an unresolved endpoint no longer raises
    `ValidationError` on construction. It is reported as `CORE.RELATION.UNRESOLVED_ENDPOINT`,
    with the relationship and the offending side named — which the exception never managed.
    """

    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    profile_version: ProfileVersion = BASELINE_PROFILE_VERSION
    model_id: ModelId
    elements: tuple[Element, ...] = ()
    relationships: tuple[Relationship, ...] = ()
    interactions: tuple[Interaction, ...] = ()
    references: tuple[Reference, ...] = ()
    reference_links: tuple[ReferenceLink, ...] = ()
    notation_bindings: tuple[NotationBinding, ...] = ()

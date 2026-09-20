"""Typed detail records (CORE-04, DATA-07, DATA-30).

data.md warns against a table per concept, so the gating rule is the one
`ARCH-TOOL-DATA-001` §2C states: create a detail family when its information has meaningful
type-specific fields or constraints. Processes and capabilities share the common element
representation; an HTTP interface does not.

**Why these are modelled explicitly rather than inferred.** DATA-30 is the requirement, and W7b
is the reason. A BPMN generator cannot produce an exclusive gateway from a `supports` edge, and
an ERD generator cannot produce a foreign key from one either. `ARCH-TOOL-DATA-001` §7 puts the
same point about schemas: "do not assume a generic JSON Schema supplies all relational
semantics." Anything a projection must emit has to be stated here or it will be invented there.

**Five variants, six families.** `DetailFamily` in `registry.py` has six members; the
`ElementDetail` union below has five. Notation bindings are the sixth family and live in
`notation.py` instead, because their subject is any canonical object — a relationship as readily
as an element — they carry their own identity, and there may be many per subject. An
element-attached variant could express none of that.

Ordered sequences are explicit. `ordinal` exists on behaviour nodes and schema fields because
authored order is semantic there and W2's canonical hash must preserve it, while reordering an
unordered collection must not read as a change.
"""

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, TypeAdapter, model_validator

from architecture_toolkit.domain.base import CompiledRecord
from architecture_toolkit.domain.identifiers import (
    Digest,
    ElementId,
    ReferenceId,
)
from architecture_toolkit.domain.registry import DetailFamily

__all__ = [
    "ELEMENT_DETAIL_ADAPTER",
    "Applicability",
    "BehaviorDetail",
    "BehaviorNode",
    "BehaviorNodeType",
    "BehaviorTransition",
    "DataSchemaDetail",
    "DeliverySemantics",
    "DeploymentDetail",
    "ElementDetail",
    "FieldCardinality",
    "InteractionMode",
    "InterfaceDetail",
    "InterfaceTransport",
    "KeyMembership",
    "Nullability",
    "RequirementCategory",
    "RequirementDetail",
    "SchemaField",
    "VerificationMethod",
]


class InteractionMode(StrEnum):
    SYNCHRONOUS = "synchronous"
    ASYNCHRONOUS = "asynchronous"
    BATCH = "batch"
    STREAMING = "streaming"


class DeliverySemantics(StrEnum):
    AT_MOST_ONCE = "at_most_once"
    AT_LEAST_ONCE = "at_least_once"
    EXACTLY_ONCE = "exactly_once"
    UNSPECIFIED = "unspecified"


class Nullability(StrEnum):
    REQUIRED = "required"
    OPTIONAL = "optional"


class FieldCardinality(StrEnum):
    ONE = "one"
    MANY = "many"


class KeyMembership(StrEnum):
    """ERD semantics DATA-30 requires stated, not inferred from a generic edge."""

    PRIMARY_KEY = "primary_key"
    UNIQUE_KEY = "unique_key"
    FOREIGN_KEY = "foreign_key"


class BehaviorNodeType(StrEnum):
    """The BPMN subset `projections.md` names, stated in the domain rather than the generator.

    The three gateways are distinct members for the reason DATA-30 exists: an exclusive gateway
    and a parallel gateway mean different things, and no edge label recovers the difference.
    """

    TASK = "task"
    MANUAL_TASK = "manual_task"
    START_EVENT = "start_event"
    END_EVENT = "end_event"
    INTERMEDIATE_EVENT = "intermediate_event"
    EXCLUSIVE_GATEWAY = "exclusive_gateway"
    PARALLEL_GATEWAY = "parallel_gateway"
    INCLUSIVE_GATEWAY = "inclusive_gateway"
    SUBPROCESS = "subprocess"


class RequirementCategory(StrEnum):
    FUNCTIONAL = "functional"
    QUALITY = "quality"
    CONSTRAINT = "constraint"
    REGULATORY = "regulatory"


class VerificationMethod(StrEnum):
    TEST = "test"
    ANALYSIS = "analysis"
    INSPECTION = "inspection"
    DEMONSTRATION = "demonstration"
    NOT_ESTABLISHED = "not_established"


class Applicability(StrEnum):
    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class InterfaceTransport(CompiledRecord):
    """Nested struct, shaped to the Arrow `interface_schema` pinned in `ARCH-TOOL-DATA-001` §3A.

    Kept nested rather than flattened so W3 maps it to the struct the specification already
    fixes, instead of three loose columns it would then have to reconcile.
    """

    protocol: str
    interaction_mode: InteractionMode
    serialization: str


class InterfaceDetail(CompiledRecord):
    detail_family: Literal[DetailFamily.INTERFACE] = DetailFamily.INTERFACE
    element_id: ElementId
    transport: InterfaceTransport
    authentication_description: str | None = None
    request_schema_id: ElementId | None = None
    response_schema_id: ElementId | None = None
    delivery_semantics: DeliverySemantics = DeliverySemantics.UNSPECIFIED
    timeout_ms: int | None = Field(default=None, ge=0)
    idempotency_description: str | None = None
    content_hash: Digest | None = None


class DeploymentDetail(CompiledRecord):
    detail_family: Literal[DetailFamily.DEPLOYMENT] = DetailFamily.DEPLOYMENT
    element_id: ElementId
    environment: str
    deployment_node_id: ElementId | None = None
    software_instance_id: ElementId | None = None
    configuration_artifact_id: ReferenceId | None = None
    content_hash: Digest | None = None


class SchemaField(CompiledRecord):
    """One field of a concrete schema. `ordinal` is authored order and is semantic."""

    field_id: str
    field_name: str
    data_type: str
    nullability: Nullability = Nullability.OPTIONAL
    cardinality: FieldCardinality = FieldCardinality.ONE
    key_membership: frozenset[KeyMembership] = frozenset()
    references_element_id: ElementId | None = None
    references_field_id: str | None = None
    ordinal: int = Field(ge=0)

    @model_validator(mode="after")
    def foreign_key_names_its_target(self) -> Self:
        """Record-local, so it belongs in Pydantic (`ARCH-TOOL-CORE-001` §3F).

        Whether the named target *exists* is cross-record and belongs to `validation/`.
        """
        declared = KeyMembership.FOREIGN_KEY in self.key_membership
        named = self.references_element_id is not None
        if declared and not named:
            message = f"field {self.field_id!r} is a foreign key but names no referenced element"
            raise ValueError(message)
        return self


class DataSchemaDetail(CompiledRecord):
    detail_family: Literal[DetailFamily.DATA_SCHEMA] = DetailFamily.DATA_SCHEMA
    element_id: ElementId
    fields: tuple[SchemaField, ...] = ()
    content_hash: Digest | None = None


class BehaviorNode(CompiledRecord):
    node_id: str
    node_type: BehaviorNodeType
    name: str
    ordinal: int = Field(ge=0)
    # DATA-41: a manual process needs no application. An absent participant is a fact here, not
    # a dangling reference to be filled in so a coverage matrix looks complete.
    participant_element_id: ElementId | None = None


class BehaviorTransition(CompiledRecord):
    transition_id: str
    source_node_id: str
    target_node_id: str
    guard: str | None = None
    ordinal: int = Field(ge=0)


class BehaviorDetail(CompiledRecord):
    detail_family: Literal[DetailFamily.BEHAVIOR] = DetailFamily.BEHAVIOR
    element_id: ElementId
    nodes: tuple[BehaviorNode, ...] = ()
    transitions: tuple[BehaviorTransition, ...] = ()
    content_hash: Digest | None = None

    @model_validator(mode="after")
    def transitions_stay_within_this_behavior(self) -> Self:
        """Record-local: both endpoints are nodes of this same record."""
        known = {node.node_id for node in self.nodes}
        dangling = sorted(
            endpoint
            for transition in self.transitions
            for endpoint in (transition.source_node_id, transition.target_node_id)
            if endpoint not in known
        )
        if dangling:
            message = f"behaviour transitions name unknown nodes: {dangling}"
            raise ValueError(message)
        return self


class RequirementDetail(CompiledRecord):
    detail_family: Literal[DetailFamily.REQUIREMENT] = DetailFamily.REQUIREMENT
    element_id: ElementId
    category: RequirementCategory
    applicability: Applicability = Applicability.UNKNOWN
    applicability_note: str | None = None
    verification_method: VerificationMethod = VerificationMethod.NOT_ESTABLISHED
    acceptance_criterion_ids: tuple[ReferenceId, ...] = ()
    content_hash: Digest | None = None


ElementDetail = Annotated[
    InterfaceDetail | DeploymentDetail | DataSchemaDetail | BehaviorDetail | RequirementDetail,
    Field(discriminator="detail_family"),
]
"""CORE-04. A stable variant tag exists, so this is field-discriminated, not a bare union."""

ELEMENT_DETAIL_ADAPTER: TypeAdapter[ElementDetail] = TypeAdapter(ElementDetail)
"""CORE-05: a natural type boundary, not a wrapper model created to call validation."""

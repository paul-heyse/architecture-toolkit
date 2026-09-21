"""Which change every field of every record is, declared once and asserted total (DATA-26).

This module is the wave's central guard. The hard gate — *layout/presentation-only changes do not
masquerade as semantic model changes* — holds because a field's nature is **declared**, not
inferred at the point a narrative is rendered. A `NotationBinding`'s `link_target` cannot reach the
change narrative, because the table says what it is and `NARRATIVE_NATURES` says what that means.

Three structural decisions, each of which is the difference between a guard and a decoration:

**Keyed by `(record class, field name)`, never by field path.** It is the shape
`semantics.py::COLLECTION_ORDER` already uses, so one reflection walk asserts both tables total and
the two can be cross-checked against each other. Path-keying cannot be asserted total at all:
paths are open (`detail.fields.<any field_id>.nullability`), so totality would degenerate into
"every path some test happened to exercise", which is an assertion that passes for the wrong reason
by construction.

**No lookup default, anywhere.** `rule_for` subscripts and lets `KeyError` escape. A `.get(key,
FIELD_MODIFIED)` would make the totality test decorative — an unclassified field would get an
answer regardless, and the test that is supposed to force a decision would still pass.
`rules/change-classification-has-no-default.yml` enforces the absence structurally.

**A residual that is guarded rather than avoided.** `Reference.authority` and
`InterfaceDetail.idempotency_description` have no named category in any contract, so
`FIELD_MODIFIED` is unavoidable. What keeps it from swallowing the table is in
`tests/unit/test_change_classification.py`: a pinned ceiling on how many fields may use it **and**
a list of fields that must never reach it. A bare count is gameable by adding rows; count plus
membership is not. It is `CANONICAL_SEMANTIC` so that an unclassified field added by a later wave
is noisy rather than silently absent from the narrative.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from pydantic import BaseModel

from architecture_toolkit.changes.errors import ClassificationError
from architecture_toolkit.changes.kinds import ChangeKind, ChangeNature, ChangeRule
from architecture_toolkit.domain.details import (
    BehaviorDetail,
    BehaviorNode,
    BehaviorTransition,
    DataSchemaDetail,
    DeploymentDetail,
    InterfaceDetail,
    InterfaceTransport,
    RequirementDetail,
    SchemaField,
)
from architecture_toolkit.domain.extensions import Extension
from architecture_toolkit.domain.model import (
    Element,
    Interaction,
    InteractionParticipant,
    Model,
    Relationship,
)
from architecture_toolkit.domain.notation import NotationBinding
from architecture_toolkit.domain.references import (
    ElementReference,
    FieldReference,
    Reference,
    ReferenceLink,
    RelationshipReference,
    ReleaseReference,
)
from architecture_toolkit.domain.status import StatusDimensions

__all__ = [
    "CHANGE_CLASSIFICATION",
    "OPTIONAL_RECORD_RULES",
    "PRESENCE_RULES",
    "optional_record_rule_for",
    "presence_rule_for",
    "rule_for",
]

_SEMANTIC = ChangeNature.CANONICAL_SEMANTIC
_MAPPING = ChangeNature.NOTATION_MAPPING
_MEMBERSHIP = ChangeNature.VIEW_MEMBERSHIP
_LAYOUT = ChangeNature.LAYOUT_ONLY
_TOOLCHAIN = ChangeNature.RENDERER_TOOLCHAIN


def _rule(kind: ChangeKind, nature: ChangeNature = _SEMANTIC) -> ChangeRule:
    return ChangeRule(kind=kind, nature=nature)


# Shared *values*, never shared keys. `validation/codes.py` does the same with its `_RECORD` /
# `_CROSS` helpers: one row per field keeps the totality assertion meaningful, while a named
# constant keeps the table readable. A wildcard rule — "anything ending `_element_id` is an
# endpoint change" — would make totality trivially satisfiable and silently classify the next
# field somebody adds, so there are none.
_IDENTITY = _rule(ChangeKind.RECORD_IDENTITY)
_DIGEST = _rule(ChangeKind.DIGEST_RESTAMPED)
_WHOLE = _rule(ChangeKind.REPORTED_AS_A_WHOLE)
_MEMBERS = _rule(ChangeKind.COLLECTION_MEMBERSHIP)
_RESIDUAL = _rule(ChangeKind.FIELD_MODIFIED)
_INTERFACE = _rule(ChangeKind.INTERFACE_CONTRACT_CHANGED)
_SCHEMA = _rule(ChangeKind.DATA_SCHEMA_CHANGED)
_BEHAVIOR = _rule(ChangeKind.BEHAVIOR_CHANGED)
_DEPLOYMENT = _rule(ChangeKind.DEPLOYMENT_CHANGED)
_FAMILY = _rule(ChangeKind.DETAIL_FAMILY_CHANGED)
_INTERACTION = _rule(ChangeKind.INTERACTION_CHANGED)
_EVIDENCE = _rule(ChangeKind.EVIDENCE_CHANGED)

CHANGE_CLASSIFICATION: Final[Mapping[tuple[type[BaseModel], str], ChangeRule]] = MappingProxyType(
    {
        # -- Model ----------------------------------------------------------------------------
        # Its own fields are classified too. A `profile_version` change is enormous — it is the
        # difference between re-mapping and re-authoring, which `domain/notation.py` says DATA-31
        # requires stay separable — and leaving `Model` out of the walk is how it would have gone
        # unclassified.
        (Model, "schema_version"): _rule(ChangeKind.SCHEMA_VERSION_CHANGED),
        (Model, "profile_version"): _rule(ChangeKind.PROFILE_VERSION_CHANGED),
        (Model, "model_id"): _IDENTITY,
        (Model, "elements"): _MEMBERS,
        (Model, "relationships"): _MEMBERS,
        (Model, "interactions"): _MEMBERS,
        (Model, "references"): _MEMBERS,
        (Model, "reference_links"): _MEMBERS,
        (Model, "notation_bindings"): _MEMBERS,
        # -- Element --------------------------------------------------------------------------
        (Element, "element_id"): _IDENTITY,
        (Element, "model_id"): _IDENTITY,
        # `commands.py` makes retyping an element inexpressible, calling it "a retire plus an add
        # at the semantic level". A store written by something that did not validate can still
        # contain one, so it is classified rather than assumed away.
        (Element, "kind_id"): _rule(ChangeKind.ELEMENT_RETYPED),
        (Element, "name"): _rule(ChangeKind.ELEMENT_RENAMED),
        (Element, "description"): _RESIDUAL,
        # The one field whose *value* narrows its kind. `RetireElement` leaves the record in
        # place, so without this a retirement would read as an anonymous field update.
        (Element, "lifecycle_state"): ChangeRule(
            kind=ChangeKind.ELEMENT_RETIRED,
            nature=_SEMANTIC,
            refine=(
                ("active", ChangeKind.ELEMENT_REACTIVATED),
                ("replaced", ChangeKind.ELEMENT_REPLACED),
            ),
        ),
        # DATA-04: excluded from semantic identity, so `semantic_delta` cannot see it at all. The
        # presentation pass reports it, and it is the purest layout-only case in the schema.
        (Element, "aliases"): _rule(ChangeKind.DISPLAY_NAME_CHANGED, _LAYOUT),
        (Element, "status"): _WHOLE,
        (Element, "detail"): _FAMILY,
        (Element, "extensions"): _rule(ChangeKind.ANNOTATION_CHANGED),
        (Element, "content_hash"): _DIGEST,
        # -- StatusDimensions -----------------------------------------------------------------
        # Five rows, not one. DATA-29's entire content is that these are independent; collapsing
        # them to `status` would make requirement applicability, evidence and qualification —
        # three separate change categories in data.md — indistinguishable from each other.
        (StatusDimensions, "design_disposition"): _rule(ChangeKind.DISPOSITION_CHANGED),
        (StatusDimensions, "implementation_state"): _rule(ChangeKind.IMPLEMENTATION_STATE_CHANGED),
        (StatusDimensions, "technical_qualification"): _rule(ChangeKind.QUALIFICATION_CHANGED),
        (StatusDimensions, "client_acceptance"): _rule(ChangeKind.ACCEPTANCE_CHANGED),
        (StatusDimensions, "evidence_review"): _rule(ChangeKind.EVIDENCE_REVIEW_CHANGED),
        # -- InterfaceDetail ------------------------------------------------------------------
        (InterfaceDetail, "detail_family"): _FAMILY,
        (InterfaceDetail, "element_id"): _IDENTITY,
        (InterfaceDetail, "transport"): _INTERFACE,
        (InterfaceDetail, "authentication_description"): _INTERFACE,
        (InterfaceDetail, "request_schema_id"): _INTERFACE,
        (InterfaceDetail, "response_schema_id"): _INTERFACE,
        (InterfaceDetail, "delivery_semantics"): _INTERFACE,
        (InterfaceDetail, "timeout_ms"): _INTERFACE,
        (InterfaceDetail, "idempotency_description"): _INTERFACE,
        (InterfaceDetail, "content_hash"): _DIGEST,
        (InterfaceTransport, "protocol"): _INTERFACE,
        (InterfaceTransport, "interaction_mode"): _INTERFACE,
        (InterfaceTransport, "serialization"): _INTERFACE,
        # -- DataSchemaDetail -----------------------------------------------------------------
        (DataSchemaDetail, "detail_family"): _FAMILY,
        (DataSchemaDetail, "element_id"): _IDENTITY,
        (DataSchemaDetail, "fields"): _SCHEMA,
        (DataSchemaDetail, "content_hash"): _DIGEST,
        (SchemaField, "field_id"): _IDENTITY,
        (SchemaField, "field_name"): _SCHEMA,
        (SchemaField, "data_type"): _SCHEMA,
        (SchemaField, "nullability"): _SCHEMA,
        (SchemaField, "cardinality"): _SCHEMA,
        (SchemaField, "key_membership"): _SCHEMA,
        (SchemaField, "references_element_id"): _SCHEMA,
        (SchemaField, "references_field_id"): _SCHEMA,
        # `ordinal` is the semantic order and the tuple position is presentation, which is what
        # makes "an order-sensitive change is detected" true without a synthetic reordered kind.
        (SchemaField, "ordinal"): _SCHEMA,
        # -- BehaviorDetail -------------------------------------------------------------------
        (BehaviorDetail, "detail_family"): _FAMILY,
        (BehaviorDetail, "element_id"): _IDENTITY,
        (BehaviorDetail, "nodes"): _BEHAVIOR,
        (BehaviorDetail, "transitions"): _BEHAVIOR,
        (BehaviorDetail, "content_hash"): _DIGEST,
        (BehaviorNode, "node_id"): _IDENTITY,
        (BehaviorNode, "node_type"): _BEHAVIOR,
        (BehaviorNode, "name"): _BEHAVIOR,
        (BehaviorNode, "ordinal"): _BEHAVIOR,
        (BehaviorNode, "participant_element_id"): _BEHAVIOR,
        (BehaviorTransition, "transition_id"): _IDENTITY,
        (BehaviorTransition, "source_node_id"): _BEHAVIOR,
        (BehaviorTransition, "target_node_id"): _BEHAVIOR,
        (BehaviorTransition, "guard"): _BEHAVIOR,
        (BehaviorTransition, "ordinal"): _BEHAVIOR,
        # -- DeploymentDetail -----------------------------------------------------------------
        (DeploymentDetail, "detail_family"): _FAMILY,
        (DeploymentDetail, "element_id"): _IDENTITY,
        (DeploymentDetail, "environment"): _DEPLOYMENT,
        (DeploymentDetail, "deployment_node_id"): _DEPLOYMENT,
        (DeploymentDetail, "software_instance_id"): _DEPLOYMENT,
        (DeploymentDetail, "configuration_artifact_id"): _DEPLOYMENT,
        (DeploymentDetail, "content_hash"): _DIGEST,
        # -- RequirementDetail ----------------------------------------------------------------
        (RequirementDetail, "detail_family"): _FAMILY,
        (RequirementDetail, "element_id"): _IDENTITY,
        (RequirementDetail, "category"): _rule(ChangeKind.REQUIREMENT_VERIFICATION_CHANGED),
        (RequirementDetail, "applicability"): _rule(ChangeKind.REQUIREMENT_APPLICABILITY_CHANGED),
        (RequirementDetail, "applicability_note"): _rule(
            ChangeKind.REQUIREMENT_APPLICABILITY_CHANGED
        ),
        (RequirementDetail, "verification_method"): _rule(
            ChangeKind.REQUIREMENT_VERIFICATION_CHANGED
        ),
        (RequirementDetail, "acceptance_criterion_ids"): _rule(
            ChangeKind.REQUIREMENT_VERIFICATION_CHANGED
        ),
        (RequirementDetail, "content_hash"): _DIGEST,
        # -- Relationship ---------------------------------------------------------------------
        (Relationship, "relationship_id"): _IDENTITY,
        (Relationship, "model_id"): _IDENTITY,
        (Relationship, "relationship_type_id"): _rule(ChangeKind.RELATIONSHIP_RETYPED),
        # The case `queries/algorithms.py::compare_architecture_releases` reports as *no change*
        # today: same relationship id, different endpoints.
        (Relationship, "source_element_id"): _rule(ChangeKind.RELATIONSHIP_ENDPOINT_CHANGED),
        (Relationship, "target_element_id"): _rule(ChangeKind.RELATIONSHIP_ENDPOINT_CHANGED),
        (Relationship, "context_id"): _rule(ChangeKind.RELATIONSHIP_CONTEXT_CHANGED),
        (Relationship, "description"): _RESIDUAL,
        (Relationship, "extensions"): _rule(ChangeKind.ANNOTATION_CHANGED),
        (Relationship, "content_hash"): _DIGEST,
        # -- Interaction ----------------------------------------------------------------------
        (Interaction, "interaction_id"): _IDENTITY,
        (Interaction, "model_id"): _IDENTITY,
        (Interaction, "name"): _INTERACTION,
        (Interaction, "interaction_kind"): _INTERACTION,
        (Interaction, "description"): _RESIDUAL,
        (Interaction, "participants"): _rule(ChangeKind.INTERACTION_PARTICIPANTS_CHANGED),
        (Interaction, "moved_object_ids"): _INTERACTION,
        (Interaction, "content_hash"): _DIGEST,
        # Two of its three fields are its identity key under `COLLECTION_ORDER`, so a role change
        # is one member leaving and another arriving. Descending would buy nothing and cost a
        # grammar exception.
        (InteractionParticipant, "element_id"): _WHOLE,
        (InteractionParticipant, "participant_role"): _WHOLE,
        (InteractionParticipant, "ordinal"): _WHOLE,
        # -- Reference and ReferenceLink ------------------------------------------------------
        (Reference, "reference_id"): _IDENTITY,
        (Reference, "model_id"): _IDENTITY,
        (Reference, "reference_kind"): _EVIDENCE,
        (Reference, "title"): _EVIDENCE,
        (Reference, "locator"): _EVIDENCE,
        (Reference, "authority"): _RESIDUAL,
        (Reference, "content_hash"): _DIGEST,
        (ReferenceLink, "link_id"): _IDENTITY,
        (ReferenceLink, "model_id"): _IDENTITY,
        (ReferenceLink, "reference_id"): _EVIDENCE,
        (ReferenceLink, "subject"): _rule(ChangeKind.EVIDENCE_SUBJECT_CHANGED),
        (ReferenceLink, "link_role"): _EVIDENCE,
        (ReferenceLink, "note"): _RESIDUAL,
        (ReferenceLink, "content_hash"): _DIGEST,
        # A `ReferenceTarget` is one address. Re-pointing it is one fact, reported at the owning
        # field, which is also what keeps the classification unambiguous: the same variant class
        # is reachable from both `ReferenceLink.subject` and `NotationBinding.subject`, where the
        # *nature* differs, and a per-component rule could only name one of them.
        (ElementReference, "subject_kind"): _WHOLE,
        (ElementReference, "element_id"): _WHOLE,
        (RelationshipReference, "subject_kind"): _WHOLE,
        (RelationshipReference, "relationship_id"): _WHOLE,
        (FieldReference, "subject_kind"): _WHOLE,
        (FieldReference, "element_id"): _WHOLE,
        (FieldReference, "field_path"): _WHOLE,
        (ReleaseReference, "subject_kind"): _WHOLE,
        (ReleaseReference, "release_id"): _WHOLE,
        # -- Extension ------------------------------------------------------------------------
        # Reported at `extensions` as a member arriving, leaving or changing. Descending into an
        # extension value would be the change layer reading an annotation, which
        # `domain/extensions.py` names as the signal it should have been a typed field.
        (Extension, "namespace"): _WHOLE,
        (Extension, "key"): _WHOLE,
        (Extension, "value"): _WHOLE,
        # -- NotationBinding ------------------------------------------------------------------
        # The record the gate turns on, and the reason this table is keyed by field rather than by
        # record: three natures across one record. A per-record rule would either make moving a
        # box into another view an architectural change, or make a mapping-profile bump invisible.
        (NotationBinding, "binding_id"): _IDENTITY,
        (NotationBinding, "model_id"): _IDENTITY,
        (NotationBinding, "subject"): _rule(ChangeKind.BINDING_RESUBJECTED, _MAPPING),
        (NotationBinding, "notation"): _rule(ChangeKind.NOTATION_MAPPING_CHANGED, _MAPPING),
        (NotationBinding, "notation_type"): _rule(ChangeKind.NOTATION_MAPPING_CHANGED, _MAPPING),
        (NotationBinding, "notation_object_id"): _rule(
            ChangeKind.NOTATION_MAPPING_CHANGED, _MAPPING
        ),
        (NotationBinding, "mapping_profile_version"): _rule(
            ChangeKind.NOTATION_MAPPING_CHANGED, _MAPPING
        ),
        # "View membership is semantic governed content" — projections.md. Which view an object
        # appears in is a modelling decision; where it sits in that view is not.
        (NotationBinding, "view_id"): _rule(ChangeKind.VIEW_MEMBERSHIP_CHANGED, _MEMBERSHIP),
        (NotationBinding, "link_target"): _rule(ChangeKind.LAYOUT_LINK_CHANGED, _LAYOUT),
        (NotationBinding, "projection_artifact_id"): _rule(
            ChangeKind.PROJECTION_PROVENANCE_CHANGED, _TOOLCHAIN
        ),
        (NotationBinding, "content_hash"): _DIGEST,
    }
)
"""Every field of every record reachable from `Model`, and what a change to it is.

Asserted total by reflection in `tests/unit/test_change_classification.py`, which is what makes a
new field a failure rather than a silent `FIELD_MODIFIED`.
"""


PRESENCE_RULES: Final[Mapping[tuple[str, bool], ChangeRule]] = MappingProxyType(
    {
        ("elements", True): _rule(ChangeKind.ELEMENT_ADDED),
        ("elements", False): _rule(ChangeKind.ELEMENT_REMOVED),
        ("relationships", True): _rule(ChangeKind.RELATIONSHIP_ADDED),
        ("relationships", False): _rule(ChangeKind.RELATIONSHIP_REMOVED),
        ("interactions", True): _rule(ChangeKind.INTERACTION_ADDED),
        ("interactions", False): _rule(ChangeKind.INTERACTION_REMOVED),
        ("references", True): _rule(ChangeKind.REFERENCE_ADDED),
        ("references", False): _rule(ChangeKind.REFERENCE_REMOVED),
        ("reference_links", True): _rule(ChangeKind.EVIDENCE_LINK_ADDED),
        ("reference_links", False): _rule(ChangeKind.EVIDENCE_LINK_REMOVED),
        ("notation_bindings", True): _rule(ChangeKind.NOTATION_BINDING_ADDED, _MAPPING),
        ("notation_bindings", False): _rule(ChangeKind.NOTATION_BINDING_REMOVED, _MAPPING),
    }
)
"""An added or removed record, by collection. `True` means present in the candidate.

Separate from the field table because an added record has no changed fields to classify. Asserted
total against `semantics.py::_MODEL_COLLECTIONS`, so a seventh collection cannot arrive without a
decision about what its appearance means.
"""


OPTIONAL_RECORD_RULES: Final[
    Mapping[tuple[type[BaseModel], str], tuple[ChangeRule, ChangeRule]]
] = MappingProxyType(
    {
        # An element acquiring a detail did not change eight fields; it acquired a contract.
        # Descending a `None` would report every field of the new record as a change, which
        # says the wrong thing at the wrong granularity.
        (Element, "detail"): (
            _rule(ChangeKind.DETAIL_ADDED),
            _rule(ChangeKind.DETAIL_REMOVED),
        ),
    }
)
"""Optional nested records, and what their arrival or departure means. `(arrived, departed)`.

One entry today. Asserted total by reflection over every `Record | None` field reachable from
`Model`, so a second optional nested record cannot arrive without a decision — which is the same
reason `PRESENCE_RULES` exists for the top-level collections.
"""


def rule_for(owner: type[BaseModel], field_name: str) -> ChangeRule:
    """The rule for one field. Subscripts deliberately: an unclassified field is a failure.

    No default, and no `.get`. A default would answer for a field nobody classified, and the
    totality test that is supposed to force that decision would keep passing.
    """
    return CHANGE_CLASSIFICATION[(owner, field_name)]


def presence_rule_for(collection: str, *, in_candidate: bool) -> ChangeRule:
    """What it means that a record appeared in, or vanished from, one collection."""
    return PRESENCE_RULES[(collection, in_candidate)]


def optional_record_rule_for(
    owner: type[BaseModel], field_name: str, *, arrived: bool
) -> ChangeRule:
    """What it means that an optional nested record appeared or vanished."""
    added, removed = OPTIONAL_RECORD_RULES[(owner, field_name)]
    return added if arrived else removed


def _check_registry() -> None:
    """Refuse an incoherent table at import, the way `validation/codes.py` does.

    Cheap structural checks only — totality against the record tree is a test, because it needs
    reflection over `Model` and importing that walk here would make the module import its own
    guard.
    """
    for owner, field_name in OPTIONAL_RECORD_RULES:
        if (owner, field_name) not in CHANGE_CLASSIFICATION:
            message = f"{owner.__name__}.{field_name} has presence rules but no field rule"
            raise ClassificationError(message)
    for (owner, field_name), rule in CHANGE_CLASSIFICATION.items():
        if field_name not in owner.model_fields:
            message = f"{owner.__name__} has no field {field_name!r}"
            raise ClassificationError(message)
        if rule.refine and rule.kind is not ChangeKind.ELEMENT_RETIRED:
            message = (
                f"{owner.__name__}.{field_name} declares a value refinement; only "
                f"lifecycle_state may, and widening that is a decision, not an edit"
            )
            raise ClassificationError(message)


_check_registry()

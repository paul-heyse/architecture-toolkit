"""Controlled kind and relationship-type registries (DATA-04, DATA-05, DATA-06).

The seven-member `Kind` enum this replaces could say that an element was a `software.system`. It
could not say whether `system-1 --supports--> process-1` was a legal statement, which direction
the relationship was authored in, what its inverse should be called, or whether a cycle of them
was an error. `profiles/default/README.md` reserved that work with the right warning: define
permitted endpoints, canonical direction, cardinality and traversal policy "before claiming
architecture validation".

**Where this lives.** The generic baseline is here in `domain/`, and profiles override it. The
toolkit has to be usable and testable standalone, DATA-04 and DATA-05 need real acceptance
evidence in W1, and `ARCH-TOOL-001` §5 asks only that the reusable core stay general — which the
ten kinds below are, being the illustrative set the specification itself names.

**A profile is a value, not a file.** `Profile` is an ordinary frozen record and `with_overrides`
is a pure function over it. That is the whole override mechanism, and it needs no loader, no
profile schema and no resolution order — none of which W1 scopes. When W2 can read YAML, a loader
produces one of these; nothing here changes.

DATA-06 is structural rather than enforced: there is exactly one direction field, so there is no
way to store `supports` and `supported_by` as separate rows. `inverse_display_label` is how the
reverse reading is rendered, and `validation/` derives inverse views from it.
"""

from enum import StrEnum
from functools import cached_property
from typing import Self

from pydantic import TypeAdapter, model_validator

from architecture_toolkit.domain.base import CompiledRecord
from architecture_toolkit.domain.identifiers import (
    ProfileVersion,
    QualifiedKind,
    RelationshipTypeId,
    RuleId,
)

__all__ = [
    "BASELINE_PROFILE",
    "BASELINE_PROFILE_VERSION",
    "CanonicalDirection",
    "Cardinality",
    "DetailFamily",
    "KindDefinition",
    "KindLayer",
    "Profile",
    "RelationshipTypeDefinition",
    "TraversalBehavior",
    "with_overrides",
]


class KindLayer(StrEnum):
    """The first segment of a qualified kind, as a closed set.

    Kinds are open — profiles add them — but the layers they sit in are not. A profile that needs
    a new top-level layer is making an architectural claim, not a vocabulary extension.
    """

    BUSINESS = "business"
    ORGANIZATION = "organization"
    SOFTWARE = "software"
    INFORMATION = "information"
    TECHNOLOGY = "technology"
    MOTIVATION = "motivation"


class DetailFamily(StrEnum):
    """The six typed detail families (DATA-07).

    Declared here rather than in `details.py` because a family is registry vocabulary: what a kind
    is *permitted* to carry is a registry statement, and putting the enum here is what lets
    `KindDefinition` reference it without `registry` and `details` importing each other.
    """

    INTERFACE = "interface"
    DEPLOYMENT = "deployment"
    DATA_SCHEMA = "data_schema"
    BEHAVIOR = "behavior"
    REQUIREMENT = "requirement"
    NOTATION_BINDING = "notation_binding"


class CanonicalDirection(StrEnum):
    """DATA-06. `SYMMETRIC` means the pair is unordered, not that both rows are stored."""

    SOURCE_TO_TARGET = "source_to_target"
    SYMMETRIC = "symmetric"


class Cardinality(StrEnum):
    ONE_TO_ONE = "one_to_one"
    ONE_TO_MANY = "one_to_many"
    MANY_TO_ONE = "many_to_one"
    MANY_TO_MANY = "many_to_many"


class TraversalBehavior(StrEnum):
    """What a graph policy is allowed to do with this type (DATA-05, consumed at W5)."""

    FORWARD_ONLY = "forward_only"
    REVERSE_ONLY = "reverse_only"
    BIDIRECTIONAL = "bidirectional"
    NOT_TRAVERSABLE = "not_traversable"


class KindDefinition(CompiledRecord):
    kind_id: QualifiedKind
    layer: KindLayer
    display_label: str
    description: str
    permitted_detail_families: frozenset[DetailFamily] = frozenset()

    @model_validator(mode="after")
    def layer_matches_kind_id(self) -> Self:
        """Record-local and deterministic, so it belongs in Pydantic (`ARCH-TOOL-CORE-001` §3F).

        Anything needing another record — that a permitted endpoint kind exists, say — is a
        cross-record rule and lives in `validation/`.
        """
        prefix = self.kind_id.split(".", 1)[0]
        if prefix != self.layer.value:
            message = (
                f"kind_id {self.kind_id!r} does not sit in declared layer {self.layer.value!r}"
            )
            raise ValueError(message)
        return self


class RelationshipTypeDefinition(CompiledRecord):
    """All eight properties `ARCH-TOOL-DATA-001` §2B requires, plus the ordering flag W2 needs.

    The eighth — `validation_rule_ids` — is the one most easily dropped, and it is what lets a
    profile say that *its* `contains` must be acyclic without editing the toolkit. W1 declares the
    ids; PR3 registers the rules and adds the guard that none of these dangles.
    """

    relationship_type_id: RelationshipTypeId
    display_label: str
    description: str
    permitted_source_kinds: frozenset[QualifiedKind]
    permitted_target_kinds: frozenset[QualifiedKind]
    canonical_direction: CanonicalDirection
    inverse_display_label: str
    cardinality: Cardinality | None = None
    traversal: TraversalBehavior = TraversalBehavior.BIDIRECTIONAL
    validation_rule_ids: frozenset[RuleId] = frozenset()
    # W2 canonicalizes unordered collections when computing the semantic hash and must not reorder
    # an authored sequence. That decision is per relationship type and its risk note names this
    # registry as its home. Uniformly false in the baseline: ordered sequences in the generic
    # profile live inside behaviour details, not between elements.
    ordered_sequence: bool = False


class Profile(CompiledRecord):
    """A named, versioned vocabulary. Frozen, hashable, and comparable by value."""

    profile_id: str
    profile_version: ProfileVersion
    kinds: tuple[KindDefinition, ...]
    relationship_types: tuple[RelationshipTypeDefinition, ...]

    @cached_property
    def kinds_by_id(self) -> dict[QualifiedKind, KindDefinition]:
        return {kind.kind_id: kind for kind in self.kinds}

    @cached_property
    def relationship_types_by_id(self) -> dict[RelationshipTypeId, RelationshipTypeDefinition]:
        return {entry.relationship_type_id: entry for entry in self.relationship_types}

    @model_validator(mode="after")
    def identities_are_unique(self) -> Self:
        for label, seen in (
            ("kind", [k.kind_id for k in self.kinds]),
            ("relationship type", [r.relationship_type_id for r in self.relationship_types]),
        ):
            if len(seen) != len(set(seen)):
                message = f"duplicate {label} identity in profile {self.profile_id!r}"
                raise ValueError(message)
        return self


def with_overrides(
    base: Profile,
    *,
    profile_id: str,
    profile_version: ProfileVersion,
    kinds: tuple[KindDefinition, ...] = (),
    relationship_types: tuple[RelationshipTypeDefinition, ...] = (),
    removed_kind_ids: frozenset[QualifiedKind] = frozenset(),
    removed_relationship_type_ids: frozenset[RelationshipTypeId] = frozenset(),
) -> Profile:
    """Derive a profile from another. Pure, total and deterministic.

    An entry whose id already exists replaces it; a new id is appended. Output is sorted by id so
    two equivalent overlays produce byte-identical schemas and digests. Removing a kind that a
    surviving relationship type still names is *not* rejected here — that is a cross-record
    condition, and `validation/` reports it as a diagnostic so a profile author sees a finding
    rather than a traceback.
    """
    merged_kinds = {
        kind.kind_id: kind for kind in base.kinds if kind.kind_id not in removed_kind_ids
    }
    merged_kinds.update({kind.kind_id: kind for kind in kinds})
    merged_types = {
        entry.relationship_type_id: entry
        for entry in base.relationship_types
        if entry.relationship_type_id not in removed_relationship_type_ids
    }
    merged_types.update({entry.relationship_type_id: entry for entry in relationship_types})
    return Profile(
        profile_id=profile_id,
        profile_version=profile_version,
        kinds=tuple(merged_kinds[key] for key in sorted(merged_kinds)),
        relationship_types=tuple(merged_types[key] for key in sorted(merged_types)),
    )


PROFILE_ADAPTER: TypeAdapter[Profile] = TypeAdapter(Profile)
"""CORE-05: a natural type boundary. Profiles arrive as data from W2 onward."""


# -- the baseline profile ---------------------------------------------------------------------
# The ten kinds and the relationship types `ARCH-TOOL-DATA-001` §2A/§2B name. The specification
# calls the kind list "illustrative", which is exactly why it ships as a profile value rather
# than a closed enum: a consumer profile adds `business.product` without editing the toolkit.

BASELINE_PROFILE_VERSION = "1.0.0"

_CAPABILITY = "business.capability"
_PROCESS = "business.process"
_ROLE = "organization.role"
_SYSTEM = "software.system"
_COMPONENT = "software.component"
_INTERFACE = "software.interface"
_OBJECT = "information.object"
_SCHEMA = "information.schema"
_DEPLOYMENT = "technology.deployment"
_REQUIREMENT = "motivation.requirement"

_ALL_KINDS = frozenset(
    {
        _CAPABILITY,
        _PROCESS,
        _ROLE,
        _SYSTEM,
        _COMPONENT,
        _INTERFACE,
        _OBJECT,
        _SCHEMA,
        _DEPLOYMENT,
        _REQUIREMENT,
    }
)

_BASELINE_KINDS: tuple[KindDefinition, ...] = (
    KindDefinition(
        kind_id=_CAPABILITY,
        layer=KindLayer.BUSINESS,
        display_label="Capability",
        description="What the organization is able to do, independent of how it is done.",
    ),
    KindDefinition(
        kind_id=_PROCESS,
        layer=KindLayer.BUSINESS,
        display_label="Process",
        description="An ordered course of activity that produces a business outcome.",
        permitted_detail_families=frozenset({DetailFamily.BEHAVIOR}),
    ),
    KindDefinition(
        kind_id=_ROLE,
        layer=KindLayer.ORGANIZATION,
        display_label="Role",
        description="An organizational responsibility, never a named individual.",
    ),
    KindDefinition(
        kind_id=_SYSTEM,
        layer=KindLayer.SOFTWARE,
        display_label="System",
        description="A deployable software system with an external boundary.",
    ),
    KindDefinition(
        kind_id=_COMPONENT,
        layer=KindLayer.SOFTWARE,
        display_label="Component",
        description="A structural part of a system, not independently deployable.",
    ),
    KindDefinition(
        kind_id=_INTERFACE,
        layer=KindLayer.SOFTWARE,
        display_label="Interface",
        description="A contract through which a system or component is reached.",
        permitted_detail_families=frozenset({DetailFamily.INTERFACE}),
    ),
    KindDefinition(
        kind_id=_OBJECT,
        layer=KindLayer.INFORMATION,
        display_label="Information object",
        description="A business-meaningful unit of information, independent of its storage.",
    ),
    KindDefinition(
        kind_id=_SCHEMA,
        layer=KindLayer.INFORMATION,
        display_label="Schema",
        description="A concrete typed structure. Related to an information object, not identical "
        "to it: a conceptual business object and its physical table are two representations.",
        permitted_detail_families=frozenset({DetailFamily.DATA_SCHEMA}),
    ),
    KindDefinition(
        kind_id=_DEPLOYMENT,
        layer=KindLayer.TECHNOLOGY,
        display_label="Deployment",
        description="Where software actually runs.",
        permitted_detail_families=frozenset({DetailFamily.DEPLOYMENT}),
    ),
    KindDefinition(
        kind_id=_REQUIREMENT,
        layer=KindLayer.MOTIVATION,
        display_label="Requirement",
        description="A stated obligation the architecture must satisfy.",
        permitted_detail_families=frozenset({DetailFamily.REQUIREMENT}),
    ),
)

# `ARCH-TOOL-DATA-001` §2B names six types that must stay distinct, on the grounds that
# "collapsing these into generic connections would undermine complex queries and interpretation
# of impacts". Two more are added because the generic toolkit demonstrably needs them and neither
# reduces to one of the six: `exposes` is not `contains` (a component may expose an interface it
# does not own), and `responsible_for` is not `supports` (accountability is not enablement).
#
# `uses_schema`, which the previous example fixture used, is deliberately *not* here. It reduces
# to `depends_on`, and its specific meaning belongs in `InterfaceDetail.request_schema_id` —
# which is DATA-30 working as intended: model it in a typed field, not a generic edge label.

_BASELINE_RELATIONSHIP_TYPES: tuple[RelationshipTypeDefinition, ...] = (
    RelationshipTypeDefinition(
        relationship_type_id="contains",
        display_label="contains",
        description="Structural composition. The target is part of the source.",
        permitted_source_kinds=frozenset({_SYSTEM, _COMPONENT, _PROCESS, _CAPABILITY, _SCHEMA}),
        permitted_target_kinds=frozenset({_COMPONENT, _INTERFACE, _PROCESS, _OBJECT, _SCHEMA}),
        canonical_direction=CanonicalDirection.SOURCE_TO_TARGET,
        inverse_display_label="is contained in",
        cardinality=Cardinality.ONE_TO_MANY,
        traversal=TraversalBehavior.FORWARD_ONLY,
        validation_rule_ids=frozenset({"endpoint-kinds", "acyclic", "single-parent"}),
    ),
    RelationshipTypeDefinition(
        relationship_type_id="supports",
        display_label="supports",
        description="The source enables the target to operate. Not accountability.",
        permitted_source_kinds=frozenset({_SYSTEM, _COMPONENT, _DEPLOYMENT, _PROCESS}),
        permitted_target_kinds=frozenset({_CAPABILITY, _PROCESS, _ROLE}),
        canonical_direction=CanonicalDirection.SOURCE_TO_TARGET,
        inverse_display_label="is supported by",
        cardinality=Cardinality.MANY_TO_MANY,
        validation_rule_ids=frozenset({"endpoint-kinds"}),
    ),
    RelationshipTypeDefinition(
        relationship_type_id="realizes",
        display_label="realizes",
        description="A concrete element fulfils an abstract one.",
        permitted_source_kinds=frozenset({_SYSTEM, _COMPONENT, _PROCESS, _DEPLOYMENT}),
        permitted_target_kinds=frozenset({_REQUIREMENT, _CAPABILITY}),
        canonical_direction=CanonicalDirection.SOURCE_TO_TARGET,
        inverse_display_label="is realized by",
        cardinality=Cardinality.MANY_TO_MANY,
        validation_rule_ids=frozenset({"endpoint-kinds"}),
    ),
    RelationshipTypeDefinition(
        relationship_type_id="exchanges_data_with",
        display_label="exchanges data with",
        description="Symmetric data exchange. Stored once; neither endpoint is privileged.",
        permitted_source_kinds=frozenset({_SYSTEM, _COMPONENT, _INTERFACE, _ROLE, _PROCESS}),
        permitted_target_kinds=frozenset({_SYSTEM, _COMPONENT, _INTERFACE, _ROLE, _PROCESS}),
        canonical_direction=CanonicalDirection.SYMMETRIC,
        inverse_display_label="exchanges data with",
        cardinality=Cardinality.MANY_TO_MANY,
        validation_rule_ids=frozenset({"endpoint-kinds", "no-duplicate-inverse", "no-self-loop"}),
    ),
    RelationshipTypeDefinition(
        relationship_type_id="depends_on",
        display_label="depends on",
        description="The source cannot function correctly without the target.",
        permitted_source_kinds=frozenset({_SYSTEM, _COMPONENT, _INTERFACE, _DEPLOYMENT, _PROCESS}),
        permitted_target_kinds=frozenset({_SYSTEM, _COMPONENT, _INTERFACE, _DEPLOYMENT, _SCHEMA}),
        canonical_direction=CanonicalDirection.SOURCE_TO_TARGET,
        inverse_display_label="is depended on by",
        cardinality=Cardinality.MANY_TO_MANY,
        validation_rule_ids=frozenset({"endpoint-kinds", "acyclic"}),
    ),
    RelationshipTypeDefinition(
        relationship_type_id="justifies",
        display_label="justifies",
        description="A requirement motivates the existence or shape of the target.",
        permitted_source_kinds=frozenset({_REQUIREMENT}),
        permitted_target_kinds=_ALL_KINDS,
        canonical_direction=CanonicalDirection.SOURCE_TO_TARGET,
        inverse_display_label="is justified by",
        cardinality=Cardinality.MANY_TO_MANY,
        traversal=TraversalBehavior.FORWARD_ONLY,
        validation_rule_ids=frozenset({"endpoint-kinds"}),
    ),
    RelationshipTypeDefinition(
        relationship_type_id="exposes",
        display_label="exposes",
        description="The source makes the interface reachable from outside its boundary.",
        permitted_source_kinds=frozenset({_SYSTEM, _COMPONENT}),
        permitted_target_kinds=frozenset({_INTERFACE}),
        canonical_direction=CanonicalDirection.SOURCE_TO_TARGET,
        inverse_display_label="is exposed by",
        cardinality=Cardinality.ONE_TO_MANY,
        validation_rule_ids=frozenset({"endpoint-kinds"}),
    ),
    RelationshipTypeDefinition(
        relationship_type_id="responsible_for",
        display_label="is responsible for",
        description="An organizational role is accountable for the target.",
        permitted_source_kinds=frozenset({_ROLE}),
        permitted_target_kinds=frozenset({_PROCESS, _SYSTEM, _COMPONENT, _CAPABILITY, _OBJECT}),
        canonical_direction=CanonicalDirection.SOURCE_TO_TARGET,
        inverse_display_label="is the responsibility of",
        cardinality=Cardinality.MANY_TO_MANY,
        validation_rule_ids=frozenset({"endpoint-kinds"}),
    ),
)

BASELINE_PROFILE: Profile = Profile(
    profile_id="default",
    profile_version=BASELINE_PROFILE_VERSION,
    kinds=_BASELINE_KINDS,
    relationship_types=_BASELINE_RELATIONSHIP_TYPES,
)
"""The generic profile. `profiles/` overrides it with `with_overrides`; nothing loads a file."""

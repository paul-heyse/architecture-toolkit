"""Versioned graph policies: what a traversal is allowed to follow, and how far (CORE-26, CORE-27).

> Impact analysis is the reason the graph exists, and the reason it must be policy-driven:
> following ownership, documentation and grouping edges indiscriminately produces misleading impact
> reports.
> — `docs/plans/w5-query-graph.md`

A `GraphPolicy` declares every field the `core.md § NetworkX analysis` fence names, and two things
make it more than a record.

**It is checked against the profile that owns the vocabulary.** W1 put `TraversalBehavior` on every
relationship type — "what a graph policy is allowed to do with this type" — and left it unused,
waiting for this wave. A policy that follows a type the profile marks `not_traversable`, or walks a
`forward_only` type backwards, is refused when it is constructed rather than producing a plausible
answer nobody can defend. The baseline marks `contains` and `justifies` forward-only, which is
exactly the documentation edge the wave's purpose warns about.

**Direction is one of two values, not three.** A traversal that could change direction mid-path
would return paths that describe nothing: "A depends on B, and C also depends on B, therefore C is
affected by A" is not a dependency. A question that genuinely needs both directions is two
traversals, and saying so is cheaper than a result type that has to explain itself.

Policies are applied through `subgraph_view` — a read-only filtered projection, never a copy
(CORE-27) — and the caps are handed to the generator rather than applied to a materialized list
(CORE-29).
"""

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from pydantic import Field

from architecture_toolkit.domain.base import CompiledRecord
from architecture_toolkit.domain.identifiers import (
    ContextId,
    PolicyId,
    QualifiedKind,
    RelationshipTypeId,
    SchemaVersion,
)
from architecture_toolkit.domain.registry import BASELINE_PROFILE, Profile, TraversalBehavior
from architecture_toolkit.queries.errors import PolicyError, UnknownPolicyError
from architecture_toolkit.queries.results import PathClassification

__all__ = [
    "POLICIES",
    "CycleHandling",
    "Direction",
    "GraphPolicy",
    "check_policy",
    "policy_for",
]


class Direction(StrEnum):
    """Which way a traversal follows a relationship."""

    FORWARD = "forward"
    """Source to target: what this object reaches."""

    REVERSE = "reverse"
    """Target to source: what reaches this object."""


class CycleHandling(StrEnum):
    """What a traversal does about a cycle in its own view."""

    SKIP = "skip"
    """Simple paths never revisit a node, so a cycle simply bounds the paths that exist."""

    REPORT = "report"
    """The cycle is the answer — `queries/algorithms.py` owns this case."""


_PERMITTED_DIRECTIONS: Final[Mapping[TraversalBehavior, frozenset[Direction]]] = MappingProxyType(
    {
        TraversalBehavior.FORWARD_ONLY: frozenset({Direction.FORWARD}),
        TraversalBehavior.REVERSE_ONLY: frozenset({Direction.REVERSE}),
        TraversalBehavior.BIDIRECTIONAL: frozenset(Direction),
        TraversalBehavior.NOT_TRAVERSABLE: frozenset(),
    }
)
"""W1's `TraversalBehavior` read as the permission it was declared to be."""


class GraphPolicy(CompiledRecord):
    """A versioned, bounded, explainable traversal declaration (CORE-26)."""

    policy_id: PolicyId
    policy_version: SchemaVersion
    purpose: str = Field(min_length=1)
    allowed_relationship_types: tuple[RelationshipTypeId, ...] = Field(min_length=1)
    direction: Direction
    allowed_node_kinds: tuple[QualifiedKind, ...] = ()
    """Empty means every kind. A policy that named them all would have to be edited by every
    project that adds a kind, which is the opposite of what a profile is for."""
    excluded_node_kinds: tuple[QualifiedKind, ...] = ()
    context_filters: tuple[ContextId, ...] = ()
    """Empty means any context, including none. `Relationship.context_id` is declared on every
    relationship and written by nothing today, so this filter is exercised by tests rather than by
    the example model — worth knowing before reading a traversal as context-aware."""
    max_depth: int = Field(ge=1)
    max_paths: int = Field(ge=1)
    max_results: int = Field(ge=1)
    stop_kinds: tuple[QualifiedKind, ...] = ()
    """Kinds a path may end on but not pass through."""
    cycle_handling: CycleHandling = CycleHandling.SKIP
    classification: PathClassification
    """What this policy's paths are permitted to claim (CORE-28, DATA-17)."""

    def permits_kind(self, kind_id: str) -> bool:
        if self.excluded_node_kinds and kind_id in self.excluded_node_kinds:
            return False
        return not self.allowed_node_kinds or kind_id in self.allowed_node_kinds

    def permits_type(self, relationship_type_id: str) -> bool:
        return relationship_type_id in self.allowed_relationship_types

    def permits_context(self, context_id: str | None) -> bool:
        return not self.context_filters or (
            context_id is not None and context_id in self.context_filters
        )


def check_policy(policy: GraphPolicy, profile: Profile = BASELINE_PROFILE) -> GraphPolicy:
    """Refuse a policy the profile's traversal vocabulary does not support (CORE-26, DATA-05)."""
    definitions = profile.relationship_types_by_id
    unknown = sorted(set(policy.allowed_relationship_types) - set(definitions))
    if unknown:
        message = (
            f"{policy.policy_id} follows relationship types {unknown} that "
            f"{profile.profile_id} does not define"
        )
        raise PolicyError(message)

    refused = sorted(
        type_id
        for type_id in policy.allowed_relationship_types
        if policy.direction not in _PERMITTED_DIRECTIONS[definitions[type_id].traversal]
    )
    if refused:
        message = (
            f"{policy.policy_id} traverses {refused} {policy.direction.value}, which "
            f"{profile.profile_id} does not permit for those types"
        )
        raise PolicyError(message)

    kinds = set(profile.kinds_by_id)
    named = (
        set(policy.allowed_node_kinds) | set(policy.excluded_node_kinds) | set(policy.stop_kinds)
    )
    missing = sorted(named - kinds)
    if missing:
        message = (
            f"{policy.policy_id} names node kinds {missing} that "
            f"{profile.profile_id} does not define"
        )
        raise PolicyError(message)
    return policy


_IMPACT = GraphPolicy(
    policy_id="impact.structural",
    policy_version="1.0.0",
    purpose=(
        "What a change to this object could reach through structural dependence. Ownership and "
        "documentation edges are excluded: `responsible_for` names who is accountable and "
        "`justifies` names why something exists, and following either would turn every requirement "
        "author and every owning role into an impacted party."
    ),
    allowed_relationship_types=(
        "contains",
        "depends_on",
        "exchanges_data_with",
        "exposes",
        "realizes",
        "supports",
    ),
    direction=Direction.FORWARD,
    max_depth=4,
    max_paths=200,
    max_results=100,
    classification=PathClassification.POTENTIALLY_AFFECTED,
)

_REQUIREMENT_IMPLEMENTATION = GraphPolicy(
    policy_id="trace.requirement_implementation",
    policy_version="1.0.0",
    purpose=(
        "What realizes a requirement. Reverse, because `realizes` runs from the implementer to the "
        "requirement, and the question is asked from the requirement."
    ),
    allowed_relationship_types=("realizes",),
    direction=Direction.REVERSE,
    max_depth=3,
    max_paths=100,
    max_results=100,
    classification=PathClassification.TRACED,
)

_INTERFACE_DEPENDENTS = GraphPolicy(
    policy_id="dependents.interface",
    policy_version="1.0.0",
    purpose=(
        "What would have to change if this interface changed. Reverse along dependence and "
        "exposure, so the answer is the things that reach the interface rather than the things it "
        "reaches."
    ),
    allowed_relationship_types=("depends_on", "exposes"),
    direction=Direction.REVERSE,
    max_depth=4,
    max_paths=200,
    max_results=100,
    classification=PathClassification.POTENTIALLY_AFFECTED,
)

_CONTAINMENT = GraphPolicy(
    policy_id="containment.descendants",
    policy_version="1.0.0",
    purpose=(
        "Everything structurally inside this object. Forward only, which is what the profile "
        "permits for `contains`."
    ),
    allowed_relationship_types=("contains",),
    direction=Direction.FORWARD,
    max_depth=8,
    max_paths=500,
    max_results=500,
    cycle_handling=CycleHandling.REPORT,
    classification=PathClassification.CONTAINED_BY,
)

_DEPENDENCIES = GraphPolicy(
    policy_id="dependencies.direct",
    policy_version="1.0.0",
    purpose=(
        "What this object depends on, following dependence alone. The narrow policy behind "
        "`find_unverified_dependencies`, which filters the reached objects by their recorded "
        "verification rather than by how they were reached."
    ),
    allowed_relationship_types=("depends_on",),
    direction=Direction.FORWARD,
    max_depth=4,
    max_paths=200,
    max_results=100,
    classification=PathClassification.POTENTIALLY_AFFECTED,
)

POLICIES: Final[Mapping[PolicyId, GraphPolicy]] = MappingProxyType(
    {
        policy.policy_id: check_policy(policy)
        for policy in (
            _IMPACT,
            _REQUIREMENT_IMPLEMENTATION,
            _INTERFACE_DEPENDENTS,
            _CONTAINMENT,
            _DEPENDENCIES,
        )
    }
)
"""Checked against the baseline profile at import, the way `validation/codes.py` checks its own
registry: a policy that the vocabulary does not support cannot be reached at all."""


def policy_for(policy_id: str) -> GraphPolicy:
    try:
        return POLICIES[policy_id]
    except KeyError:
        message = f"unknown graph policy {policy_id!r}; choose one of {sorted(POLICIES)}"
        raise UnknownPolicyError(message) from None

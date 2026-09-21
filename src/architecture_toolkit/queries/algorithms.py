"""Structural analyses over a policy view, mapped back to canonical IDs (CORE-30, CORE-31).

> Cycle, SCC, condensation and DAG analyses are used only under explicit graph semantics and retain
> mappings to canonical IDs.
> — CORE-30

"Under explicit graph semantics" is why every function here takes a `GraphPolicy`: "is this
acyclic" has no answer until somebody says which relationships count. Containment is acyclic by
rule; dependence is not, and a function that silently mixed the two would answer a question nobody
asked.

**The DAG algorithms check first and refuse rather than guess.** A topological ordering of a cyclic
graph does not exist, and NetworkX says so by raising; returning a partial ordering would be worse,
because a caller cannot tell a partial answer from a complete one.

**Three NetworkX results lose canonical identity, and each is repaired here rather than passed on.**
`simple_cycles` reports nodes and keeps no keys, so a cycle is expanded back to the relationships
that realize it — every realization, not one of them, because two parallel relationships closing a
cycle are two facts. `transitive_reduction` returns a plain `DiGraph`, so its edges are re-joined
to the relationships that back them. `transitive_closure` mints derived edges with an integer key
in the same space as a relationship ID, so closure results are returned as a record with no
relationship field at all.

This module reaches `ArchitectureGraph._view_for`, which is private to keep a NetworkX object off
the facade's public surface (CORE-24). A sibling in the same package reading it is the intended
arrangement: the graph owns the view, and the analyses own what is asked of it.
"""

from itertools import islice, product

from architecture_toolkit.domain.identifiers import ElementId, RelationshipId
from architecture_toolkit.queries import _nx
from architecture_toolkit.queries.errors import GraphError, PolicyError
from architecture_toolkit.queries.graph import ArchitectureGraph
from architecture_toolkit.queries.policy import CycleHandling, GraphPolicy, policy_for
from architecture_toolkit.queries.results import (
    ComponentResult,
    CondensationResult,
    CycleResult,
    ReachabilityEdge,
    ReductionEdge,
)

__all__ = [
    "ancestors",
    "components",
    "condensation",
    "cycles",
    "descendants",
    "find_containment_cycles",
    "generations",
    "is_acyclic",
    "minimum_equivalent",
    "reachability_closure",
]


def ancestors(
    graph: ArchitectureGraph, policy: GraphPolicy, element_id: ElementId
) -> frozenset[ElementId]:
    """Everything that reaches this object under the policy (CORE-30)."""
    return _nx.ancestors(graph._view_for(policy), _known(graph, element_id))


def descendants(
    graph: ArchitectureGraph, policy: GraphPolicy, element_id: ElementId
) -> frozenset[ElementId]:
    """Everything this object reaches under the policy (CORE-30)."""
    return _nx.descendants(graph._view_for(policy), _known(graph, element_id))


def is_acyclic(graph: ArchitectureGraph, policy: GraphPolicy) -> bool:
    """Whether the policy's view is a DAG. The precondition every function below states."""
    return _nx.is_dag(graph._view_for(policy))


def generations(graph: ArchitectureGraph, policy: GraphPolicy) -> tuple[tuple[ElementId, ...], ...]:
    """Topological generations, or `GraphError` where the view is not acyclic (CORE-30)."""
    view = graph._view_for(policy)
    if not _nx.is_dag(view):
        message = (
            f"{policy.policy_id} is cyclic in release {graph.release_id}; a topological ordering "
            "does not exist. Use `cycles` to see what closes."
        )
        raise GraphError(message)
    return _nx.topological_generations(view)


def cycles(graph: ArchitectureGraph, policy: GraphPolicy) -> tuple[CycleResult, ...]:
    """Every cycle in the policy's view, with the relationships that realize each one (CORE-30).

    Refuses a policy whose `cycle_handling` is not `REPORT`. CORE-30 says these analyses are used
    "only under explicit graph semantics", and a policy that never declared cycle semantics has not
    said what a cycle in its view would mean — `impact.structural` reaching itself through a
    containment loop is a different fact from `containment.descendants` doing so. The friction is
    the requirement, not a side effect of it.

    Bounded by `policy.max_results`, because a dense graph has a great many simple cycles and
    CORE-29's prohibition on unbounded enumeration is not limited to paths.
    """
    if policy.cycle_handling is not CycleHandling.REPORT:
        message = (
            f"{policy.policy_id} declares cycle_handling={policy.cycle_handling.value}; "
            "cycles are reported only under a policy that asks for them"
        )
        raise PolicyError(message)
    view = graph._view_for(policy)
    found: list[CycleResult] = []
    for nodes in islice(_nx.node_cycles(view, length_bound=policy.max_depth), policy.max_results):
        for realization in _realizations(view, nodes, policy.max_paths):
            found.append(
                CycleResult(
                    release_id=graph.release_id,
                    policy_id=policy.policy_id,
                    policy_version=policy.policy_version,
                    node_ids=nodes,
                    relationship_ids=realization,
                    length=len(nodes),
                )
            )
    return tuple(found)


def _realizations(
    view: _nx.Graph, nodes: tuple[ElementId, ...], limit: int
) -> tuple[tuple[RelationshipId, ...], ...]:
    """Every combination of relationships that closes this node cycle, capped.

    A cycle `a -> b -> a` where `a -> b` is realized by two relationships is two facts, not one
    with an arbitrary representative. `simple_cycles` cannot say that, so it is reconstructed.
    """
    steps = [
        _nx.edge_keys_between(view, nodes[index], nodes[(index + 1) % len(nodes)])
        for index in range(len(nodes))
    ]
    if any(not options for options in steps):
        return ()
    return tuple(islice(product(*steps), limit))


def components(graph: ArchitectureGraph, policy: GraphPolicy) -> tuple[ComponentResult, ...]:
    """Strongly connected components, largest first (CORE-30)."""
    view = graph._view_for(policy)
    found = [
        ComponentResult(
            release_id=graph.release_id,
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            element_ids=tuple(sorted(members)),
            is_cyclic=len(members) > 1 or _self_related(view, members),
        )
        for members in _nx.strongly_connected(view)
    ]
    return tuple(
        sorted(found, key=lambda component: (-len(component.element_ids), component.element_ids))
    )


def _self_related(view: _nx.Graph, members: frozenset[ElementId]) -> bool:
    """A single-element component is cyclic only through a self-relationship."""
    if len(members) != 1:
        return False
    only = next(iter(members))
    return bool(_nx.edge_keys_between(view, only, only))


def condensation(graph: ArchitectureGraph, policy: GraphPolicy) -> CondensationResult:
    """The SCC DAG, which is the shape an impact landscape is readable at (CORE-30)."""
    members, edges = _nx.condensation(graph._view_for(policy))
    view = graph._view_for(policy)
    return CondensationResult(
        release_id=graph.release_id,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        components=tuple(
            ComponentResult(
                release_id=graph.release_id,
                policy_id=policy.policy_id,
                policy_version=policy.policy_version,
                element_ids=tuple(sorted(group)),
                is_cyclic=len(group) > 1 or _self_related(view, group),
            )
            for group in members
        ),
        edges=edges,
    )


def reachability_closure(
    graph: ArchitectureGraph, policy: GraphPolicy
) -> tuple[ReachabilityEdge, ...]:
    """Who reaches whom, as derived analysis with no relationship identity (CORE-31)."""
    view = graph._view_for(policy)
    return tuple(
        ReachabilityEdge(source=source, target=target)
        for source, target in _nx.transitive_closure_pairs(view)
    )


def minimum_equivalent(graph: ArchitectureGraph, policy: GraphPolicy) -> tuple[ReductionEdge, ...]:
    """The transitive reduction, re-joined to the relationships that back each edge (CORE-31).

    A derived view of the model, never a replacement for it: the relationships the reduction drops
    still exist, and this says which relationships the ones it keeps correspond to.
    """
    view = graph._view_for(policy)
    if not _nx.is_dag(view):
        message = (
            f"{policy.policy_id} is cyclic in release {graph.release_id}; a transitive reduction "
            "is defined only for a DAG."
        )
        raise GraphError(message)
    return tuple(
        ReductionEdge(
            source=source,
            target=target,
            relationship_ids=_nx.edge_keys_between(view, source, target),
        )
        for source, target in _nx.transitive_reduction_pairs(view)
    )


def find_containment_cycles(graph: ArchitectureGraph) -> tuple[CycleResult, ...]:
    """The named analysis DATA-17 asks for: containment that closes on itself.

    `contains` declares the `acyclic` validation rule, so a published model should have none. This
    is what says so of a release that was written by something else, and it reports the
    relationships rather than only the objects — which the cross-record validator, using
    `graphlib`, cannot.
    """
    return cycles(graph, policy_for("containment.descendants"))


def _known(graph: ArchitectureGraph, element_id: ElementId) -> ElementId:
    if element_id not in set(graph.node_ids()):
        message = f"{element_id!r} is not in release {graph.release_id}"
        raise GraphError(message)
    return element_id

"""The release-derived graph, and the facade that is the only way to ask it anything.

CORE-22 through CORE-25 and DATA-16. Three decisions carry the weight.

**The graph is built from the query session, not beside it.** `build_graph` takes a
`ReleaseContext` and projects two tables out of the same DataFusion session the recipes run in. So
the M3 hard gate — "DataFusion and NetworkX read the same release" — is a property of there being
one session rather than an assertion about two code paths that happen to agree today. It also makes
CORE-23's "minimal traversal attributes only" the projection list rather than a convention: the
graph cannot carry a field the `SELECT` did not ask for.

**The rich records stay in the tables.** A node knows its kind and an edge knows its type and its
traversal context, and that is all. Anything else a caller needs is hydrated from the release, which
is what keeps the graph disposable: nothing is lost by throwing it away and rebuilding it.

**The raw `MultiDiGraph` never leaves.** `nx.freeze` is applied, but the CORE-25 tests show why it
is only a partial guard — attribute dictionaries stay mutable and a write through a filtered view
reaches the base graph. The real protection is that the handle is private and the attributes are
three strings nobody would want to mutate.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from datafusion import col

from architecture_toolkit.domain.identifiers import (
    ElementId,
    ModelId,
    RelationshipId,
    ReleaseId,
    SemanticDigest,
)
from architecture_toolkit.queries import _nx
from architecture_toolkit.queries.context import ReleaseContext
from architecture_toolkit.queries.errors import GraphError
from architecture_toolkit.queries.policy import Direction, GraphPolicy
from architecture_toolkit.queries.results import GraphPathResult, TraversalResult

__all__ = [
    "EDGE_COLUMNS",
    "NODE_COLUMNS",
    "ArchitectureGraph",
    "build_graph",
    "graph_from_rows",
]

NODE_COLUMNS: Final[tuple[str, ...]] = ("element_id", "kind_id")
"""The canonical object ID and its kind. `core.md` permits "minimal traversal attributes only"."""

EDGE_COLUMNS: Final[tuple[str, ...]] = (
    "source_element_id",
    "target_element_id",
    "relationship_id",
    "relationship_type_id",
    "context_id",
)
"""Endpoints, the canonical relationship ID that becomes the edge key, its type, and the traversal
context a policy filters on. Exactly the three attributes `docs/plans/w5-query-graph.md` names —
object kind, relationship type, selected traversal context — plus the identities."""

KIND = "kind_id"
RELATIONSHIP_TYPE = "relationship_type_id"
CONTEXT = "context_id"


@dataclass(frozen=True, slots=True)
class ArchitectureGraph:
    """A frozen, release-identified graph with query methods and no general mutation API (CORE-24).

    The facade carries its own identity because a path result has to say which release produced it,
    and a graph that could not name its release would make that provenance a caller's problem.
    """

    release_id: ReleaseId
    model_id: ModelId
    model_digest: SemanticDigest
    _graph: _nx.Graph

    @property
    def order(self) -> int:
        """How many canonical objects the graph holds."""
        return len(_nx.node_ids(self._graph))

    @property
    def size(self) -> int:
        """How many canonical relationships the graph holds, parallel ones counted separately."""
        return len(_nx.edges(self._graph))

    def node_ids(self) -> tuple[ElementId, ...]:
        return _nx.node_ids(self._graph)

    def relationship_ids(self) -> tuple[RelationshipId, ...]:
        return tuple(key for _, _, key in _nx.edges(self._graph))

    def edges(self) -> tuple[_nx.Edge, ...]:
        return _nx.edges(self._graph)

    def kind_of(self, element_id: ElementId) -> str:
        """The kind of one object, or `GraphError` for an object this release does not hold."""
        try:
            return str(_nx.node_attributes(self._graph, element_id)[KIND])
        except KeyError:
            message = f"{element_id!r} is not in release {self.release_id}"
            raise GraphError(message) from None

    def type_of(self, edge: _nx.Edge) -> str:
        return str(_nx.edge_attributes(self._graph, edge)[RELATIONSHIP_TYPE])

    def context_of(self, edge: _nx.Edge) -> str | None:
        return _nx.edge_attributes(self._graph, edge)[CONTEXT]

    def relationships_between(
        self, source: ElementId, target: ElementId
    ) -> tuple[RelationshipId, ...]:
        """Every relationship joining this pair — plural, because CORE-23 keeps parallel ones."""
        return _nx.edge_keys_between(self._graph, source, target)

    def is_frozen(self) -> bool:
        """CORE-25. True, and `tests/unit/test_graph_facade.py` says why that is not enough."""
        return _nx.is_frozen(self._graph)

    def _view_for(self, policy: GraphPolicy) -> _nx.Graph:
        """The policy's read-only filtered projection (CORE-27), never a copy of the graph.

        Private, because it is the one method that would hand a caller a NetworkX object and
        CORE-24 says the raw graph does not leave. The start object is not exempt from the filter
        either: a policy whose node kinds exclude the object being asked about has been pointed at
        the wrong question, and silently including it would hide that.
        """
        return _nx.view(
            self._graph,
            keep_node=lambda node: policy.permits_kind(self.kind_of(node)),
            keep_edge=lambda source, target, key: self._edge_permitted(
                policy, (source, target, key)
            ),
        )

    def _edge_permitted(self, policy: GraphPolicy, edge: _nx.Edge) -> bool:
        attributes = _nx.edge_attributes(self._graph, edge)
        return policy.permits_type(str(attributes[RELATIONSHIP_TYPE])) and policy.permits_context(
            attributes[CONTEXT]
        )

    def traverse(self, policy: GraphPolicy, start: ElementId) -> TraversalResult:
        """Every bounded, explainable path this policy reaches from `start` (CORE-28, CORE-29).

        The caps are handed to the generator rather than applied afterwards, so `max_paths` bounds
        the enumeration rather than trimming a list that was already built. One extra path is
        requested so the result can say it was truncated instead of quietly looking complete.
        """
        if start not in set(_nx.node_ids(self._graph)):
            message = f"{start!r} is not in release {self.release_id}"
            raise GraphError(message)
        view = self._view_for(policy)
        walk = view if policy.direction is Direction.FORWARD else _nx.reverse_view(view)
        if start not in set(_nx.node_ids(walk)):
            return self._empty(policy, start)

        reachable = _nx.descendants(walk, start)
        found = _nx.simple_edge_paths(
            walk, start, reachable, cutoff=policy.max_depth, limit=policy.max_paths + 1
        )
        truncated = len(found) > policy.max_paths
        paths = self._explain(policy, start, found[: policy.max_paths])
        limited, results_capped = self._cap(policy, paths)
        return TraversalResult(
            release_id=self.release_id,
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            start=start,
            classification=policy.classification,
            paths=limited,
            truncated=truncated or results_capped,
            limit_reached="max_paths" if truncated else ("max_results" if results_capped else None),
        )

    def reached(self, policy: GraphPolicy, start: ElementId) -> tuple[ElementId, ...]:
        """Just the objects, for a caller that wants the answer without the justification."""
        return self.traverse(policy, start).reached

    def _empty(self, policy: GraphPolicy, start: ElementId) -> TraversalResult:
        return TraversalResult(
            release_id=self.release_id,
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            start=start,
            classification=policy.classification,
        )

    def _explain(
        self, policy: GraphPolicy, start: ElementId, found: tuple[tuple[_nx.Edge, ...], ...]
    ) -> tuple[GraphPathResult, ...]:
        """Turn edge walks into results, stopping each at the first stop kind it passes.

        Truncating here rather than while enumerating is deliberate: `all_simple_edge_paths` has no
        stop-node parameter, and pre-filtering the view would remove a stop-kind object from the
        answer entirely instead of ending paths at it. Two walks can truncate to the same path, so
        the results are de-duplicated on their relationship sequence.
        """
        seen: dict[tuple[str, ...], GraphPathResult] = {}
        for walk in found:
            steps = self._until_stop(policy, walk)
            if not steps:
                continue
            relationship_ids = tuple(key for _, _, key in steps)
            if relationship_ids in seen:
                continue
            node_ids = (start, *(_step_target(step) for step in steps))
            seen[relationship_ids] = GraphPathResult(
                release_id=self.release_id,
                policy_id=policy.policy_id,
                policy_version=policy.policy_version,
                start=start,
                end=node_ids[-1],
                node_ids=node_ids,
                relationship_ids=relationship_ids,
                relationship_types=tuple(
                    self.type_of(self._as_stored(policy, step)) for step in steps
                ),
                depth=len(steps),
                classification=policy.classification,
            )
        return tuple(seen.values())

    def _until_stop(self, policy: GraphPolicy, walk: tuple[_nx.Edge, ...]) -> tuple[_nx.Edge, ...]:
        if not policy.stop_kinds:
            return walk
        kept: list[_nx.Edge] = []
        for step in walk:
            kept.append(step)
            if self.kind_of(_step_target(step)) in policy.stop_kinds:
                break
        return tuple(kept)

    def _as_stored(self, policy: GraphPolicy, step: _nx.Edge) -> _nx.Edge:
        """The edge as the graph holds it, so its attributes can be read.

        A reverse traversal walks a reversed view, where a step reads `(target, source, key)`. The
        relationship ID is the same either way; the attributes live on the stored orientation.
        """
        source, target, key = step
        return (
            (source, target, key)
            if policy.direction is Direction.FORWARD
            else (
                target,
                source,
                key,
            )
        )

    def _cap(
        self, policy: GraphPolicy, paths: tuple[GraphPathResult, ...]
    ) -> tuple[tuple[GraphPathResult, ...], bool]:
        """Bound the number of distinct objects reported, not only the number of paths."""
        kept: list[GraphPathResult] = []
        endpoints: dict[ElementId, None] = {}
        for path in paths:
            if path.end not in endpoints and len(endpoints) == policy.max_results:
                return tuple(kept), True
            endpoints.setdefault(path.end, None)
            kept.append(path)
        return tuple(kept), False


def build_graph(context: ReleaseContext) -> ArchitectureGraph:
    """Project one release into a disposable graph (CORE-22, CORE-23, DATA-16).

    Two bounded projections out of the session the recipes use, through the expression API rather
    than SQL so a side-qualified table name never has to be interpolated into a query string.
    """
    nodes = context.table("elements").select(*(col(name) for name in NODE_COLUMNS))
    relationships = context.table("relationships").select(*(col(name) for name in EDGE_COLUMNS))
    return graph_from_rows(
        release_id=context.scope.release_id,
        model_id=context.scope.model_id,
        model_digest=context.scope.model_digest,
        nodes=(
            (str(row["element_id"]), str(row[KIND])) for row in nodes.to_arrow_table().to_pylist()
        ),
        edges=(
            (
                str(row["source_element_id"]),
                str(row["target_element_id"]),
                str(row["relationship_id"]),
                str(row[RELATIONSHIP_TYPE]),
                _optional(row[CONTEXT]),
            )
            for row in relationships.to_arrow_table().to_pylist()
        ),
    )


def graph_from_rows(
    *,
    release_id: ReleaseId,
    model_id: ModelId,
    model_digest: SemanticDigest,
    nodes: Iterable[tuple[ElementId, str]],
    edges: Iterable[tuple[ElementId, ElementId, RelationshipId, str, str | None]],
) -> ArchitectureGraph:
    """Assemble the graph from already-projected rows.

    Separate from `build_graph` so the projection can be tested without a store, and so the one
    place that decides what a node and an edge carry is not also the place that talks to
    DataFusion.
    """
    node_rows: list[tuple[ElementId, _nx.Data]] = [
        (element_id, {KIND: kind_id}) for element_id, kind_id in nodes
    ]
    element_ids = {element_id for element_id, _ in node_rows}
    graph = _nx.build(
        {"release_id": release_id, "model_id": model_id},
        node_rows,
        (
            (source, target, relationship_id, {RELATIONSHIP_TYPE: type_id, CONTEXT: context_id})
            for source, target, relationship_id, type_id, context_id in edges
        ),
    )
    invented = sorted(set(_nx.node_ids(graph)) - element_ids)
    if invented:
        message = (
            f"release {release_id} has relationship endpoints that are not elements: {invented}"
        )
        raise GraphError(message)
    return ArchitectureGraph(
        release_id=release_id,
        model_id=model_id,
        model_digest=model_digest,
        _graph=_nx.freeze(graph),
    )


def _step_target(step: _nx.Edge) -> ElementId:
    """Where a step arrives, in traversal order rather than in stored orientation.

    A free function rather than a method that took a policy and deleted it: the answer does not
    depend on the policy, and a signature that says it does is a signature that lies.
    """
    return step[1]


def _optional(value: object) -> str | None:
    return None if value is None else str(value)

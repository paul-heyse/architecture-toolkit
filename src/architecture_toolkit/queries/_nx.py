"""The only module in the toolkit that imports NetworkX (CORE-22, CORE-24, DATA-16).

The same shape as `storage/delta.py`: one module owns a third-party boundary, a structural rule
keeps it that way (`rules/graph-networkx-only-in-adapter.yml`, plus a layering test because
`ast-grep test` cannot exercise an `ignores` glob), and a change of graph library is one module
rather than a search.

**There is a second reason here, and it is the stronger one.** `types-networkx` is version-matched
to the locked networkx, but it is imprecise about the thing this toolkit depends on most: multigraph
edge keys. `MultiDiGraph` takes no key type parameter, `subgraph_view`'s `filter_edge` is declared
`Callable[[_Node, _Node, int], bool]`, and `all_simple_edge_paths` is declared to yield pairs. Our
keys are canonical relationship IDs — strings — and CORE-23 makes that load-bearing. Under
`pyrefly coverage check --strict --fail-under 100` that imprecision has to be answered somewhere,
and answering it once here is better than answering it at every call site. Every suppression below
is narrow, is paired with an entry in `tests/qualification/test_networkx_stub.py` asserting the
runtime truth, and disappears when the stub is corrected.

Nothing NetworkX-shaped escapes this module except the graph handle itself, which stays inside
`queries/`. Every query returns tuples and frozensets of canonical IDs, which is what makes
CORE-30's "retain mappings to canonical IDs" a property of the signatures rather than a convention.
"""

from collections.abc import Callable, Iterable, Iterator, Mapping
from itertools import islice

import networkx as nx

__all__ = [
    "Attributes",
    "Edge",
    "EdgeKey",
    "Graph",
    "NodeId",
    "ancestors",
    "build",
    "condensation",
    "descendants",
    "edge_attributes",
    "edge_keys_between",
    "edges",
    "find_one_cycle",
    "freeze",
    "graph_attributes",
    "is_dag",
    "is_frozen",
    "node_attributes",
    "node_cycles",
    "node_ids",
    "simple_edge_paths",
    "strongly_connected",
    "topological_generations",
    "transitive_closure_pairs",
    "transitive_reduction_pairs",
    "view",
]

type NodeId = str
"""A canonical object ID (CORE-23)."""

type EdgeKey = str
"""A canonical relationship ID (CORE-23). Parallel relationships stay distinct because of it."""

type Edge = tuple[NodeId, NodeId, EdgeKey]
type Attributes = Mapping[str, str | None]
type Data = dict[str, str | None]
type Graph = nx.MultiDiGraph[NodeId, Data, Data]


def build(
    attributes: Attributes,
    nodes: Iterable[tuple[NodeId, Data]],
    edges_to_add: Iterable[tuple[NodeId, NodeId, EdgeKey, Data]],
) -> Graph:
    """One graph from one release's rows, in two library calls rather than an insertion loop.

    Nodes first and edges second on purpose: `add_edges_from` silently invents a node for an
    endpoint it has not seen, so the caller can compare the node count before and after and refuse
    a model whose relationships point at elements that are not there. `read_model` re-runs only
    record-local validators, so that is a real possibility rather than a defensive one.
    """
    graph: Graph = nx.MultiDiGraph()
    graph.graph.update(attributes)
    graph.add_nodes_from(nodes)
    # Divergence: `types-networkx` omits the multigraph four-tuple `(u, v, key, data)` from
    # `_EdgePlus`, although it is the documented way to add keyed edges in bulk. Pinned by
    # `tests/qualification/test_networkx_stub.py`.
    graph.add_edges_from(edges_to_add)  # pyrefly: ignore[bad-argument-type]
    return graph


def freeze(graph: Graph) -> Graph:
    """Refuse structural mutation. Only a partial guard — see CORE-25 and the stub qualification."""
    nx.freeze(graph)
    return graph


def is_frozen(graph: Graph) -> bool:
    return nx.is_frozen(graph)


def graph_attributes(graph: Graph) -> Attributes:
    return dict(graph.graph)


def node_ids(graph: Graph) -> tuple[NodeId, ...]:
    return tuple(graph.nodes)


def node_attributes(graph: Graph, node: NodeId) -> Attributes:
    return dict(graph.nodes[node])


def edges(graph: Graph) -> tuple[Edge, ...]:
    return tuple((source, target, str(key)) for source, target, key in graph.edges(keys=True))


def edge_attributes(graph: Graph, edge: Edge) -> Attributes:
    return dict(graph.edges[edge])


def edge_keys_between(graph: Graph, source: NodeId, target: NodeId) -> tuple[EdgeKey, ...]:
    """Every relationship that joins this pair, not an arbitrary one of them.

    The plural is the point. `simple_cycles` and `transitive_reduction` both report node pairs
    rather than edges, so recovering canonical relationship IDs from them means recovering *all*
    of the relationships that realize a step, which is what CORE-23's parallel-edge promise means
    once a result has to be explained.
    """
    return tuple(
        str(key) for _, target_id, key in graph.out_edges(source, keys=True) if target_id == target
    )


def view(
    graph: Graph,
    *,
    keep_node: Callable[[NodeId], bool],
    keep_edge: Callable[[NodeId, NodeId, EdgeKey], bool],
) -> Graph:
    """A read-only filtered projection (CORE-27), never a copy.

    The returned view already reports `nx.is_frozen` as true, so no `freeze` call is needed here.
    """
    # Divergence: the stub declares a multigraph `filter_edge` as taking an `int` key, because
    # `MultiDiGraph` carries no key type parameter. CORE-23 makes ours a relationship ID.
    return nx.subgraph_view(  # pyrefly: ignore[no-matching-overload]
        graph, filter_node=keep_node, filter_edge=keep_edge
    )


def simple_edge_paths(
    graph: Graph,
    source: NodeId,
    targets: Iterable[NodeId],
    *,
    cutoff: int,
    limit: int,
) -> tuple[tuple[Edge, ...], ...]:
    """Bounded path enumeration (CORE-29), capped before anything is materialized.

    `all_simple_edge_paths` yields lazily, so `islice` stops the generator rather than truncating a
    list that was already built. That is the difference between a cap and a filter, and on a dense
    graph it is the difference between a bounded query and one that never returns.
    """
    found = nx.all_simple_edge_paths(graph, source, list(targets), cutoff=cutoff)
    # Divergence: the stub declares the yield as pairs; a multigraph yields `(u, v, key)` triples.
    return tuple(
        tuple((str(u), str(v), str(k)) for u, v, k in path)  # pyrefly: ignore[not-iterable, bad-unpacking]
        for path in islice(found, limit)
    )


def ancestors(graph: Graph, node: NodeId) -> frozenset[NodeId]:
    return frozenset(str(found) for found in nx.ancestors(graph, node))


def descendants(graph: Graph, node: NodeId) -> frozenset[NodeId]:
    return frozenset(str(found) for found in nx.descendants(graph, node))


def is_dag(graph: Graph) -> bool:
    return nx.is_directed_acyclic_graph(graph)


def topological_generations(graph: Graph) -> tuple[tuple[NodeId, ...], ...]:
    return tuple(
        tuple(sorted(str(node) for node in generation))
        for generation in nx.topological_generations(graph)
    )


def node_cycles(graph: Graph, *, length_bound: int | None = None) -> Iterator[tuple[NodeId, ...]]:
    """Cycles as **node** sequences, which is all NetworkX reports for a multigraph.

    `simple_cycles` does not say which of two parallel relationships closed the cycle. Recovering
    that is `edge_keys_between`'s job, and it is why `queries/algorithms.py` reports every
    realization of a cycle rather than picking one.
    """
    for cycle in nx.simple_cycles(graph, length_bound=length_bound):
        yield tuple(str(node) for node in cycle)


def find_one_cycle(graph: Graph, source: NodeId | None = None) -> tuple[Edge, ...]:
    """One cycle *with* its edge keys, or `()` where the graph is acyclic.

    The complement of `node_cycles`: `find_cycle` keeps the keys but finds only one cycle, while
    `simple_cycles` finds them all and keeps none.
    """
    try:
        found = nx.find_cycle(graph, source=source)
    except nx.NetworkXNoCycle:
        return ()
    return tuple((str(u), str(v), str(k)) for u, v, k in found)


def strongly_connected(graph: Graph) -> tuple[frozenset[NodeId], ...]:
    return tuple(
        frozenset(str(node) for node in component)
        for component in nx.strongly_connected_components(graph)
    )


def condensation(graph: Graph) -> tuple[tuple[frozenset[NodeId], ...], tuple[tuple[int, int], ...]]:
    """The SCC DAG: component membership by index, and the edges between components."""
    collapsed = nx.condensation(graph)
    members = tuple(
        frozenset(str(node) for node in collapsed.nodes[index]["members"])
        for index in sorted(collapsed.nodes)
    )
    return members, tuple(sorted(collapsed.edges))


def transitive_closure_pairs(graph: Graph) -> tuple[tuple[NodeId, NodeId], ...]:
    """Reachability as node pairs, deliberately without keys (CORE-31).

    `nx.transitive_closure` mints its derived edges with the integer key `0`, which would sit in
    the same key space as canonical relationship IDs. Returning pairs makes a closure edge
    impossible to mistake for a relationship.
    """
    return tuple(sorted((str(u), str(v)) for u, v in nx.transitive_closure(graph).edges()))


def transitive_reduction_pairs(graph: Graph) -> tuple[tuple[NodeId, NodeId], ...]:
    """The minimum equivalent DAG as node pairs. Requires an acyclic graph; the caller checks."""
    return tuple(sorted((str(u), str(v)) for u, v in nx.transitive_reduction(graph).edges()))

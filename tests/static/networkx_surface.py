"""The NetworkX surface `queries/_nx.py` exposes, checked by the type checker (CORE-53, CORE-58).

The companion to `tests/qualification/test_networkx_stub.py`, in the same two-direction shape
`tests/static/pyarrow_surface.py` established. That module asserts the runtime truth and pins the
stub's declared text; this one asserts that the adapter's own signatures hold, so a `types-networkx`
release that changes a return type fails `pyrefly check` here rather than somewhere downstream.

It matters more for this adapter than for most. `_nx.py` carries three narrow suppressions, and a
suppression is a place where the checker has been told to stop looking — so the *outputs* of the
functions containing them have to be pinned somewhere the checker is still looking. This is that
place. Every value below is a tuple, frozenset or scalar of canonical IDs; none of them is a
NetworkX object, which is the property that makes CORE-30's "retain mappings to canonical IDs"
structural.

Not collected by pytest: the filename does not start with `test_`.
"""

from collections.abc import Iterator
from typing import assert_type

from architecture_toolkit.queries import _nx

_graph: _nx.Graph = _nx.build(
    {"release_id": "rel-0001"},
    (("a", {"kind_id": "software.system"}), ("b", {"kind_id": "software.component"})),
    (
        ("a", "b", "rel-1", {"relationship_type_id": "contains", "context_id": None}),
        ("a", "b", "rel-2", {"relationship_type_id": "depends_on", "context_id": None}),
        ("b", "a", "rel-3", {"relationship_type_id": "depends_on", "context_id": None}),
    ),
)

# --- identity and inspection ------------------------------------------------------------------
assert_type(_nx.freeze(_graph), _nx.Graph)
assert_type(_nx.is_frozen(_graph), bool)
assert_type(_nx.graph_attributes(_graph), _nx.Attributes)
assert_type(_nx.node_ids(_graph), tuple[str, ...])
assert_type(_nx.node_attributes(_graph, "a"), _nx.Attributes)
assert_type(_nx.edges(_graph), tuple[_nx.Edge, ...])
assert_type(_nx.edge_attributes(_graph, ("a", "b", "rel-1")), _nx.Attributes)
assert_type(_nx.edge_keys_between(_graph, "a", "b"), tuple[str, ...])

# --- policy views (CORE-27) -------------------------------------------------------------------
_view: _nx.Graph = _nx.view(
    _graph,
    keep_node=lambda node: node != "c",
    keep_edge=lambda source, target, key: key != "rel-3",
)
assert_type(_view, _nx.Graph)

# --- bounded traversal (CORE-29) --------------------------------------------------------------
assert_type(
    _nx.simple_edge_paths(_graph, "a", ["b"], cutoff=3, limit=10),
    tuple[tuple[_nx.Edge, ...], ...],
)

# --- structural algorithms (CORE-30, CORE-31) -------------------------------------------------
assert_type(_nx.ancestors(_graph, "b"), frozenset[str])
assert_type(_nx.descendants(_graph, "a"), frozenset[str])
assert_type(_nx.is_dag(_graph), bool)
assert_type(_nx.topological_generations(_view), tuple[tuple[str, ...], ...])
assert_type(_nx.node_cycles(_graph), Iterator[tuple[str, ...]])
assert_type(_nx.find_one_cycle(_graph), tuple[_nx.Edge, ...])
assert_type(_nx.strongly_connected(_graph), tuple[frozenset[str], ...])
assert_type(
    _nx.condensation(_graph), tuple[tuple[frozenset[str], ...], tuple[tuple[int, int], ...]]
)
# Pairs, never keyed edges: a derived reachability edge is not a canonical relationship (CORE-31).
assert_type(_nx.transitive_closure_pairs(_view), tuple[tuple[str, str], ...])
assert_type(_nx.transitive_reduction_pairs(_view), tuple[tuple[str, str], ...])

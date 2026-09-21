"""`types-networkx` is qualified against the pinned networkx, not trusted (CORE-53, CORE-55).

The stub is version-matched to the lock, so unlike `pyarrow-stubs` it is not stale. It is
*imprecise*, in one place that this toolkit depends on more than any other: `MultiDiGraph` carries
no key type parameter, so every declaration involving a multigraph edge key had to pick something,
and it picked `int`. CORE-23 makes ours a canonical relationship ID.

That imprecision is answered in `queries/_nx.py` by three narrow suppressions. This module is the
other half. Each divergence is asserted twice — the runtime truth, so the workaround is known to be
necessary, and the stub's own declared text, so a corrected stub fails here and the suppression is
removed deliberately rather than left behind. `tests/static/networkx_surface.py` pins what the
adapter returns, so a stub regression that changes a return type fails the type checker there.
"""

import ast
import importlib
from pathlib import Path

import networkx as nx
import pytest

from architecture_toolkit.queries import _nx

STUB_ROOT = Path(nx.__file__).resolve().parent.parent / "networkx-stubs"


def graph() -> _nx.Graph:
    """Two parallel relationships and a cycle: every divergence needs one or the other."""
    return _nx.build(
        {"release_id": "rel-0001"},
        (("a", {"kind_id": "software.system"}), ("b", {"kind_id": "software.component"})),
        (
            ("a", "b", "rel-1", {"relationship_type_id": "contains", "context_id": None}),
            ("a", "b", "rel-2", {"relationship_type_id": "depends_on", "context_id": None}),
            ("b", "a", "rel-3", {"relationship_type_id": "depends_on", "context_id": None}),
        ),
    )


def stub_text(relative: str) -> str:
    path = STUB_ROOT / relative
    if not path.is_file():
        pytest.skip(f"types-networkx ships no {relative}")
    return path.read_text(encoding="utf-8")


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("CORE-53")
def test_the_stub_package_is_installed_where_the_checker_finds_it() -> None:
    assert STUB_ROOT.is_dir(), f"types-networkx not installed beside networkx at {STUB_ROOT}"
    assert (STUB_ROOT / "classes" / "multidigraph.pyi").is_file()


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("CORE-23", "DATA-16")
def test_a_relationship_id_survives_as_an_edge_key() -> None:
    """The property CORE-23 is built on, and the reason the `int` in the stub is wrong."""
    built = graph()

    assert _nx.edge_keys_between(built, "a", "b") == ("rel-1", "rel-2")
    assert len(_nx.edges(built)) == 3


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("CORE-53", "CORE-55")
def test_the_stub_declares_a_multigraph_edge_filter_with_an_integer_key() -> None:
    """Divergence 1, and the reason for the `subgraph_view` suppression in `queries/_nx.py`.

    When `types-networkx` gives `MultiDiGraph` a key parameter, or widens this to `Hashable`, this
    assertion fails — and the suppression goes with it.
    """
    declared = stub_text("classes/graphviews.pyi")

    assert "filter_edge: Callable[[_Node, _Node, int], bool] = ...," in declared


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("CORE-53", "CORE-55")
def test_the_stub_declares_simple_edge_paths_as_yielding_pairs() -> None:
    """Divergence 2. A multigraph yields `(source, target, key)` triples, asserted below."""
    declared = stub_text("algorithms/simple_paths.pyi")

    assert "list[_Node] | list[tuple[_Node, _Node]]" in declared


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("CORE-29", "CORE-53")
def test_a_multigraph_yields_edge_paths_as_triples_not_pairs() -> None:
    """The runtime truth behind divergence 2, and CORE-29's parallel-edge promise in one place."""
    found = _nx.simple_edge_paths(graph(), "a", ["b"], cutoff=3, limit=10)

    assert all(len(step) == 3 for path in found for step in path)
    assert {path[0][2] for path in found} == {"rel-1", "rel-2"}, (
        "two parallel relationships must produce two distinct paths"
    )


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("CORE-53", "CORE-55")
def test_the_stub_omits_the_multigraph_four_tuple_edge_form() -> None:
    """Divergence 3, and the reason for the `add_edges_from` suppression.

    `(u, v, key, data)` is the documented bulk form for a multigraph; `_EdgePlus` stops at three.
    """
    declared = stub_text("classes/graph.pyi")

    assert "_EdgePlus" in declared
    assert "_Node, _Node, Hashable, " not in declared


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("CORE-25")
def test_a_filtered_view_is_already_frozen_and_is_still_not_a_deep_guard() -> None:
    """CORE-25 measured rather than restated.

    `subgraph_view` returns a view NetworkX already reports as frozen, so no `freeze` call is
    needed on it — and it is still only a structural guard, because the attribute dictionaries are
    shared with the base graph. That is why the facade, and not `freeze`, is the real protection.
    """
    built = graph()
    view = _nx.view(built, keep_node=lambda node: True, keep_edge=lambda u, v, key: key != "rel-3")

    assert _nx.is_frozen(view)
    assert len(_nx.edges(view)) == 2

    with pytest.raises(nx.NetworkXError):
        view.add_node("c")

    view.nodes["a"]["kind_id"] = "mutated through the view"
    assert _nx.node_attributes(built, "a")["kind_id"] == "mutated through the view"


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("CORE-30")
def test_simple_cycles_reports_nodes_and_find_cycle_reports_keys() -> None:
    """Why `queries/algorithms.py` expands a cycle back to relationship IDs itself.

    `simple_cycles` finds every cycle and keeps no keys; `find_cycle` keeps the keys and finds one
    cycle. Neither alone answers CORE-28's "ordered relationship IDs" for every cycle.
    """
    built = graph()

    cycles = list(_nx.node_cycles(built))
    assert cycles
    members = {node for cycle in cycles for node in cycle}
    assert members == {"a", "b"}, "these are node ids; no relationship id appears"

    one = _nx.find_one_cycle(built)
    assert {step[2] for step in one} <= {"rel-1", "rel-2", "rel-3"}


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("CORE-31")
def test_a_closure_edge_is_not_a_relationship_and_a_reduction_keeps_no_keys() -> None:
    """The hazard CORE-31 names, measured.

    `transitive_closure` mints derived edges with the integer key `0`, in the same key space as
    canonical relationship IDs; `transitive_reduction` returns a `DiGraph` and drops keys
    altogether. Both are why `queries/_nx.py` returns node pairs from each.
    """
    acyclic = _nx.build(
        {},
        (("a", {}), ("b", {}), ("c", {})),
        (("a", "b", "rel-1", {}), ("b", "c", "rel-2", {})),
    )

    assert ("a", "c") in _nx.transitive_closure_pairs(acyclic)
    assert _nx.transitive_reduction_pairs(acyclic) == (("a", "b"), ("b", "c"))

    # Divergence 4, and the only suppression outside `queries/_nx.py`: the stub declares
    # `transitive_closure` as returning `Graph`, whose `edges` view takes no `keys` argument. At
    # run time a MultiDiGraph goes in and a MultiDiGraph comes out — which is the whole point being
    # asserted here, so the assertion has to reach for the keys the declaration says are absent.
    closure = nx.transitive_closure(acyclic)
    minted = {
        (source, target, key)
        for source, target, key in closure.edges(keys=True)  # pyrefly: ignore[no-matching-overload]
    }
    assert ("a", "c", 0) in minted, (
        "a derived edge is minted with an integer key, in the same key space as a relationship id; "
        "that is why closure results are returned as pairs"
    )
    assert not nx.transitive_reduction(acyclic).is_multigraph()


def declared_names(path: Path) -> set[str]:
    """Top-level classes and functions a stub module declares, ignoring re-exports."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and not node.name.startswith("_")
    }


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("CORE-53")
@pytest.mark.parametrize(
    ("stub", "module_name"),
    [
        ("classes/graphviews.pyi", "networkx.classes.graphviews"),
        ("classes/function.pyi", "networkx.classes.function"),
        ("algorithms/dag.pyi", "networkx.algorithms.dag"),
        ("algorithms/cycles.pyi", "networkx.algorithms.cycles"),
        ("algorithms/simple_paths.pyi", "networkx.algorithms.simple_paths"),
    ],
)
def test_every_name_the_stub_declares_still_exists_at_run_time(stub: str, module_name: str) -> None:
    """Staleness in the other direction: a stub may declare what the runtime has removed."""
    path = STUB_ROOT / stub
    if not path.is_file():
        pytest.skip(f"types-networkx ships no {stub}")
    runtime = importlib.import_module(module_name)

    missing = sorted(name for name in declared_names(path) if not hasattr(runtime, name))
    assert not missing, f"{module_name} no longer has: {missing}"

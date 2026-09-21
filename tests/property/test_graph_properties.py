"""Invariants a bounded traversal must hold for any model, not only the example (CORE-28, CORE-29).

The integration tests assert what the traversals answer for one carefully-built release. These
assert the properties that must hold whatever the model is — that a cap is a cap, that every id in
a result is an id the model declares, and that a reported path is a walk somebody could follow.

`tests/strategies.coherent_models` deliberately generates models with cycles, self-loops, parallel
edges and impermissible endpoint kinds. That is the point: a traversal has to be bounded on a graph
nobody curated, and the awkward shapes are exactly where an off-by-one in a cap lives.

**A property that examines nothing proves nothing.** Many generated models reach nowhere under a
given policy, so every loop below could run zero times and the test would still pass. Two things
answer that. `event()` records whether any path was examined, so `--hypothesis-show-statistics`
shows the split rather than leaving it to be assumed — `ARCH-TOOL-CORE-001` §7G names `event()` for
exactly this. And the per-path invariant lives in `walk_is_followable`, which a deterministic test
at the bottom of this module exercises on a graph with known paths, so the check is proven to work
at least once rather than only proven not to have fired.
"""

from collections.abc import Mapping

import pytest
from hypothesis import event, given

from architecture_toolkit.domain.identifiers import ElementId, RelationshipId
from architecture_toolkit.domain.model import Model
from architecture_toolkit.queries.graph import ArchitectureGraph, graph_from_rows
from architecture_toolkit.queries.policy import POLICIES, policy_for
from architecture_toolkit.queries.results import GraphPathResult
from tests.strategies import coherent_models

DIGEST = "sha256:" + "0" * 64

type Endpoints = Mapping[RelationshipId, tuple[ElementId, ElementId]]


def graph_of(model: Model) -> ArchitectureGraph:
    return graph_from_rows(
        release_id="rel-0001",
        model_id=model.model_id,
        model_digest=DIGEST,
        nodes=((element.element_id, element.kind_id) for element in model.elements),
        edges=(
            (
                relationship.source_element_id,
                relationship.target_element_id,
                relationship.relationship_id,
                relationship.relationship_type_id,
                relationship.context_id,
            )
            for relationship in model.relationships
        ),
    )


def endpoints_of(model: Model) -> Endpoints:
    return {
        relationship.relationship_id: (
            relationship.source_element_id,
            relationship.target_element_id,
        )
        for relationship in model.relationships
    }


def walk_is_followable(path: GraphPathResult, endpoints: Endpoints) -> bool:
    """Whether every step's relationship actually joins the two nodes the path puts around it.

    Orientation-agnostic, because direction is the policy's: a reverse traversal reports the same
    relationship walked the other way. Compared as an **equality of pairs**, not a containment —
    a subset check would accept a step whose two nodes are the same while the relationship joins
    two different elements, which is the defect this function exists to catch.
    """
    if len(path.node_ids) != len(path.relationship_ids) + 1:
        return False
    if len(path.relationship_types) != len(path.relationship_ids):
        return False
    for index, relationship_id in enumerate(path.relationship_ids):
        stored = endpoints.get(relationship_id)
        if stored is None:
            return False
        if {path.node_ids[index], path.node_ids[index + 1]} != set(stored):
            return False
    return True


def observe(examined: int) -> None:
    event(f"paths examined: {'some' if examined else 'none'}")


@pytest.mark.property
@pytest.mark.slow
@pytest.mark.requirement("CORE-29")
@given(model=coherent_models())
def test_no_traversal_ever_exceeds_the_caps_its_policy_declares(model: Model) -> None:
    graph = graph_of(model)
    tight = [
        policy.model_validate(dict(policy) | {"max_depth": 2, "max_paths": 3, "max_results": 2})
        for policy in POLICIES.values()
    ]
    examined = 0

    for policy in tight:
        for element in model.elements:
            result = graph.traverse(policy, element.element_id)
            examined += len(result.paths)
            assert len(result.paths) <= policy.max_paths
            assert len(set(result.reached)) <= policy.max_results
            assert all(path.depth <= policy.max_depth for path in result.paths)
    observe(examined)


@pytest.mark.property
@pytest.mark.slow
@pytest.mark.requirement("CORE-28", "CORE-30")
@given(model=coherent_models())
def test_every_id_in_a_result_is_one_the_model_declares(model: Model) -> None:
    """CORE-30's "retain mappings to canonical IDs", as a property rather than an example."""
    graph = graph_of(model)
    element_ids = {element.element_id for element in model.elements}
    relationship_ids = set(endpoints_of(model))
    examined = 0

    for policy in POLICIES.values():
        for element in model.elements:
            for path in graph.traverse(policy, element.element_id).paths:
                examined += 1
                assert set(path.node_ids) <= element_ids
                assert set(path.relationship_ids) <= relationship_ids
                assert path.start == element.element_id
                assert path.end == path.node_ids[-1]
    observe(examined)


@pytest.mark.property
@pytest.mark.slow
@pytest.mark.requirement("CORE-28")
@given(model=coherent_models())
def test_a_reported_path_is_a_walk_somebody_could_follow(model: Model) -> None:
    """The justification has to justify: each step's relationship joins consecutive nodes."""
    graph = graph_of(model)
    endpoints = endpoints_of(model)
    examined = 0

    for policy in POLICIES.values():
        for element in model.elements:
            for path in graph.traverse(policy, element.element_id).paths:
                examined += 1
                assert walk_is_followable(path, endpoints)
    observe(examined)


@pytest.mark.property
@pytest.mark.slow
@pytest.mark.requirement("CORE-27")
@given(model=coherent_models())
def test_a_traversal_only_ever_follows_the_types_its_policy_allows(model: Model) -> None:
    graph = graph_of(model)
    examined = 0

    for policy in POLICIES.values():
        for element in model.elements:
            for path in graph.traverse(policy, element.element_id).paths:
                examined += 1
                assert set(path.relationship_types) <= set(policy.allowed_relationship_types)
    observe(examined)


# -- the deterministic companion -----------------------------------------------------------------
# In the property module rather than beside it, because the value is that both use one definition
# of "followable". A helper the properties call and nothing else proves is a helper that can rot
# into always returning True.

CHAIN = (
    ("sys-a", "software.system"),
    ("cmp-b", "software.component"),
    ("api-c", "software.interface"),
)
EDGES = (
    ("sys-a", "cmp-b", "rel-1", "contains", None),
    ("cmp-b", "api-c", "rel-2", "exposes", None),
)


def chain() -> ArchitectureGraph:
    return graph_from_rows(
        release_id="rel-0001",
        model_id="sample-service",
        model_digest=DIGEST,
        nodes=CHAIN,
        edges=EDGES,
    )


def chain_endpoints() -> Endpoints:
    return {key: (source, target) for source, target, key, _, _ in EDGES}


@pytest.mark.unit
@pytest.mark.requirement("CORE-28")
def test_the_walk_check_accepts_a_real_path() -> None:
    """The positive control the properties cannot guarantee they ever ran."""
    result = chain().traverse(policy_for("impact.structural"), "sys-a")
    endpoints = chain_endpoints()

    assert result.paths, "the fixture must produce paths, or nothing below is exercised"
    assert all(walk_is_followable(path, endpoints) for path in result.paths)
    assert {path.relationship_ids for path in result.paths} == {("rel-1",), ("rel-1", "rel-2")}


@pytest.mark.unit
@pytest.mark.requirement("CORE-28")
@pytest.mark.parametrize(
    ("broken", "why"),
    [
        ({"node_ids": ("sys-a", "sys-a", "api-c")}, "a step that stays on one node"),
        ({"relationship_ids": ("rel-1", "rel-9")}, "a relationship the model does not declare"),
        ({"node_ids": ("sys-a", "api-c", "cmp-b")}, "the right relationships in the wrong order"),
        ({"relationship_types": ("contains",)}, "fewer types than relationships"),
    ],
)
def test_the_walk_check_rejects_a_path_that_does_not_follow(
    broken: dict[str, object], why: str
) -> None:
    """The negative controls. A guard that cannot fail is not a guard.

    The first case is the one that matters most: it is exactly what the hedged `or` this module
    used to carry would have admitted.
    """
    result = chain().traverse(policy_for("impact.structural"), "sys-a")
    genuine = next(path for path in result.paths if path.depth == 2)
    damaged = genuine.model_validate(dict(genuine) | broken)

    assert not walk_is_followable(damaged, chain_endpoints()), why

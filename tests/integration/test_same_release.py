"""The M3 hard gate: DataFusion and NetworkX read the same release.

> DataFusion and NetworkX read the same release.
> — `docs/agent-handoff.md`, M3 hard gates

The design makes that hard to get wrong rather than merely asserted: `build_graph` projects its
nodes and edges out of the same `SessionContext` the recipes run in, so there is one release
selection and not two that happen to agree. These tests are what stops that from silently becoming
untrue — and, because "agree on the current release" is the easy half, the assertions that carry
weight are the ones about an *older* release, where a surface that resolved latest would pass the
first check and fail these.
"""

import pyarrow as pa
import pytest

from architecture_toolkit.domain.model import Model, Relationship
from architecture_toolkit.queries.context import ComparisonContext, ReleaseContext
from architecture_toolkit.queries.errors import GraphError
from architecture_toolkit.queries.graph import _assemble, build_graph
from architecture_toolkit.releases.store import ReleaseStore
from tests.integration.conftest import Publisher, rename_first_element

USABLE = ("materialized", "dataset", "stream")


def with_parallel_relationship(model: Model) -> Model:
    """A second relationship between a pair that already has one (CORE-23).

    `system-1 depends_on component-1` alongside `system-1 contains component-1`: both endpoint
    kinds are permitted by the baseline profile, so this is a model that publishes rather than a
    fixture that only exists in memory.
    """
    extra = Relationship(
        relationship_id="rel-9",
        model_id=model.model_id,
        relationship_type_id="depends_on",
        source_element_id="system-1",
        target_element_id="component-1",
    )
    return model.model_validate(dict(model) | {"relationships": (*model.relationships, extra)})


@pytest.mark.integration
@pytest.mark.requirement("CORE-22", "DATA-16", "DATA-46")
@pytest.mark.parametrize("provider", USABLE)
def test_both_read_surfaces_see_exactly_the_same_objects_and_relationships(
    provider: str, store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """The gate itself, through every usable rung of the provider ladder."""
    manifest = publish_release("rel-0001", example_model, expected_parent=None)
    context = ReleaseContext.for_release(store, manifest, provider=provider)
    graph = build_graph(context)

    relational_elements = {
        row["element_id"] for row in context.arrow("SELECT element_id FROM elements").to_pylist()
    }
    relational_relationships = {
        row["relationship_id"]
        for row in context.arrow("SELECT relationship_id FROM relationships").to_pylist()
    }

    assert set(graph.node_ids()) == relational_elements
    assert set(graph.relationship_ids()) == relational_relationships
    assert graph.release_id == manifest.release_id
    assert graph.model_digest == manifest.model_digest


@pytest.mark.integration
@pytest.mark.requirement("CORE-22", "DATA-16", "DATA-46")
def test_an_older_release_projects_the_graph_it_published_not_the_current_one(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """A surface resolving latest would pass the gate above and fail here.

    Three releases whose relationship sets genuinely differ, each read back through its own
    manifest. This is the graph half of the historical reproducibility the release matrix already
    checks for the relational half.
    """
    first = publish_release("rel-0001", example_model, expected_parent=None)
    second = publish_release(
        "rel-0002", with_parallel_relationship(example_model), expected_parent="rel-0001"
    )
    third = publish_release(
        "rel-0003",
        rename_first_element(with_parallel_relationship(example_model), "Third"),
        expected_parent="rel-0002",
    )

    graphs = {
        manifest.release_id: build_graph(ReleaseContext.for_release(store, manifest))
        for manifest in (first, second, third)
    }

    assert "rel-9" not in graphs["rel-0001"].relationship_ids()
    assert "rel-9" in graphs["rel-0002"].relationship_ids()
    assert graphs["rel-0001"].size + 1 == graphs["rel-0002"].size
    assert graphs["rel-0002"].size == graphs["rel-0003"].size
    assert len({graph.model_digest for graph in graphs.values()}) == 3


@pytest.mark.integration
@pytest.mark.requirement("CORE-23", "DATA-16")
def test_two_relationships_between_one_pair_survive_the_whole_path(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """Pydantic to Arrow to Delta to DataFusion to NetworkX, without collapsing (CORE-23)."""
    manifest = publish_release(
        "rel-0001", with_parallel_relationship(example_model), expected_parent=None
    )
    graph = build_graph(ReleaseContext.for_release(store, manifest))

    assert graph.relationships_between("system-1", "component-1") == ("rel-1", "rel-9")
    assert graph.type_of(("system-1", "component-1", "rel-1")) == "contains"
    assert graph.type_of(("system-1", "component-1", "rel-9")) == "depends_on"


@pytest.mark.integration
@pytest.mark.requirement("DATA-16", "DATA-47")
def test_each_side_of_a_comparison_projects_its_own_graph(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """One session, two sides, two graphs — so a comparison cannot mix them (DATA-47)."""
    base = publish_release("rel-0001", example_model, expected_parent=None)
    candidate = publish_release(
        "rel-0002", with_parallel_relationship(example_model), expected_parent="rel-0001"
    )
    comparison = ComparisonContext.of(store, base, candidate)

    base_graph = build_graph(comparison.side("base"))
    candidate_graph = build_graph(comparison.side("candidate"))

    assert base_graph.release_id == "rel-0001"
    assert candidate_graph.release_id == "rel-0002"
    assert set(candidate_graph.relationship_ids()) - set(base_graph.relationship_ids()) == {"rel-9"}


@pytest.mark.integration
@pytest.mark.requirement("CORE-22", "CORE-23")
def test_a_relationship_pointing_at_no_element_is_refused_rather_than_inventing_a_node(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """`add_edges_from` invents a node for an endpoint it has not seen; the builder must not.

    Publication runs the cross-record layer, so this release cannot be produced through
    `architecture publish` — which is exactly why the guard is worth having. It is reached by
    calling the assembly step directly with a doctored edge table, the way a store written by
    something other than this toolkit would present one. A graph that quietly grew a node would
    report an object the release does not contain, which is a same-release violation of a subtler
    kind than reading the wrong version.
    """
    manifest = publish_release("rel-0001", example_model, expected_parent=None)
    context = ReleaseContext.for_release(store, manifest)
    nodes = context.arrow("SELECT element_id, kind_id FROM elements")
    dangling = pa.table(
        {
            "source_element_id": ["system-1"],
            "target_element_id": ["ghost-1"],
            "relationship_id": ["rel-99"],
            "relationship_type_id": ["depends_on"],
            "context_id": [None],
        },
        schema=pa.schema(
            [
                pa.field("source_element_id", pa.string()),
                pa.field("target_element_id", pa.string()),
                pa.field("relationship_id", pa.string()),
                pa.field("relationship_type_id", pa.string()),
                pa.field("context_id", pa.string()),
            ]
        ),
    )

    with pytest.raises(GraphError, match="ghost-1"):
        _assemble(context, nodes, dangling)

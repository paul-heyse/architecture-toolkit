"""One session per manifest, two named sides, and no way to mutate through it.

DATA-46 says a query context registers only manifest-pinned versions; DATA-47 says a comparison
registers explicit sides; DATA-18 says the surface is read-only and parameters are bound. Each is
checked against the engine rather than against our own bookkeeping — `registered()` reads
`information_schema`, and the refusals are DataFusion's planner rejecting the statement.
"""

import pytest

from architecture_toolkit.domain.model import Model
from architecture_toolkit.queries.context import ComparisonContext, ReleaseContext
from architecture_toolkit.queries.errors import QueryError
from architecture_toolkit.releases.store import ReleaseStore
from architecture_toolkit.storage.schemas import TABLE_IDS
from tests.integration.conftest import Publisher, rename_first_element

USABLE = ("materialized", "dataset", "stream")


@pytest.mark.integration
@pytest.mark.requirement("DATA-46")
@pytest.mark.parametrize("provider", USABLE)
def test_a_context_registers_exactly_the_tables_the_manifest_pins(
    provider: str, store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """The inventory comes out of the engine, so no drift in our code can make it agree."""
    manifest = publish_release("rel-0001", example_model, expected_parent=None)
    context = ReleaseContext.for_release(store, manifest, provider=provider)

    assert context.registered() == tuple(
        sorted(("public", ref.table_id) for ref in manifest.tables)
    )
    assert {name for _, name in context.registered()} == set(TABLE_IDS)


@pytest.mark.integration
@pytest.mark.requirement("DATA-46", "DATA-15")
def test_each_release_answers_with_its_own_pinned_version(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """Three releases, three answers. A context resolving latest would give the newest name thrice.

    The assertion that carries the weight is the *third* one: a provider that opened the tip would
    pass the newest release and fail the two older ones, which is why all three are checked.
    """
    first = publish_release("rel-0001", example_model, expected_parent=None)
    second = publish_release(
        "rel-0002", rename_first_element(example_model, "Second"), expected_parent="rel-0001"
    )
    third = publish_release(
        "rel-0003", rename_first_element(example_model, "Third"), expected_parent="rel-0002"
    )
    victim = example_model.elements[0].element_id
    expected = {
        first.release_id: example_model.elements[0].name,
        second.release_id: "Second",
        third.release_id: "Third",
    }

    for manifest in (first, second, third):
        context = ReleaseContext.for_release(store, manifest)
        rows = context.arrow(
            "SELECT name FROM elements WHERE element_id = $id", {"id": victim}
        ).to_pylist()
        assert rows[0]["name"] == expected[manifest.release_id]


@pytest.mark.integration
@pytest.mark.requirement("DATA-18")
@pytest.mark.parametrize(
    "statement",
    [
        "CREATE TABLE sneaky AS SELECT * FROM elements",
        "INSERT INTO elements SELECT * FROM elements",
        "DROP TABLE elements",
        "SET datafusion.execution.batch_size = 1",
    ],
)
def test_the_engine_refuses_every_mutating_statement(
    statement: str, store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """DATA-18 through `SQLOptions`, so the refusal is the planner's and not a denylist of ours."""
    manifest = publish_release("rel-0001", example_model, expected_parent=None)
    context = ReleaseContext.for_release(store, manifest)

    with pytest.raises(Exception, match="not supported"):
        context.sql(statement).collect()


@pytest.mark.integration
@pytest.mark.requirement("DATA-18")
def test_a_parameter_is_bound_rather_than_interpolated(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """`test_data_stack.py` qualified this for DataFusion; this asserts the context keeps it."""
    manifest = publish_release("rel-0001", example_model, expected_parent=None)
    context = ReleaseContext.for_release(store, manifest)
    injection = "interface-1' OR 1=1 --"

    answer = context.arrow(
        "SELECT element_id FROM elements WHERE element_id = $id", {"id": injection}
    )
    assert answer.num_rows == 0


@pytest.mark.integration
@pytest.mark.requirement("DATA-47")
def test_a_comparison_registers_two_named_sides(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """`base.elements` and `candidate.elements`, which is the contract's own wording.

    The assertion that matters is that the two sides *disagree*, because that is only possible if
    each resolved its own manifest's pins rather than both resolving the tip.
    """
    base = publish_release("rel-0001", example_model, expected_parent=None)
    candidate = publish_release(
        "rel-0002",
        rename_first_element(example_model, "Candidate side"),
        expected_parent="rel-0001",
    )
    comparison = ComparisonContext.of(store, base, candidate)

    namespaces = {schema for schema, _ in comparison.registered()}
    assert namespaces == {"base", "candidate"}

    victim = example_model.elements[0].element_id
    row = comparison.arrow(
        "SELECT b.name AS base_name, c.name AS candidate_name "
        "FROM base.elements b JOIN candidate.elements c USING (element_id) "
        "WHERE b.element_id = $id",
        {"id": victim},
    ).to_pylist()[0]
    assert row["candidate_name"] == "Candidate side"
    assert row["base_name"] != row["candidate_name"]


@pytest.mark.integration
@pytest.mark.requirement("DATA-47")
def test_a_side_is_a_view_of_the_same_session(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """A side shares the comparison's session, so nothing can resolve a different release."""
    base = publish_release("rel-0001", example_model, expected_parent=None)
    candidate = publish_release(
        "rel-0002",
        rename_first_element(example_model, "Candidate side"),
        expected_parent="rel-0001",
    )
    comparison = ComparisonContext.of(store, base, candidate)

    side = comparison.side("candidate")
    assert side.session is comparison.session
    assert side.scope.release_id == "rel-0002"
    assert side.scope.table("elements") == "candidate.elements"
    assert side.scope.namespace == "candidate"

    rows = side.table("elements").to_arrow_table()
    assert "Candidate side" in {row["name"] for row in rows.to_pylist()}


@pytest.mark.integration
@pytest.mark.requirement("DATA-47")
def test_comparing_a_release_with_itself_is_refused(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """Two sides that name one release would report every difference as absent."""
    manifest = publish_release("rel-0001", example_model, expected_parent=None)

    with pytest.raises(QueryError, match="two releases"):
        ComparisonContext.of(store, manifest, manifest)


@pytest.mark.integration
@pytest.mark.requirement("DATA-46", "DATA-51")
def test_an_unknown_side_name_is_refused_by_the_engine(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """A schema nobody created cannot be registered into, so a typo cannot land in `public`."""
    manifest = publish_release("rel-0001", example_model, expected_parent=None)
    context = ReleaseContext.for_release(store, manifest)

    with pytest.raises(Exception, match="failed to resolve schema"):
        context.provider.register(context.session, "typo.elements", "elements", version=0)

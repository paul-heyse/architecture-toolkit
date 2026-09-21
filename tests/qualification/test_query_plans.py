"""Plan evidence for every shipped recipe, and the properties that make it worth keeping (DATA-49).

The artifact itself is written under `.runtime/`. What is asserted here are properties of the
plans, because a byte comparison against committed fixtures would turn every DataFusion upgrade
into a failed string equality that says nothing about whether the new plan is better or worse.

One property is a *declared divergence* rather than a requirement: projection pushdown does not
reach inside a recursive CTE in DataFusion 54, so `containment_hierarchy` reads every column of
`relationships` where the other four recipes read only the columns they select. It costs nothing
at this scale and it is exactly the kind of thing DATA-49 exists to make visible, so it is pinned
with the assertion inverted — when upstream pushes the projection down, this fails and the note
comes out.
"""

import pytest

from architecture_toolkit.domain.authoring import parse_model, parse_source
from architecture_toolkit.queries.context import ComparisonContext, ReleaseContext
from architecture_toolkit.queries.plans import (
    EVIDENCE_PATH,
    PlanEvidence,
    capture,
    scan_projections,
    scanned_tables,
    write_evidence,
)
from architecture_toolkit.queries.recipes import RECIPES, QueryRecipe
from architecture_toolkit.releases.candidate import ReleaseCandidate
from architecture_toolkit.releases.provenance import source_bundle
from architecture_toolkit.releases.publication import PublicationRequest, publish
from architecture_toolkit.releases.store import ReleaseStore
from architecture_toolkit.storage.schemas import TABLE_IDS
from tests.integration.conftest import EXAMPLE, MOMENT

PARAMETERS = {"root_element_id": "system-1", "max_depth": 5}


@pytest.fixture(scope="module")
def published(tmp_path_factory: pytest.TempPathFactory) -> ReleaseStore:
    """Two releases, published once for the module.

    Module-scoped against the function-scoped default because publishing twice takes seconds and
    nothing here mutates the store: every test in this file reads plans. `tests/conftest.py` asks
    for the reason to be stated at the fixture, and this is it.
    """
    store = ReleaseStore.at(tmp_path_factory.mktemp("plans")).initialize()
    model = parse_model(parse_source(EXAMPLE.read_text(), source_id="example"))
    renamed = model.model_validate(
        dict(model)
        | {
            "elements": tuple(
                element.model_validate(dict(element) | {"name": "Candidate side"})
                if element.element_id == model.elements[0].element_id
                else element
                for element in model.elements
            )
        }
    )
    for release_id, candidate, parent in (
        ("rel-0001", model, None),
        ("rel-0002", renamed, "rel-0001"),
    ):
        publish(
            PublicationRequest(
                store=store,
                candidate=ReleaseCandidate(
                    release_id=release_id,
                    model=candidate,
                    source_bundle=source_bundle(source_id="example", text=EXAMPLE.read_text()),
                ),
                expected_parent=parent,
                now=lambda: MOMENT,
                generator_commit="abc1234",
            )
        )
    return store


def context_for(store: ReleaseStore, recipe: QueryRecipe) -> ReleaseContext | ComparisonContext:
    first = store.read_manifest("rel-0001")
    if recipe.release_context == "comparison":
        return ComparisonContext.of(store, first, store.read_manifest("rel-0002"))
    return ReleaseContext.for_release(store, first)


def evidence_for(store: ReleaseStore, recipe: QueryRecipe) -> PlanEvidence:
    parameters = PARAMETERS if recipe.parameters else None
    return capture(recipe, context_for(store, recipe), parameters)


def persisted(name: str) -> str | None:
    """The table id a scanned name refers to, or `None` where it is not a persisted table."""
    bare = name.split(".")[-1]
    return bare if bare in TABLE_IDS else None


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-49")
@pytest.mark.parametrize("recipe_id", sorted(RECIPES))
def test_a_plan_scans_only_the_tables_its_recipe_declared(
    recipe_id: str, published: ReleaseStore
) -> None:
    """A recipe reading a table it never declared is a contract that stopped describing it."""
    recipe = RECIPES[recipe_id]
    evidence = evidence_for(published, recipe)

    scanned = {
        table_id
        for table_id in (
            persisted(name) for name in scanned_tables(evidence.optimized_logical_plan)
        )
        if table_id is not None
    }
    assert scanned == {item.table_id for item in recipe.inputs}


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-49", "DATA-47")
def test_a_comparison_plan_scans_a_base_and_a_candidate_table(published: ReleaseStore) -> None:
    recipe = RECIPES["application_ownership_across_releases"]
    evidence = evidence_for(published, recipe)

    scanned = set(scanned_tables(evidence.optimized_logical_plan))
    assert "base.relationships" in scanned
    assert "candidate.relationships" in scanned


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-49")
@pytest.mark.parametrize("recipe_id", sorted(RECIPES))
def test_a_physical_plan_carries_no_host_specific_repartitioning(
    recipe_id: str, published: ReleaseStore
) -> None:
    """Otherwise the evidence would differ between two machines running the same release."""
    evidence = evidence_for(published, RECIPES[recipe_id])

    assert "RepartitionExec" not in evidence.physical_plan


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-49")
@pytest.mark.parametrize("recipe_id", sorted(set(RECIPES) - {"containment_hierarchy"}))
def test_a_relational_recipe_reads_only_the_columns_it_needs(
    recipe_id: str, published: ReleaseStore
) -> None:
    """Projection pushdown, which is what stops a recipe dragging `extensions` through a join."""
    evidence = evidence_for(published, RECIPES[recipe_id])
    projections = scan_projections(evidence.optimized_logical_plan)

    # The plan is parsed with a regex, so a DataFusion release that reformatted `TableScan:` would
    # make every assertion below vacuously true. Assert the parse found the scans first.
    scanned = {table_id for table_id in map(persisted, projections) if table_id is not None}
    assert scanned == {item.table_id for item in RECIPES[recipe_id].inputs}

    unpruned = sorted(
        name for name, columns in projections.items() if persisted(name) and columns is None
    )
    assert not unpruned, f"{recipe_id} reads every column of {unpruned}"
    assert all(
        "extensions" not in (columns or ())
        for name, columns in projections.items()
        if persisted(name)
    )


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-49", "DATA-15")
def test_projection_pushdown_does_not_reach_inside_a_recursive_cte(
    published: ReleaseStore,
) -> None:
    """Declared divergence, DataFusion 54.0.0.

    The recursive term scans `relationships` whole. Harmless at this scale, and recorded rather
    than ignored because plan evidence exists to surface exactly this. When upstream pushes the
    projection down, this test fails: delete it and the note in the module docstring.
    """
    evidence = evidence_for(published, RECIPES["containment_hierarchy"])
    projections = scan_projections(evidence.optimized_logical_plan)

    assert projections["relationships"] is None
    assert projections["elements"] == ("element_id", "name")


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-49")
def test_the_evidence_artifact_records_every_recipe_and_is_reproducible(
    published: ReleaseStore,
) -> None:
    """A digest that moved between two runs of one release would not be evidence of anything."""
    first = [evidence_for(published, recipe) for recipe in RECIPES.values()]
    second = [evidence_for(published, recipe) for recipe in RECIPES.values()]

    assert [item.result_digest for item in first] == [item.result_digest for item in second]
    assert {item.query_recipe_id for item in first} == set(RECIPES)
    assert all(item.datafusion_version for item in first)
    assert all(item.materialization == "materialized" for item in first)
    assert all(item.provider_type == "MaterializedPyArrowSnapshotProvider" for item in first)

    # Written where `requirement-evidence.json` is written, so a normal `uv run pytest` leaves the
    # DATA-49 artifact behind rather than needing a separate command nobody remembers to run.
    written = write_evidence(first)
    assert written == EVIDENCE_PATH
    assert '"optimized_logical_plan"' in written.read_text()

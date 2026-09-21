"""DATA-50: built-ins first, asked of the engine rather than of the source (policy only).

`rules/queries-builtins-first.yml` forbids a `register_udf` call under `queries/`. This is the
half a source rule cannot cover: it asks a real release context which functions it actually holds
and compares that against a context built with nothing registered. A UDF added by any path — a
helper, a third-party import, a future `SessionConfig` extension — moves that comparison.

The baseline is not empty: DataFusion 54 registers its own built-ins into every context, so the
assertion is *equality with a bare context*, not emptiness. That is also the reason the comparison
is worth making: the interesting number is not how many functions exist but whether this toolkit
added any.
"""

import pytest
from datafusion import SessionContext

from architecture_toolkit.domain.model import Model
from architecture_toolkit.queries.context import ReleaseContext, session_config
from architecture_toolkit.queries.execution import execute
from architecture_toolkit.queries.recipes import RECIPES
from architecture_toolkit.releases.store import ReleaseStore
from tests.integration.conftest import Publisher


def registered(context: SessionContext) -> dict[str, frozenset[str]]:
    return {
        "scalar": frozenset(context.udfs()),
        "aggregate": frozenset(context.udafs()),
        "window": frozenset(context.udwfs()),
    }


@pytest.mark.integration
@pytest.mark.requirement("DATA-50")
def test_a_release_context_registers_no_function_beyond_the_built_ins(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    manifest = publish_release("rel-0001", example_model, expected_parent=None)
    context = ReleaseContext.for_release(store, manifest)

    assert registered(context.session) == registered(SessionContext(session_config()))


@pytest.mark.integration
@pytest.mark.requirement("DATA-50")
def test_the_baseline_is_not_empty_so_the_comparison_means_something() -> None:
    """A guard that compared two empty sets would pass whatever the toolkit registered."""
    baseline = registered(SessionContext(session_config()))

    assert len(baseline["scalar"]) > 100
    assert "count" in baseline["aggregate"]
    assert "row_number" in baseline["window"]


@pytest.mark.integration
@pytest.mark.requirement("DATA-50")
def test_every_shipped_recipe_is_expressible_in_built_ins(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """The demonstrated-capability-gap test, run the only honest way: by running the recipes.

    They all succeed against a context holding nothing but DataFusion's own functions, which is
    what "no demonstrated gap" means. A recipe that needed a UDF would fail to plan here.
    """
    manifest = publish_release("rel-0001", example_model, expected_parent=None)
    context = ReleaseContext.for_release(store, manifest)

    for recipe in RECIPES.values():
        if recipe.release_context != "single":
            continue
        parameters = {"root_element_id": "system-1", "max_depth": 5} if recipe.parameters else None
        assert execute(recipe, context, parameters).query_recipe_id == recipe.query_recipe_id

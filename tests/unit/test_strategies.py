"""The Hypothesis strategy library (CORE-45)."""

from typing import Annotated, Any, get_args, get_origin

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import StringConstraints, TypeAdapter

from architecture_toolkit.domain import identifiers
from architecture_toolkit.domain.model import Model
from architecture_toolkit.domain.semantics import MODEL_COLLECTIONS
from tests.strategies import DEFERRED_GROUPS
from tests.strategies.authoring import UNORDERED_COLLECTIONS
from tests.strategies.domain import elements, status_dimensions
from tests.strategies.ids import STRATEGY_BY_ALIAS
from tests.strategies.relations import coherent_models


def semantic_aliases() -> dict[str, Any]:
    found = {}
    for name in identifiers.__all__:
        value = getattr(identifiers, name)
        if get_origin(value) is Annotated and any(
            isinstance(item, StringConstraints) for item in get_args(value)[1:]
        ):
            found[name] = value
    return found


@pytest.mark.unit
@pytest.mark.requirement("CORE-45")
def test_every_semantic_alias_has_a_strategy() -> None:
    """A new alias without a generator would silently go unexercised by every property test."""
    assert set(semantic_aliases()) == set(STRATEGY_BY_ALIAS)


@pytest.mark.property
@pytest.mark.requirement("CORE-45")
@pytest.mark.parametrize("alias_name", sorted(STRATEGY_BY_ALIAS))
def test_drawn_identifiers_satisfy_their_alias(alias_name: str) -> None:
    """Built directly rather than filtered, so every draw is valid by construction."""
    adapter = TypeAdapter(semantic_aliases()[alias_name])

    @settings(max_examples=50, deadline=None)
    @given(STRATEGY_BY_ALIAS[alias_name])
    def check(value: str) -> None:
        adapter.validate_python(value)

    check()


@pytest.mark.property
@pytest.mark.requirement("CORE-45", "DATA-29")
@settings(max_examples=50, deadline=None)
@given(status_dimensions)
def test_generated_statuses_cover_values_and_gaps(status: object) -> None:
    from architecture_toolkit.domain.status import StatusDimensions

    assert isinstance(status, StatusDimensions)


@pytest.mark.property
@pytest.mark.requirement("CORE-45", "DATA-07")
@settings(max_examples=50, deadline=None)
@given(elements())
def test_generated_elements_are_valid_and_hashable(element: object) -> None:
    from architecture_toolkit.domain.model import Element

    assert isinstance(element, Element)
    assert isinstance(hash(element), int)
    if element.detail is not None:
        assert element.detail.element_id == element.element_id


@pytest.mark.property
@pytest.mark.slow
@pytest.mark.requirement("CORE-45", "DATA-03")
@settings(max_examples=40, deadline=None)
@given(coherent_models())
def test_generated_models_have_resolving_endpoints(model: Model) -> None:
    """Endpoints are drawn from the element pool, never generated and filtered."""
    known = {element.element_id for element in model.elements}
    for relation in model.relationships:
        assert relation.source_element_id in known
        assert relation.target_element_id in known


@pytest.mark.property
@pytest.mark.slow
@pytest.mark.requirement("CORE-45", "CORE-08")
@settings(max_examples=40, deadline=None)
@given(coherent_models())
def test_every_generated_model_is_hashable(model: Model) -> None:
    """The CORE-08 immutability guard, now total over *instances* as well as classes."""
    assert isinstance(hash(model), int)


@pytest.mark.unit
@pytest.mark.requirement("CORE-45")
def test_the_unbuilt_strategy_groups_are_recorded_not_omitted() -> None:
    """core.md names eight groups; the ones with no models yet are recorded rather than absent.

    `releases` left this set at W4 when the manifest arrived, which is the point of writing the
    reason down: a reader can tell a deferral from an oversight, and can tell when it ended.
    """
    assert set(DEFERRED_GROUPS) == {"workflows", "views", "artifacts"}
    for reason in DEFERRED_GROUPS.values():
        assert reason.startswith("W")
    assert "releases" not in DEFERRED_GROUPS, "the release strategies landed at W4"


@pytest.mark.unit
@pytest.mark.requirement("CORE-21", "CORE-45")
def test_the_reformatter_shuffles_every_unordered_top_level_collection() -> None:
    """`reformatted` proves presentation invariance by shuffling what is semantically unordered.

    A collection missing from `UNORDERED_COLLECTIONS` is not an error anywhere — it just never
    gets shuffled, so the CORE-21 property quietly stops covering it. `>=` because the tuple also
    names `extensions`, which is nested rather than top level.
    """
    assert set(UNORDERED_COLLECTIONS) >= {name for name, _ in MODEL_COLLECTIONS}


@pytest.mark.unit
@pytest.mark.requirement("CORE-45")
def test_from_type_on_a_constrained_alias_is_a_hard_failure() -> None:
    """The guard behind the whole package, proven rather than assumed.

    `st.from_type` cannot read a Pydantic constraint; it warns and yields the empty string.
    `filterwarnings` in `pyproject.toml` promotes that warning to an error, so a strategy that
    reached for the shortcut fails the suite instead of silently generating invalid data.

    Two independent guards, as it happens: Pyrefly rejects the call outright — `from_type`
    takes a type and a constrained alias is not one — so the shortcut would not survive a type
    check either. The suppression below exists purely so the runtime half can be demonstrated.
    """
    from hypothesis.errors import HypothesisWarning

    @settings(max_examples=1, deadline=None)
    # pyrefly: ignore[bad-argument-type]
    # Deliberate, and it turns out there are two guards rather than one: Pyrefly *also* rejects
    # `from_type` on an `Annotated` alias, because the stub takes a type. So the shortcut fails
    # the type check as well as the test suite, and this suppression exists only so the runtime
    # half can be proven. CORE-60 narrow suppression with a stated reason.
    @given(st.from_type(identifiers.ElementId))
    def naive(value: str) -> None:
        del value

    # `.example()` is deliberately not used here: it raises a HypothesisWarning of its own about
    # interactive use, which would satisfy the assertion for the wrong reason and leave the real
    # guard unproven.
    with pytest.raises(HypothesisWarning, match="Ignoring unsupported"):
        naive()

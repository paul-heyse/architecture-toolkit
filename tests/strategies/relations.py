"""Relationship and whole-model strategies (CORE-45, DATA-05).

The construction rule that matters: draw the element pool first, then draw endpoints with
`st.sampled_from(pool)`. Generating identifiers independently and filtering for the ones that
resolve would reject almost every example and shrink to something unreadable. core.md asks for
valid data built directly, and this is what that means in practice.
"""

from hypothesis import strategies as st

from architecture_toolkit.domain.model import Element, Model, Relationship
from architecture_toolkit.domain.registry import BASELINE_PROFILE
from tests.strategies.domain import elements
from tests.strategies.ids import element_ids, model_ids

__all__ = ["coherent_models", "relationships"]

# Drawn from the profile, so a generated relationship type always resolves in the registry.
BASELINE_TYPE_IDS = st.sampled_from(sorted(BASELINE_PROFILE.relationship_types_by_id))

# Bounded deliberately. The `ci` profile runs 100 examples; eight elements reaches every rule
# family while keeping a shrunk counterexample small enough to read in a failure message.
MAX_ELEMENTS = 8
MAX_RELATIONSHIPS = 8


@st.composite
def relationships(draw: st.DrawFn, *, pool: list[Element], model_id: str) -> Relationship:
    endpoints = st.sampled_from([element.element_id for element in pool])
    return Relationship(
        relationship_id=draw(element_ids),
        model_id=model_id,
        relationship_type_id=draw(BASELINE_TYPE_IDS),
        source_element_id=draw(endpoints),
        target_element_id=draw(endpoints),
    )


@st.composite
def coherent_models(draw: st.DrawFn) -> Model:
    """A model whose endpoints always resolve. Endpoint *kinds* may still be impermissible.

    That is deliberate: structural coherence and profile conformance are different claims, and a
    strategy that guaranteed both would make the endpoint-kind rule untestable by property.
    """
    identity = draw(model_ids)
    pool = draw(
        st.lists(
            elements(model_id=identity),
            min_size=1,
            max_size=MAX_ELEMENTS,
            unique_by=lambda element: element.element_id,
        )
    )
    relations = draw(
        st.lists(
            relationships(pool=pool, model_id=identity),
            max_size=MAX_RELATIONSHIPS,
            unique_by=lambda relation: relation.relationship_id,
        )
    )
    return Model(model_id=identity, elements=tuple(pool), relationships=tuple(relations))

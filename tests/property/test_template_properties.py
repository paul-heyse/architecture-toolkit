"""Rendering is a function of the DTO and the bundle, and of nothing else (CORE-33, CORE-36).

This is one of the two properties `docs/plans/w7a-generator-foundations.md` says carry the wave.
The other is C14N digest stability, which lives with the XML layer.
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from architecture_toolkit.domain.model import Model
from architecture_toolkit.domain.semantics import model_digest
from architecture_toolkit.projections.summary import ModelSummary, summary_of
from architecture_toolkit.projections.text import bundle_for, environment, render
from tests.strategies.relations import coherent_models

SUMMARY = "model-summary.md.j2"


@pytest.mark.property
@pytest.mark.slow
@pytest.mark.requirement("CORE-33", "CORE-36", "CORE-45")
@given(model=coherent_models())
def test_the_same_model_always_renders_the_same_bytes(model: Model) -> None:
    """Determinism, over generated models rather than over the one fixture.

    A fresh environment each time, because the risk is not that one environment is stable — it is
    that a default resolved at construction differs between two of them.
    """
    first = render(environment(), SUMMARY, summary_of(model))
    second = render(environment(), SUMMARY, summary_of(model))
    assert first == second


@pytest.mark.property
@pytest.mark.slow
@pytest.mark.requirement("CORE-21", "CORE-32", "CORE-45")
@given(data=st.data())
def test_authored_order_is_not_generated_order(data: st.DataObject) -> None:
    """Two models that differ only in the order their records were written render identically.

    CORE-21 says authored order is presentation and excluded from semantic identity. A generator
    that preserved it would emit a different artifact — and therefore a different projection
    digest — for an architecture that had not changed, which is the layout-versus-semantics
    confusion this toolkit exists to prevent, arriving through the back door.
    """
    model = data.draw(coherent_models())
    shuffled = model.model_copy(
        update={
            "elements": tuple(data.draw(st.permutations(list(model.elements)))),
            "relationships": tuple(data.draw(st.permutations(list(model.relationships)))),
        }
    )

    assert model_digest(shuffled) == model_digest(model), "the shuffle changed semantic identity"
    assert render(environment(), SUMMARY, summary_of(shuffled)) == render(
        environment(), SUMMARY, summary_of(model)
    )


@pytest.mark.property
@pytest.mark.slow
@pytest.mark.requirement("CORE-34", "CORE-36", "CORE-45")
@given(model=coherent_models())
def test_the_bundle_digest_is_a_property_of_the_templates_not_of_the_data(model: Model) -> None:
    """Whatever is rendered, the bundle behind it is the same two files and the same digest."""
    env = environment()
    bundle = bundle_for(env, SUMMARY)
    render(env, SUMMARY, summary_of(model))
    assert bundle_for(env, SUMMARY).digest == bundle.digest
    assert bundle.paths == ("_macros.md.j2", SUMMARY)
    assert set(ModelSummary.model_fields) >= {"model_id", "elements", "relationships"}

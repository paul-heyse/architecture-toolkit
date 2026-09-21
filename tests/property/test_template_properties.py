"""Rendering is a function of the DTO and the bundle, and of nothing else (CORE-33, CORE-36).

This is one of the two properties `docs/plans/w7a-generator-foundations.md` says carry the wave.
The other is C14N digest stability, which lives with the XML layer.
"""

import json

import pytest
from hypothesis import given
from hypothesis import strategies as st

from architecture_toolkit.domain.model import Model
from architecture_toolkit.domain.semantics import model_digest
from architecture_toolkit.projections.summary import summary_of
from architecture_toolkit.projections.text import (
    bundle_for,
    environment,
    md_escape,
    render,
)
from tests.strategies.relations import full_models

SUMMARY = "model-summary.md.j2"
_FIXED_BUNDLE_DIGEST = bundle_for(environment(), SUMMARY).digest


@pytest.mark.property
@pytest.mark.slow
@pytest.mark.requirement("CORE-33", "CORE-36", "CORE-45")
@given(model=full_models())
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
    model = data.draw(full_models())
    # Rebuilt through validation rather than `model_copy(update=...)`, which
    # `rules/no-validation-bypass.yml` forbids: CORE-10 says a candidate comes from the validated
    # path, and a test that took the shortcut would be demonstrating the property on an object the
    # toolkit would never actually produce.
    reordered = dict(model.model_dump(mode="json"))
    reordered["elements"] = list(data.draw(st.permutations(list(reordered["elements"]))))
    reordered["relationships"] = list(data.draw(st.permutations(list(reordered["relationships"]))))
    # `model_validate_json` rather than `model_validate`: the records are strict, so a `list`
    # is not a `tuple`, and JSON is the boundary where that coercion is intended. It is the same
    # route `tests/unit/test_rules.py` takes to build a model from plain data.
    shuffled = Model.model_validate_json(json.dumps(reordered))

    assert model_digest(shuffled) == model_digest(model), "the shuffle changed semantic identity"
    assert render(environment(), SUMMARY, summary_of(shuffled)) == render(
        environment(), SUMMARY, summary_of(model)
    )


@pytest.mark.property
@pytest.mark.slow
@pytest.mark.requirement("CORE-34", "CORE-36", "CORE-45")
@given(model=full_models())
def test_the_bundle_digest_is_a_property_of_the_templates_not_of_the_data(model: Model) -> None:
    """Whatever is rendered, the bundle behind it is the same two files and the same digest.

    Every assertion here used to be independent of the drawn model: it rendered, discarded the
    result, and compared two bundle digests and a field set — so a hundred Hypothesis examples
    re-asserted a constant. The render's output is what the digest has to be independent *of*, so
    it is now compared across draws.
    """
    env = environment()
    bundle = bundle_for(env, SUMMARY)
    rendered = render(env, SUMMARY, summary_of(model))

    assert bundle_for(env, SUMMARY).digest == bundle.digest
    assert bundle.paths == ("_macros.md.j2", SUMMARY)
    assert bundle.digest == _FIXED_BUNDLE_DIGEST, (
        "the bundle digest moved while rendering generated data; it is a property of the "
        "templates and the filters, and of nothing a model can say"
    )
    # Through the filter, not raw: an identifier containing `_` renders escaped, which is
    # `md_escape` working. Asserting the raw id would be asserting the filter is absent.
    assert rendered.startswith(f"# {md_escape(model.model_id)}")


@pytest.mark.property
@pytest.mark.slow
@pytest.mark.requirement("CORE-32", "CORE-45", "PROJ-03")
@given(model=full_models())
def test_every_view_a_model_declares_reaches_the_generated_artifact(model: Model) -> None:
    """The branch no property covered until now.

    The three properties drew `coherent_models()`, which never generates a view, so every one of
    them rendered the template's "This model defines no views" branch. The views table, the member
    count and the `md_escape` on a view title had been exercised by exactly one fixture.
    """
    rendered = render(environment(), SUMMARY, summary_of(model))

    if not model.views:
        assert "defines no views" in rendered
        return
    assert "defines no views" not in rendered
    for view in model.views:
        assert f"| {view.view_id} |" in rendered
        assert str(view.member_count) in rendered

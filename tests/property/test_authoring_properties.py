"""Authoring properties over generated models (CORE-20, CORE-21, DATA-27)."""

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from architecture_toolkit.domain.authoring import (
    apply_change_set_to_source,
    parse_model,
    parse_source,
    render_model_text,
)
from architecture_toolkit.domain.commands import build_candidate
from architecture_toolkit.domain.model import Model
from architecture_toolkit.domain.semantics import model_digest
from tests.strategies.commands import change_sets
from tests.strategies.relations import full_models


@pytest.mark.property
@pytest.mark.requirement("CORE-20", "CORE-21", "CORE-45")
@given(full_models())
def test_a_rendered_model_reloads_to_the_same_semantic_identity(model: Model) -> None:
    text = render_model_text(model)
    reloaded = parse_model(parse_source(text, source_id="generated.yaml"))
    assert model_digest(reloaded) == model_digest(model)


@pytest.mark.property
@pytest.mark.requirement("CORE-20", "CORE-45")
@settings(max_examples=60, deadline=None)
@given(data=st.data())
def test_editing_the_source_equals_applying_the_commands(data: st.DataObject) -> None:
    """CORE-20's statement as a property: the round-trip editor and the command engine agree."""
    baseline = data.draw(full_models())
    change_set = data.draw(change_sets(baseline))
    text = render_model_text(baseline)
    assume(parse_model(parse_source(text, source_id="g.yaml")).model_id == baseline.model_id)
    edited = apply_change_set_to_source(text, change_set, source_id="g.yaml")
    expected = build_candidate(baseline, change_set)
    assert model_digest(edited.model) == model_digest(expected)
    assert edited.candidate_digest == model_digest(expected)
    assert edited.base_digest == model_digest(baseline)

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
from architecture_toolkit.domain.semantics import model_digest, semantic_delta
from tests.strategies.authoring import reformatted
from tests.strategies.commands import change_sets
from tests.strategies.relations import full_models


@pytest.mark.property
@pytest.mark.slow
@pytest.mark.requirement("CORE-20", "CORE-21", "CORE-45")
@given(full_models())
def test_a_rendered_model_reloads_to_the_same_semantic_identity(model: Model) -> None:
    text = render_model_text(model)
    reloaded = parse_model(parse_source(text, source_id="generated.yaml"))
    assert model_digest(reloaded) == model_digest(model)


@pytest.mark.property
@pytest.mark.slow
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


@pytest.mark.property
@pytest.mark.slow
@pytest.mark.requirement("CORE-21", "DATA-27", "CORE-45")
@settings(max_examples=100, deadline=None)
@given(data=st.data())
def test_presentation_never_changes_the_semantic_digest(data: st.DataObject) -> None:
    """CORE-21 as a property: requote, restyle, comment, reindent, reorder — same digest.

    Unordered collections and ordinal-bearing lists are shuffled too, so this is also DATA-27's
    statement that ordered sequences are preserved through their ordinal, not their position.
    """
    model = data.draw(full_models())
    original = render_model_text(model)
    rewritten = data.draw(reformatted(original))
    reloaded = parse_model(parse_source(rewritten, source_id="rewritten.yaml"))
    assert model_digest(reloaded) == model_digest(model)
    assert semantic_delta(model, reloaded).is_empty


@pytest.mark.property
@pytest.mark.slow
@pytest.mark.requirement("CORE-21")
@settings(max_examples=40, deadline=None)
@given(data=st.data())
def test_a_content_change_under_the_same_presentation_is_detected(data: st.DataObject) -> None:
    """The negative control: one changed name is a different digest, whatever the presentation."""
    model = data.draw(full_models())
    victim = data.draw(st.sampled_from(model.elements))
    changed = model.model_validate(
        dict(model)
        | {
            "elements": tuple(
                e.model_validate(dict(e) | {"name": e.name + " (changed)"})
                if e.element_id == victim.element_id
                else e
                for e in model.elements
            )
        }
    )
    rewritten = data.draw(reformatted(render_model_text(changed)))
    reloaded = parse_model(parse_source(rewritten, source_id="changed.yaml"))
    assert model_digest(reloaded) != model_digest(model)
    delta = semantic_delta(model, reloaded)
    assert [c.changed for c in delta.collections if c.collection == "elements"] == [
        (victim.element_id,)
    ]

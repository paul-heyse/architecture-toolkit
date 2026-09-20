"""Typed change commands and the M1 hard gate (CORE-05, CORE-09, CORE-10)."""

import json
from typing import Any, get_args

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from architecture_toolkit.domain.commands import (
    CHANGE_SET_ADAPTER,
    COMMAND_BATCH_ADAPTER,
    AddElement,
    ChangeCommand,
    ChangeSet,
    CommandError,
    RenameElement,
    RetireElement,
    build_candidate,
)
from architecture_toolkit.domain.model import Model
from architecture_toolkit.domain.status import LifecycleState
from tests.strategies.commands import change_sets, rename_elements
from tests.strategies.relations import coherent_models


def _baseline(source: dict[str, Any]) -> Model:
    return Model.model_validate_json(json.dumps(source))


def _rename(baseline: Model, element_id: str, new_name: str) -> Model:
    return build_candidate(
        baseline,
        ChangeSet(
            change_set_id="cs-1",
            model_id=baseline.model_id,
            commands=(RenameElement(element_id=element_id, new_name=new_name),),
        ),
    )


# -- the hard gate ------------------------------------------------------------------------------


@pytest.mark.property
@pytest.mark.requirement("CORE-10", "DATA-04")
@settings(max_examples=60, deadline=None)
@given(data=st.data())
def test_rename_preserves_identity(data: st.DataObject) -> None:
    """The M1 hard gate, over generated models rather than one example.

    A rename changes the display name and nothing else. In particular it is a *rename*, not a
    retire plus an add: the same `element_id` is present before and after, in the same position,
    with its kind, lifecycle, status, aliases, detail and every relationship untouched.
    """
    baseline = data.draw(coherent_models())
    command = data.draw(rename_elements(baseline))
    before = {element.element_id: element for element in baseline.elements}

    candidate = _rename(baseline, command.element_id, command.new_name)
    after = {element.element_id: element for element in candidate.elements}

    assert set(after) == set(before), "rename changed the set of element identities"
    original, renamed = before[command.element_id], after[command.element_id]
    assert renamed.element_id == original.element_id
    assert renamed.name == command.new_name
    for untouched in ("kind_id", "lifecycle_state", "status", "aliases", "detail", "model_id"):
        assert getattr(renamed, untouched) == getattr(original, untouched), untouched
    assert candidate.relationships == baseline.relationships
    for other in set(before) - {command.element_id}:
        assert after[other] == before[other]


@pytest.mark.unit
@pytest.mark.requirement("CORE-10", "DATA-04")
def test_rename_is_not_a_retire_plus_an_add(minimal_model_source: dict[str, Any]) -> None:
    """Stated separately from the property because it is the distinction W6's diff depends on."""
    baseline = _baseline(minimal_model_source)
    candidate = _rename(baseline, "process-1", "Assess request")

    assert len(candidate.elements) == len(baseline.elements)
    renamed = next(e for e in candidate.elements if e.element_id == "process-1")
    assert renamed.lifecycle_state is LifecycleState.ACTIVE
    assert renamed.name == "Assess request"
    # Retiring is a different command with a different effect, which is the point.
    retired = build_candidate(
        baseline,
        ChangeSet(
            change_set_id="cs-2",
            model_id=baseline.model_id,
            commands=(RetireElement(element_id="process-1"),),
        ),
    )
    survivor = next(e for e in retired.elements if e.element_id == "process-1")
    assert survivor.lifecycle_state is LifecycleState.RETIRED
    assert survivor.name == "Review request"


# -- no bypass ----------------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.requirement("CORE-09")
def test_the_command_path_validates_what_the_bypass_would_not() -> None:
    """Why CORE-09 exists.

    The banned call is not performed here, because a test performing it is still code
    performing it and `no-validation-bypass` now covers `tests/`. What it does is recorded in
    `domain/commands.py` with the measured values: on a strict frozen record,
    `model_copy(update=...)` accepted both an empty name violating `min_length` and an integer
    where a constrained string belongs. This asserts the other half — that the sanctioned path
    rejects the same input.
    """
    baseline = _baseline(
        {
            "model_id": "m-1",
            "elements": [
                {
                    "element_id": "a-1",
                    "model_id": "m-1",
                    "kind_id": "software.system",
                    "name": "A",
                }
            ],
        }
    )
    with pytest.raises(ValidationError):
        _rename(baseline, "a-1", "")


@pytest.mark.unit
@pytest.mark.requirement("CORE-10")
def test_a_command_that_cannot_apply_leaves_the_baseline_untouched() -> None:
    baseline = _baseline({"model_id": "m-1", "elements": []})
    with pytest.raises(CommandError, match="does not exist in the baseline"):
        _rename(baseline, "ghost", "New")
    assert baseline.elements == ()


@pytest.mark.unit
@pytest.mark.requirement("CORE-10")
def test_expected_name_is_optimistic_concurrency(
    minimal_model_source: dict[str, Any],
) -> None:
    """An author renaming what they believe is X must fail if someone already renamed it."""
    baseline = _baseline(minimal_model_source)
    with pytest.raises(CommandError, match="is named 'Review request', not 'Stale name'"):
        build_candidate(
            baseline,
            ChangeSet(
                change_set_id="cs-3",
                model_id=baseline.model_id,
                commands=(
                    RenameElement(element_id="process-1", new_name="X", expected_name="Stale name"),
                ),
            ),
        )


@pytest.mark.unit
@pytest.mark.requirement("CORE-10")
def test_a_change_set_cannot_target_a_different_model() -> None:
    baseline = _baseline({"model_id": "m-1", "elements": []})
    with pytest.raises(CommandError, match="but the baseline is"):
        build_candidate(
            baseline,
            ChangeSet(
                change_set_id="cs-4",
                model_id="other-model",
                commands=(RetireElement(element_id="a-1"),),
            ),
        )


@pytest.mark.unit
@pytest.mark.requirement("CORE-10")
def test_adding_an_existing_identity_is_refused(minimal_model_source: dict[str, Any]) -> None:
    baseline = _baseline(minimal_model_source)
    duplicate = next(e for e in baseline.elements if e.element_id == "process-1")
    with pytest.raises(CommandError, match="already exists"):
        build_candidate(
            baseline,
            ChangeSet(
                change_set_id="cs-5",
                model_id=baseline.model_id,
                commands=(AddElement(element=duplicate),),
            ),
        )


# -- shape --------------------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.requirement("CORE-04")
def test_the_command_union_is_discriminated_and_retyping_is_unexpressible() -> None:
    """`kind_id` is deliberately unchangeable.

    Retyping an element changes its permitted endpoints and permitted detail families, so it is
    a retire plus an add at the semantic level. A command for it would let a model silently
    change meaning while every structural rule still passed.
    """
    variants = get_args(get_args(ChangeCommand)[0])
    assert len(variants) == 7
    commands = CHANGE_SET_ADAPTER.json_schema()["properties"]["commands"]
    discriminator = commands["items"]["discriminator"]
    assert discriminator["propertyName"] == "command"
    assert len(discriminator["mapping"]) == 7
    for variant in variants:
        assert "kind_id" not in variant.model_fields, variant.__name__


@pytest.mark.unit
@pytest.mark.requirement("CORE-05")
def test_the_batch_adapter_is_a_collection_boundary_not_a_wrapper_model() -> None:
    """CORE-05: `TypeAdapter` for a natural collection, with no model invented to hold it."""
    parsed = COMMAND_BATCH_ADAPTER.validate_json(
        json.dumps([{"command": "rename_element", "element_id": "a-1", "new_name": "B"}])
    )
    assert isinstance(parsed[0], RenameElement)


@pytest.mark.unit
@pytest.mark.requirement("CORE-10")
def test_an_empty_change_set_is_refused() -> None:
    with pytest.raises(ValidationError, match="contains no commands"):
        ChangeSet(change_set_id="cs-6", model_id="m-1", commands=())


@pytest.mark.property
@pytest.mark.requirement("CORE-10")
@settings(max_examples=40, deadline=None)
@given(data=st.data())
def test_applying_a_change_set_always_yields_a_fully_valid_candidate(
    data: st.DataObject,
) -> None:
    """The pipeline's contract: a candidate has passed complete Pydantic validation.

    Round-tripping it through validation must therefore be a no-op, not a second chance to
    catch something.
    """
    baseline = data.draw(coherent_models())
    change_set = data.draw(change_sets(baseline))
    candidate = build_candidate(baseline, change_set)
    assert Model.model_validate(dict(candidate)) == candidate

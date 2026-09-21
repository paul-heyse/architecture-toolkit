"""The W6 hard gate and its four qualification cases (DATA-26, DATA-31).

> Layout/presentation-only changes do not masquerade as semantic model changes.
> — data.md, History and semantic diff

and `ARCH-TOOL-DATA-001` §10C: *"A rename, interface modification, relationship removal and
diagram-layout edit must produce distinct semantic changes."*

Every assertion here is written against the specific way it could pass for the wrong reason, because
this repository has twice found gates that fired on an empty result. In particular a layout test
that only asserts *"nothing semantic was reported"* passes just as happily when the models are
identical, when the differ never descended, and when the classifier returns `LAYOUT_ONLY` for every
field it is shown. Each of those has its own assertion below, and the negative control is in the
same function as the positive one so a shortcut cannot satisfy one without breaking the other.
"""

from pathlib import Path

import pytest

from architecture_toolkit.changes.diff import model_changes
from architecture_toolkit.changes.kinds import ChangeKind, ChangeNature
from architecture_toolkit.domain.authoring import parse_model, parse_source
from architecture_toolkit.domain.commands import (
    ChangeSet,
    RenameElement,
    UpdateElement,
    build_candidate,
)
from architecture_toolkit.domain.details import BehaviorDetail, InterfaceDetail
from architecture_toolkit.domain.model import Model
from architecture_toolkit.domain.semantics import model_digest, semantic_delta

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "minimal" / "model.yaml"


@pytest.fixture
def base() -> Model:
    return parse_model(parse_source(EXAMPLE.read_text(), source_id="example"))


def with_binding(model: Model, **changes: object) -> Model:
    binding = model.notation_bindings[0]
    return model.model_validate(
        dict(model) | {"notation_bindings": (binding.model_validate(dict(binding) | changes),)}
    )


def with_element(model: Model, element_id: str, **changes: object) -> Model:
    victim = next(item for item in model.elements if item.element_id == element_id)
    replaced = victim.model_validate(dict(victim) | changes)
    return model.model_validate(
        dict(model)
        | {
            "elements": tuple(
                replaced if item.element_id == element_id else item for item in model.elements
            )
        }
    )


def renamed(model: Model) -> Model:
    return with_element(model, "capability-1", name="Portfolio Technology Evaluation")


def interface_modified(model: Model) -> Model:
    victim = next(item for item in model.elements if item.element_id == "interface-1")
    detail = victim.detail
    assert isinstance(detail, InterfaceDetail)
    return with_element(
        model, "interface-1", detail=detail.model_validate(dict(detail) | {"timeout_ms": 5000})
    )


def relationship_removed(model: Model) -> Model:
    return model.model_validate(dict(model) | {"relationships": model.relationships[1:]})


def layout_edited(model: Model) -> Model:
    return with_binding(model, link_target="diagrams/review.svg#Process_ReviewRequest")


# -- the gate -------------------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requirement("DATA-26", "DATA-31")
def test_a_layout_only_edit_is_reported_and_stays_out_of_the_narrative(base: Model) -> None:
    """The hard gate, with every way it could pass for the wrong reason closed off.

    Sabotages this kills: classifying every `NotationBinding` field as layout fails the negative
    control; returning an empty change record fails the exactness assertion; comparing a model to
    itself fails the digest assertion; never descending fails the exact-path assertion.
    """
    candidate = layout_edited(base)

    # 1. Something really changed. Without this, every assertion below is free.
    assert model_digest(base) != model_digest(candidate)
    assert not semantic_delta(base, candidate).is_empty

    changes = model_changes(base, candidate)

    # 2. The record is non-empty and exact. A gate that fires on an empty result cannot be told
    #    apart from a gate that fires on a broken differ.
    assert len(changes.records) == 1
    assert len(changes.presentation) == 1
    field = changes.presentation[0].fields[0]
    assert (field.collection, field.identity, field.field_path) == (
        "notation_bindings",
        "binding-1",
        "link_target",
    )
    assert field.kind is ChangeKind.LAYOUT_LINK_CHANGED
    assert field.nature is ChangeNature.LAYOUT_ONLY

    # 3. The gate itself.
    assert changes.narrative == ()

    # 4. Nothing else moved, so the test cannot be quietly exercising an element edit.
    assert not [r for r in changes.records if r.collection == "elements"]
    assert base.elements == candidate.elements

    # 5. The negative control, on the same record and the same code path. Without it, a classifier
    #    that returns LAYOUT_ONLY for every binding field passes this test forever.
    semantic = model_changes(base, with_binding(base, mapping_profile_version="2.0.0"))
    assert len(semantic.narrative) == 1
    assert semantic.narrative[0].fields[0].field_path == "mapping_profile_version"
    assert semantic.narrative[0].fields[0].nature is ChangeNature.NOTATION_MAPPING
    assert semantic.presentation == ()


@pytest.mark.integration
@pytest.mark.requirement("DATA-04", "DATA-26", "DATA-31")
def test_an_alias_edit_changes_no_digest_and_is_still_reported(base: Model) -> None:
    """The purest layout-only case: the model digest does not even move.

    The first assertion is the opposite of the previous test's, which is why both exist — one
    covers a presentation field inside the preimage, the other a field outside it entirely, and a
    differ can be right about one and blind to the other.
    """
    candidate = with_element(base, "capability-1", aliases=("Portfolio Eval",))

    assert model_digest(base) == model_digest(candidate)
    assert semantic_delta(base, candidate).is_empty
    assert base.elements != candidate.elements

    changes = model_changes(base, candidate)

    assert len(changes.presentation) == 1
    assert changes.presentation[0].fields[0].identity_path == "elements.capability-1.aliases"
    assert changes.narrative == ()


# -- the four qualification cases -----------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.qualification
@pytest.mark.requirement("DATA-26")
def test_the_four_qualification_cases_produce_four_distinct_classifications(base: Model) -> None:
    """§10C. Pairwise distinctness *and* the expected value for each.

    Distinctness alone is satisfiable by four residuals with different paths, so the expected
    pairs are pinned too. Two of these cases — the rename and the interface modification — are
    identical one level up, both reporting `elements: changed`, which is why the classification
    has to reach the field to tell them apart at all.
    """
    cases = {
        "rename": renamed(base),
        "interface": interface_modified(base),
        "relationship removal": relationship_removed(base),
        "layout": layout_edited(base),
    }
    observed = {name: model_changes(base, candidate) for name, candidate in cases.items()}

    signatures = {
        name: (changes.kinds, bool(changes.narrative)) for name, changes in observed.items()
    }
    assert len(set(signatures.values())) == len(cases), signatures

    assert observed["rename"].kinds == {ChangeKind.ELEMENT_RENAMED}
    assert observed["interface"].kinds == {ChangeKind.INTERFACE_CONTRACT_CHANGED}
    assert observed["relationship removal"].kinds == {ChangeKind.RELATIONSHIP_REMOVED}
    assert observed["layout"].kinds == {ChangeKind.LAYOUT_LINK_CHANGED}

    assert [bool(changes.narrative) for changes in observed.values()] == [True, True, True, False]

    # The two that collapse one level up really do collapse there, which is the measurement that
    # made per-field classification necessary rather than merely tidy.
    collapsed = {
        name: tuple(
            (delta.collection, delta.changed)
            for delta in semantic_delta(base, cases[name]).collections
            if not delta.is_empty
        )
        for name in ("rename", "interface")
    }
    assert collapsed["rename"][0][0] == collapsed["interface"][0][0] == "elements"


@pytest.mark.integration
@pytest.mark.requirement("DATA-26")
def test_a_rename_is_a_rename_and_never_a_retire_plus_an_add(base: Model) -> None:
    """The M1 gate, restated where a change narrative could still get it wrong."""
    changes = model_changes(base, renamed(base))

    assert ChangeKind.ELEMENT_RENAMED in changes.kinds
    assert ChangeKind.ELEMENT_ADDED not in changes.kinds
    assert ChangeKind.ELEMENT_REMOVED not in changes.kinds
    assert ChangeKind.ELEMENT_RETIRED not in changes.kinds
    assert len(changes.records) == 1


@pytest.mark.integration
@pytest.mark.requirement("CORE-10", "DATA-26")
def test_the_diff_reads_content_and_not_the_command_that_produced_it(base: Model) -> None:
    """`RenameElement` and an equivalent `UpdateElement` must produce identical change records.

    The cheapest possible check that nobody wired the diff to the change set: a change set records
    the author's *intent*, and DATA-27 hashes validated records rather than source precisely so the
    answer is about content. If these two ever disagree, the differ has started reading intent.
    """
    victim = base.elements[0]
    by_rename = build_candidate(
        base,
        ChangeSet(
            change_set_id="cs-rename",
            model_id=base.model_id,
            commands=(RenameElement(element_id=victim.element_id, new_name="Same New Name"),),
        ),
    )
    by_update = build_candidate(
        base,
        ChangeSet(
            change_set_id="cs-update",
            model_id=base.model_id,
            commands=(UpdateElement(element_id=victim.element_id, name="Same New Name"),),
        ),
    )

    assert model_changes(base, by_rename) == model_changes(base, by_update)
    assert model_changes(base, by_rename).kinds == {ChangeKind.ELEMENT_RENAMED}


@pytest.mark.integration
@pytest.mark.requirement("DATA-26")
def test_an_order_sensitive_behaviour_change_is_detected(base: Model) -> None:
    """The gate's third clause. The ordinals carry it; no synthetic "reordered" kind is needed."""
    victim = next(item for item in base.elements if item.element_id == "process-1")
    detail = victim.detail
    assert isinstance(detail, BehaviorDetail)
    last = len(detail.nodes) - 1
    reordered = detail.model_validate(
        dict(detail)
        | {
            "nodes": tuple(
                node.model_validate(dict(node) | {"ordinal": last - node.ordinal})
                for node in detail.nodes
            )
        }
    )
    candidate = with_element(base, "process-1", detail=reordered)

    changes = model_changes(base, candidate)

    # Reversing an odd-length sequence leaves the middle element where it was, so the expected
    # set is computed rather than guessed — the count is the thing most easily asserted wrongly.
    moved = {node.node_id for node in detail.nodes if last - node.ordinal != node.ordinal}
    assert changes.kinds == {ChangeKind.BEHAVIOR_CHANGED}
    assert {change.field_path for change in changes.records[0].fields} == {
        f"detail.nodes.{node_id}.ordinal" for node_id in moved
    }
    # Non-vacuity, stated as a floor rather than an exact count: an exact one would encode the
    # arithmetic of this particular fixture's length rather than the property being tested.
    assert len(moved) >= 2

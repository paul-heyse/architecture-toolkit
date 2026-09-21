"""The field differ agrees with the digest, in both directions (DATA-26, DATA-27).

One property carries this file, and it is the reason the rest of the wave's tests can be
demonstrations rather than proofs:

    field_changes(a, b) == ()  ⟺  record_digest(a) == record_digest(b)

Left to right says the differ cannot invent a change the digest does not see. Right to left says it
cannot be blind to one the digest does. Both halves matter and they fail differently: a differ that
returns nothing satisfies one direction perfectly.

It holds because both sides read `normalize_record` — the field diff and the digest preimage are
the same function, not two functions that happen to agree today.

`event()` records whether each generated pair actually exercised the interesting branch, because a
`@given` test over models that are usually identical proves very little and looks exactly like one
that proves a lot.
"""

import pytest
from hypothesis import HealthCheck, event, given, settings
from hypothesis import strategies as st

from architecture_toolkit.changes.diff import (
    PRESENTATION_FIELDS,
    field_changes,
    model_changes,
    presentation_changes,
)
from architecture_toolkit.domain.commands import build_candidate
from architecture_toolkit.domain.model import Model
from architecture_toolkit.domain.semantics import model_digest, record_digest
from tests.strategies.commands import change_sets
from tests.strategies.relations import full_models


@pytest.mark.property
@pytest.mark.requirement("DATA-26", "DATA-27")
@given(data=st.data())
@settings(suppress_health_check=[HealthCheck.too_slow])
def test_the_field_diff_is_empty_exactly_when_the_record_digests_agree(
    data: st.DataObject,
) -> None:
    """The load-bearing property. A differ that returns nothing satisfies only half of it."""
    baseline = data.draw(full_models())
    change_set = data.draw(change_sets(baseline))
    candidate = build_candidate(baseline, change_set)

    before = {element.element_id: element for element in baseline.elements}
    after = {element.element_id: element for element in candidate.elements}
    compared = sorted(set(before) & set(after))
    event(f"elements compared: {'some' if compared else 'none'}")
    # `event()` reports; it does not gate. The whole body of this property is inside the loop
    # below, so without this the load-bearing property of the wave would pass green on any draw
    # that produced no comparable pair — which is the failure this file's own docstring warns of.
    assert compared, "no element survived the change set; the property examined nothing"

    changed = 0
    for element_id in compared:
        was, now = before[element_id], after[element_id]
        digests_agree = record_digest(was) == record_digest(now)
        found = field_changes("elements", element_id, was, now)
        assert bool(found) is not digests_agree, (
            f"{element_id}: digests {'agree' if digests_agree else 'differ'} but the diff "
            f"reported {len(found)} field changes"
        )
        changed += 0 if digests_agree else 1
    event(f"records whose digest moved: {'some' if changed else 'none'}")


@pytest.mark.property
@pytest.mark.requirement("DATA-26")
@given(data=st.data())
@settings(suppress_health_check=[HealthCheck.too_slow])
def test_every_reported_change_names_a_field_that_really_differs(
    data: st.DataObject,
) -> None:
    """Not implied by the property above: a differ could report the right *count* of wrong paths."""
    baseline = data.draw(full_models())
    change_set = data.draw(change_sets(baseline))
    candidate = build_candidate(baseline, change_set)

    changes = model_changes(baseline, candidate)
    reported = [change for record in changes.records for change in record.fields]
    event(f"field changes: {'some' if reported else 'none'}")
    # The same shape as above: a nested loop whose body is the assertion. `change_sets` always
    # draws at least one command and every command in the library moves a field, so an empty
    # result here means the differ stopped seeing them rather than that the draw was dull.
    assert reported or not changes.records, "records changed but no field change was reported"

    for record in changes.records:
        for change in record.fields:
            assert change.before != change.after, f"{change.identity_path} reports no difference"
            assert change.identity == record.identity
            assert change.collection == record.collection


@pytest.mark.property
@pytest.mark.requirement("DATA-26", "DATA-27")
@given(model=full_models())
def test_a_model_compared_with_itself_reports_nothing_at_all(model: Model) -> None:
    """Including the presentation pass, which the digest cannot speak for."""
    changes = model_changes(model, model)

    assert changes.is_empty
    assert changes.narrative == ()
    assert changes.presentation == ()
    assert changes.base_digest == changes.candidate_digest


@pytest.mark.property
@pytest.mark.requirement("DATA-26", "DATA-04")
@given(data=st.data())
def test_an_alias_edit_moves_no_digest_and_is_still_reported(data: st.DataObject) -> None:
    """The purest layout-only case the schema can express, and the spine of the gate.

    `Element.aliases` is excluded from the preimage, so the model digest does not move and
    `semantic_delta` sees nothing. If the presentation pass were gated on the changed set — the
    obvious optimisation — this would report nothing and the test would be asserting an absence
    against an absence.
    """
    baseline = data.draw(full_models().filter(lambda model: bool(model.elements)))
    victim = baseline.elements[0]
    renamed_label = data.draw(st.text(min_size=1, max_size=12).filter(lambda t: t.strip()))
    relabelled = victim.model_validate(dict(victim) | {"aliases": (renamed_label,)})
    candidate = baseline.model_validate(
        dict(baseline) | {"elements": (relabelled, *baseline.elements[1:])}
    )

    event(f"alias was already set: {bool(victim.aliases)}")
    changes = model_changes(baseline, candidate)

    assert model_digest(baseline) == model_digest(candidate)
    assert record_digest(victim) == record_digest(relabelled)
    assert field_changes("elements", victim.element_id, victim, relabelled) == ()
    # Both branches assert. Hypothesis can draw the alias the element already had, and a guarded
    # body that simply skips in that case is a branch where the property proves nothing — which is
    # the shape two earlier hardening passes were spent removing.
    reported = presentation_changes("elements", victim.element_id, victim, relabelled)
    assert changes.narrative == ()
    if victim.aliases == (renamed_label,):
        assert reported == ()
        assert changes.is_empty
    else:
        assert [change.field_path for change in reported] == ["aliases"]
        assert len(changes.presentation) == 1


@pytest.mark.property
@pytest.mark.requirement("DATA-26")
def test_the_presentation_field_set_is_derived_and_not_empty() -> None:
    """A derived set that came out empty would make the pass above vacuous everywhere."""
    assert PRESENTATION_FIELDS
    assert all(name in owner.model_fields for owner, name in PRESENTATION_FIELDS)

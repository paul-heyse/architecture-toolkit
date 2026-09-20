"""The three diagnostic axes (CORE-07, DATA-31, PROJ-07)."""

import pytest

from architecture_toolkit.validation.taxonomy import (
    DATA31_MEANINGS,
    DiagnosticCategory,
    Disposition,
    Severity,
    ValidationClaim,
)


@pytest.mark.unit
@pytest.mark.requirement("CORE-07")
def test_each_axis_has_the_membership_its_contract_names() -> None:
    assert len(DiagnosticCategory) == 9
    assert len(ValidationClaim) == 6
    assert len(Disposition) == 4


@pytest.mark.unit
@pytest.mark.requirement("CORE-07", "DATA-31")
def test_the_axes_are_disjoint_so_a_bare_value_is_never_ambiguous() -> None:
    """Three enums over strings: an overlapping value would make a serialized report unreadable."""
    axes = {
        "severity": {m.value for m in Severity},
        "category": {m.value for m in DiagnosticCategory},
        "claim": {m.value for m in ValidationClaim},
        "disposition": {m.value for m in Disposition},
    }
    for left, left_values in axes.items():
        for right, right_values in axes.items():
            if left < right:
                assert not left_values & right_values, f"{left} overlaps {right}"


@pytest.mark.unit
@pytest.mark.requirement("DATA-31")
def test_data31s_four_meanings_partition_proj07s_six_claims() -> None:
    """The reconciliation, made checkable.

    DATA-31 asks for four meanings of validation success; PROJ-07 names six dimensions. Defining
    six is a refinement rather than a contradiction only if the four map cleanly onto them — so
    assert it: every claim covered, none covered twice.
    """
    assert len(DATA31_MEANINGS) == 4
    covered: list[ValidationClaim] = []
    for claims in DATA31_MEANINGS.values():
        covered.extend(claims)
    assert sorted(covered, key=lambda c: c.value) == sorted(ValidationClaim, key=lambda c: c.value)
    assert len(covered) == len(set(covered)), "a claim is claimed by two meanings"


@pytest.mark.unit
@pytest.mark.requirement("CORE-66")
def test_the_engineering_category_exists_but_no_w1_rule_uses_it() -> None:
    """`domain/engineering.py` forbids Diagnostic carrying source-code quality signals.

    The category is defined because W9 needs it for findings about a *run*. Nothing in W1 may
    use it, and the import boundary is checked separately in `test_layering.py`.
    """
    from architecture_toolkit.validation.codes import CODES

    used = {spec.category for spec in CODES.values()}
    assert DiagnosticCategory.ENGINEERING_QUALIFICATION not in used

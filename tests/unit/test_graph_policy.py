"""What a policy may declare, and what the profile refuses to let it declare (CORE-26, CORE-27)."""

import pytest

from architecture_toolkit.domain.registry import BASELINE_PROFILE, TraversalBehavior
from architecture_toolkit.queries.errors import PolicyError, UnknownPolicyError
from architecture_toolkit.queries.policy import (
    POLICIES,
    Direction,
    GraphPolicy,
    check_policy,
    policy_for,
)
from architecture_toolkit.queries.results import PathClassification

FORWARD_ONLY = {
    type_id
    for type_id, definition in BASELINE_PROFILE.relationship_types_by_id.items()
    if definition.traversal is TraversalBehavior.FORWARD_ONLY
}


def policy(**overrides: object) -> GraphPolicy:
    base = GraphPolicy(
        policy_id="test.policy",
        policy_version="1.0.0",
        purpose="A policy built for one assertion.",
        allowed_relationship_types=("depends_on",),
        direction=Direction.FORWARD,
        max_depth=3,
        max_paths=10,
        max_results=10,
        classification=PathClassification.POTENTIALLY_AFFECTED,
    )
    return base.model_validate(dict(base) | overrides)


@pytest.mark.unit
@pytest.mark.requirement("CORE-26")
def test_the_baseline_marks_two_types_forward_only_and_the_registry_respects_it() -> None:
    """W1 declared `TraversalBehavior` "consumed at W5". This is the consumption."""
    assert FORWARD_ONLY == {"contains", "justifies"}

    for declared in POLICIES.values():
        if declared.direction is Direction.REVERSE:
            assert not set(declared.allowed_relationship_types) & FORWARD_ONLY


@pytest.mark.unit
@pytest.mark.requirement("CORE-26")
def test_a_forward_only_type_cannot_be_traversed_backwards() -> None:
    """The refusal that stops a plausible-looking answer nobody can defend."""
    with pytest.raises(PolicyError, match="does not permit"):
        check_policy(policy(allowed_relationship_types=("contains",), direction=Direction.REVERSE))


@pytest.mark.unit
@pytest.mark.requirement("CORE-26")
def test_a_relationship_type_the_profile_does_not_define_is_refused() -> None:
    with pytest.raises(PolicyError, match="does not define"):
        check_policy(policy(allowed_relationship_types=("invented_type",)))


@pytest.mark.unit
@pytest.mark.requirement("CORE-26")
def test_a_node_kind_the_profile_does_not_define_is_refused() -> None:
    with pytest.raises(PolicyError, match="node kinds"):
        check_policy(policy(allowed_node_kinds=("software.invented",)))


@pytest.mark.unit
@pytest.mark.requirement("CORE-26")
def test_the_default_impact_policy_excludes_ownership_and_documentation_edges() -> None:
    """The wave's own warning, as a test.

    `responsible_for` names who is accountable and `justifies` names why something exists. Neither
    carries a change through the system, and following them would turn every requirement author
    and every owning role into an impacted party.
    """
    impact = policy_for("impact.structural")

    assert "justifies" not in impact.allowed_relationship_types
    assert "responsible_for" not in impact.allowed_relationship_types
    assert set(impact.allowed_relationship_types) == {
        "contains",
        "depends_on",
        "exchanges_data_with",
        "exposes",
        "realizes",
        "supports",
    }


@pytest.mark.unit
@pytest.mark.requirement("CORE-26", "CORE-29")
@pytest.mark.parametrize("policy_id", sorted(POLICIES))
def test_every_policy_declares_all_three_caps(policy_id: str) -> None:
    """CORE-29 forbids unbounded enumeration, so a policy with no bound cannot exist."""
    declared = POLICIES[policy_id]

    assert declared.max_depth >= 1
    assert declared.max_paths >= 1
    assert declared.max_results >= 1


@pytest.mark.unit
@pytest.mark.requirement("CORE-29")
def test_a_cap_of_zero_is_not_expressible() -> None:
    """A bound of zero would be an unbounded traversal spelled as a bounded one."""
    with pytest.raises(ValueError, match="max_depth"):
        policy(max_depth=0)


@pytest.mark.unit
@pytest.mark.requirement("CORE-27")
def test_an_empty_kind_list_means_every_kind_rather_than_none() -> None:
    """A policy naming every kind would need editing by every project that adds one."""
    declared = policy()

    assert declared.permits_kind("software.system")
    assert policy(allowed_node_kinds=("software.system",)).permits_kind("software.system")
    assert not policy(allowed_node_kinds=("software.system",)).permits_kind("business.process")
    assert not policy(excluded_node_kinds=("software.system",)).permits_kind("software.system")


@pytest.mark.unit
@pytest.mark.requirement("CORE-27")
def test_an_empty_context_filter_accepts_a_relationship_with_no_context() -> None:
    """`context_id` is written by nothing today, so the default must not exclude every edge."""
    assert policy().permits_context(None)
    assert policy(context_filters=("ctx-1",)).permits_context("ctx-1")
    assert not policy(context_filters=("ctx-1",)).permits_context(None)
    assert not policy(context_filters=("ctx-1",)).permits_context("ctx-2")


@pytest.mark.unit
@pytest.mark.requirement("CORE-26")
def test_an_unknown_policy_is_refused_by_name() -> None:
    with pytest.raises(UnknownPolicyError, match="unknown graph policy"):
        policy_for("no.such.policy")

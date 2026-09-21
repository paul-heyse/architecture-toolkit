"""A design alternative is not a later revision of its baseline (DATA-28).

> Alternatives/scenarios have separate model/scenario identity plus explicit baseline, not
> sequential release semantics. — data.md

and `ARCH-TOOL-DATA-001` §6B: *"Its existence does not imply that it superseded or was selected
over the current design."*

The requirement's teeth are in the refusals, not in the two new manifest fields, so most of this
file is about what the toolkit declines to do. Physical separation needs no new machinery: one
store has one current pointer and overwrites its tables wholesale, so an alternative is published
into its own store root, which `--store` already provides — and that also keeps it clear of
`CORE.RELEASE.MULTIPLE_ROOTS`, which a second root in one store would trip.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from architecture_toolkit.changes.alternatives import compare_alternative
from architecture_toolkit.changes.errors import LineageError
from architecture_toolkit.changes.kinds import ChangeKind
from architecture_toolkit.changes.record import ArchitectureChangeSet
from architecture_toolkit.changes.releases import diff_releases
from architecture_toolkit.domain.model import Model
from architecture_toolkit.releases.candidate import ReleaseCandidate
from architecture_toolkit.releases.errors import ReleaseError
from architecture_toolkit.releases.lineage import ancestors, is_ancestor, lineage_of
from architecture_toolkit.releases.manifest import ArchitectureRelease
from architecture_toolkit.releases.provenance import source_bundle
from architecture_toolkit.releases.publication import PublicationRequest, publish
from architecture_toolkit.releases.store import ReleaseStore
from architecture_toolkit.validation.release import alternative_line_breaks
from tests.integration.conftest import Publisher, rename_first_element

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "minimal" / "model.yaml"
MOMENT = datetime(2026, 9, 20, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def scenario_store(tmp_path: Path) -> ReleaseStore:
    """An alternative lives in its own store root, which is all the separation it needs."""
    return ReleaseStore.at(tmp_path / "alternative").initialize()


def publish_alternative(
    store: ReleaseStore,
    model: Model,
    *,
    release_id: str = "rel-0001",
    scenario_id: str = "alt-thinner-api",
    baseline_release_id: str = "rel-0001",
) -> ArchitectureRelease:
    return publish(
        PublicationRequest(
            store=store,
            candidate=ReleaseCandidate(
                release_id=release_id,
                model=model,
                source_bundle=source_bundle(source_id="alt", text=EXAMPLE.read_text()),
                scenario_id=scenario_id,
                baseline_release_id=baseline_release_id,
            ),
            expected_parent=None,
            now=lambda: MOMENT,
            generator_commit="abc1234",
        )
    )


# -- identity and reference -------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requirement("DATA-28")
def test_an_alternative_carries_its_own_identity_and_names_its_baseline(
    scenario_store: ReleaseStore, example_model: Model
) -> None:
    alternative = publish_alternative(
        scenario_store, rename_first_element(example_model, "Thinner API")
    )

    assert alternative.is_alternative
    assert alternative.scenario_id == "alt-thinner-api"
    assert alternative.baseline_release_id == "rel-0001"
    # The relation that is *not* claimed: an alternative has no position in the baseline chain.
    assert alternative.parent_release_id is None


@pytest.mark.integration
@pytest.mark.requirement("DATA-28")
def test_a_baseline_release_claims_neither_field(
    example_model: Model, publish_release: Publisher
) -> None:
    """The negative control for the test above: the fields are not set on everything."""
    baseline = publish_release("rel-0001", example_model, expected_parent=None)

    assert not baseline.is_alternative
    assert baseline.scenario_id is None
    assert baseline.baseline_release_id is None


# -- the refusals -----------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requirement("DATA-28")
def test_a_scenario_identity_without_a_baseline_is_refused(
    example_model: Model, publish_release: Publisher
) -> None:
    """Half the relation is not the relation; an orphan alternative interprets to nothing."""
    baseline = publish_release("rel-0001", example_model, expected_parent=None)

    with pytest.raises(ValidationError, match="sets one of scenario_id"):
        baseline.model_validate(dict(baseline) | {"scenario_id": "alt-a"})

    with pytest.raises(ValidationError, match="sets one of scenario_id"):
        baseline.model_validate(dict(baseline) | {"baseline_release_id": "rel-0001"})


@pytest.mark.integration
@pytest.mark.requirement("DATA-28")
def test_an_alternative_whose_parent_is_its_baseline_is_refused(
    example_model: Model, publish_release: Publisher
) -> None:
    """Sequential release semantics, spelled out: a parent supersedes, a baseline does not."""
    baseline = publish_release("rel-0001", example_model, expected_parent=None)

    with pytest.raises(ValidationError, match="both its parent and its baseline"):
        baseline.model_validate(
            dict(baseline)
            | {
                "release_id": "rel-0002",
                "scenario_id": "alt-a",
                "baseline_release_id": "rel-0001",
                "parent_release_id": "rel-0001",
            }
        )


@pytest.mark.integration
@pytest.mark.requirement("DATA-28")
def test_diffing_a_baseline_against_an_alternative_is_refused_and_says_what_to_do(
    store: ReleaseStore,
    scenario_store: ReleaseStore,
    example_model: Model,
    publish_release: Publisher,
) -> None:
    """The failure DATA-28 exists to prevent: an alternative presented as a change somebody made."""
    baseline = publish_release("rel-0001", example_model, expected_parent=None)
    alternative = publish_alternative(
        scenario_store, rename_first_element(example_model, "Thinner API")
    )

    with pytest.raises(ReleaseError, match="not a later revision of its baseline"):
        diff_releases(store, baseline, alternative)

    # And the operation that *is* right for the pair works, so the refusal is a redirection rather
    # than a dead end.
    comparison = compare_alternative(
        baseline, alternative, baseline_store=store, alternative_store=scenario_store
    )
    assert comparison.kinds == {ChangeKind.ELEMENT_RENAMED}


@pytest.mark.integration
@pytest.mark.requirement("DATA-28")
def test_an_alternative_is_compared_only_against_the_baseline_it_declares(
    store: ReleaseStore,
    scenario_store: ReleaseStore,
    example_model: Model,
    publish_release: Publisher,
) -> None:
    """Comparing against some other release looks authoritative and answers nobody's question."""
    publish_release("rel-0001", example_model, expected_parent=None)
    second = publish_release(
        "rel-0002", rename_first_element(example_model, "Renamed"), expected_parent="rel-0001"
    )
    alternative = publish_alternative(
        scenario_store, rename_first_element(example_model, "Thinner API")
    )

    with pytest.raises(LineageError, match="declares 'rel-0001' as its baseline"):
        compare_alternative(
            second, alternative, baseline_store=store, alternative_store=scenario_store
        )


@pytest.mark.integration
@pytest.mark.requirement("DATA-28")
def test_a_revision_is_not_compared_as_an_alternative(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """Both directions. A diff dressed as an alternative comparison is the same error inverted."""
    baseline = publish_release("rel-0001", example_model, expected_parent=None)
    second = publish_release(
        "rel-0002", rename_first_element(example_model, "Renamed"), expected_parent="rel-0001"
    )

    with pytest.raises(LineageError, match="is not an alternative"):
        compare_alternative(baseline, second, baseline_store=store, alternative_store=store)


# -- the comparison is not a change set ---------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requirement("DATA-28")
def test_an_alternative_comparison_cannot_be_published_as_a_change_set(
    store: ReleaseStore,
    scenario_store: ReleaseStore,
    example_model: Model,
    publish_release: Publisher,
) -> None:
    """Enforced by the type, not by a convention somebody has to remember.

    `ArchitectureChangeSet.changes` is a `ModelChanges`, and an `AlternativeComparison` is not one
    and does not contain one — the same enforcement-by-missing-field W5 used to stop a derived
    reachability edge from claiming a relationship identity.
    """
    baseline = publish_release("rel-0001", example_model, expected_parent=None)
    alternative = publish_alternative(
        scenario_store, rename_first_element(example_model, "Thinner API")
    )

    comparison = compare_alternative(
        baseline, alternative, baseline_store=store, alternative_store=scenario_store
    )

    assert not hasattr(comparison, "narrative")
    assert "changes" not in type(comparison).model_fields
    assert "narrative" not in type(comparison).model_fields
    with pytest.raises(ValidationError):
        ArchitectureChangeSet.model_validate(
            {
                "change_set_id": "cs-0001",
                "model_id": example_model.model_id,
                "authored_by": {"author_id": "someone", "author_kind": "person"},
                "changes": comparison,
            }
        )


# -- lineage on the read side -------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requirement("DATA-28")
def test_lineage_walks_the_chain_and_an_alternative_is_not_on_it(
    store: ReleaseStore,
    scenario_store: ReleaseStore,
    example_model: Model,
    publish_release: Publisher,
) -> None:
    """`parent_release_id` has been written since W4 and read back by nothing until now."""
    first = publish_release("rel-0001", example_model, expected_parent=None)
    second = publish_release(
        "rel-0002", rename_first_element(example_model, "Renamed"), expected_parent="rel-0001"
    )
    third = publish_release(
        "rel-0003", rename_first_element(example_model, "Again"), expected_parent="rel-0002"
    )
    alternative = publish_alternative(
        scenario_store, rename_first_element(example_model, "Thinner API")
    )

    assert lineage_of(store, third) == ("rel-0003", "rel-0002", "rel-0001")
    assert is_ancestor(store, first, of=third)
    assert not is_ancestor(store, third, of=first)
    assert [item.release_id for item in ancestors(store, second)] == ["rel-0001"]
    # The alternative has no ancestors at all: it was derived, not descended.
    assert list(ancestors(scenario_store, alternative)) == []
    assert not is_ancestor(scenario_store, alternative, of=alternative)


@pytest.mark.integration
@pytest.mark.requirement("DATA-28")
def test_a_scenario_whose_parent_is_on_another_line_is_reported() -> None:
    """The hole the record-local validator cannot see: the *parent's* line.

    A manifest knows its own scenario id and its parent's id, but not its parent's scenario id, so
    "derived from the baseline" and "descended from the baseline history" are indistinguishable
    without looking at both. This is the store-level half.
    """
    broken = alternative_line_breaks([("rel-0001", None, None), ("rel-0002", "rel-0001", "alt-a")])

    assert [finding.code for finding in broken] == ["CORE.RELEASE.ALTERNATIVE_LINE_BROKEN"]
    assert "alt-a" in broken[0].message
    assert "baseline" in broken[0].message

    # The negative control: the same shape, both releases on the same line, reports nothing.
    assert (
        alternative_line_breaks([("rel-0001", None, "alt-a"), ("rel-0002", "rel-0001", "alt-a")])
        == ()
    )
    assert alternative_line_breaks([("rel-0001", None, None), ("rel-0002", "rel-0001", None)]) == ()

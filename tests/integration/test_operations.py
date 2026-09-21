"""The eight lifecycle operations, in the order the contract states them (DATA-38).

> Load baseline -> apply typed change set -> validate -> preview semantic diff and impact ->
> obtain required review -> persist -> publish release -> generate outputs.

The first test walks the whole sequence once, because DATA-38 is about the operations being one
surface rather than eight things that happen to exist; the rest are the refusals, which is where
the requirement actually bites.
"""

from pathlib import Path

import pytest

from architecture_toolkit.changes.errors import ChangeError, ReviewError
from architecture_toolkit.changes.kinds import ChangeKind
from architecture_toolkit.changes.operations import (
    ArchitectureOperations,
    OutputNotImplemented,
)
from architecture_toolkit.changes.record import AuthorKind, Authorship, ReviewDecision
from architecture_toolkit.domain.commands import ChangeSet, RenameElement
from architecture_toolkit.domain.model import Model
from architecture_toolkit.releases.candidate import ReleaseCandidate
from architecture_toolkit.releases.provenance import source_bundle
from architecture_toolkit.releases.publication import PublicationRequest
from architecture_toolkit.releases.recovery import is_orphan, resume
from architecture_toolkit.releases.store import ReleaseStore
from tests.integration.conftest import MOMENT, Publisher

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "minimal" / "model.yaml"
AGENT = Authorship(author_id="agent-01", author_kind=AuthorKind.AGENT, tool="architecture-toolkit")
REVIEWER = Authorship(author_id="reviewer-01", author_kind=AuthorKind.PERSON)


@pytest.fixture
def ops(store: ReleaseStore) -> ArchitectureOperations:
    return ArchitectureOperations(store=store, now=lambda: MOMENT)


def rename_command(model: Model, new_name: str) -> ChangeSet:
    victim = model.elements[0]
    return ChangeSet(
        change_set_id="cs-0001",
        model_id=model.model_id,
        commands=(
            RenameElement(
                element_id=victim.element_id, expected_name=victim.name, new_name=new_name
            ),
        ),
    )


def request_for(
    store: ReleaseStore, model: Model, release_id: str, parent: str | None
) -> PublicationRequest:
    return PublicationRequest(
        store=store,
        candidate=ReleaseCandidate(
            release_id=release_id,
            model=model,
            source_bundle=source_bundle(source_id="s", text=EXAMPLE.read_text()),
        ),
        expected_parent=parent,
        now=lambda: MOMENT,
        generator_commit="abc1234",
    )


@pytest.mark.integration
@pytest.mark.requirement("DATA-38", "DATA-26")
def test_the_whole_lifecycle_runs_through_one_surface(
    store: ReleaseStore,
    ops: ArchitectureOperations,
    example_model: Model,
    publish_release: Publisher,
) -> None:
    """All eight, in order, with the assertion that matters stated at each step."""
    publish_release("rel-0001", example_model, expected_parent=None)

    # 1. baseline — read back from the release, not re-parsed from source.
    baseline = ops.baseline()
    assert baseline.model_id == example_model.model_id

    # 2. change
    commands = rename_command(baseline, "Portfolio Technology Evaluation")
    candidate = ops.change(baseline, commands)
    assert candidate.elements[0].name == "Portfolio Technology Evaluation"

    # 3. validate
    report = ops.validate(candidate)
    assert report.hard_errors == ()

    # 4. diff and impact, both *before* anything is persisted.
    changes = ops.diff(baseline, candidate)
    assert changes.kinds == {ChangeKind.ELEMENT_RENAMED}
    impact = ops.impact(changes)

    record = ops.change_set(
        change_set_id="cs-0001",
        changes=changes,
        authored_by=AGENT,
        base_release_id="rel-0001",
        command_change_set_id=commands.change_set_id,
        rationale="Align the capability name with the accepted decision.",
        validation=report,
        impact=impact,
    )
    assert record.is_preview
    assert not record.is_approved

    # 5. review
    reviewed = ops.review(record, reviewer=REVIEWER, decision=ReviewDecision.APPROVED)
    assert reviewed.is_approved
    assert reviewed.review is not None
    assert reviewed.review.reviewed_at == MOMENT

    # 6. persist — the manifest exists and is not current.
    staged = ops.persist(request_for(store, candidate, "rel-0002", "rel-0001"), change_set=reviewed)
    assert staged.release_id == "rel-0002"
    assert store.current_id() == "rel-0001"
    assert is_orphan(store, "rel-0002")

    # 7. publish — here, by finishing what persist started.
    published = resume(store, "rel-0002")
    assert store.current_id() == "rel-0002"
    assert published.parent_release_id == "rel-0001"

    # The preview was honest: the same narrative comes back out of the published pair.
    assert ops.diff_published("rel-0001", "rel-0002").records == changes.records

    # 8. output
    assert isinstance(ops.output(), OutputNotImplemented)
    assert ops.output().release_id == "rel-0002"


@pytest.mark.integration
@pytest.mark.requirement("DATA-38")
def test_persist_leaves_the_current_pointer_where_it_was(
    store: ReleaseStore,
    ops: ArchitectureOperations,
    example_model: Model,
    publish_release: Publisher,
) -> None:
    """The distinction between persist and publish is the eighth protocol line and nothing else."""
    publish_release("rel-0001", example_model, expected_parent=None)
    candidate = ops.change(ops.baseline(), rename_command(ops.baseline(), "Renamed"))

    ops.persist(request_for(store, candidate, "rel-0002", "rel-0001"))

    assert store.has_manifest("rel-0002")
    assert store.current_id() == "rel-0001"
    assert is_orphan(store, "rel-0002")


@pytest.mark.integration
@pytest.mark.requirement("DATA-38")
def test_publishing_without_the_required_review_is_refused(
    store: ReleaseStore,
    ops: ArchitectureOperations,
    example_model: Model,
    publish_release: Publisher,
) -> None:
    """An absent review is not an approval, and a rejected one is certainly not."""
    publish_release("rel-0001", example_model, expected_parent=None)
    baseline = ops.baseline()
    candidate = ops.change(baseline, rename_command(baseline, "Renamed"))
    record = ops.change_set(
        change_set_id="cs-0001",
        changes=ops.diff(baseline, candidate),
        authored_by=AGENT,
        base_release_id="rel-0001",
        validation=ops.validate(candidate),
    )
    request = request_for(store, candidate, "rel-0002", "rel-0001")

    with pytest.raises(ReviewError, match="an absent review is not an approval"):
        ops.publish(request, change_set=record, require_review=True)

    rejected = ops.review(record, reviewer=REVIEWER, decision=ReviewDecision.REJECTED)
    with pytest.raises(ReviewError, match=r"review: rejected"):
        ops.publish(request, change_set=rejected, require_review=True)

    # The positive control, so the refusal is not simply "publish never works with a review".
    approved = ops.review(record, reviewer=REVIEWER, decision=ReviewDecision.APPROVED)
    published = ops.publish(request, change_set=approved, require_review=True)
    assert published.release_id == "rel-0002"
    assert store.current_id() == "rel-0002"


@pytest.mark.integration
@pytest.mark.requirement("DATA-38")
def test_requiring_a_review_of_nothing_is_refused_rather_than_silently_satisfied(
    store: ReleaseStore,
    ops: ArchitectureOperations,
    example_model: Model,
    publish_release: Publisher,
) -> None:
    """The vacuous pass this guard would otherwise have: no change set, so nothing to approve."""
    publish_release("rel-0001", example_model, expected_parent=None)
    candidate = ops.change(ops.baseline(), rename_command(ops.baseline(), "Renamed"))

    with pytest.raises(ReviewError, match="carries no change set"):
        ops.publish(
            request_for(store, candidate, "rel-0002", "rel-0001"),
            change_set=None,
            require_review=True,
        )


@pytest.mark.integration
@pytest.mark.requirement("DATA-38", "DATA-26")
def test_a_change_set_with_hard_validation_errors_is_not_publishable(
    store: ReleaseStore,
    ops: ArchitectureOperations,
    example_model: Model,
    publish_release: Publisher,
) -> None:
    """Validation results are carried so they can be acted on, not so they can be displayed."""
    publish_release("rel-0001", example_model, expected_parent=None)
    baseline = ops.baseline()
    candidate = ops.change(baseline, rename_command(baseline, "Renamed"))
    broken = example_model.model_validate(
        dict(example_model)
        | {"relationships": (*example_model.relationships, _dangling(example_model))}
    )
    record = ops.change_set(
        change_set_id="cs-0001",
        changes=ops.diff(baseline, candidate),
        authored_by=AGENT,
        validation=ops.validate(broken),
    )

    assert record.has_hard_errors
    with pytest.raises(ChangeError, match="hard validation errors"):
        ops.publish(request_for(store, candidate, "rel-0002", "rel-0001"), change_set=record)


def _dangling(model: Model) -> object:
    from architecture_toolkit.domain.model import Relationship

    return Relationship(
        relationship_id="rel-dangling",
        model_id=model.model_id,
        relationship_type_id="depends_on",
        source_element_id="system-1",
        target_element_id="nowhere-1",
    )


@pytest.mark.integration
@pytest.mark.requirement("DATA-38")
def test_a_store_with_no_current_release_refuses_to_invent_a_baseline(
    ops: ArchitectureOperations,
) -> None:
    with pytest.raises(ChangeError, match="no current release"):
        ops.baseline()


@pytest.mark.integration
@pytest.mark.requirement("DATA-26", "CORE-30")
def test_impact_reports_what_a_changed_element_reaches(
    ops: ArchitectureOperations, example_model: Model, publish_release: Publisher
) -> None:
    """DATA-26 wants impact-analysis results on the record, which is why this package can import
    `queries/`. An empty tuple here would satisfy the field's type and none of its purpose."""
    publish_release("rel-0001", example_model, expected_parent=None)
    baseline = ops.baseline()
    victim = next(item for item in baseline.elements if item.element_id == "system-1")
    renamed = baseline.model_validate(
        dict(baseline)
        | {
            "elements": tuple(
                item.model_validate(dict(item) | {"name": "Renamed System"})
                if item.element_id == victim.element_id
                else item
                for item in baseline.elements
            )
        }
    )

    impact = ops.impact(ops.diff(baseline, renamed))

    assert len(impact) == 1
    assert impact[0].start == "system-1"
    assert impact[0].reached
    assert impact[0].policy_id == "impact.structural"


@pytest.mark.integration
@pytest.mark.requirement("DATA-26")
def test_impact_of_a_presentation_only_change_is_empty(
    ops: ArchitectureOperations, example_model: Model, publish_release: Publisher
) -> None:
    """A layout edit reaches nothing, because it is not in the narrative to start from."""
    publish_release("rel-0001", example_model, expected_parent=None)
    baseline = ops.baseline()
    binding = baseline.notation_bindings[0]
    relaid = baseline.model_validate(
        dict(baseline)
        | {"notation_bindings": (binding.model_validate(dict(binding) | {"link_target": "a.svg"}),)}
    )

    changes = ops.diff(baseline, relaid)

    assert changes.presentation
    assert ops.impact(changes) == ()


@pytest.mark.integration
@pytest.mark.requirement("DATA-38", "DATA-26")
def test_a_change_set_that_was_never_validated_is_not_publishable(
    store: ReleaseStore,
    ops: ArchitectureOperations,
    example_model: Model,
    publish_release: Publisher,
) -> None:
    """ "Clean" and "unexamined" are different, and for one wave only a docstring said so.

    `has_hard_errors` is `False` when `validation is None`, which is correct — there are no errors
    because nothing looked. The refusal for the second case has to be separate, and the docstring
    claiming `publish` made it was describing a check that did not exist.
    """
    publish_release("rel-0001", example_model, expected_parent=None)
    baseline = ops.baseline()
    candidate = ops.change(baseline, rename_command(baseline, "Renamed"))
    unexamined = ops.change_set(
        change_set_id="cs-0001", changes=ops.diff(baseline, candidate), authored_by=AGENT
    )

    assert not unexamined.has_hard_errors
    with pytest.raises(ChangeError, match="an unexamined model is not a clean one"):
        ops.publish(request_for(store, candidate, "rel-0002", "rel-0001"), change_set=unexamined)

    # The positive control: the same change set with a report publishes.
    examined = unexamined.model_validate(dict(unexamined) | {"validation": ops.validate(candidate)})
    published = ops.publish(
        request_for(store, candidate, "rel-0002", "rel-0001"), change_set=examined
    )
    assert published.release_id == "rel-0002"

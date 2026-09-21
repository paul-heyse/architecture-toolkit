"""The eight-step publication protocol (DATA-21, DATA-22, DATA-23, DATA-24)."""

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from architecture_toolkit.domain.authoring import parse_model, parse_source
from architecture_toolkit.domain.commands import ChangeSet, RenameElement
from architecture_toolkit.domain.model import Model
from architecture_toolkit.domain.protocols import Publisher
from architecture_toolkit.domain.semantics import model_digest, stamp_digests
from architecture_toolkit.releases.candidate import ReleaseCandidate, next_release_id
from architecture_toolkit.releases.errors import (
    PublicationLockError,
    ReleaseError,
    StaleParentError,
)
from architecture_toolkit.releases.lock import publication_lock
from architecture_toolkit.releases.manifest import ArchitectureRelease
from architecture_toolkit.releases.provenance import source_bundle
from architecture_toolkit.releases.publication import (
    STEP_ORDER,
    STEPS,
    DeltaPublisher,
    PublicationRequest,
    PublicationState,
    publish,
)
from architecture_toolkit.releases.reader import read_model
from architecture_toolkit.releases.staging import StagingOutcome
from architecture_toolkit.releases.store import ReleaseStore
from architecture_toolkit.storage.schemas import TABLE_IDS

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "minimal" / "model.yaml"
CONTRACT = ROOT / "docs" / "contracts" / "data.md"
MOMENT = datetime(2026, 9, 20, 12, 0, 0, tzinfo=UTC)


def example_text() -> str:
    return EXAMPLE.read_text()


def example() -> Model:
    return parse_model(parse_source(example_text(), source_id="example"))


def candidate(release_id: str, model: Model | None = None) -> ReleaseCandidate:
    return ReleaseCandidate(
        release_id=release_id,
        model=model if model is not None else example(),
        source_bundle=source_bundle(source_id="examples/minimal/model.yaml", text=example_text()),
    )


def request(
    store: ReleaseStore,
    release_id: str,
    *,
    expected_parent: str | None,
    model: Model | None = None,
    change_set: ChangeSet | None = None,
    attempt: int = 1,
) -> PublicationRequest:
    return PublicationRequest(
        store=store,
        candidate=candidate(release_id, model),
        expected_parent=expected_parent,
        change_set=change_set,
        attempt=attempt,
        now=lambda: MOMENT,
        generator_commit="abc1234",
    )


# -- the protocol itself --------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.requirement("DATA-23")
def test_the_step_order_is_the_contract_fence_verbatim() -> None:
    """The eight steps are quoted from `data.md`, so a renamed step must fail rather than drift."""
    fence = re.search(r"```text\n(load expected parent.*?)```", CONTRACT.read_text(), re.DOTALL)
    assert fence is not None, "data.md no longer states the protocol as a text fence"
    steps = tuple(
        line.strip().removeprefix("-> ").strip()
        for line in fence.group(1).splitlines()
        if line.strip()
    )
    assert steps == STEP_ORDER


@pytest.mark.integration
@pytest.mark.requirement("DATA-21", "DATA-23")
def test_a_first_publication_pins_every_table_and_becomes_current(tmp_path: Path) -> None:
    store = ReleaseStore.at(tmp_path).initialize()
    manifest = publish(request(store, "rel-0001", expected_parent=None))

    assert tuple(ref.table_id for ref in manifest.tables) == TABLE_IDS
    assert manifest.parent_release_id is None
    assert manifest.published_at == MOMENT
    assert manifest.generator.toolkit_commit == "abc1234"
    assert store.current_id() == "rel-0001"
    assert store.current() == manifest
    # The release reads back as the model that was published.
    assert model_digest(read_model(store, manifest)) == model_digest(stamp_digests(example()))


@pytest.mark.integration
@pytest.mark.requirement("DATA-21")
def test_the_manifest_pins_its_validation_report(tmp_path: Path) -> None:
    """DATA-21 asks a release to pin its validation report, so the report has to outlive the run."""
    store = ReleaseStore.at(tmp_path).initialize()
    manifest = publish(request(store, "rel-0001", expected_parent=None))
    report = store.artifact_dir("rel-0001") / "validation-report.json"
    assert report.is_file()
    assert manifest.validation_report_digest is not None
    assert manifest.validation_report_digest.startswith("sha256:")


@pytest.mark.integration
@pytest.mark.requirement("DATA-23")
def test_a_stale_expected_parent_fails_and_changes_nothing(tmp_path: Path) -> None:
    """The DATA-23 gate. Raised by step one, before anything is written."""
    store = ReleaseStore.at(tmp_path).initialize()
    publish(request(store, "rel-0001", expected_parent=None))
    before = store.current_id()

    with pytest.raises(StaleParentError, match="expected parent"):
        publish(request(store, "rel-0002", expected_parent=None))

    assert store.current_id() == before
    assert not store.has_manifest("rel-0002")


@pytest.mark.integration
@pytest.mark.requirement("DATA-23")
def test_publishing_against_the_wrong_parent_fails(tmp_path: Path) -> None:
    store = ReleaseStore.at(tmp_path).initialize()
    publish(request(store, "rel-0001", expected_parent=None))
    with pytest.raises(StaleParentError):
        publish(request(store, "rel-0002", expected_parent="rel-0009", attempt=2))
    assert store.current_id() == "rel-0001"


@pytest.mark.integration
@pytest.mark.requirement("DATA-22")
def test_a_second_release_reuses_the_versions_it_did_not_change(tmp_path: Path) -> None:
    """Two manifests side by side: one pin moved, ten did not."""
    store = ReleaseStore.at(tmp_path).initialize()
    first = publish(request(store, "rel-0001", expected_parent=None))

    model = example()
    victim = model.elements[0]
    change_set = ChangeSet(
        change_set_id="cs-0001",
        model_id=model.model_id,
        expected_base_digest=model_digest(stamp_digests(model)),
        commands=(
            RenameElement(
                element_id=victim.element_id, expected_name=victim.name, new_name="Renamed"
            ),
        ),
    )
    second = publish(
        request(store, "rel-0002", expected_parent="rel-0001", change_set=change_set, attempt=2)
    )

    before = dict(first.pinned_versions)
    after = dict(second.pinned_versions)
    assert after["elements"] == before["elements"] + 1
    assert {t: after[t] for t in TABLE_IDS if t != "elements"} == {
        t: before[t] for t in TABLE_IDS if t != "elements"
    }
    assert second.parent_release_id is None or second.parent_release_id == "rel-0001"
    assert store.current_id() == "rel-0002"


@pytest.mark.integration
@pytest.mark.requirement("DATA-23")
def test_a_change_set_expecting_a_different_baseline_is_refused(tmp_path: Path) -> None:
    """`ChangeSet.expected_base_digest` has existed since W1 and this is its first reader."""
    store = ReleaseStore.at(tmp_path).initialize()
    publish(request(store, "rel-0001", expected_parent=None))
    model = example()
    stale = ChangeSet(
        change_set_id="cs-0001",
        model_id=model.model_id,
        expected_base_digest="sha256:" + "f" * 64,
        commands=(
            RenameElement(
                element_id=model.elements[0].element_id,
                expected_name=model.elements[0].name,
                new_name="Renamed",
            ),
        ),
    )
    with pytest.raises(StaleParentError, match="different baseline"):
        publish(request(store, "rel-0002", expected_parent="rel-0001", change_set=stale, attempt=2))
    assert store.current_id() == "rel-0001"


@pytest.mark.integration
@pytest.mark.requirement("DATA-21")
def test_a_manifest_is_never_overwritten(tmp_path: Path) -> None:
    store = ReleaseStore.at(tmp_path).initialize()
    publish(request(store, "rel-0001", expected_parent=None))
    with pytest.raises(ReleaseError, match="already published"):
        publish(request(store, "rel-0001", expected_parent="rel-0001", attempt=2))


@pytest.mark.integration
@pytest.mark.requirement("DATA-23")
def test_a_second_writer_is_refused_while_the_lock_is_held(tmp_path: Path) -> None:
    """One local writer is the contract; the lock is how it is kept."""
    store = ReleaseStore.at(tmp_path).initialize()
    with publication_lock(store.lock_path):
        with pytest.raises(PublicationLockError, match="is held by"):
            publish(request(store, "rel-0001", expected_parent=None))
    assert store.current_id() is None
    # The lock is released, so publication works immediately afterwards.
    publish(request(store, "rel-0001", expected_parent=None))
    assert store.current_id() == "rel-0001"


@pytest.mark.integration
@pytest.mark.requirement("DATA-23")
def test_the_lock_is_released_even_when_a_step_raises(tmp_path: Path) -> None:
    store = ReleaseStore.at(tmp_path).initialize()
    with pytest.raises(StaleParentError):
        publish(request(store, "rel-0001", expected_parent="rel-9999"))
    assert not store.lock_path.exists()


@pytest.mark.integration
@pytest.mark.requirement("DATA-54")
def test_retrying_one_attempt_publishes_the_same_versions(tmp_path: Path) -> None:
    """A retry after a crash between staging and the pointer move must not double-write."""
    store = ReleaseStore.at(tmp_path).initialize()
    first = publish(request(store, "rel-0001", expected_parent=None, attempt=1))
    versions = dict(first.pinned_versions)

    # Same attempt number, new release id: every table is already committed, so nothing is
    # written again and the pins are identical.
    second = publish(request(store, "rel-0002", expected_parent="rel-0001", attempt=1))
    assert dict(second.pinned_versions) == versions


@pytest.mark.integration
@pytest.mark.requirement("CORE-58", "DATA-21")
def test_the_shipped_publisher_satisfies_the_protocol(tmp_path: Path) -> None:
    store = ReleaseStore.at(tmp_path).initialize()
    publisher: Publisher = DeltaPublisher(store)
    assert isinstance(publisher, Publisher)
    manifest = publisher.publish(candidate(next_release_id(())), expected_parent=None)
    assert isinstance(manifest, ArchitectureRelease)
    assert store.current_id() == manifest.release_id


@pytest.mark.integration
@pytest.mark.requirement("DATA-22")
def test_every_table_is_written_once_on_a_first_publication(tmp_path: Path) -> None:

    store = ReleaseStore.at(tmp_path).initialize()
    state = PublicationState(request=request(store, "rel-0001", expected_parent=None))
    for name in STEP_ORDER[:4]:
        state = STEPS[name](state)
    assert {item.outcome for item in state.staged} == {StagingOutcome.WRITTEN}

"""Completing or clearing a publication that crashed between steps seven and eight (DATA-24)."""

import sys
from pathlib import Path

import pytest

from architecture_toolkit.cli import main
from architecture_toolkit.domain.model import Model
from architecture_toolkit.domain.semantics import model_digest
from architecture_toolkit.releases.candidate import ReleaseCandidate
from architecture_toolkit.releases.errors import ReleaseError, StaleParentError
from architecture_toolkit.releases.provenance import source_bundle
from architecture_toolkit.releases.publication import PublicationRequest, publish
from architecture_toolkit.releases.reader import read_model
from architecture_toolkit.releases.recovery import discard, is_orphan, orphans, resume
from architecture_toolkit.releases.store import ReleaseStore
from architecture_toolkit.storage import delta
from architecture_toolkit.storage.schemas import TABLE_IDS
from tests.integration.conftest import MOMENT, Publisher, rename_first_element
from tests.integration.test_publication_faults import InjectedFailure, a_request, failing_at

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "minimal" / "model.yaml"


def crash_after_the_manifest(store: ReleaseStore, release_id: str, parent: str | None) -> None:
    """Exactly the W4 gate's step-eight case: manifest written, pointer never moved."""
    with pytest.raises(InjectedFailure):
        publish(
            a_request(store, release_id, expected_parent=parent),
            steps=failing_at("atomically move current pointer"),
        )


def a_request_for(
    store: ReleaseStore, release_id: str, model: Model, *, expected_parent: str | None
) -> PublicationRequest:
    """`a_request` with a model of the caller's choosing, so a crash can change content."""
    return PublicationRequest(
        store=store,
        candidate=ReleaseCandidate(
            release_id=release_id,
            model=model,
            source_bundle=source_bundle(source_id="s", text=EXAMPLE.read_text()),
        ),
        expected_parent=expected_parent,
        now=lambda: MOMENT,
        generator_commit="abc1234",
    )


def run(monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["architecture", *argv])
    return main()


# -- detecting one -------------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requirement("DATA-24", "DATA-21")
def test_an_orphan_is_detectable_only_because_the_chain_links(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """Before `parent_release_id` was populated, "a manifest nobody points at" and "a superseded
    manifest" were the same thing, so this could not have been written."""
    publish_release("rel-0001", example_model, expected_parent=None)
    publish_release(
        "rel-0002", rename_first_element(example_model, "Second"), expected_parent="rel-0001"
    )
    # A superseded release is not an orphan: rel-0002 names it.
    assert orphans(store) == ()

    crash_after_the_manifest(store, "rel-0003", "rel-0002")
    assert orphans(store) == ("rel-0003",)
    assert is_orphan(store, "rel-0003")
    assert not is_orphan(store, "rel-0001")
    assert store.current_id() == "rel-0002"


# -- resuming ------------------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requirement("DATA-24")
def test_resuming_finishes_the_publication_without_restaging(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """The manifest already pins versions that were read back and verified; only the pointer move
    did not happen. Re-staging would write new versions and produce a different release."""
    publish_release("rel-0001", example_model, expected_parent=None)
    crash_after_the_manifest(store, "rel-0002", "rel-0001")
    versions = {t: delta.tip(store.table_location(t)) for t in TABLE_IDS}

    manifest = resume(store, "rel-0002")

    assert store.current_id() == "rel-0002"
    assert {t: delta.tip(store.table_location(t)) for t in TABLE_IDS} == versions
    assert model_digest(read_model(store, manifest)) == manifest.model_digest
    assert orphans(store) == ()


@pytest.mark.integration
@pytest.mark.requirement("DATA-23", "DATA-24")
def test_resuming_past_a_pointer_that_moved_on_is_refused(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """A stale resume would rewind the store to an older history, which is the stale-parent
    failure wearing a different hat — so it raises the same error."""
    publish_release("rel-0001", example_model, expected_parent=None)
    crash_after_the_manifest(store, "rel-0002", "rel-0001")
    # Someone publishes past it instead of resuming.
    publish_release(
        "rel-0003", rename_first_element(example_model, "Third"), expected_parent="rel-0001"
    )

    with pytest.raises(StaleParentError, match="rewinding"):
        resume(store, "rel-0002")
    assert store.current_id() == "rel-0003"


@pytest.mark.integration
@pytest.mark.requirement("DATA-24")
def test_resuming_the_current_release_is_refused(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    publish_release("rel-0001", example_model, expected_parent=None)
    with pytest.raises(ReleaseError, match="nothing to resume"):
        resume(store, "rel-0001")


@pytest.mark.integration
@pytest.mark.requirement("DATA-24", "DATA-58")
def test_resuming_a_manifest_whose_storage_moved_under_it_is_refused(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """Resume verifies rather than trusts, with the same code publication's sixth step uses.

    Reaching this state takes deliberate damage, which is itself worth recording: an orphan
    manifest is counted by `referenced_versions`, so ordinary retention protects the versions it
    pins. Only a vacuum given a keep-list that excludes them — which is what a policy ignoring
    the manifests would produce — can strand a resume.
    """
    publish_release("rel-0001", example_model, expected_parent=None)

    # The orphan changes `elements`, so it pins a version of its own rather than reusing v0.
    changed = rename_first_element(example_model, "Stranded")
    with pytest.raises(InjectedFailure):
        publish(
            a_request_for(store, "rel-0002", changed, expected_parent="rel-0001"),
            steps=failing_at("atomically move current pointer"),
        )
    orphaned_version = store.read_manifest("rel-0002").table("elements").delta_version
    assert orphaned_version == 1

    # Move the tip past it, then vacuum with a keep-list that ignores the orphan.
    publish_release(
        "rel-0003", rename_first_element(example_model, "Third"), expected_parent="rel-0001"
    )
    location = store.table_location("elements")
    delta.vacuum(location, version=delta.tip(location), keep_versions=[0, 2], dry_run=False)

    with pytest.raises(ReleaseError, match=r"no longer match|cannot resume"):
        resume(store, "rel-0002")
    assert store.current_id() == "rel-0003"


# -- discarding ----------------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requirement("DATA-24")
def test_discarding_removes_an_orphan_and_its_artifacts(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    publish_release("rel-0001", example_model, expected_parent=None)
    crash_after_the_manifest(store, "rel-0002", "rel-0001")
    assert store.artifact_dir("rel-0002").is_dir()

    discard(store, "rel-0002")

    assert not store.has_manifest("rel-0002")
    assert not store.artifact_dir("rel-0002").exists()
    assert orphans(store) == ()
    assert store.current_id() == "rel-0001"


@pytest.mark.integration
@pytest.mark.requirement("DATA-24", "DATA-22")
def test_discarding_leaves_the_delta_versions_for_retention_to_judge(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """DATA-22's reuse means two manifests routinely pin the same version, so deciding what is
    now unreferenced belongs to the module that computes it from the manifests that remain."""
    first = publish_release("rel-0001", example_model, expected_parent=None)
    crash_after_the_manifest(store, "rel-0002", "rel-0001")
    tips = {t: delta.tip(store.table_location(t)) for t in TABLE_IDS}

    discard(store, "rel-0002")

    assert {t: delta.tip(store.table_location(t)) for t in TABLE_IDS} == tips
    assert model_digest(read_model(store, first)) == first.model_digest


@pytest.mark.integration
@pytest.mark.requirement("DATA-24")
def test_a_current_or_referenced_release_is_not_discardable(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    publish_release("rel-0001", example_model, expected_parent=None)
    publish_release(
        "rel-0002", rename_first_element(example_model, "Second"), expected_parent="rel-0001"
    )
    with pytest.raises(ReleaseError, match="is current"):
        discard(store, "rel-0002")
    with pytest.raises(ReleaseError, match="is the parent of"):
        discard(store, "rel-0001")


# -- the operator surface ----------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requirement("DATA-24")
def test_the_operator_can_see_and_finish_an_orphan(
    monkeypatch: pytest.MonkeyPatch,
    store: ReleaseStore,
    example_model: Model,
    publish_release: Publisher,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The gap W4 left: a crash at step eight was survivable and had no exit."""
    publish_release("rel-0001", example_model, expected_parent=None)
    crash_after_the_manifest(store, "rel-0002", "rel-0001")
    root = str(store.root)

    assert run(monkeypatch, "releases", "--store", root) == 0
    listed = capsys.readouterr().out
    assert "! rel-0002" in listed
    assert "orphan: never became current" in listed

    assert run(monkeypatch, "resume", "rel-0002", "--store", root) == 0
    assert "resumed rel-0002" in capsys.readouterr().out
    assert store.current_id() == "rel-0002"


@pytest.mark.integration
@pytest.mark.requirement("DATA-24")
def test_the_operator_can_clear_an_orphan_instead(
    monkeypatch: pytest.MonkeyPatch,
    store: ReleaseStore,
    example_model: Model,
    publish_release: Publisher,
    capsys: pytest.CaptureFixture[str],
) -> None:
    publish_release("rel-0001", example_model, expected_parent=None)
    crash_after_the_manifest(store, "rel-0002", "rel-0001")
    root = str(store.root)

    assert run(monkeypatch, "discard", "rel-0002", "--store", root) == 0
    assert "discarded rel-0002" in capsys.readouterr().out
    assert run(monkeypatch, "releases", "--store", root) == 0
    assert "rel-0002" not in capsys.readouterr().out


@pytest.mark.integration
@pytest.mark.requirement("DATA-55")
def test_the_operator_can_bring_a_store_into_constraint_compliance(
    monkeypatch: pytest.MonkeyPatch,
    store: ReleaseStore,
    example_model: Model,
    publish_release: Publisher,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """DATA-55 was a capability and not a practice: nothing called `apply_constraints`."""
    publish_release("rel-0001", example_model, expected_parent=None)
    root = str(store.root)

    assert run(monkeypatch, "constraints", "--store", root) == 0
    reported = capsys.readouterr().out
    assert "missing" in reported
    assert "reporting only" in reported

    assert run(monkeypatch, "constraints", "--store", root, "--apply") == 0
    assert "added" in capsys.readouterr().out

    assert run(monkeypatch, "constraints", "--store", root) == 0
    assert "every row-local constraint is in force" in capsys.readouterr().out

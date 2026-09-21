"""The M2 hard gate: fault injection at every stage never exposes partial state (DATA-24).

> Fault injection after every publication stage never exposes partial state.
> — `docs/agent-handoff.md`, M2 hard gates

The gate is parametrized over `STEP_ORDER`, so it is not a test that happens to cover eight cases
— it is a test that covers *every* step by construction, and adding a ninth step to the protocol
without handling its failure makes this fail. That is the reason `publication.py` exposes the
steps by name instead of running one function.

What "never exposes partial state" means precisely, and what each case asserts:

- the current pointer still names the previous release, or nothing at all if there was none;
- that release still reads back as the model it was published with;
- the failed release id has no manifest, so nothing can later point at it;
- the publication lock is released, so the next attempt is not blocked by a crash.

**Orphans are permitted and are asserted to be harmless.** DATA-24 says a crash "may leave orphan
staged versions" — Delta commits one table at a time and nothing can undo that — so a failure
after step four leaves table versions nothing references. The gate is not that they are absent; it
is that they are invisible to a reader, which they are, because a reader opens the versions a
manifest names and no manifest names them.

Every failure is injected deterministically with no sleeps, no network and no randomness
(CORE-51). `tmp_path` gives each case its own store.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from architecture_toolkit.domain.authoring import parse_model, parse_source
from architecture_toolkit.domain.model import Model
from architecture_toolkit.domain.semantics import model_digest, stamp_digests
from architecture_toolkit.releases.candidate import ReleaseCandidate
from architecture_toolkit.releases.manifest import ArchitectureRelease
from architecture_toolkit.releases.provenance import source_bundle
from architecture_toolkit.releases.publication import (
    STEP_ORDER,
    STEPS,
    PublicationRequest,
    PublicationState,
    Step,
    publish,
)
from architecture_toolkit.releases.reader import read_model
from architecture_toolkit.releases.store import ReleaseStore
from architecture_toolkit.storage import delta
from architecture_toolkit.storage.schemas import TABLE_IDS

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "minimal" / "model.yaml"
MOMENT = datetime(2026, 9, 20, 12, 0, 0, tzinfo=UTC)


class InjectedFailure(RuntimeError):
    """A deliberate failure, distinguishable from a real one the protocol might raise."""


def example_text() -> str:
    return EXAMPLE.read_text()


def example() -> Model:
    return parse_model(parse_source(example_text(), source_id="example"))


def a_request(
    store: ReleaseStore, release_id: str, *, expected_parent: str | None
) -> PublicationRequest:
    return PublicationRequest(
        store=store,
        candidate=ReleaseCandidate(
            release_id=release_id,
            model=example(),
            source_bundle=source_bundle(
                source_id="examples/minimal/model.yaml", text=example_text()
            ),
        ),
        expected_parent=expected_parent,
        now=lambda: MOMENT,
        generator_commit="abc1234",
    )


def failing_at(step_name: str) -> dict[str, Step]:
    """The real protocol with exactly one stage replaced by a failure."""

    def boom(state: PublicationState) -> PublicationState:
        raise InjectedFailure(step_name)

    return {**STEPS, step_name: boom}


def assert_nothing_partial(
    store: ReleaseStore, *, expected_current: str | None, failed_release_id: str, failed_at: str
) -> None:
    """What "no partial state is visible" means, precisely.

    The universal invariant is about the *pointer*, not about what is lying on disk. A failure at
    step eight happens after step seven has written the manifest, so an orphan manifest exists —
    and that is the permitted state, not a violation, because a manifest nothing points at is a
    file rather than a release. Asserting "no manifest" universally would have been asserting
    something the protocol never promised, so the shape of the claim follows the shape of the
    guarantee: the failed release is never *current*, and a manifest may exist only if the
    failure came after the step that writes one.
    """
    assert store.current_id() == expected_current
    assert store.current_id() != failed_release_id, "a failed release became current"
    assert not store.lock_path.exists(), "a failed publication kept the lock"

    wrote_manifest = failed_at == "atomically move current pointer"
    assert store.has_manifest(failed_release_id) == wrote_manifest, (
        f"failing at {failed_at!r} left the wrong manifest state"
    )

    if expected_current is not None:
        current = store.read_manifest(expected_current)
        assert isinstance(current, ArchitectureRelease)
        # The previous release still resolves to exactly the model it was published with.
        assert model_digest(read_model(store, current)) == current.model_digest


# -- the gate, over every step ---------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requirement("DATA-24", "CORE-51")
@pytest.mark.parametrize("step_name", STEP_ORDER)
def test_a_failure_at_any_stage_of_a_first_publication_exposes_nothing(
    step_name: str, tmp_path: Path
) -> None:
    """An empty store stays empty. There is no previous release to fall back to, so the reader
    must see no release at all rather than a half-built one."""
    store = ReleaseStore.at(tmp_path).initialize()

    with pytest.raises(InjectedFailure):
        publish(a_request(store, "rel-0001", expected_parent=None), steps=failing_at(step_name))

    assert_nothing_partial(
        store, expected_current=None, failed_release_id="rel-0001", failed_at=step_name
    )
    assert store.current() is None


@pytest.mark.integration
@pytest.mark.requirement("DATA-24", "CORE-51")
@pytest.mark.parametrize("step_name", STEP_ORDER)
def test_a_failure_at_any_stage_leaves_the_previous_release_current(
    step_name: str, tmp_path: Path
) -> None:
    """The gate proper: one good release, then a failed second at each stage in turn."""
    store = ReleaseStore.at(tmp_path).initialize()
    first = publish(a_request(store, "rel-0001", expected_parent=None))
    assert store.current_id() == "rel-0001"

    with pytest.raises(InjectedFailure):
        publish(
            a_request(store, "rel-0002", expected_parent="rel-0001"),
            steps=failing_at(step_name),
        )

    assert_nothing_partial(
        store, expected_current="rel-0001", failed_release_id="rel-0002", failed_at=step_name
    )
    assert store.read_manifest("rel-0001") == first
    assert read_model(store, first) == stamp_digests(example())


@pytest.mark.integration
@pytest.mark.requirement("DATA-24")
def test_a_failure_after_the_manifest_is_written_still_does_not_publish_it(
    tmp_path: Path,
) -> None:
    """Steps seven and eight are separate for exactly this reason.

    A manifest on disk is not a release. Only the pointer move makes one, so a crash in between
    leaves an orphan manifest that no reader will ever open — the state the store test calls out
    and the protocol is built to survive.
    """
    store = ReleaseStore.at(tmp_path).initialize()
    publish(a_request(store, "rel-0001", expected_parent=None))

    with pytest.raises(InjectedFailure):
        publish(
            a_request(store, "rel-0002", expected_parent="rel-0001"),
            steps=failing_at("atomically move current pointer"),
        )

    # The manifest exists; the release does not.
    assert store.has_manifest("rel-0002")
    assert store.current_id() == "rel-0001"
    assert set(store.release_ids()) == {"rel-0001", "rel-0002"}
    assert not store.lock_path.exists()
    # A reader following the pointer never sees it.
    assert store.current() == store.read_manifest("rel-0001")


@pytest.mark.integration
@pytest.mark.requirement("DATA-24")
def test_orphan_table_versions_are_permitted_and_invisible(tmp_path: Path) -> None:
    """DATA-24 permits orphans; the gate is that they cannot be reached.

    Delta commits one table at a time and there is no undo, so a failure after staging leaves
    versions nothing references. A reader opens what a manifest names, and no manifest names
    these.
    """
    store = ReleaseStore.at(tmp_path).initialize()
    first = publish(a_request(store, "rel-0001", expected_parent=None))
    pinned = dict(first.pinned_versions)

    with pytest.raises(InjectedFailure):
        publish(
            a_request(store, "rel-0002", expected_parent="rel-0001"),
            steps=failing_at("read back exact staged versions"),
        )

    # Nothing was orphaned here, because the second publication's content was identical and every
    # table was reused. The observable guarantee is the one that matters either way.
    for table_id in TABLE_IDS:
        tip = delta.tip(store.table_location(table_id))
        assert tip >= pinned[table_id]
    assert store.current_id() == "rel-0001"
    assert model_digest(read_model(store, first)) == first.model_digest


@pytest.mark.integration
@pytest.mark.requirement("DATA-24")
def test_orphan_versions_from_changed_content_are_still_invisible(tmp_path: Path) -> None:
    """The same guarantee where a version genuinely is orphaned."""
    store = ReleaseStore.at(tmp_path).initialize()
    first = publish(a_request(store, "rel-0001", expected_parent=None))
    pinned = dict(first.pinned_versions)

    changed = example()
    victim = changed.elements[0]
    changed = changed.model_validate(
        dict(changed)
        | {
            "elements": tuple(
                element.model_validate(dict(element) | {"name": element.name + " (orphan)"})
                if element.element_id == victim.element_id
                else element
                for element in changed.elements
            )
        }
    )
    request = PublicationRequest(
        store=store,
        candidate=ReleaseCandidate(
            release_id="rel-0002",
            model=changed,
            source_bundle=source_bundle(source_id="s", text="x"),
        ),
        expected_parent="rel-0001",
        now=lambda: MOMENT,
        generator_commit="abc1234",
    )
    with pytest.raises(InjectedFailure):
        publish(request, steps=failing_at("validate schema/content/artifacts"))

    # A new `elements` version exists and is orphaned.
    assert delta.tip(store.table_location("elements")) == pinned["elements"] + 1
    # The current release still pins the old one, and still reads as what it published.
    assert store.current_id() == "rel-0001"
    assert dict(store.read_manifest("rel-0001").pinned_versions) == pinned
    assert model_digest(read_model(store, first)) == first.model_digest


@pytest.mark.integration
@pytest.mark.requirement("DATA-24", "DATA-54")
def test_publication_succeeds_on_a_retry_after_a_failed_attempt(tmp_path: Path) -> None:
    """A crash is recoverable: the same attempt retried reuses its staged versions."""
    store = ReleaseStore.at(tmp_path).initialize()

    with pytest.raises(InjectedFailure):
        publish(
            a_request(store, "rel-0001", expected_parent=None),
            steps=failing_at("publish immutable manifest"),
        )
    assert store.current_id() is None
    staged = {t: delta.tip(store.table_location(t)) for t in TABLE_IDS}

    manifest = publish(a_request(store, "rel-0001", expected_parent=None))
    assert store.current_id() == "rel-0001"
    # The retry wrote nothing new: the attempt marker said those tables were already committed.
    assert dict(manifest.pinned_versions) == staged
    assert {t: delta.tip(store.table_location(t)) for t in TABLE_IDS} == staged

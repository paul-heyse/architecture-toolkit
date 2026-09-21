"""Writing what changed and reusing what did not (DATA-22, DATA-54)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from architecture_toolkit.domain.authoring import parse_model, parse_source
from architecture_toolkit.domain.model import Model
from architecture_toolkit.releases.manifest import (
    ArchitectureRelease,
    GeneratorProvenance,
    SourceBundle,
)
from architecture_toolkit.releases.staging import (
    StagedTable,
    StagingOutcome,
    app_id,
    stage_tables,
)
from architecture_toolkit.releases.store import ReleaseStore
from architecture_toolkit.storage import delta
from architecture_toolkit.storage.digests import table_semantic_digest, table_set_digests
from architecture_toolkit.storage.mappings import compile_tables
from architecture_toolkit.storage.schemas import STORAGE_SCHEMA_VERSION, TABLE_IDS

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "minimal" / "model.yaml"
DIGEST = "sha256:" + "0" * 64


def example() -> Model:
    return parse_model(parse_source(EXAMPLE.read_text(), source_id="example"))


def renamed(model: Model) -> Model:
    """The same model with one element renamed. Touches `elements` and nothing else."""
    victim = model.elements[0]
    return model.model_validate(
        dict(model)
        | {
            "elements": tuple(
                element.model_validate(dict(element) | {"name": element.name + " (renamed)"})
                if element.element_id == victim.element_id
                else element
                for element in model.elements
            )
        }
    )


def stage(
    store: ReleaseStore,
    model: Model,
    *,
    parent: ArchitectureRelease | None = None,
    release_id: str = "rel-0001",
) -> tuple[StagedTable, ...]:
    return stage_tables(
        store,
        compile_tables(model),
        parent=parent,
        release_id=release_id,
        source_bundle_digest=DIGEST,
        generator_commit="abc1234",
    )


@pytest.mark.integration
@pytest.mark.requirement("DATA-22")
def test_the_first_publication_writes_every_table_at_version_zero(tmp_path: Path) -> None:
    store = ReleaseStore.at(tmp_path).initialize()
    staged = stage(store, example())
    assert len(staged) == len(TABLE_IDS)
    assert all(item.outcome is StagingOutcome.WRITTEN for item in staged)
    assert all(item.delta_version == 0 for item in staged)
    for table_id in TABLE_IDS:
        assert delta.is_table(store.table_location(table_id))


@pytest.mark.integration
@pytest.mark.requirement("DATA-22")
def test_only_the_table_a_rename_touches_is_rewritten(tmp_path: Path) -> None:
    """DATA-22's reuse rule, observable as the difference between two sets of pins.

    An identical overwrite still creates a Delta version, so reuse cannot mean "write it again" —
    it means do not write at all and carry the parent's version forward.
    """
    store = ReleaseStore.at(tmp_path).initialize()
    model = example()
    first = stage(store, model, release_id="rel-0001")
    parent = _manifest_from(store, first)

    second = stage(store, renamed(model), parent=parent, release_id="rel-0002")
    by_table = {item.table_id: item for item in second}

    assert by_table["elements"].outcome is StagingOutcome.WRITTEN
    assert by_table["elements"].delta_version == 1
    reused = [t for t in TABLE_IDS if t != "elements"]
    assert all(by_table[t].outcome is StagingOutcome.REUSED for t in reused)
    assert all(by_table[t].delta_version == 0 for t in reused)


@pytest.mark.integration
@pytest.mark.requirement("DATA-54")
def test_restaging_one_release_writes_nothing_twice(tmp_path: Path) -> None:
    """deltalake records the marker and does not act on it; the skip is ours.

    Without the read-then-skip a retry would produce a second commit of identical content, and
    the version the first run recorded would no longer be the tip.
    """
    store = ReleaseStore.at(tmp_path).initialize()
    model = example()
    stage(store, model, release_id="rel-0001")
    versions_before = {t: delta.tip(store.table_location(t)) for t in TABLE_IDS}

    replay = stage(store, model, release_id="rel-0001")
    assert all(item.outcome is StagingOutcome.ALREADY_COMMITTED for item in replay)
    assert {t: delta.tip(store.table_location(t)) for t in TABLE_IDS} == versions_before


@pytest.mark.integration
@pytest.mark.requirement("DATA-54")
def test_a_different_release_is_not_skipped_by_another_release_marker(tmp_path: Path) -> None:
    """A marker belongs to one release; another release's write must not be suppressed by it.

    The counter this replaced was derived from the number of manifests in the store, which shifts
    when a failed publication leaves an orphan manifest behind — so a retry after the one crash
    the marker exists to survive would have been handed a different number and rewritten every
    table. One id per release has no such state.
    """
    store = ReleaseStore.at(tmp_path).initialize()
    model = example()
    stage(store, model, release_id="rel-0001")
    second = stage(store, renamed(model), release_id="rel-0002")
    by_table = {item.table_id: item for item in second}
    assert by_table["elements"].outcome is StagingOutcome.WRITTEN
    assert by_table["elements"].delta_version == 1


@pytest.mark.integration
@pytest.mark.requirement("DATA-53")
def test_every_staged_commit_carries_its_publication_provenance(tmp_path: Path) -> None:
    """DATA-53's fields come back as top-level keys of a history entry — Delta's doing, not ours."""
    store = ReleaseStore.at(tmp_path).initialize()
    stage(store, example(), release_id="rel-0001")

    location = store.table_location("elements")
    entry = delta.history(location, version=0)[0]
    assert entry["publication_attempt_id"] == "rel-0001"
    assert entry["table_id"] == "elements"
    assert entry["model_id"] == "sample-service"
    assert entry["generator_commit"] == "abc1234"
    assert entry["source_bundle_digest"] == DIGEST
    assert entry["storage_schema_version"] == STORAGE_SCHEMA_VERSION
    # A first release genuinely has no parent, so the key is absent rather than "None".
    assert "expected_parent_release_id" not in entry


@pytest.mark.integration
@pytest.mark.requirement("DATA-54")
def test_the_application_transaction_marker_is_readable_per_table(tmp_path: Path) -> None:
    store = ReleaseStore.at(tmp_path).initialize()
    stage(store, example(), release_id="rel-0007")
    location = store.table_location("elements")
    assert delta.committed_attempt(location, app_id=app_id("rel-0007"), version=0) == 1
    assert delta.committed_attempt(location, app_id=app_id("rel-0008"), version=0) is None
    assert delta.committed_attempt(location, app_id="someone-else", version=0) is None
    assert app_id("rel-0007") != app_id("rel-0008")


@pytest.mark.integration
@pytest.mark.requirement("DATA-22", "DATA-45")
def test_staged_content_reads_back_with_the_digest_that_was_staged(tmp_path: Path) -> None:
    store = ReleaseStore.at(tmp_path).initialize()
    model = example()
    staged = stage(store, model, release_id="rel-0001")
    expected = table_set_digests(compile_tables(model))
    for item in staged:
        read = delta.read_version(store.table_location(item.table_id), version=item.delta_version)
        assert table_semantic_digest(item.table_id, read) == expected[item.table_id]


def _manifest_from(store: ReleaseStore, staged: tuple[StagedTable, ...]) -> ArchitectureRelease:
    """A minimal parent manifest carrying the pins a staging run produced."""
    return ArchitectureRelease(
        release_id="rel-0001",
        model_id="sample-service",
        schema_version="1.0.0",
        profile_version="1.0.0",
        model_digest=DIGEST,
        published_at=datetime(2026, 9, 20, tzinfo=UTC),
        tables=tuple(item.as_ref(uri=store.table_uri(item.table_id)) for item in staged),
        source_bundle=SourceBundle(source_id="examples/minimal/model.yaml", digest=DIGEST),
        generator=GeneratorProvenance(
            toolkit_version="0.1.0",
            toolkit_commit="abc1234",
            storage_schema_version="1.0.0",
            hash_algorithm_version="1",
        ),
    )

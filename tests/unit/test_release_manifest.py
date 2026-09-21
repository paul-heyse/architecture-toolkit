"""The immutable release manifest and the store that holds it (DATA-20, DATA-21, DATA-23)."""

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from architecture_toolkit.domain.semantics import model_digest, stamp_digests
from architecture_toolkit.releases.candidate import next_release_id
from architecture_toolkit.releases.errors import ReleaseError, UnknownReleaseError
from architecture_toolkit.releases.manifest import (
    ArchitectureRelease,
    GeneratorProvenance,
    SourceBundle,
    TableRef,
)
from architecture_toolkit.releases.store import DEFAULT_STORE_ROOT, ReleaseStore
from architecture_toolkit.storage.schemas import TABLE_IDS
from tests.strategies.relations import full_models
from tests.strategies.releases import manifests

DIGEST = "sha256:" + "a" * 64
OTHER = "sha256:" + "b" * 64
MOMENT = datetime(2026, 9, 20, 12, 0, 0, tzinfo=UTC)


def a_manifest(
    *,
    release_id: str = "rel-0001",
    parent_release_id: str | None = None,
    model_digest: str = DIGEST,
    published_at: datetime = MOMENT,
    tables: tuple[TableRef, ...] | None = None,
) -> ArchitectureRelease:
    """A minimal valid manifest. Typed parameters rather than `**overrides`: a `dict[str, object]`
    splat type-checks as `object` per field and would suppress every argument error in the file."""
    return ArchitectureRelease(
        release_id=release_id,
        model_id="sample-service",
        parent_release_id=parent_release_id,
        schema_version="1.0.0",
        profile_version="1.0.0",
        model_digest=model_digest,
        published_at=published_at,
        tables=(
            (
                TableRef(
                    table_id="elements",
                    uri="tables/elements",
                    delta_version=0,
                    semantic_digest=OTHER,
                    row_count=10,
                ),
            )
            if tables is None
            else tables
        ),
        source_bundle=SourceBundle(source_id="examples/minimal/model.yaml", digest=DIGEST),
        generator=GeneratorProvenance(
            toolkit_version="0.1.0",
            toolkit_commit="abc1234",
            storage_schema_version="1.0.0",
            hash_algorithm_version="1",
        ),
    )


# -- the manifest -------------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.requirement("DATA-20", "DATA-21")
def test_a_manifest_pins_a_table_at_an_exact_version() -> None:
    """DATA-20: a Delta version is not a release; the manifest is what a release is."""
    manifest = a_manifest()
    assert manifest.table("elements").delta_version == 0
    assert manifest.pinned_versions == (("elements", 0),)
    with pytest.raises(KeyError):
        manifest.table("relationships")


@pytest.mark.unit
@pytest.mark.requirement("DATA-21")
def test_a_manifest_is_frozen_and_hashable() -> None:
    """Immutable after creation. A published manifest that could be edited would make every
    digest it pins a claim about nothing."""
    manifest = a_manifest()
    assert isinstance(hash(manifest), int)
    with pytest.raises(ValidationError):
        manifest.release_id = "rel-0002"  # type: ignore[misc]


@pytest.mark.unit
@pytest.mark.requirement("DATA-21")
def test_the_same_table_cannot_be_pinned_twice() -> None:
    """Two pins for one table is not a release with a preference; it is an unreadable manifest."""
    twice = (
        TableRef(
            table_id="elements",
            uri="tables/elements",
            delta_version=0,
            semantic_digest=OTHER,
            row_count=1,
        ),
        TableRef(
            table_id="elements",
            uri="tables/elements",
            delta_version=3,
            semantic_digest=DIGEST,
            row_count=2,
        ),
    )
    with pytest.raises(ValidationError, match="more than once"):
        a_manifest(tables=twice)


@pytest.mark.unit
@pytest.mark.requirement("DATA-12", "DATA-21")
def test_published_at_must_be_utc() -> None:
    """DATA-12's UTC instants. An offset is still ambiguous to a reader a year later."""
    assert a_manifest(published_at=MOMENT).published_at.utcoffset() == timedelta(0)
    with pytest.raises(ValidationError, match="must be UTC"):
        a_manifest(published_at=datetime(2026, 9, 20, tzinfo=timezone(timedelta(hours=2))))


@pytest.mark.unit
@pytest.mark.requirement("DATA-21", "DATA-25")
def test_a_table_uri_is_relative_to_the_store() -> None:
    """An absolute uri would make a manifest host-bound, and a milestone archive not portable."""
    with pytest.raises(ValidationError, match="must be relative"):
        TableRef(
            table_id="elements",
            uri="/var/data/elements",
            delta_version=0,
            semantic_digest=DIGEST,
            row_count=0,
        )
    with pytest.raises(ValidationError, match="must be relative"):
        TableRef(
            table_id="elements",
            uri="s3://bucket/elements",
            delta_version=0,
            semantic_digest=DIGEST,
            row_count=0,
        )


@pytest.mark.unit
@pytest.mark.requirement("DATA-51")
def test_a_delta_version_is_a_nonnegative_integer() -> None:
    for bad in (-1, "0"):
        with pytest.raises(ValidationError):
            TableRef(
                table_id="elements",
                uri="tables/elements",
                delta_version=bad,  # type: ignore[arg-type]
                semantic_digest=DIGEST,
                row_count=0,
            )


@pytest.mark.unit
@pytest.mark.requirement("DATA-21")
def test_the_w8_artifact_fields_exist_and_are_empty() -> None:
    """Declared at W4 so PROJ-41 fills them at W8 without a DATA-56 migration on every release."""
    manifest = a_manifest()
    assert manifest.projection_artifact_digests == ()
    assert manifest.render_artifact_digests == ()
    assert manifest.validation_reports == ()
    assert manifest.outputs == ()


@pytest.mark.unit
@pytest.mark.requirement("DATA-21", "CORE-12")
def test_a_manifest_round_trips_through_its_own_json() -> None:
    """The schema family is a machine-facing contract, so the document must reload exactly."""
    manifest = a_manifest()
    assert ArchitectureRelease.model_validate_json(manifest.model_dump_json()) == manifest


# -- the store ----------------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.requirement("DATA-23")
def test_the_store_lays_itself_out_and_keeps_uris_relative(tmp_path: Path) -> None:
    store = ReleaseStore.at(tmp_path).initialize()
    assert store.tables_root.is_dir()
    assert store.releases_root.is_dir()
    assert store.table_uri("elements") == "tables/elements"
    assert store.table_location("elements") == tmp_path / "tables" / "elements"
    assert store.resolve("tables/elements") == tmp_path / "tables" / "elements"
    # Idempotent: initializing twice is not an error.
    assert store.initialize().root == tmp_path


@pytest.mark.unit
@pytest.mark.requirement("DATA-21")
def test_a_published_manifest_cannot_be_overwritten(tmp_path: Path) -> None:
    """The only place immutability can be enforced: nothing downstream can tell a rewritten
    manifest from an original one."""
    store = ReleaseStore.at(tmp_path).initialize()
    manifest = a_manifest()
    store.write_manifest(manifest)
    assert store.read_manifest("rel-0001") == manifest
    with pytest.raises(ReleaseError, match="already published"):
        store.write_manifest(manifest)
    with pytest.raises(ReleaseError, match="already published"):
        store.write_manifest(a_manifest(model_digest=OTHER))


@pytest.mark.unit
@pytest.mark.requirement("DATA-21")
def test_an_unknown_release_is_a_key_error(tmp_path: Path) -> None:
    store = ReleaseStore.at(tmp_path).initialize()
    with pytest.raises(UnknownReleaseError):
        store.read_manifest("rel-9999")
    assert not store.has_manifest("rel-9999")
    assert store.release_ids() == ()
    assert list(store.iter_manifests()) == []


@pytest.mark.unit
@pytest.mark.requirement("DATA-23", "DATA-24")
def test_the_current_pointer_moves_atomically_and_only_to_a_published_release(
    tmp_path: Path,
) -> None:
    """The commit point of the whole protocol."""
    store = ReleaseStore.at(tmp_path).initialize()
    assert store.current() is None
    assert store.current_id() is None

    first = a_manifest()
    with pytest.raises(ReleaseError, match="manifest is not published"):
        store.set_current(first)

    store.write_manifest(first)
    store.set_current(first)
    assert store.current_id() == "rel-0001"
    assert store.current() == first

    second = a_manifest(release_id="rel-0002", parent_release_id="rel-0001")
    store.write_manifest(second)
    store.set_current(second)
    assert store.current_id() == "rel-0002"
    # No staging file is left behind by an atomic replace.
    assert not (tmp_path / "CURRENT.staged").exists()


@pytest.mark.unit
@pytest.mark.requirement("DATA-24")
def test_a_manifest_that_exists_is_not_the_same_as_a_release_that_is_current(
    tmp_path: Path,
) -> None:
    """Exactly the state a crash between steps seven and eight leaves behind.

    DATA-24 permits it and requires the previous release to keep resolving.
    """
    store = ReleaseStore.at(tmp_path).initialize()
    published = a_manifest()
    store.write_manifest(published)
    store.set_current(published)

    orphan = a_manifest(release_id="rel-0002", parent_release_id="rel-0001")
    store.write_manifest(orphan)  # written, never pointed at

    assert store.current_id() == "rel-0001"
    assert set(store.release_ids()) == {"rel-0001", "rel-0002"}


@pytest.mark.unit
@pytest.mark.requirement("DATA-23")
def test_a_garbled_pointer_is_reported_rather_than_guessed(tmp_path: Path) -> None:
    store = ReleaseStore.at(tmp_path).initialize()
    store.pointer_path.write_text(json.dumps({"release_id": 7}), encoding="utf-8")
    with pytest.raises(ReleaseError, match="non-string release_id"):
        store.current_id()


@pytest.mark.unit
@pytest.mark.requirement("DATA-36")
def test_the_default_store_root_is_under_the_ignored_runtime_directory() -> None:
    """Live Delta directories stay host-local; `check_boundaries.py` refuses a committed one."""
    assert DEFAULT_STORE_ROOT.parts[0] == ".runtime"


@pytest.mark.unit
@pytest.mark.requirement("DATA-21")
def test_release_ids_sort_in_publication_order() -> None:
    assert next_release_id(()) == "rel-0001"
    assert next_release_id(("rel-0001",)) == "rel-0002"
    assert next_release_id(("rel-0001", "rel-0009")) == "rel-0010"
    assert next_release_id(("not-a-release",)) == "rel-0001"
    assert sorted(("rel-0010", "rel-0002")) == ["rel-0002", "rel-0010"]


@pytest.mark.property
@pytest.mark.requirement("DATA-21", "CORE-45")
@settings(max_examples=25, deadline=None)
@given(data=st.data())
def test_a_manifest_pins_every_declared_table_of_a_generated_model(data: st.DataObject) -> None:
    """The strategy is only useful if the manifests it draws are truthful about their model."""
    model = data.draw(full_models())
    manifest = data.draw(manifests(model))
    assert tuple(ref.table_id for ref in manifest.tables) == TABLE_IDS
    assert manifest.model_digest == model_digest(stamp_digests(model))
    assert manifest.model_id == model.model_id

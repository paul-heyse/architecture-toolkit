"""Self-contained milestone archives and the operator surface (DATA-25)."""

import json
import sys
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from architecture_toolkit.cli import main
from architecture_toolkit.domain.model import Model
from architecture_toolkit.domain.semantics import model_digest
from architecture_toolkit.releases.archive import ARCHIVE_INDEX, verify_archive, write_archive
from architecture_toolkit.releases.errors import ArchiveError
from architecture_toolkit.releases.store import ReleaseStore
from architecture_toolkit.storage.digests import table_semantic_digest
from architecture_toolkit.storage.schemas import TABLE_IDS
from tests.integration.conftest import Publisher, rename_first_element

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "minimal" / "model.yaml"


def run(monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["architecture", *argv])
    return main()


# -- archives ------------------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requirement("DATA-25")
def test_an_archive_holds_every_table_as_parquet_with_its_digest_intact(
    store: ReleaseStore, example_model: Model, publish_release: Publisher, tmp_path: Path
) -> None:
    """The claim that matters: readable without the live Delta directory.

    Parquet rather than a Delta pointer, so the archive needs no transaction log, no retention
    policy and no library that understands one.
    """
    manifest = publish_release("rel-0001", example_model, expected_parent=None, attempt=1)
    result = write_archive(store, manifest, tmp_path / "milestone")

    assert result.table_count == len(TABLE_IDS)
    for table_id in TABLE_IDS:
        parquet = result.root / "tables" / f"{table_id}.parquet"
        assert parquet.is_file()
        restored = pq.read_table(parquet)
        assert table_semantic_digest(table_id, restored) == manifest.table(table_id).semantic_digest


@pytest.mark.integration
@pytest.mark.requirement("DATA-25")
def test_an_archive_carries_the_manifest_schemas_and_reports(
    store: ReleaseStore, example_model: Model, publish_release: Publisher, tmp_path: Path
) -> None:
    """§5F's contents list, minus outputs, which W8 fills."""
    manifest = publish_release("rel-0001", example_model, expected_parent=None, attempt=1)
    result = write_archive(store, manifest, tmp_path / "milestone")

    assert (result.root / "manifest.json").is_file()
    assert (result.root / "reports" / "validation-report.json").is_file()
    assert list((result.root / "schemas").glob("*.schema.json"))
    assert (result.root / "outputs").is_dir()
    assert not list((result.root / "outputs").iterdir()), "W8 fills outputs; W4 declares it"

    index = json.loads((result.root / ARCHIVE_INDEX).read_text())
    assert index["release_id"] == "rel-0001"
    assert index["outputs"] == []
    assert index["model_digest"] == manifest.model_digest


@pytest.mark.integration
@pytest.mark.requirement("DATA-25")
def test_every_archived_file_is_digested_and_verifiable(
    store: ReleaseStore, example_model: Model, publish_release: Publisher, tmp_path: Path
) -> None:
    """An archive whose contents cannot be checked is a directory of hopeful files."""
    manifest = publish_release("rel-0001", example_model, expected_parent=None, attempt=1)
    result = write_archive(store, manifest, tmp_path / "milestone")
    assert verify_archive(result.root) == ()

    tampered = result.root / "tables" / "elements.parquet"
    tampered.write_bytes(tampered.read_bytes() + b"tamper")
    assert verify_archive(result.root) == ("tables/elements.parquet",)


@pytest.mark.integration
@pytest.mark.requirement("DATA-25")
def test_two_archives_of_one_release_are_byte_identical(
    store: ReleaseStore, example_model: Model, publish_release: Publisher, tmp_path: Path
) -> None:
    """Canonical form on the way out, so an archive can be compared with another copy of itself."""
    manifest = publish_release("rel-0001", example_model, expected_parent=None, attempt=1)
    first = write_archive(store, manifest, tmp_path / "a")
    second = write_archive(store, manifest, tmp_path / "b")
    assert first.contents == second.contents


@pytest.mark.integration
@pytest.mark.requirement("DATA-25")
def test_an_archive_is_written_once(
    store: ReleaseStore, example_model: Model, publish_release: Publisher, tmp_path: Path
) -> None:
    manifest = publish_release("rel-0001", example_model, expected_parent=None, attempt=1)
    write_archive(store, manifest, tmp_path / "milestone")
    with pytest.raises(ArchiveError, match="not empty"):
        write_archive(store, manifest, tmp_path / "milestone")


@pytest.mark.integration
@pytest.mark.requirement("DATA-25", "DATA-58")
def test_a_superseded_release_still_archives_after_a_vacuum(
    store: ReleaseStore, example_model: Model, publish_release: Publisher, tmp_path: Path
) -> None:
    """Retention protects it, so the archive of a historical baseline is still possible later."""
    from architecture_toolkit.releases.retention import vacuum_table

    first = publish_release("rel-0001", example_model, expected_parent=None, attempt=1)
    publish_release(
        "rel-0002",
        rename_first_element(example_model, "Second"),
        expected_parent="rel-0001",
        attempt=2,
    )
    for table_id in TABLE_IDS:
        vacuum_table(store, table_id, apply=True)

    result = write_archive(store, first, tmp_path / "historical")
    assert verify_archive(result.root) == ()
    restored = pq.read_table(result.root / "tables" / "elements.parquet")
    assert table_semantic_digest("elements", restored) == first.table("elements").semantic_digest


# -- the operator surface --------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requirement("DATA-21", "DATA-23")
def test_publish_list_show_and_archive_from_the_command_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = str(tmp_path / "store")
    assert run(monkeypatch, "publish", str(EXAMPLE), "--store", root) == 0
    assert "published rel-0001" in capsys.readouterr().out

    assert run(monkeypatch, "releases", "--store", root, "--verify") == 0
    listed = capsys.readouterr().out
    assert "* rel-0001" in listed
    assert "reads back" in listed

    assert run(monkeypatch, "show", "rel-0001", "--store", root) == 0
    manifest = json.loads(capsys.readouterr().out)
    assert manifest["release_id"] == "rel-0001"
    assert len(manifest["tables"]) == len(TABLE_IDS)

    assert run(monkeypatch, "archive", "rel-0001", "--store", root) == 0
    assert "archived rel-0001" in capsys.readouterr().out


@pytest.mark.integration
@pytest.mark.requirement("DATA-23")
def test_publishing_without_saying_the_parent_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """DATA-23 asks a publication to say what it was built against.

    A flag that silently defaulted to the current release would turn the stale-parent check into
    a formality, so an omitted `--expect-parent` is a usage error once a release exists.
    """
    root = str(tmp_path / "store")
    assert run(monkeypatch, "publish", str(EXAMPLE), "--store", root) == 0
    capsys.readouterr()

    with pytest.raises(SystemExit) as exited:
        run(monkeypatch, "publish", str(EXAMPLE), "--store", root)
    assert exited.value.code == 2
    assert "--expect-parent is required" in capsys.readouterr().err


@pytest.mark.integration
@pytest.mark.requirement("DATA-23")
def test_publishing_against_a_stale_parent_reports_and_changes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = str(tmp_path / "store")
    assert run(monkeypatch, "publish", str(EXAMPLE), "--store", root) == 0
    capsys.readouterr()

    assert (
        run(monkeypatch, "publish", str(EXAMPLE), "--store", root, "--expect-parent", "rel-9999")
        == 1
    )
    assert "StaleParentError" in capsys.readouterr().out
    assert ReleaseStore.at(root).current_id() == "rel-0001"


@pytest.mark.integration
@pytest.mark.requirement("DATA-58")
def test_vacuum_is_a_dry_run_from_the_command_line_too(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = str(tmp_path / "store")
    assert run(monkeypatch, "publish", str(EXAMPLE), "--store", root) == 0
    capsys.readouterr()
    assert run(monkeypatch, "vacuum", "--store", root) == 0
    assert "nothing to remove" in capsys.readouterr().out


@pytest.mark.integration
@pytest.mark.requirement("DATA-21")
def test_listing_an_empty_store_is_not_an_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(monkeypatch, "releases", "--store", str(tmp_path / "empty")) == 0
    assert "no releases" in capsys.readouterr().out


@pytest.mark.integration
@pytest.mark.requirement("DATA-21")
def test_showing_a_release_that_does_not_exist_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exited:
        run(monkeypatch, "show", "rel-9999", "--store", str(tmp_path))
    assert exited.value.code == 2
    assert "No release" in capsys.readouterr().err


@pytest.mark.integration
@pytest.mark.requirement("DATA-22")
def test_a_second_publication_reports_how_many_tables_it_reused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The reuse gate, visible to an operator rather than only to a test."""
    root = tmp_path / "store"
    assert run(monkeypatch, "publish", str(EXAMPLE), "--store", str(root)) == 0
    capsys.readouterr()
    assert (
        run(
            monkeypatch,
            "publish",
            str(EXAMPLE),
            "--store",
            str(root),
            "--expect-parent",
            "rel-0001",
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "published rel-0002" in out
    assert model_digest(example_from(root)) is not None


def example_from(root: Path) -> Model:
    from architecture_toolkit.releases.reader import read_model

    store = ReleaseStore.at(root)
    current = store.current()
    assert current is not None
    return read_model(store, current)

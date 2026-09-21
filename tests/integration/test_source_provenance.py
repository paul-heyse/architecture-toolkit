"""What a release records about where its model came from (DATA-37, DATA-25)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from architecture_toolkit.domain.model import Model
from architecture_toolkit.releases.archive import verify_archive, write_archive
from architecture_toolkit.releases.candidate import ReleaseCandidate
from architecture_toolkit.releases.errors import ArchiveError
from architecture_toolkit.releases.manifest import ArchitectureRelease, SourceBundle
from architecture_toolkit.releases.provenance import digest_bytes, source_bundle, source_revision
from architecture_toolkit.releases.publication import PublicationRequest, publish
from architecture_toolkit.releases.store import ReleaseStore
from tests.integration.conftest import MOMENT

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "minimal" / "model.yaml"


def publish_with(
    store: ReleaseStore, model: Model, *, preserve: bool = True, revision: str | None = None
) -> ArchitectureRelease:
    text = EXAMPLE.read_text()
    return publish(
        PublicationRequest(
            store=store,
            candidate=ReleaseCandidate(
                release_id="rel-0001",
                model=model,
                source_bundle=source_bundle(
                    source_id="examples/minimal/model.yaml", text=text, revision=revision
                ),
            ),
            expected_parent=None,
            source_text=text,
            preserve_source=preserve,
            attempt=1,
            now=lambda: MOMENT,
            generator_commit="abc1234",
        )
    )


@pytest.mark.integration
@pytest.mark.requirement("DATA-37")
def test_a_published_release_preserves_the_source_it_was_built_from(
    store: ReleaseStore, example_model: Model
) -> None:
    """The branch that never ran in W4: nothing set `snapshot_path`, so nothing was preserved."""
    manifest = publish_with(store, example_model)
    bundle = manifest.source_bundle
    assert bundle.snapshot_path == "artifacts/rel-0001/source/model.yaml"

    preserved = store.resolve(bundle.snapshot_path)
    assert preserved.is_file()
    assert preserved.read_text() == EXAMPLE.read_text()
    assert digest_bytes(preserved.read_bytes()) == bundle.digest


@pytest.mark.integration
@pytest.mark.requirement("DATA-37")
def test_the_snapshot_is_the_text_that_was_parsed_not_the_file_on_disk(
    store: ReleaseStore, example_model: Model, tmp_path: Path
) -> None:
    """A file can change between being read and being published; the bundle pins what was read."""
    text = "# the exact bytes that were parsed\n" + EXAMPLE.read_text()
    manifest = publish(
        PublicationRequest(
            store=store,
            candidate=ReleaseCandidate(
                release_id="rel-0001",
                model=example_model,
                source_bundle=source_bundle(source_id="somewhere/model.yaml", text=text),
            ),
            expected_parent=None,
            source_text=text,
            attempt=1,
            now=lambda: MOMENT,
            generator_commit="abc1234",
        )
    )
    preserved = store.resolve(manifest.source_bundle.snapshot_path or "")
    assert preserved.read_text() == text
    assert digest_bytes(text.encode()) == manifest.source_bundle.digest


@pytest.mark.integration
@pytest.mark.requirement("DATA-37")
def test_preserving_the_source_can_be_declined(store: ReleaseStore, example_model: Model) -> None:
    """DATA-37 says "authorized snapshot", which implies some sources must not be copied."""
    manifest = publish_with(store, example_model, preserve=False)
    assert manifest.source_bundle.snapshot_path is None
    assert manifest.source_bundle.digest.startswith("sha256:")
    assert not (store.artifact_dir("rel-0001") / "source").exists()


@pytest.mark.integration
@pytest.mark.requirement("DATA-37")
def test_a_revision_is_recorded_when_the_source_is_tracked(
    store: ReleaseStore, example_model: Model
) -> None:
    manifest = publish_with(store, example_model, revision="a" * 40)
    assert manifest.source_bundle.revision == "a" * 40


@pytest.mark.unit
@pytest.mark.requirement("DATA-37")
def test_a_revision_is_none_where_there_is_not_one(tmp_path: Path) -> None:
    """Untracked, not a checkout, or no git: three situations, one honest answer.

    DATA-37 is about what a revision *means*. A mutable path does not become a version by being
    written down, so the absence has to be expressible.
    """
    outside = tmp_path / "loose.yaml"
    outside.write_text("model_id: x\n", encoding="utf-8")
    assert source_revision(outside) is None
    # The repository's own example is tracked, so this is the positive control.
    assert source_revision(EXAMPLE) is not None


@pytest.mark.unit
@pytest.mark.requirement("DATA-37", "DATA-25")
def test_a_snapshot_path_must_be_relative_to_the_store() -> None:
    """Same reason `TableRef.uri` is: an absolute path stops meaning anything when the store moves,
    and a milestone archive that is supposed to be self-contained would be machine-bound."""
    assert SourceBundle(source_id="s", digest="sha256:" + "0" * 64, snapshot_path=None)
    for bad in ("/var/data/model.yaml", "s3://bucket/model.yaml"):
        with pytest.raises(ValidationError, match="must be relative"):
            SourceBundle(source_id="s", digest="sha256:" + "0" * 64, snapshot_path=bad)


@pytest.mark.integration
@pytest.mark.requirement("DATA-25", "DATA-37")
def test_an_archive_now_carries_the_source_it_claims_to(
    store: ReleaseStore, example_model: Model, tmp_path: Path
) -> None:
    """The self-containment DATA-25 asks for, which W4's archives never had."""
    manifest = publish_with(store, example_model)
    result = write_archive(store, manifest, tmp_path / "milestone")

    assert "sources/model.yaml" in result.contents
    archived = result.root / "sources" / "model.yaml"
    assert archived.read_text() == EXAMPLE.read_text()
    assert result.contents["sources/model.yaml"] == manifest.source_bundle.digest
    assert verify_archive(result.root) == ()


@pytest.mark.integration
@pytest.mark.requirement("DATA-25")
def test_an_archive_refuses_a_source_that_does_not_match_its_digest(
    store: ReleaseStore, example_model: Model, tmp_path: Path
) -> None:
    """An archive claiming provenance it cannot support is worse than one claiming none."""
    manifest = publish_with(store, example_model)
    preserved = store.resolve(manifest.source_bundle.snapshot_path or "")
    preserved.write_text("something else entirely\n", encoding="utf-8")

    with pytest.raises(ArchiveError, match="does not match the digest"):
        write_archive(store, manifest, tmp_path / "milestone")


@pytest.mark.integration
@pytest.mark.requirement("DATA-25")
def test_an_archive_refuses_a_snapshot_that_has_been_removed(
    store: ReleaseStore, example_model: Model, tmp_path: Path
) -> None:
    manifest = publish_with(store, example_model)
    store.resolve(manifest.source_bundle.snapshot_path or "").unlink()
    with pytest.raises(ArchiveError, match="not there"):
        write_archive(store, manifest, tmp_path / "milestone")

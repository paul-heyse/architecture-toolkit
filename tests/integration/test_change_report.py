"""The change record as a release artifact, and the storage cross-check (DATA-26, DATA-57).

`ArchitectureRelease.change_report_digest` has been declared since W4 and written by nothing;
`tests/integration/test_manifest_completeness.py` named W6 as the wave that fills it. These are the
tests that make the field a claim rather than a reservation.
"""

import json
from pathlib import Path

import pytest

from architecture_toolkit.changes.audit import compared_tables, storage_disagreements
from architecture_toolkit.changes.operations import ArchitectureOperations
from architecture_toolkit.changes.record import ArchitectureChangeSet, AuthorKind, Authorship
from architecture_toolkit.domain.commands import ChangeSet, RenameElement
from architecture_toolkit.domain.model import Model
from architecture_toolkit.releases.audit import changed_row_counts, net_row_changes
from architecture_toolkit.releases.candidate import ReleaseCandidate
from architecture_toolkit.releases.provenance import digest_bytes, source_bundle
from architecture_toolkit.releases.publication import PublicationRequest
from architecture_toolkit.releases.store import ReleaseStore
from tests.integration.conftest import EXAMPLE, MOMENT, Publisher

AGENT = Authorship(author_id="agent-01", author_kind=AuthorKind.AGENT)


@pytest.fixture
def ops(store: ReleaseStore) -> ArchitectureOperations:
    return ArchitectureOperations(store=store, now=lambda: MOMENT)


def rename(model: Model, new_name: str) -> ChangeSet:
    victim = model.elements[0]
    return ChangeSet(
        change_set_id="cs-0001",
        model_id=model.model_id,
        commands=(RenameElement(element_id=victim.element_id, new_name=new_name),),
    )


# -- the manifest hook ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requirement("DATA-21", "DATA-26")
def test_publishing_with_a_change_record_writes_it_and_pins_its_digest(
    store: ReleaseStore,
    ops: ArchitectureOperations,
    example_model: Model,
    publish_release: Publisher,
) -> None:
    """DATA-21 asks a manifest to pin "validation and change reports". Now it can."""
    publish_release("rel-0001", example_model, expected_parent=None)
    baseline = ops.baseline()
    candidate = ops.change(baseline, rename(baseline, "Portfolio Technology Evaluation"))
    record = ops.change_set(
        change_set_id="cs-0001",
        changes=ops.diff(baseline, candidate),
        authored_by=AGENT,
        base_release_id="rel-0001",
        rationale="Align the name with the accepted decision.",
        validation=ops.validate(candidate),
    )
    assert record.is_preview

    published = ops.publish(
        PublicationRequest(
            store=store,
            candidate=ReleaseCandidate(
                release_id="rel-0002",
                model=candidate,
                source_bundle=source_bundle(source_id="s", text=EXAMPLE.read_text()),
            ),
            expected_parent="rel-0001",
            now=lambda: MOMENT,
            generator_commit="abc1234",
        ),
        change_set=record,
    )

    assert published.change_report_digest is not None
    written = store.artifact_dir("rel-0002") / "change-report.json"
    assert written.exists()
    assert published.change_report_digest == digest_bytes(written.read_bytes())

    # The report on disk is the record, and it names the release it describes — which the preview
    # could not, because at preview time that release did not exist.
    restored = ArchitectureChangeSet.model_validate_json(written.read_text())
    assert restored.new_release_id == "rel-0002"
    assert not restored.is_preview
    assert restored.rationale == "Align the name with the accepted decision."
    assert restored.changes == record.changes


@pytest.mark.integration
@pytest.mark.requirement("DATA-21")
def test_publishing_without_a_change_record_pins_nothing_and_writes_nothing(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """The negative control: a first release has nothing to be a change from."""
    first = publish_release("rel-0001", example_model, expected_parent=None)

    assert first.change_report_digest is None
    assert not (store.artifact_dir("rel-0001") / "change-report.json").exists()


@pytest.mark.integration
@pytest.mark.requirement("DATA-26")
def test_the_written_report_is_the_published_change_contract(
    store: ReleaseStore,
    ops: ArchitectureOperations,
    example_model: Model,
    publish_release: Publisher,
) -> None:
    """What lands on disk validates against the family `architecture schema` emits."""
    import jsonschema

    from tests.integration.test_change_cli import CONTRACT

    publish_release("rel-0001", example_model, expected_parent=None)
    baseline = ops.baseline()
    candidate = ops.change(baseline, rename(baseline, "Renamed"))
    ops.publish(
        PublicationRequest(
            store=store,
            candidate=ReleaseCandidate(
                release_id="rel-0002",
                model=candidate,
                source_bundle=source_bundle(source_id="s", text=EXAMPLE.read_text()),
            ),
            expected_parent="rel-0001",
            now=lambda: MOMENT,
            generator_commit="abc1234",
        ),
        change_set=ops.change_set(
            change_set_id="cs-0001",
            changes=ops.diff(baseline, candidate),
            authored_by=AGENT,
            validation=ops.validate(candidate),
        ),
    )

    payload = json.loads((store.artifact_dir("rel-0002") / "change-report.json").read_text())
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    jsonschema.validate(
        payload,
        {
            "$schema": contract["$schema"],
            "$defs": contract["$defs"],
            "$ref": "#/$defs/ArchitectureChangeSet",
        },
    )


# -- the storage cross-check ----------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requirement("DATA-57", "DATA-26")
def test_the_netted_change_feed_names_the_same_identities_as_the_digest(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """The cross-check section 11H asks for, and the arithmetic that makes it possible.

    The raw counts and the netted identities answer different questions about the same feed, and
    this asserts both: storage moved far more rows than the architecture changed, *and* once the
    rows that did not really move are cancelled, what is left is exactly what the digest says.
    """
    from tests.integration.conftest import rename_first_element

    base = publish_release("rel-0001", example_model, expected_parent=None)
    candidate = publish_release(
        "rel-0002", rename_first_element(example_model, "Renamed"), expected_parent="rel-0001"
    )

    assert compared_tables(base, candidate) == ("elements",)
    assert storage_disagreements(store, base, candidate) == ()

    versions = {
        "base_version": base.table("elements").delta_version,
        "candidate_version": candidate.table("elements").delta_version,
    }
    raw = changed_row_counts(store, "elements", **versions)
    netted = net_row_changes(store, "elements", "element_id", **versions)

    # The two numbers are *expected* to differ — that inequality is the DATA-57 lesson, and the
    # netted comparison is a different claim about a different quantity, not a tightening of it.
    assert sum(raw.values()) == 2 * len(example_model.elements)
    assert netted["changed"] == (example_model.elements[0].element_id,)
    assert netted["added"] == ()
    assert netted["removed"] == ()
    assert sum(raw.values()) > len(netted["changed"])


@pytest.mark.integration
@pytest.mark.requirement("DATA-57")
def test_a_reused_table_is_compared_by_nothing_rather_than_agreed_with(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """Silence is not agreement, and a caller that cannot tell them apart reports the wrong one."""
    from tests.integration.conftest import rename_first_element

    base = publish_release("rel-0001", example_model, expected_parent=None)
    candidate = publish_release(
        "rel-0002", rename_first_element(example_model, "Renamed"), expected_parent="rel-0001"
    )

    compared = compared_tables(base, candidate)

    assert "relationships" not in compared, "an unwritten table has nothing to cross-check"
    assert base.table("relationships").delta_version == (
        candidate.table("relationships").delta_version
    )
    assert net_row_changes(
        store, "relationships", "relationship_id", base_version=0, candidate_version=0
    ) == {"added": (), "removed": (), "changed": ()}


@pytest.mark.integration
@pytest.mark.requirement("DATA-57")
def test_the_storage_cross_check_reports_a_disagreement_it_is_given(
    store: ReleaseStore,
    example_model: Model,
    publish_release: Publisher,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two agree by construction on honest input, so a disagreement has to be injected."""
    from tests.integration.conftest import rename_first_element

    base = publish_release("rel-0001", example_model, expected_parent=None)
    candidate = publish_release(
        "rel-0002", rename_first_element(example_model, "Renamed"), expected_parent="rel-0001"
    )
    assert storage_disagreements(store, base, candidate) == ()

    monkeypatch.setattr(
        "architecture_toolkit.changes.audit.net_row_changes",
        lambda *args, **kwargs: {"added": ("invented-1",), "removed": (), "changed": ()},
    )

    found = storage_disagreements(store, base, candidate)

    assert len(found) == 2
    assert any("invented-1" in message for message in found)
    assert all("Delta change feed" in message for message in found)


@pytest.mark.integration
@pytest.mark.requirement("DATA-57")
def test_the_netted_feed_reports_additions_and_removals_not_only_changes(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """Every storage cross-check test renamed something, so two thirds of the netting never ran.

    `net_row_changes` cancels rows identical in `(identity, content_hash)`; what survives is the
    added, removed and changed sets. A corpus that only ever renames exercises the third arm and
    leaves the other two asserted by nothing.
    """
    from architecture_toolkit.domain.model import Relationship

    base = publish_release("rel-0001", example_model, expected_parent=None)
    extra = Relationship(
        relationship_id="rel-9",
        model_id=example_model.model_id,
        relationship_type_id="depends_on",
        source_element_id="system-1",
        target_element_id="component-1",
    )
    widened = example_model.model_validate(
        dict(example_model) | {"relationships": (*example_model.relationships[1:], extra)}
    )
    candidate = publish_release("rel-0002", widened, expected_parent="rel-0001")

    versions = {
        "base_version": base.table("relationships").delta_version,
        "candidate_version": candidate.table("relationships").delta_version,
    }
    netted = net_row_changes(store, "relationships", "relationship_id", **versions)

    assert netted["added"] == ("rel-9",)
    assert netted["removed"] == (example_model.relationships[0].relationship_id,)
    assert netted["changed"] == ()
    assert storage_disagreements(store, base, candidate) == ()


@pytest.mark.integration
@pytest.mark.requirement("DATA-25", "DATA-26")
def test_a_milestone_archive_carries_the_change_report(
    store: ReleaseStore,
    ops: ArchitectureOperations,
    example_model: Model,
    publish_release: Publisher,
    tmp_path: Path,
) -> None:
    """`archive.py` says an archive holds "the semantic change and validation reports".

    It copied only the validation one, so an archive of a release published with a change record
    lost it — and the digest the manifest pins would have had nothing in the archive to check
    against, which is the one thing a self-contained archive is for.
    """
    from architecture_toolkit.releases.archive import verify_archive, write_archive

    publish_release("rel-0001", example_model, expected_parent=None)
    baseline = ops.baseline()
    candidate = ops.change(baseline, rename(baseline, "Renamed"))
    published = ops.publish(
        PublicationRequest(
            store=store,
            candidate=ReleaseCandidate(
                release_id="rel-0002",
                model=candidate,
                source_bundle=source_bundle(source_id="s", text=EXAMPLE.read_text()),
            ),
            expected_parent="rel-0001",
            now=lambda: MOMENT,
            generator_commit="abc1234",
        ),
        change_set=ops.change_set(
            change_set_id="cs-0001",
            changes=ops.diff(baseline, candidate),
            authored_by=AGENT,
            validation=ops.validate(candidate),
        ),
    )
    assert published.change_report_digest is not None

    archived = write_archive(store, published, tmp_path / "milestone")

    copied = archived.root / "reports" / "change-report.json"
    assert copied.is_file()
    assert digest_bytes(copied.read_bytes()) == published.change_report_digest
    assert (archived.root / "reports" / "validation-report.json").is_file()
    assert verify_archive(archived.root) == ()

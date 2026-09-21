"""Retention that cannot invalidate a retained release (DATA-25, DATA-58)."""

import pytest

from architecture_toolkit.domain.model import Model
from architecture_toolkit.domain.semantics import model_digest
from architecture_toolkit.releases.errors import RetentionSafetyError
from architecture_toolkit.releases.reader import read_model
from architecture_toolkit.releases.retention import (
    probe_readability,
    referenced_versions,
    retention_plan,
    vacuum_table,
)
from architecture_toolkit.releases.store import ReleaseStore
from architecture_toolkit.storage import delta
from architecture_toolkit.storage.schemas import TABLE_IDS
from tests.integration.conftest import Publisher, rename_first_element


@pytest.mark.integration
@pytest.mark.requirement("DATA-58")
def test_the_protected_set_is_every_version_every_manifest_pins(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """Computed from the manifests, so it cannot be a stale idea of which releases exist."""
    publish_release("rel-0001", example_model, expected_parent=None, attempt=1)
    publish_release(
        "rel-0002",
        rename_first_element(example_model, "Second"),
        expected_parent="rel-0001",
        attempt=2,
    )

    protected = referenced_versions(store)
    assert set(protected) == set(TABLE_IDS)
    # Two releases pinned two different `elements` versions; both are protected.
    assert protected["elements"] == frozenset({0, 1})
    # A table neither release changed has one protected version.
    assert protected["references"] == frozenset({0})


@pytest.mark.integration
@pytest.mark.requirement("DATA-58")
def test_a_superseded_release_still_protects_its_versions(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """DATA-58 protects "a retained manifest", not "the current one"."""
    first = publish_release("rel-0001", example_model, expected_parent=None, attempt=1)
    publish_release(
        "rel-0002",
        rename_first_element(example_model, "Second"),
        expected_parent="rel-0001",
        attempt=2,
    )
    assert store.current_id() == "rel-0002"

    vacuum_table(store, "elements", apply=True)

    # The superseded release still reads, which is the whole claim.
    assert model_digest(read_model(store, first)) == first.model_digest
    assert probe_readability(store) == ()


@pytest.mark.integration
@pytest.mark.requirement("DATA-58")
def test_vacuum_is_a_dry_run_until_it_is_asked_not_to_be(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """Nothing is vacuumed by default. A destructive default would be the wrong one."""
    publish_release("rel-0001", example_model, expected_parent=None, attempt=1)
    publish_release(
        "rel-0002",
        rename_first_element(example_model, "Second"),
        expected_parent="rel-0001",
        attempt=2,
    )
    before = delta.read_version(store.table_location("elements"), version=0).num_rows

    plan = vacuum_table(store, "elements")
    assert plan.keep_versions == (0, 1)
    assert delta.read_version(store.table_location("elements"), version=0).num_rows == before


@pytest.mark.integration
@pytest.mark.requirement("DATA-58")
def test_a_plan_reports_what_it_would_protect(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    publish_release("rel-0001", example_model, expected_parent=None, attempt=1)
    plan = retention_plan(store, "elements")
    assert plan.table_id == "elements"
    assert plan.keep_versions == (0,)
    assert plan.is_empty, "a single release has nothing to remove"


@pytest.mark.integration
@pytest.mark.requirement("DATA-58")
def test_vacuuming_a_table_no_manifest_describes_is_refused(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """Either the table is not part of any release, or this is the wrong store. Both are reasons
    to stop rather than to delete."""
    publish_release("rel-0001", example_model, expected_parent=None, attempt=1)
    manifest = store.read_manifest("rel-0001")
    narrowed = manifest.model_validate(
        dict(manifest) | {"tables": tuple(r for r in manifest.tables if r.table_id != "elements")}
    )
    store.manifest_path("rel-0001").write_text(narrowed.model_dump_json(), encoding="utf-8")

    with pytest.raises(RetentionSafetyError, match="refusing to vacuum"):
        vacuum_table(store, "elements", apply=True)


@pytest.mark.integration
@pytest.mark.requirement("DATA-58", "DATA-25")
def test_every_retained_release_stays_readable_after_vacuuming_every_table(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """The M2 gate's fourth clause: "retained historical releases remain readable"."""
    first = publish_release("rel-0001", example_model, expected_parent=None, attempt=1)
    second = publish_release(
        "rel-0002",
        rename_first_element(example_model, "Second"),
        expected_parent="rel-0001",
        attempt=2,
    )
    third = publish_release(
        "rel-0003",
        rename_first_element(example_model, "Third"),
        expected_parent="rel-0002",
        attempt=3,
    )

    for table_id in TABLE_IDS:
        vacuum_table(store, table_id, apply=True)

    assert probe_readability(store) == ()
    for manifest in (first, second, third):
        assert model_digest(read_model(store, manifest)) == manifest.model_digest


@pytest.mark.integration
@pytest.mark.requirement("DATA-58")
def test_readability_is_probed_rather_than_assumed(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """A release made unreadable outside this module is reported, not discovered at read time."""
    publish_release("rel-0001", example_model, expected_parent=None, attempt=1)
    assert probe_readability(store) == ()

    # Vacuum with an empty keep-list, which is what a policy that ignored manifests would do.
    location = store.table_location("elements")
    publish_release(
        "rel-0002",
        rename_first_element(example_model, "Second"),
        expected_parent="rel-0001",
        attempt=2,
    )
    delta.vacuum(location, version=delta.tip(location), keep_versions=[], dry_run=False)

    findings = probe_readability(store)
    assert findings, "a vacuum that ignored the manifests should be detectable"
    assert all(finding.code == "CORE.RELEASE.VERSION_UNREADABLE" for finding in findings)

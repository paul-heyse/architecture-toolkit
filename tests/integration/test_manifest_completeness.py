"""Every pin DATA-21 requires is actually pinned by a real publication.

This is the guard for a *class* of defect rather than for one instance of it. W4 shipped with
`parent_release_id` and `change_set_id` never set, so the release chain did not link and the CLI
reported "0 reused" forever — and the test that should have caught it read
`assert x is None or x == "rel-0001"`, which is not an assertion.

The fix for that is not to assert those two fields. It is to enumerate what the contract says a
manifest must pin and check the whole list against a manifest that was actually published, so the
next field added to `ArchitectureRelease` and forgotten in `read_back_staged_versions` fails here
without anyone remembering to write a test for it.

`data.md` § ArchitectureRelease publication lists:

    release/model/parent/change-set IDs; schema/profile versions; exact table URI + Delta version
    + semantic digest; source bundle digest/revision; generator/toolkit commit; validation/change
    reports; required projection/export digests where release policy governs them.
"""

from pathlib import Path

import pytest

from architecture_toolkit.domain.commands import ChangeSet, RenameElement
from architecture_toolkit.domain.model import Model
from architecture_toolkit.domain.semantics import model_digest, stamp_digests
from architecture_toolkit.releases.candidate import ReleaseCandidate
from architecture_toolkit.releases.manifest import ArchitectureRelease
from architecture_toolkit.releases.provenance import source_bundle
from architecture_toolkit.releases.publication import PublicationRequest, publish
from architecture_toolkit.releases.store import ReleaseStore
from architecture_toolkit.storage.schemas import TABLE_IDS
from architecture_toolkit.validation.release import chain_breaks
from tests.integration.conftest import MOMENT, Publisher, rename_first_element

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "minimal" / "model.yaml"

# Every field a published manifest must carry a real value for, and how to read it. A field here
# that is left at its default is the defect this module exists to catch.
REQUIRED_PINS: dict[str, str] = {
    "release_id": "DATA-21: the release's own identity",
    "model_id": "DATA-21: which model this is a revision of",
    "schema_version": "DATA-21: the domain schema it validates against",
    "profile_version": "DATA-21: the vocabulary it was validated against",
    "model_digest": "DATA-21 via DATA-27: the semantic identity of the whole model",
    "published_at": "DATA-12: a UTC microsecond instant",
    "tables": "DATA-21: exact table uri, Delta version and semantic digest",
    "source_bundle": "DATA-21, DATA-37: what it was authored from",
    "generator": "DATA-21: the toolkit commit and the durable conventions",
    "validation_report_digest": "DATA-21: the validation report it pins",
}

# Fields that are legitimately absent, each with the wave that fills it. Recorded in the same
# shape as `tests/strategies/__init__.py::DEFERRED_GROUPS`, so a deferral stays distinguishable
# from an oversight — which is precisely the distinction this module exists to keep.
DEFERRED_PINS: dict[str, str] = {
    "change_report_digest": "W6 — no change report exists until semantic change records (DATA-26)",
    "projection_artifact_digests": "W8 — PROJ-41; declared at W4 so filling it is no migration",
    "render_artifact_digests": "W8 — PROJ-41",
    "validation_reports": "W8 — PROJ-41",
    "outputs": "W8 — PROJ-41",
}

# Only on a release that had a parent and a change set. A first release genuinely has neither.
REQUIRED_ON_A_DESCENDANT: dict[str, str] = {
    "parent_release_id": "DATA-21: the release it was built against",
    "change_set_id": "DATA-21: the typed change set that produced it",
}

# Only on a design alternative, and refused on anything else. A third conditional list rather than
# a second entry in the one above, because the condition is different: a release is a descendant or
# a root by position, and an alternative or a revision by intent.
REQUIRED_ON_AN_ALTERNATIVE: dict[str, str] = {
    "scenario_id": "DATA-28: which alternative this release belongs to",
    "baseline_release_id": "DATA-28: the design it is an alternative to",
}


@pytest.mark.unit
@pytest.mark.requirement("DATA-21")
def test_the_two_lists_together_cover_every_manifest_field() -> None:
    """A field in neither list is a field nobody decided about.

    Without this, adding a manifest field and forgetting to populate it would leave both lists
    unchanged and every assertion below still passing.
    """
    declared = set(ArchitectureRelease.model_fields)
    accounted = (
        set(REQUIRED_PINS)
        | set(DEFERRED_PINS)
        | set(REQUIRED_ON_A_DESCENDANT)
        | set(REQUIRED_ON_AN_ALTERNATIVE)
    )
    assert declared == accounted, f"unaccounted manifest fields: {sorted(declared ^ accounted)}"


@pytest.mark.integration
@pytest.mark.requirement("DATA-21")
def test_a_published_manifest_pins_every_required_field(
    example_model: Model, publish_release: Publisher
) -> None:
    manifest = publish_release("rel-0001", example_model, expected_parent=None)
    empty = ArchitectureRelease.model_fields
    unset = {
        name: reason
        for name, reason in REQUIRED_PINS.items()
        if getattr(manifest, name) in (None, (), "", empty[name].default)
    }
    assert not unset, f"a published manifest left these at their defaults: {unset}"


@pytest.mark.integration
@pytest.mark.requirement("DATA-21")
def test_a_descendant_pins_its_parent_and_its_change_set(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """The defect W4 shipped: both of these were always `None`."""
    publish_release("rel-0001", example_model, expected_parent=None)

    victim = example_model.elements[0]
    change_set = ChangeSet(
        change_set_id="cs-0001",
        model_id=example_model.model_id,
        expected_base_digest=model_digest(stamp_digests(example_model)),
        commands=(
            RenameElement(
                element_id=victim.element_id, expected_name=victim.name, new_name="Renamed"
            ),
        ),
    )
    second = publish(
        PublicationRequest(
            store=store,
            candidate=ReleaseCandidate(
                release_id="rel-0002",
                model=example_model,
                source_bundle=source_bundle(source_id="s", text=EXAMPLE.read_text()),
            ),
            expected_parent="rel-0001",
            change_set=change_set,
            now=lambda: MOMENT,
            generator_commit="abc1234",
        )
    )

    for name, reason in REQUIRED_ON_A_DESCENDANT.items():
        assert getattr(second, name) is not None, f"{name} unset: {reason}"
    assert second.parent_release_id == "rel-0001"
    assert second.change_set_id == "cs-0001"


@pytest.mark.integration
@pytest.mark.requirement("DATA-21")
def test_a_release_without_a_change_set_still_pins_its_parent(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """Re-authoring a source is a publication with a parent and no change set."""
    publish_release("rel-0001", example_model, expected_parent=None)
    second = publish_release(
        "rel-0002",
        rename_first_element(example_model, "Re-authored"),
        expected_parent="rel-0001",
    )
    assert second.parent_release_id == "rel-0001"
    assert second.change_set_id is None


@pytest.mark.integration
@pytest.mark.requirement("DATA-21")
def test_the_chain_of_a_real_store_links_and_has_one_root(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """Three releases, one navigable history."""
    publish_release("rel-0001", example_model, expected_parent=None)
    publish_release(
        "rel-0002",
        rename_first_element(example_model, "Second"),
        expected_parent="rel-0001",
    )
    publish_release(
        "rel-0003",
        rename_first_element(example_model, "Third"),
        expected_parent="rel-0002",
    )

    entries = [(m.release_id, m.parent_release_id, m.model_id) for m in store.iter_manifests()]
    assert chain_breaks(entries) == ()

    # And the chain is walkable from the current release back to the first.
    walked = []
    current = store.current_id()
    while current is not None:
        walked.append(current)
        current = store.read_manifest(current).parent_release_id
    assert walked == ["rel-0003", "rel-0002", "rel-0001"]


@pytest.mark.unit
@pytest.mark.requirement("DATA-21")
def test_the_chain_check_catches_each_way_a_chain_fails() -> None:
    """A guard nothing exercises is indistinguishable from one that matches nothing."""
    missing = chain_breaks([("rel-0002", "rel-0001", "m")])
    assert [d.code for d in missing] == ["CORE.RELEASE.PARENT_NOT_FOUND"]

    cycle = chain_breaks([("rel-0001", "rel-0002", "m"), ("rel-0002", "rel-0001", "m")])
    assert {d.code for d in cycle} == {"CORE.RELEASE.CHAIN_CYCLE"}

    two_roots = chain_breaks([("rel-0001", None, "m"), ("rel-0002", None, "m")])
    assert [d.code for d in two_roots] == ["CORE.RELEASE.MULTIPLE_ROOTS"]

    # Two models in one store each having a root is not a break.
    assert chain_breaks([("rel-0001", None, "a"), ("rel-0002", None, "b")]) == ()


@pytest.mark.integration
@pytest.mark.requirement("DATA-22")
def test_the_reuse_count_a_publication_reports_is_the_real_one(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """`cli._reused` compares against the parent manifest, so it was dead logic until now.

    Republishing identical content reuses every table, which is DATA-22's rule at its limit.
    """
    publish_release("rel-0001", example_model, expected_parent=None)
    second = publish_release("rel-0002", example_model, expected_parent="rel-0001")

    first_pins = dict(store.read_manifest("rel-0001").pinned_versions)
    assert dict(second.pinned_versions) == first_pins
    assert len(first_pins) == len(TABLE_IDS)

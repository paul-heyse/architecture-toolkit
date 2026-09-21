"""The compatibility matrix through the whole contract path (DATA-60, DATA-39).

`data.md` names the path exactly:

```text
Pydantic -> PyArrow -> deltalake -> explicit version -> SnapshotProvider -> DataFusion
 -> Arrow result
```

W3 seeded the Arrow-only half in `test_arrow_matrix.py`. This runs the rest: every case is
published as a real release, read back through every usable provider, queried in a release-scoped
DataFusion context and validated back into Pydantic. That closes the two §11I dimensions W3 could
not reach — **query correctness** end to end, and **historical reproducibility**, which needs more
than one release to mean anything.

The header table in `test_arrow_matrix.py` marked historical reproducibility `W4`. This is it.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from datafusion import SessionContext

from architecture_toolkit.domain.authoring import parse_model, parse_source
from architecture_toolkit.domain.model import Model
from architecture_toolkit.domain.semantics import model_digest, stamp_digests
from architecture_toolkit.releases.candidate import ReleaseCandidate
from architecture_toolkit.releases.manifest import ArchitectureRelease
from architecture_toolkit.releases.provenance import source_bundle
from architecture_toolkit.releases.publication import PublicationRequest, publish
from architecture_toolkit.releases.reader import read_model, read_table_set
from architecture_toolkit.releases.store import ReleaseStore
from architecture_toolkit.storage.catalog import register_pins
from architecture_toolkit.storage.digests import table_set_digests
from architecture_toolkit.storage.schemas import TABLE_IDS
from architecture_toolkit.storage.snapshot import provider_named

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "minimal" / "model.yaml"
MOMENT = datetime(2026, 9, 20, 12, 0, 0, tzinfo=UTC)
USABLE = ("materialized", "dataset", "stream")


def example() -> Model:
    return parse_model(parse_source(EXAMPLE.read_text(), source_id="example"))


def renamed(model: Model, new_name: str) -> Model:
    victim = model.elements[0]
    return model.model_validate(
        dict(model)
        | {
            "elements": tuple(
                element.model_validate(dict(element) | {"name": new_name})
                if element.element_id == victim.element_id
                else element
                for element in model.elements
            )
        }
    )


def publish_into(
    store: ReleaseStore, release_id: str, model: Model, *, parent: str | None
) -> ArchitectureRelease:
    return publish(
        PublicationRequest(
            store=store,
            candidate=ReleaseCandidate(
                release_id=release_id,
                model=model,
                source_bundle=source_bundle(source_id="s", text=EXAMPLE.read_text()),
            ),
            expected_parent=parent,
            now=lambda: MOMENT,
            generator_commit="abc1234",
        )
    )


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-60", "DATA-14", "DATA-51")
@pytest.mark.parametrize("provider_name", USABLE)
def test_the_whole_path_round_trips_for_every_provider(
    provider_name: str, tmp_path: Path, record_property: object
) -> None:
    """Pydantic to Arrow to Delta to an explicit version to a provider to DataFusion and back."""
    assert callable(record_property)
    store = ReleaseStore.at(tmp_path).initialize()
    manifest = publish_into(store, "rel-0001", example(), parent=None)

    reader = provider_named(
        provider_name, {ref.table_id: store.resolve(ref.uri) for ref in manifest.tables}
    )
    record_property("provider", reader.describe().model_dump_json())
    record_property("release", manifest.release_id)

    # -> SnapshotProvider -> DataFusion
    context = SessionContext()
    register_pins(context, reader, dict(manifest.pinned_versions))
    answer = context.sql(
        "SELECT element_id, name FROM elements ORDER BY element_id LIMIT 1"
    ).to_arrow_table()
    assert answer.num_rows == 1

    # -> Arrow result -> Pydantic
    restored = read_model(store, manifest, provider=reader)
    assert restored == stamp_digests(example())
    assert model_digest(restored) == manifest.model_digest


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-60", "DATA-21")
@pytest.mark.parametrize("provider_name", USABLE)
def test_historical_reproducibility_across_three_releases(
    provider_name: str, tmp_path: Path
) -> None:
    """§11I's historical-version reproducibility, and the M2 gate's fourth clause.

    Three releases, each with a different `elements` version. Every one must still reproduce the
    model it published — not the current one — through every provider. A provider that resolved
    latest would pass the first assertion and fail the others, which is why all three are checked
    rather than only the oldest.
    """
    store = ReleaseStore.at(tmp_path).initialize()
    models = {
        "rel-0001": example(),
        "rel-0002": renamed(example(), "Second"),
        "rel-0003": renamed(example(), "Third"),
    }
    parents = {"rel-0001": None, "rel-0002": "rel-0001", "rel-0003": "rel-0002"}
    manifests = {
        release_id: publish_into(store, release_id, model, parent=parents[release_id])
        for release_id, model in models.items()
    }
    # The releases genuinely differ in storage, not only in name.
    versions = {rid: dict(m.pinned_versions)["elements"] for rid, m in manifests.items()}
    assert sorted(versions.values()) == [0, 1, 2]

    for release_id, manifest in manifests.items():
        reader = provider_named(
            provider_name, {ref.table_id: store.resolve(ref.uri) for ref in manifest.tables}
        )
        restored = read_model(store, manifest, provider=reader)
        assert model_digest(restored) == model_digest(stamp_digests(models[release_id]))
        assert restored.elements[0].name == models[release_id].elements[0].name


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-60", "DATA-45")
def test_table_digests_survive_the_whole_storage_round_trip(tmp_path: Path) -> None:
    """Type and metadata fidelity together: what went in is what comes out, per table."""
    store = ReleaseStore.at(tmp_path).initialize()
    from architecture_toolkit.storage.mappings import compile_tables

    expected = table_set_digests(compile_tables(example()))
    manifest = publish_into(store, "rel-0001", example(), parent=None)
    observed = table_set_digests(read_table_set(store, manifest))

    assert dict(observed) == dict(expected)
    assert {ref.table_id: ref.semantic_digest for ref in manifest.tables} == dict(expected)
    assert set(observed) == set(TABLE_IDS)


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-60", "DATA-39", "DATA-47")
def test_two_releases_are_queryable_side_by_side_without_mixing_latest(tmp_path: Path) -> None:
    """§11D: cross-release comparison uses explicit named sides.

    The assertion that matters is that the two sides *disagree*, because that is only possible if
    each resolved its own pinned versions rather than both resolving the tip.
    """
    store = ReleaseStore.at(tmp_path).initialize()
    first = publish_into(store, "rel-0001", example(), parent=None)
    second = publish_into(
        store, "rel-0002", renamed(example(), "Candidate side"), parent="rel-0001"
    )

    context = SessionContext()
    for prefix, manifest in (("base_", first), ("candidate_", second)):
        reader = provider_named(
            "materialized", {ref.table_id: store.resolve(ref.uri) for ref in manifest.tables}
        )
        register_pins(context, reader, dict(manifest.pinned_versions), prefix=prefix)

    victim = example().elements[0].element_id
    # Bound rather than interpolated, which is what `tests/qualification/test_data_stack.py`
    # already qualified DataFusion for and what keeps the recipe shape honest for W5.
    answer = context.sql(
        "SELECT b.name AS base_name, c.name AS candidate_name "
        "FROM base_elements b JOIN candidate_elements c USING (element_id) "
        "WHERE b.element_id = $id",
        param_values={"id": victim},
    ).to_arrow_table()
    row = answer.to_pylist()[0]
    assert row["candidate_name"] == "Candidate side"
    assert row["base_name"] != row["candidate_name"]

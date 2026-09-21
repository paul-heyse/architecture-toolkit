"""The SnapshotProvider ladder, qualified against a real published release (DATA-51, DATA-52).

`data.md` lists five provider rows and `ARCH-TOOL-DATA-001` §11B states seven obligations every
one of them must meet. This runs all of them over the eleven tables of an actual release, because
a provider that is only exercised on a one-column fixture has not been qualified against anything
the toolkit stores.

The obligation that matters most is the one a lazy provider is most likely to break quietly:
**a pinned version stays pinned**. A dataset or a stream built from version 0 must still read
version 0 after the table has moved on. A provider that silently followed the tip would violate
invariant 5 in the least visible way there is — everything would work, and the answers would be
about the wrong release.

DATA-52's wording is "qualify … *before* replacing the materialized provider". Qualifying is not
replacing, so the default is asserted to be unchanged here too.
"""

from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pytest
from datafusion import SessionContext

from architecture_toolkit.domain.authoring import parse_model, parse_source
from architecture_toolkit.domain.model import Model
from architecture_toolkit.domain.protocols import SnapshotProvider
from architecture_toolkit.domain.providers import Materialization
from architecture_toolkit.releases.candidate import ReleaseCandidate
from architecture_toolkit.releases.manifest import ArchitectureRelease
from architecture_toolkit.releases.provenance import source_bundle
from architecture_toolkit.releases.publication import PublicationRequest, publish
from architecture_toolkit.releases.store import ReleaseStore
from architecture_toolkit.storage.catalog import register_pins
from architecture_toolkit.storage.digests import table_semantic_digest, table_set_digests
from architecture_toolkit.storage.errors import StorageError
from architecture_toolkit.storage.interchange import as_table
from architecture_toolkit.storage.mappings import compile_tables
from architecture_toolkit.storage.schemas import TABLE_IDS, TABLE_SCHEMAS
from architecture_toolkit.storage.snapshot import (
    DEFAULT_PROVIDER,
    PROVIDERS,
    MaterializedPyArrowSnapshotProvider,
    NativeProviderUnavailableError,
    provider_named,
)

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "minimal" / "model.yaml"
MOMENT = datetime(2026, 9, 20, 12, 0, 0, tzinfo=UTC)

# Every rung that is usable under this lock. `native` is excluded because it refuses by design,
# and its refusal is asserted separately rather than swept into a skip.
USABLE = ("materialized", "dataset", "stream")


def example() -> Model:
    return parse_model(parse_source(EXAMPLE.read_text(), source_id="example"))


def published(tmp_path: Path) -> tuple[ReleaseStore, ArchitectureRelease]:
    store = ReleaseStore.at(tmp_path).initialize()
    manifest = publish(
        PublicationRequest(
            store=store,
            candidate=ReleaseCandidate(
                release_id="rel-0001",
                model=example(),
                source_bundle=source_bundle(source_id="s", text=EXAMPLE.read_text()),
            ),
            expected_parent=None,
            attempt=1,
            now=lambda: MOMENT,
            generator_commit="abc1234",
        )
    )
    return store, manifest


def provider(
    name: str, store: ReleaseStore, manifest: ArchitectureRelease
) -> MaterializedPyArrowSnapshotProvider:
    return provider_named(name, {ref.table_id: store.resolve(ref.uri) for ref in manifest.tables})


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-51")
@pytest.mark.parametrize("name", USABLE)
def test_every_provider_returns_the_same_records_for_every_table(name: str, tmp_path: Path) -> None:
    """§11B: "produce logically equivalent records independent of batch/chunk boundaries"."""
    store, manifest = published(tmp_path)
    expected = table_set_digests(compile_tables(example()))
    reader = provider(name, store, manifest)

    for ref in manifest.tables:
        table = as_table(reader.open(ref.table_id, version=ref.delta_version))
        assert table_semantic_digest(ref.table_id, table) == expected[ref.table_id]


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-51", "DATA-52")
@pytest.mark.parametrize("name", USABLE)
def test_every_provider_reports_the_declared_schema(name: str, tmp_path: Path) -> None:
    """§11B: "expose the expected Arrow schema for that table version"."""
    store, manifest = published(tmp_path)
    reader = provider(name, store, manifest)
    for ref in manifest.tables:
        schema = reader.schema_for(ref.table_id, version=ref.delta_version)
        declared = TABLE_SCHEMAS[ref.table_id].bare()
        assert pa.schema(schema).equals(declared, check_metadata=False), ref.table_id


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-51", "DATA-21")
@pytest.mark.parametrize("name", USABLE)
def test_a_pinned_version_stays_pinned_after_the_table_moves_on(name: str, tmp_path: Path) -> None:
    """The obligation a lazy provider is most likely to break quietly.

    A second release moves `elements` to version 1. Every provider opened at version 0 must still
    return the ten rows of version 0 — otherwise a release would answer with another release's
    data and nothing would look wrong.
    """
    store, first = published(tmp_path)
    changed = example()
    victim = changed.elements[0]
    changed = changed.model_validate(
        dict(changed)
        | {
            "elements": tuple(
                element.model_validate(dict(element) | {"name": "Moved on"})
                if element.element_id == victim.element_id
                else element
                for element in changed.elements
            )
        }
    )
    publish(
        PublicationRequest(
            store=store,
            candidate=ReleaseCandidate(
                release_id="rel-0002",
                model=changed,
                source_bundle=source_bundle(source_id="s", text="x"),
            ),
            expected_parent="rel-0001",
            attempt=2,
            now=lambda: MOMENT,
            generator_commit="abc1234",
        )
    )
    assert dict(store.read_manifest("rel-0002").pinned_versions)["elements"] == 1

    reader = provider(name, store, first)
    names = as_table(reader.open("elements", version=0)).column("name").to_pylist()
    assert "Moved on" not in names
    assert (
        table_semantic_digest("elements", as_table(reader.open("elements", version=0)))
        == dict(table_set_digests(compile_tables(example())))["elements"]
    )


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-51", "DATA-39")
@pytest.mark.parametrize("name", USABLE)
def test_every_provider_registers_a_release_catalog_with_the_same_answers(
    name: str, tmp_path: Path
) -> None:
    """DATA-39: the catalog is rebuilt from the manifest, whichever provider does the reading."""
    store, manifest = published(tmp_path)
    context = SessionContext()
    schemas = register_pins(
        context, provider(name, store, manifest), dict(manifest.pinned_versions)
    )

    assert set(schemas) == set(TABLE_IDS)
    counts = {
        table_id: context.sql(f'SELECT count(*) AS c FROM "{table_id}"')  # noqa: S608
        .to_arrow_table()
        .to_pylist()[0]["c"]
        for table_id in TABLE_IDS
    }
    assert counts["elements"] == 10
    assert counts["relationships"] == 8
    # §11B's "preserve typed empties": the example has no deployment detail beyond one element,
    # so the assertion that matters is the exact count each table actually holds — `>= 0` would
    # have been true of a provider that returned nothing at all.
    expected = {table_id: compile_tables(example())[table_id].num_rows for table_id in TABLE_IDS}
    assert counts == expected


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-39", "DATA-47")
def test_two_releases_register_as_explicit_named_sides(tmp_path: Path) -> None:
    """§11D's `base.*` / `candidate.*` shape, which is what stops a comparison mixing latest state.

    W5 owns query recipes; this only proves the registration primitive supports the shape, so W5
    does not have to reopen the provider layer to get it.
    """
    store, first = published(tmp_path)
    context = SessionContext()
    reader = provider("materialized", store, first)
    register_pins(context, reader, dict(first.pinned_versions), prefix="base_")
    register_pins(context, reader, dict(first.pinned_versions), prefix="candidate_")
    answer = context.sql(
        "SELECT (SELECT count(*) FROM base_elements) AS b, "
        "(SELECT count(*) FROM candidate_elements) AS c"
    ).to_arrow_table()
    assert answer.to_pylist() == [{"b": 10, "c": 10}]


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-34", "DATA-51")
@pytest.mark.parametrize("name", sorted(PROVIDERS))
def test_every_provider_describes_itself_deterministically(name: str, tmp_path: Path) -> None:
    """§11B: "report provider type and relevant library versions in qualification diagnostics"."""
    store, manifest = published(tmp_path)
    description = provider(name, store, manifest).describe()
    assert description.provider_type == PROVIDERS[name].__name__
    assert description.native_ffi_enabled is False
    assert [library for library, _ in description.library_versions] == sorted(
        ("pyarrow", "deltalake", "datafusion", "arro3-core")
    )
    assert description == provider(name, store, manifest).describe()
    assert isinstance(provider(name, store, manifest), SnapshotProvider)


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-51")
def test_each_rung_names_its_own_materialization_behaviour() -> None:
    """§11B: "make its materialization/streaming behavior explicit" — a caller chooses on this."""
    expected = {
        "materialized": Materialization.MATERIALIZED,
        "dataset": Materialization.LAZY_DATASET,
        "stream": Materialization.STREAMING,
    }
    for name, how in expected.items():
        assert provider_named(name, {}).describe().materialization is how


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-52", "DATA-60")
def test_the_native_provider_refuses_under_this_lock(tmp_path: Path) -> None:
    """DATA-52 and the handoff's "never enable native FFI merely because it exists".

    deltalake exports a DataFusion 55.x provider and the lock pins 54. The library rejects the
    mismatch itself; this asserts the toolkit does not route around it. When the majors align,
    this test fails and somebody enables the rung deliberately.
    """
    store, manifest = published(tmp_path)
    native = provider("native", store, manifest)
    for call in (
        lambda: native.schema_for("elements", version=0),
        lambda: native.open("elements", version=0),
        lambda: native.register(SessionContext(), "elements", "elements", version=0),
    ):
        with pytest.raises(NativeProviderUnavailableError, match="disabled"):
            call()
    assert native.describe().native_ffi_enabled is False


@pytest.mark.qualification
@pytest.mark.requirement("DATA-52")
def test_the_materialized_provider_remains_the_default() -> None:
    """Qualifying the candidates is not replacing the baseline."""
    assert DEFAULT_PROVIDER == "materialized"
    assert PROVIDERS[DEFAULT_PROVIDER] is MaterializedPyArrowSnapshotProvider


@pytest.mark.qualification
@pytest.mark.requirement("DATA-51")
def test_an_unknown_provider_name_is_refused_with_the_choices() -> None:
    with pytest.raises(StorageError, match="unknown snapshot provider"):
        provider_named("quantum", {})

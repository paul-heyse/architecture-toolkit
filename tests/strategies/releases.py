"""Release manifest strategies (CORE-45, DATA-21).

The eighth of the strategy groups `core.md` names, and the last one W4 can build — `views` and
`artifacts` still have no models. A manifest is drawn *against a model* rather than in isolation,
for the same reason commands are: a manifest whose table digests correspond to nothing is a valid
record and an incoherent release, and only the second is interesting.

`manifests(model)` produces a manifest that genuinely pins what `compile_tables(model)` produces,
so a property may assume the pins are truthful and go on to test what publication does with them.
"""

from datetime import UTC, datetime

from hypothesis import strategies as st

from architecture_toolkit.domain.model import Model
from architecture_toolkit.domain.semantics import model_digest, stamp_digests
from architecture_toolkit.releases.manifest import (
    ArchitectureRelease,
    GeneratorProvenance,
    SourceBundle,
    TableRef,
)
from architecture_toolkit.storage.digests import table_set_digests
from architecture_toolkit.storage.mappings import compile_tables
from architecture_toolkit.storage.schemas import STORAGE_SCHEMA_VERSION, TABLE_IDS
from tests.strategies.ids import digests

__all__ = ["generator_provenances", "manifests", "release_ids", "source_bundles", "table_refs"]

release_ids = st.integers(min_value=1, max_value=9999).map(lambda n: f"rel-{n:04d}")

# Instants are drawn inside a bounded UTC window: `published_at` is a real timestamp, and a
# strategy that wandered across the whole datetime range would spend its examples on calendar
# edge cases rather than on release behaviour.
published_instants = st.datetimes(
    min_value=datetime(2020, 1, 1), max_value=datetime(2030, 12, 31)
).map(lambda value: value.replace(tzinfo=UTC))

source_bundles = st.builds(
    SourceBundle,
    source_id=st.text(min_size=1, max_size=40).filter(lambda value: bool(value.strip())),
    digest=digests,
    revision=st.none() | st.text(min_size=1, max_size=40),
    snapshot_path=st.none(),
)

generator_provenances = st.builds(
    GeneratorProvenance,
    toolkit_version=st.just("0.1.0"),
    toolkit_commit=st.text(min_size=1, max_size=40).filter(lambda value: bool(value.strip())),
    storage_schema_version=st.just(STORAGE_SCHEMA_VERSION),
    hash_algorithm_version=st.just("1"),
)

table_refs = st.builds(
    TableRef,
    table_id=st.sampled_from(TABLE_IDS),
    uri=st.sampled_from(TABLE_IDS).map(lambda name: f"tables/{name}"),
    delta_version=st.integers(min_value=0, max_value=50),
    semantic_digest=digests,
    row_count=st.integers(min_value=0, max_value=1000),
)


@st.composite
def manifests(draw: st.DrawFn, model: Model) -> ArchitectureRelease:
    """A manifest that truthfully pins what compiling `model` produces.

    Delta versions are drawn independently per table, which is the realistic shape: DATA-22's
    reuse rule means a revision that touches one table leaves the other ten at whatever version
    they already had.
    """
    stamped = stamp_digests(model)
    table_set = compile_tables(stamped)
    digests_by_table = table_set_digests(table_set)
    return ArchitectureRelease(
        release_id=draw(release_ids),
        model_id=stamped.model_id,
        parent_release_id=draw(st.none() | release_ids),
        change_set_id=draw(st.none() | st.just("cs-0001")),
        schema_version=stamped.schema_version,
        profile_version=stamped.profile_version,
        model_digest=model_digest(stamped),
        published_at=draw(published_instants),
        tables=tuple(
            TableRef(
                table_id=table_id,
                uri=f"tables/{table_id}",
                delta_version=draw(st.integers(min_value=0, max_value=50)),
                semantic_digest=digests_by_table[table_id],
                row_count=table_set[table_id].num_rows,
            )
            for table_id in TABLE_IDS
        ),
        source_bundle=draw(source_bundles),
        generator=draw(generator_provenances),
    )

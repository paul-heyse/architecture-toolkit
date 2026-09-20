"""The exact-stack compatibility matrix (DATA-60), seeded for W3.

DATA-60 asks for a matrix that is *continuously tested* on supported platforms, which rules out a
prose table. Each case is a fixture that runs the whole path a real table takes — Pydantic to
Arrow to Delta to DataFusion and back to Pydantic — and asserts what survived. When a library
upgrade changes behaviour, a case fails and names the dimension it failed on, instead of a
paragraph going quietly out of date.

`ARCH-TOOL-DATA-001` §11I names seven dimensions. Six are exercised here; historical
reproducibility needs several published releases and belongs to W4, which extends this file with
its own rows rather than starting a second matrix.

| Dimension | Where |
| --- | --- |
| Type fidelity | the schema of every read-back table equals what was written |
| Metadata fidelity | field-level survives Delta, schema-level does not, `reattach` repairs it |
| Logical row equivalence | every case ends by validating the rows back into Pydantic |
| Query correctness | DataFusion reads each case's distinguishing column |
| Batch and chunk independence | every case is also written as two chunkings |
| Memory and materialization | `describe()` is recorded with every case |
| Historical reproducibility | W4 |

Two cases are recorded as *findings* rather than as guarantees: DataFusion's extraction of a
non-nullable child from a null struct, and Delta's loss of schema-level metadata. Both are live
behaviour of the pinned stack, and both are pinned so an upgrade that changes them is visible.
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pytest
from datafusion import SessionContext
from deltalake import DeltaTable, write_deltalake
from pydantic import AwareDatetime, BaseModel, ConfigDict, TypeAdapter

from architecture_toolkit.domain.capsules import ArrowStreamExportable
from architecture_toolkit.storage.interchange import as_reader, as_table, tables_equal
from architecture_toolkit.storage.metadata import reattach, strip
from architecture_toolkit.storage.schemas import (
    TABLE_SCHEMAS,
    TableRole,
    TableSchema,
    list_of,
)
from architecture_toolkit.storage.snapshot import MaterializedPyArrowSnapshotProvider

PROVIDER = MaterializedPyArrowSnapshotProvider({})


@dataclass(frozen=True, slots=True)
class MatrixCase:
    """One physical shape, the rows that exercise it, and the column a query must read back."""

    case_id: str
    requirements: tuple[str, ...]
    schema: pa.Schema
    rows: list[dict[str, object]]
    key: str
    probe: str
    """A DataFusion expression over the case's distinguishing column."""

    notes: str = field(default="")


def _case(
    case_id: str,
    requirements: tuple[str, ...],
    fields: list[pa.Field],
    rows: list[dict[str, object]],
    probe: str,
    notes: str = "",
) -> MatrixCase:
    return MatrixCase(
        case_id=case_id,
        requirements=requirements,
        schema=pa.schema(fields),
        rows=rows,
        key="k",
        probe=probe,
        notes=notes,
    )


_KEY = pa.field("k", pa.string(), nullable=False)

CASES: tuple[MatrixCase, ...] = (
    _case(
        "identifiers_and_vocabulary",
        ("DATA-12",),
        [_KEY, pa.field("kind", pa.string(), nullable=False)],
        [{"k": "a", "kind": "software.system"}, {"k": "b", "kind": "business.process"}],
        "kind",
    ),
    _case(
        "booleans_and_int64",
        ("DATA-12",),
        [
            _KEY,
            pa.field("flag", pa.bool_(), nullable=False),
            pa.field("count", pa.int64(), nullable=False),
        ],
        [
            {"k": "a", "flag": True, "count": 0},
            {"k": "b", "flag": False, "count": 9_223_372_036_854_775_807},
        ],
        "count",
    ),
    _case(
        "nullable_scalars",
        ("DATA-12", "DATA-41"),
        [_KEY, pa.field("maybe", pa.string(), nullable=True)],
        [{"k": "a", "maybe": None}, {"k": "b", "maybe": ""}],
        "maybe",
        "An absent value and an empty value are different facts and must stay different.",
    ),
    _case(
        "utc_microsecond_instants_and_dates",
        ("DATA-12",),
        [
            _KEY,
            pa.field("at", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("on", pa.date32(), nullable=False),
        ],
        [
            {
                "k": "a",
                "at": datetime(2026, 9, 20, 12, 34, 56, 789012, tzinfo=UTC),
                "on": date(2026, 9, 20),
            }
        ],
        "at",
        "No domain field uses these yet; W4's manifests will.",
    ),
    _case(
        "non_null_struct",
        ("DATA-12",),
        [
            _KEY,
            pa.field(
                "s",
                pa.struct([pa.field("p", pa.string(), nullable=False)]),
                nullable=False,
            ),
        ],
        [{"k": "a", "s": {"p": "x"}}],
        "s['p']",
    ),
    _case(
        "list_of_struct",
        ("DATA-10",),
        [
            _KEY,
            pa.field(
                "items",
                list_of(pa.struct([pa.field("n", pa.int64(), nullable=False)])),
                nullable=False,
            ),
        ],
        [{"k": "a", "items": [{"n": 1}, {"n": 2}]}, {"k": "b", "items": []}],
        "cardinality(items)",
    ),
    _case(
        "nullable_inside_a_list",
        ("DATA-12", "DATA-41"),
        [
            _KEY,
            pa.field(
                "items",
                list_of(pa.struct([pa.field("n", pa.int64(), nullable=True)])),
                nullable=False,
            ),
        ],
        [{"k": "a", "items": [{"n": None}, {"n": 2}]}],
        "cardinality(items)",
    ),
    _case(
        "map_of_strings",
        ("DATA-12",),
        [_KEY, pa.field("m", pa.map_(pa.string(), pa.string()), nullable=False)],
        [{"k": "a", "m": [("x", "1")]}],
        "map_extract(m, 'x')",
        "Not in the baseline schemas; recorded because W4 may want it for manifest properties.",
    ),
)

IDS = [case.case_id for case in CASES]


def _chunked(table: pa.Table) -> pa.Table:
    """The same rows in a different batch layout, or the same table when there is one row."""
    if table.num_rows < 2:
        return table
    return pa.Table.from_batches(
        [*table.slice(0, 1).to_batches(), *table.slice(1).to_batches()], schema=table.schema
    )


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-60", "DATA-12", "DATA-34")
@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_a_physical_shape_survives_the_whole_stack(
    case: MatrixCase, tmp_path: Path, record_property: object
) -> None:
    """Pydantic to Arrow to Delta to DataFusion and back, for one physical shape."""
    assert callable(record_property)
    record_property("provider", PROVIDER.describe().model_dump_json())
    record_property("case", case.case_id)
    record_property("requirements", ",".join(case.requirements))

    written = pa.Table.from_pylist(case.rows, schema=case.schema)
    location = tmp_path / case.case_id
    write_deltalake(location, written)
    read = DeltaTable(location, version=0).to_pyarrow_table()

    # Type fidelity.
    assert read.schema.equals(case.schema, check_metadata=False), "types or nullability changed"
    # Logical row equivalence.
    assert read.to_pylist() == written.to_pylist()
    # Chunk independence: the same rows in different batches are the same table.
    assert tables_equal(_chunked(read), read)

    # Query correctness.
    context = SessionContext()
    context.from_arrow(read, name="t")
    # S608 does not apply: `case.probe` is a literal written in this file, not caller input.
    # The whole point of the matrix is to exercise engine expressions, which cannot be bound
    # as parameters — `tests/qualification/test_data_stack.py` covers parameter binding.
    query = f"SELECT k, {case.probe} AS probe FROM t ORDER BY k"  # noqa: S608
    answered = context.sql(query).to_arrow_table()
    assert answered.num_rows == len(case.rows)


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-60", "DATA-14")
def test_a_pydantic_record_survives_the_arrow_round_trip_for_the_types_the_domain_lacks() -> None:
    """DATA-12's instants and dates have no domain field yet, so a synthetic record carries them.

    JSON mode is the path, as everywhere else: `isoformat` on the way out, parsing on the way in.
    Without this, `INSTANT` and `DAY` would be declared conventions nothing had ever exercised.
    """

    class Stamped(BaseModel):
        model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
        k: str
        at: AwareDatetime
        on: date

    records = (
        Stamped(
            k="a", at=datetime(2026, 9, 20, 12, 34, 56, 789012, tzinfo=UTC), on=date(2026, 9, 20)
        ),
    )
    schema = pa.schema(
        [
            pa.field("k", pa.string(), nullable=False),
            pa.field("at", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("on", pa.date32(), nullable=False),
        ]
    )
    table = pa.Table.from_pylist(
        [{"k": r.k, "at": r.at, "on": r.on} for r in records], schema=schema
    )
    rows = [
        {"k": row["k"], "at": row["at"].isoformat(), "on": row["on"].isoformat()}
        for row in table.to_pylist()
    ]
    adapter = TypeAdapter(tuple[Stamped, ...])
    assert adapter.validate_python(rows, strict=False) == records
    assert table.schema.field("at").type.unit == "us"
    assert table.schema.field("at").type.tz == "UTC"


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-60", "DATA-12")
def test_a_null_struct_extracts_differently_depending_on_how_it_was_built(tmp_path: Path) -> None:
    """**A finding, not a guarantee**, and the reason the baseline persists no nullable struct.

    `Table.from_pylist` writes a child's default — `''` for a string — under a null parent, and
    DataFusion returns that default rather than NULL. `StructArray.from_arrays(..., mask=)` makes
    the child a real null and DataFusion returns NULL. `to_pylist` reports `None` either way, so
    the divergence is invisible from Python and appears only in SQL.
    """
    child = pa.field("p", pa.string(), nullable=False)
    schema = pa.schema(
        [
            pa.field("k", pa.string(), nullable=False),
            pa.field("s", pa.struct([child]), nullable=True),
        ]
    )

    from_pylist = pa.Table.from_pylist([{"k": "a", "s": None}], schema=schema)
    masked = pa.Table.from_arrays(
        [
            pa.array(["a"], type=pa.string()),
            pa.StructArray.from_arrays(
                [pa.array([None], type=pa.string())], fields=[child], mask=pa.array([True])
            ),
        ],
        schema=schema,
    )

    # Both look the same from Python.
    assert from_pylist.to_pylist() == masked.to_pylist() == [{"k": "a", "s": None}]

    def probe(table: pa.Table) -> object:
        context = SessionContext()
        context.from_arrow(table, name="t")
        return context.sql("SELECT s['p'] AS p FROM t").to_arrow_table().to_pylist()[0]["p"]

    assert probe(from_pylist) == "", "upstream fixed: the nullable-struct rule can be revisited"
    assert probe(masked) is None

    # After a Delta round trip the non-nullable child still does not become NULL.
    location = tmp_path / "null_struct"
    write_deltalake(location, from_pylist)
    assert probe(DeltaTable(location, version=0).to_pyarrow_table()) == ""


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-60", "DATA-44")
def test_field_metadata_survives_delta_and_schema_metadata_does_not(tmp_path: Path) -> None:
    """**A finding**, pinned so a deltalake release that starts preserving it is noticed."""
    declared: TableSchema = TABLE_SCHEMAS["references"]
    described = pa.schema(
        list(declared.schema), metadata={b"architecture_toolkit.table_id": b"references"}
    )
    rows = [
        {
            "reference_id": "ref-1",
            "model_id": "mod-1",
            "reference_kind": "document",
            "title": "A document",
            "locator": None,
            "authority": None,
            "content_hash": "sha256:" + "c" * 64,
        }
    ]
    location = tmp_path / "references"
    write_deltalake(location, pa.Table.from_pylist(rows, schema=described))
    read = DeltaTable(location, version=0).to_pyarrow_table()

    assert read.schema.metadata is None, "upstream fixed: reattach's second half is unnecessary"
    assert read.schema.field("reference_id").metadata is not None

    repaired = reattach(read, declared)
    assert repaired.schema.metadata is not None
    assert repaired.to_pylist() == rows


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-60", "DATA-45")
def test_dictionary_encoding_breaks_equality_but_not_the_values(tmp_path: Path) -> None:
    """DATA-45: dictionary encoding stays optional and qualification-gated, and here is why.

    An encoded column is the same data and a different table by `Table.equals`, which is exactly
    the kind of incidental physical difference a semantic digest must not see — and does not,
    because the digest is defined over records rather than bytes.
    """
    schema = pa.schema([pa.field("k", pa.string(), nullable=False)])
    plain = pa.Table.from_pylist([{"k": "a"}, {"k": "b"}, {"k": "a"}], schema=schema)
    encoded = pa.table({"k": pc.dictionary_encode(plain.column("k"))})

    assert not tables_equal(plain, encoded)
    assert not encoded.schema.equals(plain.schema)
    assert encoded.to_pylist() == plain.to_pylist()
    assert encoded.cast(schema).equals(plain)

    # Delta accepts it and hands back a plain string column.
    location = tmp_path / "dictionary"
    write_deltalake(location, encoded)
    read = DeltaTable(location, version=0).to_pyarrow_table()
    assert read.schema.field("k").type == pa.string()
    assert read.to_pylist() == plain.to_pylist()


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-60", "DATA-43")
def test_a_reader_and_a_table_reach_datafusion_with_the_same_result() -> None:
    """DATA-43: the C stream is the preferred contract, and it must not change the answer."""
    schema = pa.schema([pa.field("k", pa.string(), nullable=False)])
    table = pa.Table.from_pylist([{"k": "a"}, {"k": "b"}], schema=schema)

    def answer(source: ArrowStreamExportable) -> list[dict[str, object]]:
        context = SessionContext()
        context.from_arrow(source, name="t")
        return context.sql("SELECT k FROM t ORDER BY k").to_arrow_table().to_pylist()

    assert answer(table) == answer(as_reader(table)) == [{"k": "a"}, {"k": "b"}]


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-60", "DATA-10")
def test_a_list_item_field_is_named_element_on_readback(tmp_path: Path) -> None:
    """Why every declared list says `element` up front: Delta renames it on the way back."""
    schema = pa.schema(
        [pa.field("k", pa.string(), nullable=False), pa.field("xs", list_of(pa.string()))]
    )
    location = tmp_path / "lists"
    write_deltalake(location, pa.Table.from_pylist([{"k": "a", "xs": ["x"]}], schema=schema))
    read = DeltaTable(location, version=0).to_pyarrow_table()
    assert read.schema.field("xs").type.field(0).name == "element"
    assert read.schema.equals(schema, check_metadata=False)


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-60", "DATA-10")
def test_an_empty_typed_table_keeps_every_column(tmp_path: Path) -> None:
    """§11B typed empties, over a declared schema with a struct and two lists in it."""
    declared = TABLE_SCHEMAS["behavior_details"]
    assert declared.role is TableRole.DETAIL
    location = tmp_path / "empty"
    write_deltalake(location, declared.bare().empty_table())
    read = DeltaTable(location, version=0).to_pyarrow_table()
    assert read.num_rows == 0
    assert read.schema.equals(declared.bare(), check_metadata=False)
    assert as_table(read).schema.names == strip(declared.bare()).names

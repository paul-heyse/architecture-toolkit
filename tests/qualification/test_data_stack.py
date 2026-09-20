"""Real locked-stack interop checks; these do not implement release publication."""

from pathlib import Path

import networkx as nx
import pyarrow as pa
import pytest
from datafusion import SessionContext
from deltalake import DeltaTable, write_deltalake
from pydantic import BaseModel, ConfigDict

from architecture_toolkit.storage.datafusion_adapter import register_snapshot


class Transport(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    protocol: str
    timeout_ms: int | None


class Interface(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    element_id: str
    transport: Transport
    references: list[str]


SCHEMA = pa.schema(
    [
        pa.field("element_id", pa.string(), nullable=False),
        pa.field(
            "transport",
            pa.struct(
                [
                    pa.field("protocol", pa.string(), nullable=False),
                    pa.field("timeout_ms", pa.int64()),
                ]
            ),
            nullable=False,
        ),
        pa.field("references", pa.list_(pa.string()), nullable=False),
    ]
)


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-12", "DATA-18", "DATA-51")
def test_pinned_snapshot_nested_null_empty_and_scalar_query(tmp_path: Path) -> None:
    record = Interface(
        element_id="api-1",
        transport=Transport(protocol="HTTP", timeout_ms=None),
        references=["synthetic-reference"],
    )
    table = pa.Table.from_pylist([record.model_dump()], schema=SCHEMA)
    location = tmp_path / "interfaces"
    write_deltalake(location, table)
    write_deltalake(location, pa.Table.from_pylist([], schema=SCHEMA), mode="overwrite")
    pinned = DeltaTable(location, version=0)
    restored = pinned.to_pyarrow_table()
    assert restored.to_pylist() == table.to_pylist()
    assert DeltaTable(location, version=1).to_pyarrow_table().num_rows == 0
    # The baseline adapter route must retain the explicitly pinned snapshot.
    ctx = SessionContext()
    register_snapshot(ctx, "interfaces", location, version=0)
    result = ctx.sql(
        "SELECT element_id FROM interfaces WHERE element_id = $id", param_values={"id": "api-1"}
    ).to_arrow_table()
    assert result.to_pylist() == [{"element_id": "api-1"}]
    assert (
        ctx.sql(
            "SELECT * FROM interfaces WHERE element_id = $id",
            param_values={"id": "api-1' OR 1=1 --"},
        )
        .to_arrow_table()
        .num_rows
        == 0
    )
    # A provider API can exist while its binary ABI is incompatible; qualify separately.


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-12", "DATA-51")
def test_empty_snapshot_retains_schema(tmp_path: Path) -> None:
    location = tmp_path / "empty"
    write_deltalake(location, pa.Table.from_pylist([], schema=SCHEMA))
    ctx = SessionContext()
    schema = register_snapshot(ctx, "interfaces", location, version=0)
    assert schema.names == SCHEMA.names
    assert ctx.sql("SELECT count(*) AS n FROM interfaces").to_arrow_table().to_pylist() == [
        {"n": 0}
    ]


@pytest.mark.qualification
@pytest.mark.requirement("CORE-23", "DATA-16")
def test_parallel_graph_edges_do_not_collapse() -> None:
    graph = nx.MultiDiGraph(release_id="qualification-only")
    graph.add_edge("a", "b", key="supports-1", kind="supports")
    graph.add_edge("a", "b", key="depends-1", kind="depends_on")
    assert graph.number_of_edges("a", "b") == 2

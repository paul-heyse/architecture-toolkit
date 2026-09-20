"""`pyarrow-stubs` is qualified against the pinned pyarrow, not trusted (CORE-53, CORE-55).

The stub's declared target is pyarrow major 20 and the lock pins 25.0.1, so it can be absent —
harmless, the checker says so — or *wrong*, which is worse: a misdeclared return type passes
`pyrefly check` and fails at run time. `tests/static/pyarrow_surface.py` writes every call
`storage/` makes with the type it must have, so a misreport fails the checker there. This module
is the other half: it asserts the runtime truth and pins the two known divergences, so a stub
upgrade that fixes either one fails here and the workaround is removed deliberately rather than
left behind (CORE-52's discipline, expressed as a test because `xfail` cannot see a type).

It also guards against staleness in the other direction: every class and function the stub
declares must still exist on the runtime module.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pytest

STUB_ROOT = Path(pa.__file__).resolve().parent.parent / "pyarrow-stubs"


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("CORE-53")
def test_the_stub_package_is_installed_where_the_checker_finds_it() -> None:
    assert STUB_ROOT.is_dir(), f"pyarrow-stubs not installed beside pyarrow at {STUB_ROOT}"
    assert (STUB_ROOT / "__init__.pyi").is_file()


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("CORE-53", "CORE-55")
def test_table_equals_returns_a_bool_however_the_stub_declares_it() -> None:
    """Known divergence 1. The stub says `Table`; pyarrow 25.0.1 returns `bool`.

    `storage.interchange.tables_equal` exists to give callers the true type. When a stub release
    corrects the declaration, `tests/static/pyarrow_surface.py` fails first and both go.
    """
    schema = pa.schema([pa.field("x", pa.string(), nullable=False)])
    table = pa.Table.from_pylist([{"x": "a"}], schema=schema)
    assert type(table.equals(table)) is bool
    assert table.equals(table) is True
    assert table.equals(pa.Table.from_pylist([{"x": "b"}], schema=schema)) is False


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("CORE-53", "CORE-55")
def test_dictionary_decode_exists_although_the_stub_omits_it() -> None:
    """Known divergence 2, and the reason for the one narrow suppression in the static harness."""
    assert hasattr(pc, "dictionary_decode")
    column = pa.chunked_array([pa.array(["a", "b", "a"], type=pa.string())])
    assert pc.dictionary_decode(pc.dictionary_encode(column)).to_pylist() == ["a", "b", "a"]


def _declared_names(path: Path) -> set[str]:
    """Top-level classes and functions a stub module declares, ignoring re-exports."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and not node.name.startswith("_")
    }


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("CORE-53")
@pytest.mark.parametrize("module_name", ["compute", "dataset", "ipc", "fs"])
def test_every_name_the_stub_declares_still_exists_at_run_time(module_name: str) -> None:
    """Staleness in the other direction: a stub may declare what pyarrow 25 removed."""
    stub = STUB_ROOT / f"{module_name}.pyi"
    if not stub.is_file():
        pytest.skip(f"pyarrow-stubs ships no {module_name}.pyi")
    runtime = importlib.import_module(f"pyarrow.{module_name}")
    missing = sorted(name for name in _declared_names(stub) if not hasattr(runtime, name))
    assert not missing, f"pyarrow.{module_name} no longer has: {missing}"

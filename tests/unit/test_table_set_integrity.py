"""Eleven individually valid tables that do not describe one model (DATA-10, DATA-14).

None of these is a schema violation: every row satisfies its own schema and every record would
validate on its own. They are statements about the *set*, which is exactly the class of failure
a normalized layout introduces and the reason `TableSetIntegrityError` is its own type.
"""

from pathlib import Path

import pyarrow as pa
import pytest

from architecture_toolkit.domain.authoring import parse_model, parse_source
from architecture_toolkit.domain.model import Model
from architecture_toolkit.storage.errors import TableSetIntegrityError, UnknownTableError
from architecture_toolkit.storage.mappings import TableSet, assemble_model, compile_tables

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "minimal" / "model.yaml"


def example() -> Model:
    return parse_model(parse_source(EXAMPLE.read_text(), source_id="example"))


def duplicated(table: pa.Table, index: int = 0) -> pa.Table:
    """The table with one row repeated, which is what a bad merge produces."""
    return pa.concat_tables([table, table.slice(index, 1)]).combine_chunks()


def retargeted(table: pa.Table, column: str, value: str) -> pa.Table:
    """The table with one column's first value replaced."""
    rows = table.to_pylist()
    rows[0][column] = value
    return pa.Table.from_pylist(rows, schema=table.schema)


@pytest.mark.unit
@pytest.mark.requirement("DATA-10")
def test_two_detail_rows_for_one_element_in_the_same_table_are_refused() -> None:
    table_set = compile_tables(example())
    broken = table_set.with_tables(
        {"interface_details": duplicated(table_set["interface_details"])}
    )
    with pytest.raises(TableSetIntegrityError, match="interface_details"):
        assemble_model(broken)


@pytest.mark.unit
@pytest.mark.requirement("DATA-10")
def test_detail_rows_for_one_element_in_two_different_tables_are_refused() -> None:
    """The failure only a single pass over all five detail tables can see.

    An element with an interface detail *and* a deployment detail is exactly as incoherent as one
    with two interface details, and checking each table on its own would miss it.
    """
    table_set = compile_tables(example())
    interface_element = table_set["interface_details"].to_pylist()[0]["element_id"]
    deployment = retargeted(table_set["deployment_details"], "element_id", str(interface_element))
    broken = table_set.with_tables({"deployment_details": deployment})
    with pytest.raises(TableSetIntegrityError, match="has detail in both"):
        assemble_model(broken)


@pytest.mark.unit
@pytest.mark.requirement("DATA-10")
def test_a_detail_row_with_no_element_is_refused() -> None:
    table_set = compile_tables(example())
    orphan = retargeted(table_set["requirement_details"], "element_id", "no-such-element")
    broken = table_set.with_tables({"requirement_details": orphan})
    with pytest.raises(TableSetIntegrityError, match="no-such-element"):
        assemble_model(broken)


@pytest.mark.unit
@pytest.mark.requirement("DATA-03", "DATA-10")
def test_a_row_belonging_to_another_model_is_refused() -> None:
    """`model_id` is not bookkeeping: two clients' models must not become one bag of rows."""
    table_set = compile_tables(example())
    foreign = retargeted(table_set["relationships"], "model_id", "other-model")
    broken = table_set.with_tables({"relationships": foreign})
    with pytest.raises(TableSetIntegrityError, match="other-model"):
        assemble_model(broken)


@pytest.mark.unit
@pytest.mark.requirement("DATA-10")
def test_substituting_a_table_that_does_not_exist_is_refused() -> None:
    table_set = compile_tables(example())
    with pytest.raises(UnknownTableError):
        table_set.with_tables({"no_such_table": table_set["elements"]})
    with pytest.raises(UnknownTableError):
        _ = table_set["no_such_table"]


@pytest.mark.unit
@pytest.mark.requirement("DATA-10")
def test_a_coherent_set_still_assembles_after_all_of_that() -> None:
    """The positive control: the failures above are the tampering, not the fixture."""
    table_set = compile_tables(example())
    assert isinstance(assemble_model(table_set), Model)
    assert isinstance(table_set, TableSet)

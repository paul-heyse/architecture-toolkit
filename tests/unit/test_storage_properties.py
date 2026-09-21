"""The M2 hard gate: semantic identity ignores Arrow chunk layout (DATA-45, DATA-14).

> Semantic equality/hashes ignore incidental Arrow chunk layout
> — `docs/contracts/data.md`

Chunk independence is a *consequence* of how `table_semantic_digest` is defined — over the records
a table encodes, not over its bytes — rather than a property somebody remembered to preserve. It
is asserted here anyway, because a definition nothing exercises can rot around a changed
`from_arrow`, and because the gate is what the milestone is measured by.

These carry the `property` marker but also run as deterministic examples, so the gate does not
depend on a Hypothesis profile drawing the right shape.

None of them pins `max_examples`, deliberately: a per-test setting overrides the profile, which
would make `--hypothesis-profile=deep` a silent no-op on the one gate most worth exploring
deeply. `deadline` is disabled because compiling eleven Arrow tables is slower than Hypothesis's
default per-example budget and a timeout here would be noise, not a finding.
"""

from itertools import pairwise
from pathlib import Path

import pyarrow as pa
import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from architecture_toolkit.domain.authoring import parse_model, parse_source
from architecture_toolkit.domain.commands import ChangeSet, RenameElement, build_candidate
from architecture_toolkit.domain.model import Model
from architecture_toolkit.domain.semantics import (
    collection_digest,
    model_digest,
    stamp_digests,
)
from architecture_toolkit.storage.digests import (
    canonical_table,
    table_semantic_digest,
    table_set_digests,
)
from architecture_toolkit.storage.mappings import (
    TableSet,
    assemble_model,
    compile_tables,
    mapping_for,
)
from architecture_toolkit.storage.metadata import strip
from architecture_toolkit.storage.schemas import TABLE_IDS
from tests.strategies.relations import full_models

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "minimal" / "model.yaml"


def example() -> Model:
    return parse_model(parse_source(EXAMPLE.read_text(), source_id="example"))


def rechunk(table: pa.Table, boundaries: list[int]) -> pa.Table:
    """The same rows in different batches. `boundaries` are row offsets, ascending."""
    edges = [0, *boundaries, table.num_rows]
    batches: list[pa.RecordBatch] = []
    for start, end in pairwise(edges):
        if end > start:
            batches.extend(table.slice(start, end - start).combine_chunks().to_batches())
    return pa.Table.from_batches(batches, schema=table.schema)


# -- the hard gate -------------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.requirement("DATA-45")
def test_chunk_layout_never_changes_the_digest_deterministic() -> None:
    """The gate as a fixed example: `[[a], [b, c]]` and `[[a, b], [c]]` hash the same."""
    table_set = compile_tables(example())
    for table_id in TABLE_IDS:
        table = table_set[table_id]
        if table.num_rows < 3:
            continue
        one = rechunk(table, [1])
        two = rechunk(table, [2])
        assert [b.num_rows for b in one.to_batches()] != [b.num_rows for b in two.to_batches()]
        assert table_semantic_digest(table_id, one) == table_semantic_digest(table_id, two)
        assert table_semantic_digest(table_id, one) == table_semantic_digest(table_id, table)


@pytest.mark.property
@pytest.mark.slow
@pytest.mark.requirement("DATA-45", "CORE-45")
@settings(deadline=None)
@given(data=st.data())
def test_chunk_layout_never_changes_the_digest(data: st.DataObject) -> None:
    """The gate as a property, over drawn models and drawn batch boundaries."""
    model = data.draw(full_models())
    table_set = compile_tables(model)
    expected = table_set_digests(table_set)
    for table_id in TABLE_IDS:
        table = table_set[table_id]
        boundaries = data.draw(
            st.lists(st.integers(min_value=1, max_value=max(table.num_rows, 1)), max_size=3).map(
                lambda values: sorted(set(values))
            )
        )
        rechunked = rechunk(table, boundaries)
        assert rechunked.to_pylist() == table.to_pylist()
        assert table_semantic_digest(table_id, rechunked) == expected[table_id]


@pytest.mark.property
@pytest.mark.slow
@pytest.mark.requirement("DATA-45", "CORE-45")
@settings(deadline=None)
@given(data=st.data())
def test_a_changed_name_changes_the_elements_digest(data: st.DataObject) -> None:
    """The negative control. Without it the gate above passes for a digest of nothing."""
    model = data.draw(full_models())
    victim = data.draw(st.sampled_from(model.elements))
    new_name = data.draw(st.text(min_size=1, max_size=20).filter(lambda t: bool(t.strip())))
    assume(new_name != victim.name)

    before = table_set_digests(compile_tables(model))
    renamed = build_candidate(
        model,
        ChangeSet(
            change_set_id="cs-1",
            model_id=model.model_id,
            commands=(
                RenameElement(
                    element_id=victim.element_id, expected_name=victim.name, new_name=new_name
                ),
            ),
        ),
    )
    after = table_set_digests(compile_tables(renamed))
    assert after["elements"] != before["elements"]
    # And nothing else moved: a rename is an element-table change.
    assert {k: v for k, v in after.items() if k != "elements"} == {
        k: v for k, v in before.items() if k != "elements"
    }


# -- the definition the gate rests on ------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.requirement("DATA-45", "DATA-27")
def test_a_table_digest_is_the_domain_digest_of_the_records_it_encodes() -> None:
    """One hash implementation, so W4's manifest digest cannot disagree with the domain's.

    `elements` is the one table whose digest is not a whole domain collection's, because detail
    is normalized out of it; the digest covers what the table actually holds.
    """
    model = example()
    stamped = stamp_digests(model)
    table_set = compile_tables(model)
    digests = table_set_digests(table_set)

    for table_id, records in (
        ("relationships", stamped.relationships),
        ("interactions", stamped.interactions),
        ("references", stamped.references),
        ("reference_links", stamped.reference_links),
        ("notation_bindings", stamped.notation_bindings),
    ):
        assert digests[table_id] == collection_digest(records)

    without_detail = tuple(
        element.model_validate(dict(element) | {"detail": None}) for element in stamped.elements
    )
    assert digests["elements"] == collection_digest(without_detail)

    details = tuple(element.detail for element in stamped.elements if element.detail is not None)
    interface = tuple(d for d in details if d.detail_family.value == "interface")
    assert digests["interface_details"] == collection_digest(interface)


@pytest.mark.unit
@pytest.mark.requirement("DATA-44", "DATA-45")
def test_metadata_never_reaches_a_digest() -> None:
    """Stripped or replaced, the digest is the same — because no digest input reads metadata."""
    table_set = compile_tables(example())
    for table_id in TABLE_IDS:
        table = table_set[table_id]
        stripped = table.cast(strip(table.schema))
        bogus = stripped.replace_schema_metadata({b"architecture_toolkit.table_id": b"nonsense"})
        expected = table_semantic_digest(table_id, table)
        assert table_semantic_digest(table_id, stripped) == expected
        assert table_semantic_digest(table_id, bogus) == expected


@pytest.mark.unit
@pytest.mark.requirement("DATA-45")
def test_the_canonical_table_is_byte_identical_across_chunkings() -> None:
    """The physical normal form, which is a different question from the semantic digest."""
    table_set = compile_tables(example())
    table = table_set["elements"]
    one = canonical_table("elements", rechunk(table, [1]))
    two = canonical_table("elements", rechunk(table, [2, 5]))
    assert one.equals(two)
    assert len(one.to_batches()) == 1
    assert one.schema.metadata is None
    # Sorted by the declared key fields, which for `elements` is `(model_id, element_id)`.
    keys = list(
        zip(one.column("model_id").to_pylist(), one.column("element_id").to_pylist(), strict=True)
    )
    assert keys == sorted(keys)


# -- the model round trip -------------------------------------------------------------------------


@pytest.mark.property
@pytest.mark.slow
@pytest.mark.requirement("DATA-14", "CORE-45")
@settings(deadline=None)
@given(full_models())
def test_a_model_survives_the_arrow_round_trip(model: Model) -> None:
    """DATA-14 as a property: compile and assemble are inverses over generated models."""
    table_set = compile_tables(model)
    assembled = assemble_model(table_set)
    assert assembled == stamp_digests(model)
    assert model_digest(assembled) == model_digest(model)


@pytest.mark.property
@pytest.mark.slow
@pytest.mark.requirement("DATA-14", "DATA-45", "CORE-45")
@settings(deadline=None)
@given(full_models())
def test_reassembly_survives_rechunking_every_table(model: Model) -> None:
    """Row order in memory is preserved, so this is equality rather than digest equality."""
    table_set = compile_tables(model)
    rechunked = TableSet(
        model_id=table_set.model_id,
        schema_version=table_set.schema_version,
        profile_version=table_set.profile_version,
        storage_schema_version=table_set.storage_schema_version,
        tables={table_id: rechunk(table_set[table_id], [1]) for table_id in TABLE_IDS},
    )
    assert assemble_model(rechunked) == assemble_model(table_set)


@pytest.mark.unit
@pytest.mark.requirement("DATA-45")
def test_every_declared_table_has_a_digest_in_the_declared_order() -> None:
    digests = table_set_digests(compile_tables(example()))
    assert list(digests) == list(TABLE_IDS)
    assert all(value.startswith("sha256:") for value in digests.values())
    # An empty table has a digest too, and it is the digest of no records.
    assert digests["deployment_details"] != digests["interface_details"]
    empty = mapping_for("elements").table.schema.empty_table()
    assert table_semantic_digest("elements", empty) == collection_digest(())

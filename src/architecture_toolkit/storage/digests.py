"""Table-level semantic identity, defined in terms of the domain's (DATA-45, DATA-27).

DATA-45 requires a table hash that ignores Arrow chunk layout. There are two ways to get one and
only one of them is safe. The tempting way is to canonicalize the physical table — combine
chunks, sort, serialize — and hash the bytes; then the hash depends on Arrow's serialization, on
dictionary encoding, on metadata, and on every future pyarrow release.

The way taken here is to **define** a table's digest as the domain digest of the records it
encodes:

    table_semantic_digest(t) == collection_digest(mapping_for(t).from_arrow(source))

Chunk independence is then not a property to be tested for and hoped for — it is a consequence of
the definition, because `to_pylist` does not depend on batch boundaries and the records it
produces do not either. The same argument covers dictionary encoding and metadata. And because
there is one hash implementation rather than two, W4's per-table manifest digest cannot disagree
with the model digest W2 computes; that is the DATA-27 rationale, carried through.

The hard-gate test still asserts chunk independence explicitly, because a definition that nothing
exercises is a definition that can rot around a changed `from_arrow`.

**The per-table digests are not a decomposition of the model digest, and are not read as one.**
A table's digest covers the records *that table* encodes, and `elements` deliberately does not
encode detail — it was normalized into the five detail tables. So the `elements` digest is the
digest of elements with no detail attached, and a model that changes only one interface's timeout
moves `interface_details` and leaves `elements` alone. That is the useful behaviour, and it is
what DATA-21's "unchanged table versions can be reused" gate needs: a per-table digest answers
*which tables must be republished*, while `model_digest` answers *is this the same model*. W4
records both, for those two different questions.

Nothing is lost by the split: every detail row carries its `element_id`, so the join that
`assemble_model` performs is determined by the data, and two models with the same table digests
assemble to the same model.

`canonical_table` is the *physical* normal form and is deliberately not a digest input. It exists
for byte-level equality assertions and for W4's read-back step, where the question really is
whether two Arrow tables are the same bytes.
"""

from collections.abc import Mapping

import pyarrow as pa

from architecture_toolkit.domain.identifiers import SemanticDigest, TableId
from architecture_toolkit.domain.semantics import collection_digest
from architecture_toolkit.storage.interchange import as_table
from architecture_toolkit.storage.mappings import TableSet, mapping_for
from architecture_toolkit.storage.metadata import strip
from architecture_toolkit.storage.schemas import TABLE_IDS, schema_for

__all__ = ["canonical_table", "table_semantic_digest", "table_set_digests"]


def table_semantic_digest(table_id: str, source: object) -> SemanticDigest:
    """The semantic digest of the records a table encodes. See the module docstring."""
    return collection_digest(mapping_for(table_id).from_arrow(source))


def table_set_digests(table_set: TableSet) -> Mapping[TableId, SemanticDigest]:
    """One digest per table, in `TABLE_IDS` order. What W4 pins in a manifest."""
    return {
        table_id: table_semantic_digest(table_id, table_set[table_id]) for table_id in TABLE_IDS
    }


def canonical_table(table_id: str, source: object) -> pa.Table:
    """The physical normal form: declared types, one chunk, key order, no metadata.

    `cast` first, because it is what restores nullability and field metadata that `set_column`
    drops and what turns a dictionary-encoded column back into a plain string. Then
    `combine_chunks` and `sort_by`, after which two tables holding the same rows serialize to
    identical IPC bytes whatever batches they arrived in.

    Not a digest input — `table_semantic_digest` is defined over records, not bytes.
    """
    declared = schema_for(table_id)
    table = as_table(source).cast(declared.bare())
    ordered = table.combine_chunks().sort_by([(name, "ascending") for name in declared.key_fields])
    return ordered.cast(strip(declared.bare()))

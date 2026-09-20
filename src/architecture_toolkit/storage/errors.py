"""What the storage layer refuses, and why each refusal is its own type.

A single `StorageError` would make every failure look alike to a caller that has to decide
whether to retry, to fix a model or to stop. These five say different things: the table is not
one this toolkit knows, the data violates the schema it claims to satisfy, the table set does not
describe one coherent model, or a single-pass stream has already been read.
"""

__all__ = [
    "ConsumedStreamError",
    "SchemaViolation",
    "StorageError",
    "TableSetIntegrityError",
    "UnknownTableError",
]


class StorageError(Exception):
    """Base for every failure the storage layer raises on its own account."""


class UnknownTableError(StorageError, KeyError):
    """A table id that is not in the registry.

    `KeyError` as well, because the registry is a mapping and a caller indexing it should be able
    to catch what indexing a mapping normally raises.
    """


class SchemaViolation(StorageError):
    """Data does not satisfy the schema it is presented under.

    Arrow does not enforce nullability — `Table.from_pylist` will happily write a null into a
    non-nullable field — and Delta enforces it only at write time. Reading is therefore where the
    mapping has to check, which is what `storage.mappings.check_nullability` does.
    """


class TableSetIntegrityError(StorageError):
    """Eleven individually valid tables that do not describe one coherent model.

    A detail row with no element, two detail rows for one element, or a row whose `model_id` is
    not the table set's. None of these is a schema violation; each is a statement about the set.
    """


class ConsumedStreamError(StorageError):
    """A single-pass Arrow stream has already been read.

    `DeltaTable.scan()` and DataFusion's `execute()` return readers that can be consumed once.
    Reading one twice raises `OSError: Cannot read from closed stream` from the arro3 layer,
    which says nothing about what the caller did wrong; this does.
    """

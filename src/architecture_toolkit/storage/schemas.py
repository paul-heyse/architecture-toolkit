"""Explicit physical Arrow schemas for every compiled table (DATA-10, DATA-11, DATA-12).

DATA-10 asks for schemas that are written down rather than inferred, and the reason is DATA-11:
an inferred schema changes when the data changes. A table built from a model whose every
`timeout_ms` happened to be null would infer a null column; the next release would infer int64;
the two would not be comparable and nothing would have said so. Every schema here is declared
field by field, and `tests/unit/test_storage_schemas.py` asserts the invariants that make the set
usable as a contract.

**The type conventions are named once and used everywhere.** DATA-12 asks for a small, explicit
type vocabulary, and the vocabulary is smaller than Arrow's on purpose:

- One integer type. `int64` for every integer, including ordinals that will never exceed a
  hundred, because a mixed-width schema forces a literal cast into every W5 query recipe and the
  space saved is irrelevant at the scale `docs/contracts/data.md` commits to.
- One instant type and one date type: `timestamp[us, UTC]` and `date32`. Microseconds because
  that is what Delta round-trips losslessly, UTC because a local time in a release manifest is
  ambiguous a year later.
- No union, no extension type, no dictionary encoding, no `large_*` variant. Each is either
  unsupported somewhere in the stack or changes `Table.equals` without changing the data.

**No nullable struct appears in the baseline, and that is a measured decision.** DataFusion 54
returns a non-nullable child's default value — `''` for a string — instead of NULL when the
parent struct is null and the child was built by `Table.from_pylist`. A nullable child reads back
correctly. The rule adopted is the one that cannot go wrong: the baseline persists no nullable
struct at all, and every child of any future nullable struct is nullable. Both constructions are
recorded in the compatibility matrix so a DataFusion upgrade that fixes the extraction is
noticed.

**List item fields are named `element` up front.** Delta renames them to `element` on read, so a
schema declaring `item` would stop matching itself after one round trip.

Detail tables carry no `model_id`. They are in exact bijection with the detail records of one
model, which the element table already scopes; a second copy of the same scope is a second thing
that can disagree.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

import pyarrow as pa

from architecture_toolkit.domain.identifiers import TableId
from architecture_toolkit.domain.registry import DetailFamily
from architecture_toolkit.storage.errors import UnknownTableError

__all__ = [
    "BASELINE_TYPES",
    "COUNT",
    "DAY",
    "DETAIL_TABLE_BY_FAMILY",
    "DIGEST",
    "FLAG",
    "IDENTIFIER",
    "INSTANT",
    "STORAGE_SCHEMA_VERSION",
    "TABLE_IDS",
    "TABLE_SCHEMAS",
    "TEXT",
    "VIEWS",
    "VIEW_FILTER_STRUCT",
    "VOCABULARY",
    "FieldRole",
    "TableRole",
    "TableSchema",
    "field",
    "list_of",
    "schema_for",
]

STORAGE_SCHEMA_VERSION: Final[str] = "1.1.0"
"""The migration anchor. A change to any schema below is a change to this value and a migration."""

ROLE_KEY: Final[bytes] = b"architecture_toolkit.role"
"""Field-level metadata key. Read only by `storage/metadata.py`; never consulted for meaning."""


class TableRole(StrEnum):
    """What a table is, so a reader can tell a normalized detail from an independent record."""

    ENTITY = "entity"
    RELATION = "relation"
    LINK = "link"
    DETAIL = "detail"


class FieldRole(StrEnum):
    """What a column is for. Self-description (DATA-44), not semantics.

    Nothing reads these to decide behaviour — `storage/mappings.py` never consults metadata, and
    a test asserts that stripping it changes no record and no digest. They exist so a table
    inspected outside this toolkit says what its columns are.
    """

    IDENTITY = "identity"
    FOREIGN_KEY = "foreign_key"
    VOCABULARY = "vocabulary"
    DIGEST = "digest"
    EXTENSION = "extension"
    OWNED = "owned"


IDENTIFIER: Final[pa.DataType] = pa.string()
VOCABULARY: Final[pa.DataType] = pa.string()
TEXT: Final[pa.DataType] = pa.string()
DIGEST: Final[pa.DataType] = pa.string()
COUNT: Final[pa.DataType] = pa.int64()
FLAG: Final[pa.DataType] = pa.bool_()
INSTANT: Final[pa.DataType] = pa.timestamp("us", tz="UTC")
DAY: Final[pa.DataType] = pa.date32()

BASELINE_TYPES: Final[tuple[pa.DataType, ...]] = (
    pa.string(),
    pa.int64(),
    pa.bool_(),
    pa.timestamp("us", tz="UTC"),
    pa.date32(),
)
"""Every scalar type permitted anywhere in a persisted schema. Asserted exhaustive by test."""


def list_of(item: pa.DataType) -> pa.DataType:
    """A list whose item field is already named what Delta will rename it to.

    The list itself is non-nullable wherever it is used and so is the item: an empty collection
    is `[]`, never null, because "no aliases" and "we do not know the aliases" are different
    statements and DATA-41 requires the second to be said with a status, not a null.
    """
    return pa.list_(pa.field("element", item, nullable=False))


def field(name: str, dtype: pa.DataType, *, role: FieldRole, nullable: bool = False) -> pa.Field:
    """A field carrying its role as metadata. Non-nullable unless a null means something."""
    return pa.field(name, dtype, nullable=nullable, metadata={ROLE_KEY: role.value.encode()})


def _child(name: str, dtype: pa.DataType, *, nullable: bool = False) -> pa.Field:
    """A struct or list child. No role metadata: roles are a top-level column property."""
    return pa.field(name, dtype, nullable=nullable)


# -- shared structs, every one non-nullable ----------------------------------------------------

STATUS_STRUCT: Final[pa.DataType] = pa.struct(
    [
        _child("design_disposition", VOCABULARY),
        _child("implementation_state", VOCABULARY),
        _child("technical_qualification", VOCABULARY),
        _child("client_acceptance", VOCABULARY),
        _child("evidence_review", VOCABULARY),
    ]
)

EXTENSION_STRUCT: Final[pa.DataType] = pa.struct(
    [_child("namespace", IDENTIFIER), _child("key", TEXT), _child("value", TEXT)]
)

SUBJECT_STRUCT: Final[pa.DataType] = pa.struct(
    [
        _child("subject_kind", VOCABULARY),
        _child("element_id", IDENTIFIER, nullable=True),
        _child("relationship_id", IDENTIFIER, nullable=True),
        _child("field_path", TEXT, nullable=True),
        _child("release_id", IDENTIFIER, nullable=True),
    ]
)
"""`ReferenceTarget` flattened. Arrow has a union type and DATA-10 forbids it: a union changes
the physical layout when a variant is added, and the discriminator plus nullable slots says the
same thing in a layout every engine in the stack reads identically. `extra="forbid"` on the
domain variants is what rejects a row that fills a slot the discriminator does not permit."""


@dataclass(frozen=True, slots=True)
class TableSchema:
    """One declared table. Not a `CompiledRecord`: it holds a `pa.Schema`, which is not Pydantic.

    `key_fields` is the sort key that puts a table in canonical order and the identity a reader
    joins on. It is a tuple because several tables are keyed on a pair.
    """

    table_id: TableId
    role: TableRole
    key_fields: tuple[str, ...]
    schema: pa.Schema

    def bare(self) -> pa.Schema:
        """The schema with every `architecture_toolkit.*` metadata key removed.

        What Delta hands back, because it drops schema-level metadata and keeps field-level.
        Comparing a read table against this is comparing types and nullability, which is the
        part that has to match.
        """
        return pa.schema([pa.field(f.name, f.type, nullable=f.nullable) for f in self.schema])


def _table(
    table_id: str, role: TableRole, key_fields: tuple[str, ...], fields: list[pa.Field]
) -> TableSchema:
    return TableSchema(
        table_id=table_id, role=role, key_fields=key_fields, schema=pa.schema(fields)
    )


_CONTENT_HASH = field("content_hash", DIGEST, role=FieldRole.DIGEST)

ELEMENTS: Final[TableSchema] = _table(
    "elements",
    TableRole.ENTITY,
    ("model_id", "element_id"),
    [
        field("element_id", IDENTIFIER, role=FieldRole.IDENTITY),
        field("model_id", IDENTIFIER, role=FieldRole.IDENTITY),
        field("kind_id", VOCABULARY, role=FieldRole.VOCABULARY),
        field("name", TEXT, role=FieldRole.OWNED),
        field("description", TEXT, role=FieldRole.OWNED, nullable=True),
        field("lifecycle_state", VOCABULARY, role=FieldRole.VOCABULARY),
        # Persisted although excluded from the semantic hash: an alias is data a person wrote and
        # a projection shows. Excluded from identity is not the same as not worth storing.
        field("aliases", list_of(TEXT), role=FieldRole.OWNED),
        field("status", STATUS_STRUCT, role=FieldRole.OWNED),
        field("extensions", list_of(EXTENSION_STRUCT), role=FieldRole.EXTENSION),
        _CONTENT_HASH,
    ],
)

RELATIONSHIPS: Final[TableSchema] = _table(
    "relationships",
    TableRole.RELATION,
    ("model_id", "relationship_id"),
    [
        field("relationship_id", IDENTIFIER, role=FieldRole.IDENTITY),
        field("model_id", IDENTIFIER, role=FieldRole.IDENTITY),
        field("relationship_type_id", VOCABULARY, role=FieldRole.VOCABULARY),
        field("source_element_id", IDENTIFIER, role=FieldRole.FOREIGN_KEY),
        field("target_element_id", IDENTIFIER, role=FieldRole.FOREIGN_KEY),
        field("context_id", IDENTIFIER, role=FieldRole.FOREIGN_KEY, nullable=True),
        field("description", TEXT, role=FieldRole.OWNED, nullable=True),
        field("extensions", list_of(EXTENSION_STRUCT), role=FieldRole.EXTENSION),
        _CONTENT_HASH,
    ],
)

PARTICIPANT_STRUCT: Final[pa.DataType] = pa.struct(
    [
        _child("element_id", IDENTIFIER),
        _child("participant_role", VOCABULARY),
        _child("ordinal", COUNT),
    ]
)

INTERACTIONS: Final[TableSchema] = _table(
    "interactions",
    TableRole.ENTITY,
    ("model_id", "interaction_id"),
    [
        field("interaction_id", IDENTIFIER, role=FieldRole.IDENTITY),
        field("model_id", IDENTIFIER, role=FieldRole.IDENTITY),
        field("name", TEXT, role=FieldRole.OWNED),
        field("interaction_kind", VOCABULARY, role=FieldRole.VOCABULARY),
        field("description", TEXT, role=FieldRole.OWNED, nullable=True),
        # Physical order is the authored order. The semantic order is `ordinal`, which is why
        # the hash sorts by it and this column does not have to.
        field("participants", list_of(PARTICIPANT_STRUCT), role=FieldRole.OWNED),
        field("moved_object_ids", list_of(IDENTIFIER), role=FieldRole.FOREIGN_KEY),
        _CONTENT_HASH,
    ],
)

REFERENCES: Final[TableSchema] = _table(
    "references",
    TableRole.ENTITY,
    ("model_id", "reference_id"),
    [
        field("reference_id", IDENTIFIER, role=FieldRole.IDENTITY),
        field("model_id", IDENTIFIER, role=FieldRole.IDENTITY),
        field("reference_kind", VOCABULARY, role=FieldRole.VOCABULARY),
        field("title", TEXT, role=FieldRole.OWNED),
        field("locator", TEXT, role=FieldRole.OWNED, nullable=True),
        field("authority", TEXT, role=FieldRole.OWNED, nullable=True),
        _CONTENT_HASH,
    ],
)

REFERENCE_LINKS: Final[TableSchema] = _table(
    "reference_links",
    TableRole.LINK,
    ("model_id", "link_id"),
    [
        field("link_id", IDENTIFIER, role=FieldRole.IDENTITY),
        field("model_id", IDENTIFIER, role=FieldRole.IDENTITY),
        field("reference_id", IDENTIFIER, role=FieldRole.FOREIGN_KEY),
        field("subject", SUBJECT_STRUCT, role=FieldRole.FOREIGN_KEY),
        field("link_role", VOCABULARY, role=FieldRole.VOCABULARY),
        field("note", TEXT, role=FieldRole.OWNED, nullable=True),
        _CONTENT_HASH,
    ],
)

NOTATION_BINDINGS: Final[TableSchema] = _table(
    "notation_bindings",
    TableRole.LINK,
    ("model_id", "binding_id"),
    [
        field("binding_id", IDENTIFIER, role=FieldRole.IDENTITY),
        field("model_id", IDENTIFIER, role=FieldRole.IDENTITY),
        field("subject", SUBJECT_STRUCT, role=FieldRole.FOREIGN_KEY),
        field("notation", VOCABULARY, role=FieldRole.VOCABULARY),
        field("notation_type", TEXT, role=FieldRole.OWNED),
        field("notation_object_id", IDENTIFIER, role=FieldRole.OWNED),
        field("view_id", IDENTIFIER, role=FieldRole.FOREIGN_KEY, nullable=True),
        field("mapping_profile_version", TEXT, role=FieldRole.OWNED),
        field("projection_artifact_id", IDENTIFIER, role=FieldRole.FOREIGN_KEY, nullable=True),
        field("link_target", TEXT, role=FieldRole.OWNED, nullable=True),
        _CONTENT_HASH,
    ],
)

VIEW_FILTER_STRUCT: Final[pa.DataType] = pa.struct(
    [
        _child("filter_mode", VOCABULARY),
        _child("dimension", VOCABULARY),
        _child("values", list_of(TEXT)),
    ]
)
"""One selection rule inside a view. A struct in a list, like `extensions`.

Every scalar in it is a string, so `BASELINE_TYPES` holds at every depth and the nested
`list_of(TEXT)` is the shape `SCHEMA_FIELD_STRUCT.key_membership` already proves works.
"""

VIEWS: Final[TableSchema] = _table(
    "views",
    TableRole.ENTITY,
    ("model_id", "view_id"),
    [
        field("view_id", IDENTIFIER, role=FieldRole.IDENTITY),
        field("model_id", IDENTIFIER, role=FieldRole.IDENTITY),
        field("view_type", VOCABULARY, role=FieldRole.VOCABULARY),
        field("notation", VOCABULARY, role=FieldRole.VOCABULARY),
        field("scope", IDENTIFIER, role=FieldRole.FOREIGN_KEY, nullable=True),
        field("audience", TEXT, role=FieldRole.OWNED, nullable=True),
        field("title", TEXT, role=FieldRole.OWNED),
        field("description", TEXT, role=FieldRole.OWNED, nullable=True),
        field("membership_policy", VOCABULARY, role=FieldRole.VOCABULARY),
        # Non-nullable lists: an empty view is `[]`, never null, for the reason `list_of` states.
        field("included_element_ids", list_of(IDENTIFIER), role=FieldRole.FOREIGN_KEY),
        field("included_relationship_ids", list_of(IDENTIFIER), role=FieldRole.FOREIGN_KEY),
        field("perspective", TEXT, role=FieldRole.OWNED, nullable=True),
        field("filter", list_of(VIEW_FILTER_STRUCT), role=FieldRole.OWNED),
        field("layout_profile_id", IDENTIFIER, role=FieldRole.FOREIGN_KEY, nullable=True),
        field("publication_state", VOCABULARY, role=FieldRole.VOCABULARY),
        _CONTENT_HASH,
    ],
)
"""View definitions (PROJ-03). `ENTITY`, not `LINK`.

`reference_links` and `notation_bindings` are links because their whole content is an association
— a subject and a role. A view has a title, an audience and a publication state; it is a thing
that exists in its own right and happens to name members.

Nullable exactly where "not stated" is a fact DATA-41 wants preserved: a landscape view has no
`scope`, and no `layout_profile_id` is what automatic layout looks like. Everything else has a
domain default, so a null there would be a lie.
"""

TRANSPORT_STRUCT: Final[pa.DataType] = pa.struct(
    [
        _child("protocol", TEXT),
        _child("interaction_mode", VOCABULARY),
        _child("serialization", TEXT),
    ]
)

INTERFACE_DETAILS: Final[TableSchema] = _table(
    "interface_details",
    TableRole.DETAIL,
    ("element_id",),
    [
        field("element_id", IDENTIFIER, role=FieldRole.IDENTITY),
        field("transport", TRANSPORT_STRUCT, role=FieldRole.OWNED),
        field("authentication_description", TEXT, role=FieldRole.OWNED, nullable=True),
        field("request_schema_id", IDENTIFIER, role=FieldRole.FOREIGN_KEY, nullable=True),
        field("response_schema_id", IDENTIFIER, role=FieldRole.FOREIGN_KEY, nullable=True),
        field("delivery_semantics", VOCABULARY, role=FieldRole.VOCABULARY),
        field("timeout_ms", COUNT, role=FieldRole.OWNED, nullable=True),
        field("idempotency_description", TEXT, role=FieldRole.OWNED, nullable=True),
        _CONTENT_HASH,
    ],
)
"""DATA-11's worked example: the nested interface schema, declared rather than inferred."""

DEPLOYMENT_DETAILS: Final[TableSchema] = _table(
    "deployment_details",
    TableRole.DETAIL,
    ("element_id",),
    [
        field("element_id", IDENTIFIER, role=FieldRole.IDENTITY),
        field("environment", TEXT, role=FieldRole.OWNED),
        field("deployment_node_id", IDENTIFIER, role=FieldRole.FOREIGN_KEY, nullable=True),
        field("software_instance_id", IDENTIFIER, role=FieldRole.FOREIGN_KEY, nullable=True),
        field("configuration_artifact_id", IDENTIFIER, role=FieldRole.FOREIGN_KEY, nullable=True),
        _CONTENT_HASH,
    ],
)

SCHEMA_FIELD_STRUCT: Final[pa.DataType] = pa.struct(
    [
        _child("field_id", TEXT),
        _child("field_name", TEXT),
        _child("data_type", TEXT),
        _child("nullability", VOCABULARY),
        _child("cardinality", VOCABULARY),
        # A frozenset in the domain, so it has no order of its own; written sorted.
        _child("key_membership", list_of(VOCABULARY)),
        _child("references_element_id", IDENTIFIER, nullable=True),
        _child("references_field_id", TEXT, nullable=True),
        _child("ordinal", COUNT),
    ]
)

DATA_SCHEMA_DETAILS: Final[TableSchema] = _table(
    "data_schema_details",
    TableRole.DETAIL,
    ("element_id",),
    [
        field("element_id", IDENTIFIER, role=FieldRole.IDENTITY),
        field("fields", list_of(SCHEMA_FIELD_STRUCT), role=FieldRole.OWNED),
        _CONTENT_HASH,
    ],
)

BEHAVIOR_NODE_STRUCT: Final[pa.DataType] = pa.struct(
    [
        _child("node_id", TEXT),
        _child("node_type", VOCABULARY),
        _child("name", TEXT),
        _child("ordinal", COUNT),
        _child("participant_element_id", IDENTIFIER, nullable=True),
    ]
)

BEHAVIOR_TRANSITION_STRUCT: Final[pa.DataType] = pa.struct(
    [
        _child("transition_id", TEXT),
        _child("source_node_id", TEXT),
        _child("target_node_id", TEXT),
        _child("guard", TEXT, nullable=True),
        _child("ordinal", COUNT),
    ]
)

BEHAVIOR_DETAILS: Final[TableSchema] = _table(
    "behavior_details",
    TableRole.DETAIL,
    ("element_id",),
    [
        field("element_id", IDENTIFIER, role=FieldRole.IDENTITY),
        field("nodes", list_of(BEHAVIOR_NODE_STRUCT), role=FieldRole.OWNED),
        field("transitions", list_of(BEHAVIOR_TRANSITION_STRUCT), role=FieldRole.OWNED),
        _CONTENT_HASH,
    ],
)

REQUIREMENT_DETAILS: Final[TableSchema] = _table(
    "requirement_details",
    TableRole.DETAIL,
    ("element_id",),
    [
        field("element_id", IDENTIFIER, role=FieldRole.IDENTITY),
        field("category", VOCABULARY, role=FieldRole.VOCABULARY),
        field("applicability", VOCABULARY, role=FieldRole.VOCABULARY),
        field("applicability_note", TEXT, role=FieldRole.OWNED, nullable=True),
        field("verification_method", VOCABULARY, role=FieldRole.VOCABULARY),
        field("acceptance_criterion_ids", list_of(IDENTIFIER), role=FieldRole.FOREIGN_KEY),
        _CONTENT_HASH,
    ],
)

TABLE_IDS: Final[tuple[TableId, ...]] = (
    "elements",
    "relationships",
    "interactions",
    "references",
    "reference_links",
    "notation_bindings",
    "views",
    "interface_details",
    "deployment_details",
    "data_schema_details",
    "behavior_details",
    "requirement_details",
)
"""Fixed order: the six independent collections, then the five details. W4 pins digests in it."""

TABLE_SCHEMAS: Final[Mapping[TableId, TableSchema]] = MappingProxyType(
    {
        schema.table_id: schema
        for schema in (
            ELEMENTS,
            RELATIONSHIPS,
            INTERACTIONS,
            REFERENCES,
            REFERENCE_LINKS,
            NOTATION_BINDINGS,
            VIEWS,
            INTERFACE_DETAILS,
            DEPLOYMENT_DETAILS,
            DATA_SCHEMA_DETAILS,
            BEHAVIOR_DETAILS,
            REQUIREMENT_DETAILS,
        )
    }
)

DETAIL_TABLE_BY_FAMILY: Final[Mapping[DetailFamily, TableId]] = MappingProxyType(
    {
        DetailFamily.INTERFACE: "interface_details",
        DetailFamily.DEPLOYMENT: "deployment_details",
        DetailFamily.DATA_SCHEMA: "data_schema_details",
        DetailFamily.BEHAVIOR: "behavior_details",
        DetailFamily.REQUIREMENT: "requirement_details",
    }
)
"""The five element-attachable families. `NOTATION_BINDING` is the sixth and is not among them:
its subject may be a relationship, so it is an independent table rather than a detail."""


def schema_for(table_id: str) -> TableSchema:
    """The declared schema for a table id, or `UnknownTableError`."""
    try:
        return TABLE_SCHEMAS[table_id]
    except KeyError:
        raise UnknownTableError(table_id) from None

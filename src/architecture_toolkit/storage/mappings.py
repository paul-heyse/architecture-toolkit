"""Pydantic records to Arrow tables and back, field by field (DATA-14).

DATA-14 asks for tested bidirectional mappings, and the word carrying the weight is *tested*: a
mapping that only runs forwards is a mapping whose inverse nobody has checked.
`tests/unit/test_storage_mappings.py` runs every table both ways over records that exercise every
Optional as null and every collection as empty, and
`tests/unit/test_storage_properties.py` runs the whole model both ways over generated input.

**Rows are written field by field, never from `model_dump`.** A dump follows whatever the record
happens to look like; an explicit row follows the declared schema, so adding a field to a record
without adding a column produces a failure here rather than a silently narrower table. It also
puts the two directions next to each other, which is the only way a reader can check that they
agree.

**The reverse direction goes through JSON, as everywhere else in this toolkit.** Strict Python
mode rejects a `list` for a `tuple[...]` field with the error location collapsed to the field,
and rejects a plain string for a `StrEnum`. `TypeAdapter.validate_json` accepts both and reports
full locations. Arrow gives lists and strings, so JSON is the honest path, not a detour.

**Metadata is written and never read.** `from_row` consults no metadata and neither does anything
it calls; a table stripped of every `architecture_toolkit.*` key produces identical records and
identical digests, which `tests/unit/test_storage_mappings.py` asserts directly.
"""

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final, Protocol, assert_never

import pyarrow as pa
from pydantic import TypeAdapter

from architecture_toolkit.domain.base import CompiledRecord
from architecture_toolkit.domain.details import (
    BehaviorDetail,
    DataSchemaDetail,
    DeploymentDetail,
    ElementDetail,
    InterfaceDetail,
    RequirementDetail,
)
from architecture_toolkit.domain.identifiers import TableId
from architecture_toolkit.domain.model import Element, Interaction, Model, Relationship
from architecture_toolkit.domain.notation import NotationBinding
from architecture_toolkit.domain.references import (
    ElementReference,
    FieldReference,
    Reference,
    ReferenceLink,
    ReferenceTarget,
    RelationshipReference,
    ReleaseReference,
)
from architecture_toolkit.domain.registry import DetailFamily
from architecture_toolkit.domain.semantics import stamp_digests
from architecture_toolkit.domain.views import ViewDefinition, ViewFilter
from architecture_toolkit.storage.errors import (
    SchemaViolation,
    TableSetIntegrityError,
    UnknownTableError,
)
from architecture_toolkit.storage.interchange import as_table
from architecture_toolkit.storage.metadata import describe
from architecture_toolkit.storage.schemas import (
    DETAIL_TABLE_BY_FAMILY,
    STORAGE_SCHEMA_VERSION,
    TABLE_IDS,
    TABLE_SCHEMAS,
    TableRole,
    TableSchema,
)

__all__ = [
    "MAPPINGS",
    "ErasedMapping",
    "Row",
    "TableMapping",
    "TableSet",
    "assemble_model",
    "check_columns",
    "check_nullability",
    "compile_tables",
    "mapping_for",
]

type Row = dict[str, object]
"""A JSON-ready row: only `str`, `int`, `bool`, `None`, `list` and `dict` values."""


def _text(value: StrEnum | str) -> str:
    """A vocabulary value as the string Arrow stores. `StrEnum` members are already strings."""
    return value.value if isinstance(value, StrEnum) else value


def _require_digest(row: Row, table_id: str) -> Row:
    """`content_hash` is non-nullable in every table, so it must already be stamped."""
    if row.get("content_hash") is None:
        message = (
            f"{table_id}: a record has no content_hash; call stamp_digests(model) before compiling"
        )
        raise ValueError(message)
    return row


# -- shared value objects -----------------------------------------------------------------------


def _subject_to_row(subject: ReferenceTarget) -> Row:
    """`ReferenceTarget` flattened into the non-nullable `subject` struct.

    A `match` with `assert_never` rather than `getattr`, so a fifth variant fails `pyrefly check`
    here instead of writing nulls into every slot at run time.
    """
    row: Row = {
        "subject_kind": _text(subject.subject_kind),
        "element_id": None,
        "relationship_id": None,
        "field_path": None,
        "release_id": None,
    }
    match subject:
        case ElementReference():
            row["element_id"] = subject.element_id
        case RelationshipReference():
            row["relationship_id"] = subject.relationship_id
        case FieldReference():
            row["element_id"] = subject.element_id
            row["field_path"] = subject.field_path
        case ReleaseReference():
            row["release_id"] = subject.release_id
        case _ as unreachable:
            assert_never(unreachable)
    return row


def _subject_from_row(value: object) -> Row:
    """The inverse: keep the discriminator, drop every slot the variant does not use.

    A slot that is *not* null but should have been is left in place deliberately, so
    `extra="forbid"` on the variant rejects it rather than the mapping silently discarding a
    value somebody wrote.
    """
    if not isinstance(value, dict):
        message = f"subject is {type(value).__name__}, expected a struct"
        raise SchemaViolation(message)
    return {key: item for key, item in value.items() if item is not None or key == "subject_kind"}


# -- forward rows -------------------------------------------------------------------------------


def _element_to_row(element: Element) -> Row:
    status = element.status
    return _require_digest(
        {
            "element_id": element.element_id,
            "model_id": element.model_id,
            "kind_id": element.kind_id,
            "name": element.name,
            "description": element.description,
            "lifecycle_state": _text(element.lifecycle_state),
            "aliases": list(element.aliases),
            "status": {
                "design_disposition": _text(status.design_disposition),
                "implementation_state": _text(status.implementation_state),
                "technical_qualification": _text(status.technical_qualification),
                "client_acceptance": _text(status.client_acceptance),
                "evidence_review": _text(status.evidence_review),
            },
            "extensions": [
                {"namespace": e.namespace, "key": e.key, "value": e.value}
                for e in element.extensions
            ],
            "content_hash": element.content_hash,
        },
        "elements",
    )


def _relationship_to_row(relationship: Relationship) -> Row:
    return _require_digest(
        {
            "relationship_id": relationship.relationship_id,
            "model_id": relationship.model_id,
            "relationship_type_id": relationship.relationship_type_id,
            "source_element_id": relationship.source_element_id,
            "target_element_id": relationship.target_element_id,
            "context_id": relationship.context_id,
            "description": relationship.description,
            "extensions": [
                {"namespace": e.namespace, "key": e.key, "value": e.value}
                for e in relationship.extensions
            ],
            "content_hash": relationship.content_hash,
        },
        "relationships",
    )


def _interaction_to_row(interaction: Interaction) -> Row:
    return _require_digest(
        {
            "interaction_id": interaction.interaction_id,
            "model_id": interaction.model_id,
            "name": interaction.name,
            "interaction_kind": _text(interaction.interaction_kind),
            "description": interaction.description,
            "participants": [
                {
                    "element_id": p.element_id,
                    "participant_role": _text(p.participant_role),
                    "ordinal": p.ordinal,
                }
                for p in interaction.participants
            ],
            "moved_object_ids": list(interaction.moved_object_ids),
            "content_hash": interaction.content_hash,
        },
        "interactions",
    )


def _reference_to_row(reference: Reference) -> Row:
    return _require_digest(
        {
            "reference_id": reference.reference_id,
            "model_id": reference.model_id,
            "reference_kind": _text(reference.reference_kind),
            "title": reference.title,
            "locator": reference.locator,
            "authority": reference.authority,
            "content_hash": reference.content_hash,
        },
        "references",
    )


def _reference_link_to_row(link: ReferenceLink) -> Row:
    return _require_digest(
        {
            "link_id": link.link_id,
            "model_id": link.model_id,
            "reference_id": link.reference_id,
            "subject": _subject_to_row(link.subject),
            "link_role": _text(link.link_role),
            "note": link.note,
            "content_hash": link.content_hash,
        },
        "reference_links",
    )


def _notation_binding_to_row(binding: NotationBinding) -> Row:
    return _require_digest(
        {
            "binding_id": binding.binding_id,
            "model_id": binding.model_id,
            "subject": _subject_to_row(binding.subject),
            "notation": _text(binding.notation),
            "notation_type": binding.notation_type,
            "notation_object_id": binding.notation_object_id,
            "view_id": binding.view_id,
            "mapping_profile_version": binding.mapping_profile_version,
            "projection_artifact_id": binding.projection_artifact_id,
            "link_target": binding.link_target,
            "content_hash": binding.content_hash,
        },
        "notation_bindings",
    )


def _view_filter_to_row(rule: ViewFilter) -> Row:
    return {
        "filter_mode": _text(rule.filter_mode),
        "dimension": _text(rule.dimension),
        "values": list(rule.values),
    }


def _view_to_row(view: ViewDefinition) -> Row:
    return _require_digest(
        {
            "view_id": view.view_id,
            "model_id": view.model_id,
            "view_type": _text(view.view_type),
            "notation": _text(view.notation),
            "scope": view.scope,
            "audience": view.audience,
            "title": view.title,
            "description": view.description,
            "membership_policy": _text(view.membership_policy),
            "included_element_ids": list(view.included_element_ids),
            "included_relationship_ids": list(view.included_relationship_ids),
            "perspective": view.perspective,
            "filter": [_view_filter_to_row(rule) for rule in view.filter],
            "layout_profile_id": view.layout_profile_id,
            "publication_state": _text(view.publication_state),
            "content_hash": view.content_hash,
        },
        "views",
    )


def _interface_detail_to_row(detail: InterfaceDetail) -> Row:
    return _require_digest(
        {
            "element_id": detail.element_id,
            "transport": {
                "protocol": detail.transport.protocol,
                "interaction_mode": _text(detail.transport.interaction_mode),
                "serialization": detail.transport.serialization,
            },
            "authentication_description": detail.authentication_description,
            "request_schema_id": detail.request_schema_id,
            "response_schema_id": detail.response_schema_id,
            "delivery_semantics": _text(detail.delivery_semantics),
            "timeout_ms": detail.timeout_ms,
            "idempotency_description": detail.idempotency_description,
            "content_hash": detail.content_hash,
        },
        "interface_details",
    )


def _deployment_detail_to_row(detail: DeploymentDetail) -> Row:
    return _require_digest(
        {
            "element_id": detail.element_id,
            "environment": detail.environment,
            "deployment_node_id": detail.deployment_node_id,
            "software_instance_id": detail.software_instance_id,
            "configuration_artifact_id": detail.configuration_artifact_id,
            "content_hash": detail.content_hash,
        },
        "deployment_details",
    )


def _data_schema_detail_to_row(detail: DataSchemaDetail) -> Row:
    return _require_digest(
        {
            "element_id": detail.element_id,
            "fields": [
                {
                    "field_id": field.field_id,
                    "field_name": field.field_name,
                    "data_type": field.data_type,
                    "nullability": _text(field.nullability),
                    "cardinality": _text(field.cardinality),
                    # A frozenset has no order, so one is imposed on write. Reading it back into
                    # a frozenset discards it again, which is why the digest is unaffected.
                    "key_membership": sorted(_text(k) for k in field.key_membership),
                    "references_element_id": field.references_element_id,
                    "references_field_id": field.references_field_id,
                    "ordinal": field.ordinal,
                }
                for field in detail.fields
            ],
            "content_hash": detail.content_hash,
        },
        "data_schema_details",
    )


def _behavior_detail_to_row(detail: BehaviorDetail) -> Row:
    return _require_digest(
        {
            "element_id": detail.element_id,
            "nodes": [
                {
                    "node_id": node.node_id,
                    "node_type": _text(node.node_type),
                    "name": node.name,
                    "ordinal": node.ordinal,
                    "participant_element_id": node.participant_element_id,
                }
                for node in detail.nodes
            ],
            "transitions": [
                {
                    "transition_id": transition.transition_id,
                    "source_node_id": transition.source_node_id,
                    "target_node_id": transition.target_node_id,
                    "guard": transition.guard,
                    "ordinal": transition.ordinal,
                }
                for transition in detail.transitions
            ],
            "content_hash": detail.content_hash,
        },
        "behavior_details",
    )


def _requirement_detail_to_row(detail: RequirementDetail) -> Row:
    return _require_digest(
        {
            "element_id": detail.element_id,
            "category": _text(detail.category),
            "applicability": _text(detail.applicability),
            "applicability_note": detail.applicability_note,
            "verification_method": _text(detail.verification_method),
            "acceptance_criterion_ids": list(detail.acceptance_criterion_ids),
            "content_hash": detail.content_hash,
        },
        "requirement_details",
    )


# -- reverse rows -------------------------------------------------------------------------------


def _identity(row: Row) -> Row:
    """Most tables need no reverse adjustment: JSON mode does list to tuple and enum by value."""
    return row


def _with_subject(row: Row) -> Row:
    return {**row, "subject": _subject_from_row(row["subject"])}


def _detail_from_row(family: DetailFamily) -> Callable[[Row], Row]:
    """`detail_family` is not a column: the table a row came from is what says which family it is.

    Storing the discriminator as well would be a second copy of the same fact, and a row whose
    column disagreed with its table would have no defensible reading.
    """

    def convert(row: Row) -> Row:
        return {"detail_family": family.value, **row}

    return convert


# -- schema checks ------------------------------------------------------------------------------


def check_columns(table: pa.Table, expected: TableSchema) -> None:
    """The table has exactly the declared columns, with the declared types."""
    declared = expected.bare()
    if table.schema.names != declared.names:
        message = f"{expected.table_id}: columns {table.schema.names} do not match {declared.names}"
        raise SchemaViolation(message)
    for field in declared:
        actual = table.schema.field(field.name)
        if not actual.type.equals(field.type):
            message = f"{expected.table_id}.{field.name}: type {actual.type} is not {field.type}"
            raise SchemaViolation(message)


def check_nullability(table: pa.Table, expected: TableSchema) -> None:
    """No null in a column the schema declares non-nullable.

    Arrow does not enforce nullability — `Table.from_pylist` writes a null into a non-nullable
    field without complaint — and Delta enforces it only at write time. Reading is therefore
    where it has to be checked, before any row is built.
    """
    for field in expected.bare():
        if field.nullable:
            continue
        column = table.column(field.name)
        if column.null_count:
            message = (
                f"{expected.table_id}.{field.name} is non-nullable "
                f"but holds {column.null_count} null(s)"
            )
            raise SchemaViolation(message)


# -- the mapping ---------------------------------------------------------------------------------


class ErasedMapping(Protocol):
    """A `TableMapping` with its record type forgotten.

    The registry is heterogeneous — one mapping per declared table, over as many record types — and
    `TableMapping[R]` is invariant, because `to_row` puts `R` in a parameter position. So the
    registry cannot be typed as a mapping of any single instantiation, and `Any` would give up
    more than necessary: every record type in it is a `CompiledRecord`, which is exactly what a
    caller reading a table generically needs to know.
    """

    @property
    def table(self) -> TableSchema: ...

    def to_arrow(self, records: Iterable[Any]) -> pa.Table: ...

    def rows_from_arrow(self, source: object) -> list[Row]: ...

    def from_arrow(self, source: object) -> tuple[CompiledRecord, ...]: ...


@dataclass(frozen=True, slots=True)
class TableMapping[R: CompiledRecord]:
    """One table, both directions, and the adapter that validates the reverse one."""

    table: TableSchema
    adapter: TypeAdapter[tuple[R, ...]]
    to_row: Callable[[R], Row]
    from_row: Callable[[Row], Row]

    def to_arrow(self, records: Iterable[R]) -> pa.Table:
        """Records as a described Arrow table. Zero records still produce the typed schema."""
        rows = [self.to_row(record) for record in records]
        schema = describe(self.table.schema, table_id=self.table.table_id, role=self.table.role)
        return pa.Table.from_pylist(rows, schema=schema)

    def rows_from_arrow(self, source: object) -> list[Row]:
        """JSON-ready rows, checked against the declared schema first."""
        table = as_table(source)
        check_columns(table, self.table)
        check_nullability(table, self.table)
        return [self.from_row(row) for row in table.to_pylist()]

    def from_arrow(self, source: object) -> tuple[R, ...]:
        """Validated records. Every record-local validator runs again on the way in."""
        return self.adapter.validate_json(json.dumps(self.rows_from_arrow(source)))


def _mapping[R: CompiledRecord](
    table_id: TableId,
    adapter: TypeAdapter[tuple[R, ...]],
    to_row: Callable[[R], Row],
    from_row: Callable[[Row], Row] = _identity,
) -> TableMapping[R]:
    return TableMapping(
        table=TABLE_SCHEMAS[table_id], adapter=adapter, to_row=to_row, from_row=from_row
    )


ELEMENTS: Final[TableMapping[Element]] = _mapping(
    "elements", TypeAdapter(tuple[Element, ...]), _element_to_row
)
RELATIONSHIPS: Final[TableMapping[Relationship]] = _mapping(
    "relationships", TypeAdapter(tuple[Relationship, ...]), _relationship_to_row
)
INTERACTIONS: Final[TableMapping[Interaction]] = _mapping(
    "interactions", TypeAdapter(tuple[Interaction, ...]), _interaction_to_row
)
REFERENCES: Final[TableMapping[Reference]] = _mapping(
    "references", TypeAdapter(tuple[Reference, ...]), _reference_to_row
)
REFERENCE_LINKS: Final[TableMapping[ReferenceLink]] = _mapping(
    "reference_links", TypeAdapter(tuple[ReferenceLink, ...]), _reference_link_to_row, _with_subject
)
NOTATION_BINDINGS: Final[TableMapping[NotationBinding]] = _mapping(
    "notation_bindings",
    TypeAdapter(tuple[NotationBinding, ...]),
    _notation_binding_to_row,
    _with_subject,
)
VIEWS: Final[TableMapping[ViewDefinition]] = _mapping(
    "views",
    TypeAdapter(tuple[ViewDefinition, ...]),
    _view_to_row,
)
INTERFACE_DETAILS: Final[TableMapping[InterfaceDetail]] = _mapping(
    "interface_details",
    TypeAdapter(tuple[InterfaceDetail, ...]),
    _interface_detail_to_row,
    _detail_from_row(DetailFamily.INTERFACE),
)
DEPLOYMENT_DETAILS: Final[TableMapping[DeploymentDetail]] = _mapping(
    "deployment_details",
    TypeAdapter(tuple[DeploymentDetail, ...]),
    _deployment_detail_to_row,
    _detail_from_row(DetailFamily.DEPLOYMENT),
)
DATA_SCHEMA_DETAILS: Final[TableMapping[DataSchemaDetail]] = _mapping(
    "data_schema_details",
    TypeAdapter(tuple[DataSchemaDetail, ...]),
    _data_schema_detail_to_row,
    _detail_from_row(DetailFamily.DATA_SCHEMA),
)
BEHAVIOR_DETAILS: Final[TableMapping[BehaviorDetail]] = _mapping(
    "behavior_details",
    TypeAdapter(tuple[BehaviorDetail, ...]),
    _behavior_detail_to_row,
    _detail_from_row(DetailFamily.BEHAVIOR),
)
REQUIREMENT_DETAILS: Final[TableMapping[RequirementDetail]] = _mapping(
    "requirement_details",
    TypeAdapter(tuple[RequirementDetail, ...]),
    _requirement_detail_to_row,
    _detail_from_row(DetailFamily.REQUIREMENT),
)

MAPPINGS: Final[Mapping[TableId, ErasedMapping]] = MappingProxyType(
    {
        "elements": ELEMENTS,
        "relationships": RELATIONSHIPS,
        "interactions": INTERACTIONS,
        "references": REFERENCES,
        "reference_links": REFERENCE_LINKS,
        "notation_bindings": NOTATION_BINDINGS,
        "views": VIEWS,
        "interface_details": INTERFACE_DETAILS,
        "deployment_details": DEPLOYMENT_DETAILS,
        "data_schema_details": DATA_SCHEMA_DETAILS,
        "behavior_details": BEHAVIOR_DETAILS,
        "requirement_details": REQUIREMENT_DETAILS,
    }
)


def mapping_for(table_id: str) -> ErasedMapping:
    try:
        return MAPPINGS[table_id]
    except KeyError:
        raise UnknownTableError(table_id) from None


# -- table sets -----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TableSet:
    """Every declared table of one model, plus the versions that say how to read them."""

    model_id: str
    schema_version: str
    profile_version: str
    storage_schema_version: str
    tables: Mapping[TableId, pa.Table]

    def __getitem__(self, table_id: str) -> pa.Table:
        try:
            return self.tables[table_id]
        except KeyError:
            raise UnknownTableError(table_id) from None

    def with_tables(self, replacements: Mapping[TableId, pa.Table]) -> TableSet:
        """The same set with some tables substituted — a Delta read-back, a rechunking, a scan."""
        unknown = sorted(set(replacements) - set(TABLE_IDS))
        if unknown:
            raise UnknownTableError(str(unknown))
        return TableSet(
            model_id=self.model_id,
            schema_version=self.schema_version,
            profile_version=self.profile_version,
            storage_schema_version=self.storage_schema_version,
            tables=MappingProxyType({**self.tables, **replacements}),
        )


def _detail_table_of(detail: ElementDetail) -> TableId:
    """Which of the five tables a detail belongs in.

    `assert_never` is what makes the family cut structural: a sixth element-attachable variant
    fails `pyrefly check` here, so the storage layer cannot be left behind by a domain change.
    """
    match detail:
        case InterfaceDetail():
            return "interface_details"
        case DeploymentDetail():
            return "deployment_details"
        case DataSchemaDetail():
            return "data_schema_details"
        case BehaviorDetail():
            return "behavior_details"
        case RequirementDetail():
            return "requirement_details"
        case _ as unreachable:
            assert_never(unreachable)


def compile_tables(model: Model) -> TableSet:
    """A validated model as twelve Arrow tables, digests stamped first.

    Stamping is not optional: `content_hash` is non-nullable in every schema, so an unstamped
    model cannot be written at all — and the error says which call is missing rather than
    surfacing as a null constraint deep inside Arrow.
    """
    stamped = stamp_digests(model)
    details: dict[TableId, list[CompiledRecord]] = {
        table_id: [] for table_id in DETAIL_TABLE_BY_FAMILY.values()
    }
    for element in stamped.elements:
        if element.detail is not None:
            details[_detail_table_of(element.detail)].append(element.detail)

    tables: dict[TableId, pa.Table] = {
        "elements": ELEMENTS.to_arrow(stamped.elements),
        "relationships": RELATIONSHIPS.to_arrow(stamped.relationships),
        "interactions": INTERACTIONS.to_arrow(stamped.interactions),
        "references": REFERENCES.to_arrow(stamped.references),
        "reference_links": REFERENCE_LINKS.to_arrow(stamped.reference_links),
        "notation_bindings": NOTATION_BINDINGS.to_arrow(stamped.notation_bindings),
        # Always written, empty or not: `TABLE_IDS` is what a manifest pins, so a release
        # with no views still pins a `views` table with the declared schema and zero rows.
        "views": VIEWS.to_arrow(()),
    }
    for table_id, records in details.items():
        tables[table_id] = mapping_for(table_id).to_arrow(records)

    return TableSet(
        model_id=stamped.model_id,
        schema_version=stamped.schema_version,
        profile_version=stamped.profile_version,
        storage_schema_version=STORAGE_SCHEMA_VERSION,
        tables=MappingProxyType({table_id: tables[table_id] for table_id in TABLE_IDS}),
    )


def _details_by_element(table_set: TableSet) -> dict[str, Row]:
    """One detail row per element, or `TableSetIntegrityError` naming the offender.

    Duplicates are checked across the five tables together, not within each: an element with an
    interface detail *and* a behaviour detail is exactly as incoherent as one with two interface
    details, and only a single pass over all five can see it.
    """
    found: dict[str, Row] = {}
    origin: dict[str, TableId] = {}
    for table_id in DETAIL_TABLE_BY_FAMILY.values():
        for row in mapping_for(table_id).rows_from_arrow(table_set[table_id]):
            element_id = row["element_id"]
            if not isinstance(element_id, str):
                message = f"{table_id}: element_id is {type(element_id).__name__}"
                raise SchemaViolation(message)
            if element_id in found:
                message = (
                    f"element {element_id!r} has detail in both {origin[element_id]!r} "
                    f"and {table_id!r}"
                )
                raise TableSetIntegrityError(message)
            found[element_id] = row
            origin[element_id] = table_id
    return found


def assemble_model(table_set: TableSet) -> Model:
    """The inverse of `compile_tables`: every declared table back into one validated model.

    The five detail tables are joined onto the element rows here rather than being carried as
    records, because the model is validated once at the end — one `model_validate_json` over the
    whole payload re-runs every record-local validator, including the ones that relate a detail
    to the element it is attached to.
    """
    elements = ELEMENTS.rows_from_arrow(table_set["elements"])
    details = _details_by_element(table_set)

    for row in elements:
        element_id = row["element_id"]
        if isinstance(element_id, str) and element_id in details:
            row["detail"] = details.pop(element_id)

    if details:
        message = f"detail rows with no element: {sorted(details)}"
        raise TableSetIntegrityError(message)

    payload: dict[str, object] = {
        "schema_version": table_set.schema_version,
        "profile_version": table_set.profile_version,
        "model_id": table_set.model_id,
        "elements": elements,
        "relationships": RELATIONSHIPS.rows_from_arrow(table_set["relationships"]),
        "interactions": INTERACTIONS.rows_from_arrow(table_set["interactions"]),
        "references": REFERENCES.rows_from_arrow(table_set["references"]),
        "reference_links": REFERENCE_LINKS.rows_from_arrow(table_set["reference_links"]),
        "notation_bindings": NOTATION_BINDINGS.rows_from_arrow(table_set["notation_bindings"]),
    }
    _check_model_ids(payload, table_set.model_id)
    return Model.model_validate_json(json.dumps(payload))


def _check_model_ids(payload: Mapping[str, object], model_id: str) -> None:
    """Every row belongs to the model the table set names.

    A foreign `model_id` is not a schema violation — the column is a perfectly good string — and
    it is not something a record-local validator can see. It is a statement about the set.
    """
    for table_id in TABLE_IDS:
        if TABLE_SCHEMAS[table_id].role is TableRole.DETAIL:
            continue
        rows = payload.get(_collection_of(table_id))
        if not isinstance(rows, Sequence):
            continue
        foreign = sorted({str(row["model_id"]) for row in rows if row["model_id"] != model_id})
        if foreign:
            message = f"{table_id}: rows carry model_id {foreign}, not {model_id!r}"
            raise TableSetIntegrityError(message)


_COLLECTION_BY_TABLE: Final[Mapping[TableId, str]] = MappingProxyType(
    {
        "elements": "elements",
        "relationships": "relationships",
        "interactions": "interactions",
        "references": "references",
        "reference_links": "reference_links",
        "notation_bindings": "notation_bindings",
        "views": "views",
    }
)


def _collection_of(table_id: TableId) -> str:
    return _COLLECTION_BY_TABLE[table_id]

"""Both directions of every table mapping (DATA-14, DATA-10)."""

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from architecture_toolkit.domain.authoring import parse_model, parse_source
from architecture_toolkit.domain.details import (
    BehaviorDetail,
    BehaviorNode,
    BehaviorNodeType,
    BehaviorTransition,
    DataSchemaDetail,
    DeliverySemantics,
    DeploymentDetail,
    InteractionMode,
    InterfaceDetail,
    InterfaceTransport,
    KeyMembership,
    RequirementCategory,
    RequirementDetail,
    SchemaField,
)
from architecture_toolkit.domain.extensions import Extension
from architecture_toolkit.domain.model import (
    Element,
    Interaction,
    InteractionKind,
    InteractionParticipant,
    Model,
    ParticipantRole,
    Relationship,
)
from architecture_toolkit.domain.notation import Notation, NotationBinding
from architecture_toolkit.domain.references import (
    ElementReference,
    FieldReference,
    LinkRole,
    Reference,
    ReferenceKind,
    ReferenceLink,
    RelationshipReference,
    ReleaseReference,
)
from architecture_toolkit.domain.semantics import stamp_digests
from architecture_toolkit.domain.views import (
    FilterDimension,
    FilterMode,
    MembershipPolicy,
    PublicationState,
    ViewDefinition,
    ViewFilter,
    ViewType,
)
from architecture_toolkit.storage.errors import SchemaViolation
from architecture_toolkit.storage.mappings import (
    DATA_SCHEMA_DETAILS,
    MAPPINGS,
    assemble_model,
    compile_tables,
    mapping_for,
)
from architecture_toolkit.storage.metadata import read_description, strip
from architecture_toolkit.storage.schemas import STORAGE_SCHEMA_VERSION, TABLE_IDS, TABLE_SCHEMAS

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "minimal" / "model.yaml"

DIGEST = "sha256:" + "a" * 64
OTHER = "sha256:" + "b" * 64


def example_model() -> Model:
    return parse_model(parse_source(EXAMPLE.read_text(), source_id="example"))


# -- per-table records: one entirely sparse, one entirely populated ----------------------------


def _sparse_and_full() -> dict[str, tuple[Any, Any]]:
    """For each table, a record with every Optional null and every collection empty, and one
    with every Optional set and every collection populated."""
    return {
        "elements": (
            Element(
                element_id="elt-1",
                model_id="mod-1",
                kind_id="software.system",
                name="Sparse",
                content_hash=DIGEST,
            ),
            Element(
                element_id="elt-2",
                model_id="mod-1",
                kind_id="software.component",
                name="Full",
                description="described",
                aliases=("one", "two"),
                extensions=(
                    Extension(namespace="acme.finance", key="cc", value="42"),
                    Extension(namespace="acme.legal", key="owner", value=""),
                ),
                content_hash=OTHER,
            ),
        ),
        "relationships": (
            Relationship(
                relationship_id="rel-1",
                model_id="mod-1",
                relationship_type_id="contains",
                source_element_id="elt-1",
                target_element_id="elt-2",
                content_hash=DIGEST,
            ),
            Relationship(
                relationship_id="rel-2",
                model_id="mod-1",
                relationship_type_id="contains",
                source_element_id="elt-1",
                target_element_id="elt-2",
                context_id="ctx-1",
                description="described",
                extensions=(Extension(namespace="acme.finance", key="cc", value="42"),),
                content_hash=OTHER,
            ),
        ),
        "interactions": (
            Interaction(
                interaction_id="int-1",
                model_id="mod-1",
                name="Sparse",
                interaction_kind=InteractionKind.HANDOFF,
                content_hash=DIGEST,
            ),
            Interaction(
                interaction_id="int-2",
                model_id="mod-1",
                name="Full",
                interaction_kind=InteractionKind.EXCHANGE,
                description="described",
                participants=(
                    InteractionParticipant(
                        element_id="elt-1", participant_role=ParticipantRole.SENDER, ordinal=0
                    ),
                    InteractionParticipant(
                        element_id="elt-2", participant_role=ParticipantRole.RECEIVER, ordinal=1
                    ),
                ),
                moved_object_ids=("elt-1",),
                content_hash=OTHER,
            ),
        ),
        "references": (
            Reference(
                reference_id="ref-1",
                model_id="mod-1",
                reference_kind=ReferenceKind.INTERVIEW,
                title="Sparse",
                content_hash=DIGEST,
            ),
            Reference(
                reference_id="ref-2",
                model_id="mod-1",
                reference_kind=ReferenceKind.DOCUMENT,
                title="Full",
                locator="https://example.invalid/doc",
                authority="an authority",
                content_hash=OTHER,
            ),
        ),
        "reference_links": (
            ReferenceLink(
                link_id="lnk-1",
                model_id="mod-1",
                reference_id="ref-1",
                subject=ElementReference(element_id="elt-1"),
                link_role=LinkRole.SUPPORTS,
                content_hash=DIGEST,
            ),
            ReferenceLink(
                link_id="lnk-2",
                model_id="mod-1",
                reference_id="ref-2",
                subject=FieldReference(element_id="elt-2", field_path="detail.transport.protocol"),
                link_role=LinkRole.QUALIFIES,
                note="a note",
                content_hash=OTHER,
            ),
        ),
        "notation_bindings": (
            NotationBinding(
                binding_id="bnd-1",
                model_id="mod-1",
                subject=RelationshipReference(relationship_id="rel-1"),
                notation=Notation.BPMN,
                notation_type="bpmn:Task",
                notation_object_id="Task_1",
                mapping_profile_version="1.0.0",
                content_hash=DIGEST,
            ),
            NotationBinding(
                binding_id="bnd-2",
                model_id="mod-1",
                subject=ReleaseReference(release_id="rel-2026-01"),
                notation=Notation.ARCHIMATE,
                notation_type="ArchiMate:ApplicationComponent",
                notation_object_id="id-abc",
                view_id="view-1",
                mapping_profile_version="1.0.0",
                projection_artifact_id="art-1",
                link_target="#anchor",
                content_hash=OTHER,
            ),
        ),
        "interface_details": (
            InterfaceDetail(
                element_id="elt-1",
                transport=InterfaceTransport(
                    protocol="https",
                    interaction_mode=InteractionMode.SYNCHRONOUS,
                    serialization="json",
                ),
                timeout_ms=0,
                content_hash=DIGEST,
            ),
            InterfaceDetail(
                element_id="elt-2",
                transport=InterfaceTransport(
                    protocol="amqp",
                    interaction_mode=InteractionMode.ASYNCHRONOUS,
                    serialization="avro",
                ),
                authentication_description="Bearer token",
                request_schema_id="elt-1",
                response_schema_id="elt-1",
                delivery_semantics=DeliverySemantics.EXACTLY_ONCE,
                timeout_ms=600000,
                idempotency_description="idempotent",
                content_hash=OTHER,
            ),
        ),
        "deployment_details": (
            DeploymentDetail(element_id="elt-1", environment="dev", content_hash=DIGEST),
            DeploymentDetail(
                element_id="elt-2",
                environment="prod",
                deployment_node_id="elt-1",
                software_instance_id="elt-1",
                configuration_artifact_id="ref-1",
                content_hash=OTHER,
            ),
        ),
        "data_schema_details": (
            DataSchemaDetail(element_id="elt-1", content_hash=DIGEST),
            DataSchemaDetail(
                element_id="elt-2",
                fields=(
                    SchemaField(
                        field_id="id",
                        field_name="id",
                        data_type="string",
                        key_membership=frozenset(
                            {KeyMembership.PRIMARY_KEY, KeyMembership.UNIQUE_KEY}
                        ),
                        ordinal=0,
                    ),
                    SchemaField(
                        field_id="owner",
                        field_name="owner",
                        data_type="string",
                        key_membership=frozenset({KeyMembership.FOREIGN_KEY}),
                        references_element_id="elt-1",
                        references_field_id="id",
                        ordinal=1,
                    ),
                ),
                content_hash=OTHER,
            ),
        ),
        "behavior_details": (
            BehaviorDetail(element_id="elt-1", content_hash=DIGEST),
            BehaviorDetail(
                element_id="elt-2",
                nodes=(
                    BehaviorNode(
                        node_id="start", node_type=BehaviorNodeType.START_EVENT, name="A", ordinal=0
                    ),
                    BehaviorNode(
                        node_id="task",
                        node_type=BehaviorNodeType.TASK,
                        name="B",
                        ordinal=1,
                        participant_element_id="elt-1",
                    ),
                ),
                transitions=(
                    BehaviorTransition(
                        transition_id="t1",
                        source_node_id="start",
                        target_node_id="task",
                        guard="always",
                        ordinal=0,
                    ),
                ),
                content_hash=OTHER,
            ),
        ),
        "views": (
            ViewDefinition(
                view_id="view-1",
                model_id="m-1",
                view_type=ViewType.SYSTEM_LANDSCAPE,
                notation=Notation.C4,
                title="Landscape",
                content_hash=DIGEST,
            ),
            ViewDefinition(
                view_id="view-2",
                model_id="m-1",
                view_type=ViewType.CONTAINER,
                notation=Notation.C4,
                scope="elt-1",
                audience="platform engineering",
                title="Containers",
                description="Every container of the billing system.",
                membership_policy=MembershipPolicy.DERIVED,
                included_element_ids=("elt-1", "elt-2"),
                included_relationship_ids=("rel-1",),
                perspective="ownership",
                filter=(
                    ViewFilter(
                        filter_mode=FilterMode.INCLUDE,
                        dimension=FilterDimension.KIND,
                        values=("software.container", "software.system"),
                    ),
                    ViewFilter(
                        filter_mode=FilterMode.EXCLUDE,
                        dimension=FilterDimension.LIFECYCLE_STATE,
                        values=("retired",),
                    ),
                ),
                layout_profile_id="layout-1",
                publication_state=PublicationState.PUBLISHED,
                content_hash=OTHER,
            ),
        ),
        "requirement_details": (
            RequirementDetail(
                element_id="elt-1",
                category=RequirementCategory.FUNCTIONAL,
                content_hash=DIGEST,
            ),
            RequirementDetail(
                element_id="elt-2",
                category=RequirementCategory.REGULATORY,
                applicability_note="a note",
                acceptance_criterion_ids=("ref-1", "ref-2"),
                content_hash=OTHER,
            ),
        ),
    }


RECORDS = _sparse_and_full()
IDS = list(TABLE_IDS)


@pytest.mark.unit
@pytest.mark.requirement("DATA-14")
def test_every_declared_table_has_a_mapping_and_a_fixture() -> None:
    """Totality in both directions: no table without a mapping, no mapping without a table."""
    assert set(MAPPINGS) == set(TABLE_IDS)
    assert set(RECORDS) == set(TABLE_IDS)


@pytest.mark.unit
@pytest.mark.requirement("DATA-14")
@pytest.mark.parametrize("table_id", IDS)
def test_records_survive_a_round_trip_through_arrow(table_id: str) -> None:
    """The sparse record exercises every null; the full one exercises every collection."""
    mapping = mapping_for(table_id)
    records = RECORDS[table_id]
    table = mapping.to_arrow(records)
    assert table.num_rows == 2
    assert mapping.from_arrow(table) == records


@pytest.mark.unit
@pytest.mark.requirement("DATA-10", "DATA-14")
@pytest.mark.parametrize("table_id", IDS)
def test_no_records_still_produce_the_declared_schema(table_id: str) -> None:
    """DATA-11's typed empty: zero rows is not zero schema."""
    mapping = mapping_for(table_id)
    table = mapping.to_arrow(())
    assert table.num_rows == 0
    assert table.schema.equals(TABLE_SCHEMAS[table_id].schema, check_metadata=False)
    assert read_description(table.schema).table_id == table_id
    assert mapping.from_arrow(table) == ()


@pytest.mark.unit
@pytest.mark.requirement("DATA-44")
@pytest.mark.parametrize("table_id", IDS)
def test_stripping_every_metadata_key_changes_no_record(table_id: str) -> None:
    """Metadata is self-description and carries no meaning, asserted rather than asserted-to-be."""
    mapping = mapping_for(table_id)
    table = mapping.to_arrow(RECORDS[table_id])
    stripped = table.cast(strip(table.schema))
    assert read_description(stripped.schema).table_id is None
    assert mapping.from_arrow(stripped) == mapping.from_arrow(table)


@pytest.mark.unit
@pytest.mark.requirement("DATA-14")
def test_an_unstamped_record_names_the_call_that_is_missing() -> None:
    """`content_hash` is non-nullable everywhere, so this would otherwise surface inside Arrow."""
    unstamped = Element(
        element_id="elt-9", model_id="mod-1", kind_id="software.system", name="Unstamped"
    )
    with pytest.raises(ValueError, match="call stamp_digests"):
        mapping_for("elements").to_arrow([unstamped])


@pytest.mark.unit
@pytest.mark.requirement("DATA-10", "DATA-14")
def test_a_null_in_a_non_nullable_column_is_refused_on_read() -> None:
    """Arrow does not enforce nullability and `from_pylist` will happily write the null."""
    declared = TABLE_SCHEMAS["references"]
    rows = [
        {
            "reference_id": "ref-1",
            "model_id": "mod-1",
            "reference_kind": "document",
            "title": None,
            "locator": None,
            "authority": None,
            "content_hash": DIGEST,
        }
    ]
    # The nullable schema is what makes the bad table constructible at all.
    permissive = pa.schema([pa.field(f.name, f.type, nullable=True) for f in declared.bare()])
    table = pa.Table.from_pylist(rows, schema=permissive).cast(
        pa.schema([pa.field(f.name, f.type, nullable=True) for f in declared.bare()])
    )
    with pytest.raises(SchemaViolation, match=r"references\.title is non-nullable"):
        mapping_for("references").from_arrow(table)


@pytest.mark.unit
@pytest.mark.requirement("DATA-10")
def test_an_unexpected_column_is_refused() -> None:
    table = pa.table({"element_id": ["elt-1"], "surprise": ["x"]})
    with pytest.raises(SchemaViolation, match="do not match"):
        mapping_for("elements").from_arrow(table)


@pytest.mark.unit
@pytest.mark.requirement("DATA-09", "DATA-14")
def test_a_subject_row_filling_a_slot_its_variant_forbids_is_refused() -> None:
    """The union is flattened, so this is the check that replaces Arrow's absent union tag."""
    mapping = mapping_for("reference_links")
    table = mapping.to_arrow(RECORDS["reference_links"])
    rows = table.to_pylist()
    # An element subject that also claims a release: `extra="forbid"` is what catches it.
    rows[0]["subject"]["release_id"] = "rel-2026-01"
    broken = pa.Table.from_pylist(rows, schema=table.schema)
    with pytest.raises(Exception, match="release_id"):
        mapping.from_arrow(broken)


@pytest.mark.unit
@pytest.mark.requirement("DATA-09")
def test_every_subject_variant_round_trips() -> None:
    """All four, because the flattened struct is the one place a variant can be lost."""
    subjects = (
        ElementReference(element_id="elt-1"),
        RelationshipReference(relationship_id="rel-1"),
        FieldReference(element_id="elt-1", field_path="a.b"),
        ReleaseReference(release_id="rel-2026-01"),
    )
    links = tuple(
        ReferenceLink(
            link_id=f"lnk-{index}",
            model_id="mod-1",
            reference_id="ref-1",
            subject=subject,
            link_role=LinkRole.SUPPORTS,
            content_hash=DIGEST,
        )
        for index, subject in enumerate(subjects)
    )
    mapping = mapping_for("reference_links")
    assert mapping.from_arrow(mapping.to_arrow(links)) == links


@pytest.mark.unit
@pytest.mark.requirement("DATA-14")
def test_key_membership_is_written_sorted_and_read_back_as_a_set() -> None:
    """A frozenset has no order, so one is imposed on write and discarded on read."""
    # The concrete mapping, not `mapping_for`: the registry's erased view returns
    # `tuple[CompiledRecord, ...]`, which is the right type for a generic caller and the wrong
    # one for reaching into a specific record's fields.
    table = DATA_SCHEMA_DETAILS.to_arrow(RECORDS["data_schema_details"])
    written = table.to_pylist()[1]["fields"][0]["key_membership"]
    assert written == sorted(written)
    assert DATA_SCHEMA_DETAILS.from_arrow(table)[1].fields[0].key_membership == frozenset(
        {KeyMembership.PRIMARY_KEY, KeyMembership.UNIQUE_KEY}
    )


# -- the whole model ----------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.requirement("DATA-10", "DATA-14")
def test_the_example_compiles_to_every_declared_table_and_assembles_back() -> None:
    model = example_model()
    table_set = compile_tables(model)
    assert list(table_set.tables) == list(TABLE_IDS)
    assert table_set.model_id == model.model_id
    assert table_set.storage_schema_version == STORAGE_SCHEMA_VERSION
    assert assemble_model(table_set) == stamp_digests(model)


@pytest.mark.unit
@pytest.mark.requirement("DATA-10")
def test_each_detail_lands_in_the_table_for_its_family() -> None:
    table_set = compile_tables(example_model())
    for table_id in ("interface_details", "deployment_details", "requirement_details"):
        rows = table_set[table_id].to_pylist()
        assert len(rows) == 1, table_id
    # And no element row carries a detail column at all.
    assert "detail" not in table_set["elements"].schema.names


@pytest.mark.unit
@pytest.mark.requirement("DATA-14")
def test_compile_tables_stamps_so_every_content_hash_is_present() -> None:
    model = example_model()
    assert model.elements[0].content_hash is None
    table_set = compile_tables(model)
    for table_id in TABLE_IDS:
        column = table_set[table_id].column("content_hash")
        assert column.null_count == 0
        assert all(str(value).startswith("sha256:") for value in column.to_pylist())


@pytest.mark.unit
@pytest.mark.requirement("DATA-14")
def test_a_table_set_can_have_tables_substituted() -> None:
    """What a Delta read-back or a rechunking does, without rebuilding the set."""
    table_set = compile_tables(example_model())
    rechunked = pa.Table.from_batches(
        table_set["elements"].to_batches(), schema=table_set["elements"].schema
    )
    substituted = table_set.with_tables({"elements": rechunked})
    assert substituted.model_id == table_set.model_id
    assert assemble_model(substituted) == assemble_model(table_set)


@pytest.mark.unit
@pytest.mark.requirement("DATA-14")
def test_rows_are_json_ready() -> None:
    """The reverse path serializes them, so a non-JSON value would fail there instead of here."""
    table_set = compile_tables(example_model())
    for table_id in TABLE_IDS:
        rows = mapping_for(table_id).rows_from_arrow(table_set[table_id])
        json.dumps(rows)

"""Element, status and detail strategies (CORE-45, DATA-03, DATA-07, DATA-29)."""

from hypothesis import strategies as st

from architecture_toolkit.domain.details import (
    Applicability,
    BehaviorDetail,
    BehaviorNode,
    BehaviorNodeType,
    BehaviorTransition,
    DataSchemaDetail,
    DeliverySemantics,
    DeploymentDetail,
    ElementDetail,
    FieldCardinality,
    InteractionMode,
    InterfaceDetail,
    InterfaceTransport,
    KeyMembership,
    Nullability,
    RequirementCategory,
    RequirementDetail,
    SchemaField,
    VerificationMethod,
)
from architecture_toolkit.domain.model import Element
from architecture_toolkit.domain.references import Reference, ReferenceKind
from architecture_toolkit.domain.registry import BASELINE_PROFILE
from architecture_toolkit.domain.status import (
    ClientAcceptance,
    DesignDisposition,
    EvidenceReview,
    GapState,
    ImplementationState,
    LifecycleState,
    StatusDimensions,
    TechnicalQualification,
)
from tests.strategies.ids import element_ids, model_ids

__all__ = ["element_details", "elements", "references", "status_dimensions"]

names = st.text(min_size=1, max_size=40).filter(lambda value: bool(value.strip()))
descriptions = st.none() | st.text(max_size=120)

# Strict Python mode requires an actual enum member, not its string value, so every enum field
# is drawn from the members rather than from text. JSON mode would accept the string; these
# strategies build records in process.
BASELINE_KIND_IDS = st.sampled_from(sorted(BASELINE_PROFILE.kinds_by_id))


def _dimension[T](values: type[T]) -> st.SearchStrategy[object]:
    """A vocabulary value or an explicit gap — the shape DATA-41 requires of every dimension."""
    return st.sampled_from([*list(values), *list(GapState)])  # type: ignore[call-overload]


status_dimensions = st.builds(
    StatusDimensions,
    design_disposition=_dimension(DesignDisposition),
    implementation_state=_dimension(ImplementationState),
    technical_qualification=_dimension(TechnicalQualification),
    client_acceptance=_dimension(ClientAcceptance),
    evidence_review=_dimension(EvidenceReview),
)


def _interface_details(owner: str) -> st.SearchStrategy[InterfaceDetail]:
    return st.builds(
        InterfaceDetail,
        element_id=st.just(owner),
        transport=st.builds(
            InterfaceTransport,
            protocol=st.sampled_from(["https", "grpc", "amqp", "sftp"]),
            interaction_mode=st.sampled_from(list(InteractionMode)),
            serialization=st.sampled_from(["json", "protobuf", "avro", "csv"]),
        ),
        delivery_semantics=st.sampled_from(list(DeliverySemantics)),
        timeout_ms=st.none() | st.integers(min_value=0, max_value=600_000),
    )


def _schema_details(owner: str) -> st.SearchStrategy[DataSchemaDetail]:
    field = st.builds(
        SchemaField,
        field_id=st.from_regex(r"[a-z][a-z0-9_]{1,20}", fullmatch=True),
        field_name=names,
        data_type=st.sampled_from(["string", "integer", "boolean", "timestamp"]),
        nullability=st.sampled_from(list(Nullability)),
        cardinality=st.sampled_from(list(FieldCardinality)),
        # Foreign keys are excluded here: the record-local validator requires a referenced
        # element, and generating one that resolves needs the element pool. `relations.py`
        # composes that case.
        key_membership=st.sampled_from(
            [
                frozenset(),
                frozenset({KeyMembership.PRIMARY_KEY}),
                frozenset({KeyMembership.UNIQUE_KEY}),
            ]
        ),
        ordinal=st.integers(min_value=0, max_value=32),
    )
    return st.builds(
        DataSchemaDetail,
        element_id=st.just(owner),
        fields=st.lists(field, max_size=4).map(tuple),
    )


def _behavior_details(owner: str) -> st.SearchStrategy[BehaviorDetail]:
    """Transitions are drawn from the node ids already generated, never filtered into validity."""
    node_ids = st.lists(
        st.from_regex(r"n[a-z0-9]{1,6}", fullmatch=True), min_size=1, max_size=5, unique=True
    )

    @st.composite
    def _build(draw: st.DrawFn) -> BehaviorDetail:
        ids = draw(node_ids)
        nodes = tuple(
            BehaviorNode(
                node_id=identity,
                node_type=draw(st.sampled_from(list(BehaviorNodeType))),
                name=draw(names),
                ordinal=index,
                participant_element_id=None,
            )
            for index, identity in enumerate(ids)
        )
        transitions = tuple(
            BehaviorTransition(
                transition_id=f"t{index}",
                source_node_id=ids[index],
                target_node_id=ids[index + 1],
                ordinal=index,
            )
            for index in range(len(ids) - 1)
        )
        return BehaviorDetail(element_id=owner, nodes=nodes, transitions=transitions)

    return _build()


def element_details(owner: str) -> st.SearchStrategy[ElementDetail]:
    """One strategy per variant, unioned. Every variant is reachable."""
    return st.one_of(
        _interface_details(owner),
        st.builds(DeploymentDetail, element_id=st.just(owner), environment=names),
        _schema_details(owner),
        _behavior_details(owner),
        st.builds(
            RequirementDetail,
            element_id=st.just(owner),
            category=st.sampled_from(list(RequirementCategory)),
            applicability=st.sampled_from(list(Applicability)),
            verification_method=st.sampled_from(list(VerificationMethod)),
        ),
    )


@st.composite
def elements(draw: st.DrawFn, *, model_id: str | None = None) -> Element:
    identity = draw(element_ids)
    return Element(
        element_id=identity,
        model_id=model_id or draw(model_ids),
        kind_id=draw(BASELINE_KIND_IDS),
        name=draw(names),
        description=draw(descriptions),
        lifecycle_state=draw(st.sampled_from(list(LifecycleState))),
        aliases=tuple(draw(st.lists(names, max_size=2))),
        status=draw(status_dimensions),
        detail=draw(st.none() | element_details(identity)),
    )


def references(*, model_id: str) -> st.SearchStrategy[Reference]:
    return st.builds(
        Reference,
        reference_id=element_ids,
        model_id=st.just(model_id),
        reference_kind=st.sampled_from(list(ReferenceKind)),
        title=names,
        locator=st.none() | st.text(max_size=60),
    )

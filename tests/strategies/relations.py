"""Relationship and whole-model strategies (CORE-45, DATA-05).

The construction rule that matters: draw the element pool first, then draw endpoints with
`st.sampled_from(pool)`. Generating identifiers independently and filtering for the ones that
resolve would reject almost every example and shrink to something unreadable. core.md asks for
valid data built directly, and this is what that means in practice.
"""

from hypothesis import strategies as st

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
    ReferenceLink,
    RelationshipReference,
    ReleaseReference,
)
from architecture_toolkit.domain.registry import BASELINE_PROFILE
from tests.strategies.domain import descriptions, elements, extensions, names, references
from tests.strategies.ids import element_ids, model_ids, versions

__all__ = [
    "coherent_models",
    "full_models",
    "interactions",
    "notation_bindings",
    "reference_links",
    "relationships",
]

# Drawn from the profile, so a generated relationship type always resolves in the registry.
BASELINE_TYPE_IDS = st.sampled_from(sorted(BASELINE_PROFILE.relationship_types_by_id))

# Bounded deliberately. The `ci` profile runs 100 examples; eight elements reaches every rule
# family while keeping a shrunk counterexample small enough to read in a failure message.
MAX_ELEMENTS = 8
MAX_RELATIONSHIPS = 8


@st.composite
def relationships(draw: st.DrawFn, *, pool: list[Element], model_id: str) -> Relationship:
    endpoints = st.sampled_from([element.element_id for element in pool])
    return Relationship(
        relationship_id=draw(element_ids),
        model_id=model_id,
        relationship_type_id=draw(BASELINE_TYPE_IDS),
        source_element_id=draw(endpoints),
        target_element_id=draw(endpoints),
        extensions=draw(extensions()),
    )


@st.composite
def coherent_models(draw: st.DrawFn) -> Model:
    """A model whose endpoints always resolve. Endpoint *kinds* may still be impermissible.

    That is deliberate: structural coherence and profile conformance are different claims, and a
    strategy that guaranteed both would make the endpoint-kind rule untestable by property.
    """
    identity = draw(model_ids)
    pool = draw(
        st.lists(
            elements(model_id=identity),
            min_size=1,
            max_size=MAX_ELEMENTS,
            unique_by=lambda element: element.element_id,
        )
    )
    relations = draw(
        st.lists(
            relationships(pool=pool, model_id=identity),
            max_size=MAX_RELATIONSHIPS,
            unique_by=lambda relation: relation.relationship_id,
        )
    )
    return Model(model_id=identity, elements=tuple(pool), relationships=tuple(relations))


# -- the four collections `coherent_models` leaves empty ----------------------------------------
# Bounded like the rest: three of each is enough to exercise every canonicalization policy and
# every `ReferenceTarget` variant while a shrunk failure stays readable.
MAX_PER_COLLECTION = 3


def _subjects(pool: list[Element], relations: list[Relationship]) -> st.SearchStrategy[object]:
    """Every `ReferenceTarget` variant, addressed at records that exist in the model."""
    element_pool = st.sampled_from([element.element_id for element in pool])
    variants: list[st.SearchStrategy[object]] = [
        st.builds(ElementReference, element_id=element_pool),
        st.builds(FieldReference, element_id=element_pool, field_path=st.just("detail")),
        st.builds(ReleaseReference, release_id=element_ids),
    ]
    if relations:
        relation_pool = st.sampled_from([relation.relationship_id for relation in relations])
        variants.append(st.builds(RelationshipReference, relationship_id=relation_pool))
    return st.one_of(*variants)


@st.composite
def interactions(draw: st.DrawFn, *, pool: list[Element], model_id: str) -> Interaction:
    """Participants carry consecutive ordinals; the tuple order is the ordinal order here.

    W2's presentation-invariance property permutes the tuple separately to prove the ordinal, not
    the position, is what the digest reads.
    """
    identities = [element.element_id for element in pool]
    chosen = draw(st.lists(st.sampled_from(identities), max_size=MAX_PER_COLLECTION))
    participants = tuple(
        InteractionParticipant(
            element_id=identity,
            participant_role=draw(st.sampled_from(list(ParticipantRole))),
            ordinal=index,
        )
        for index, identity in enumerate(chosen)
    )
    moved = draw(st.lists(st.sampled_from(identities), max_size=2, unique=True))
    return Interaction(
        interaction_id=draw(element_ids),
        model_id=model_id,
        name=draw(names),
        interaction_kind=draw(st.sampled_from(list(InteractionKind))),
        description=draw(descriptions),
        participants=participants,
        moved_object_ids=tuple(moved),
    )


def reference_links(
    *, pool: list[Element], relations: list[Relationship], refs: list[Reference], model_id: str
) -> st.SearchStrategy[ReferenceLink]:
    return st.builds(
        ReferenceLink,
        link_id=element_ids,
        model_id=st.just(model_id),
        reference_id=st.sampled_from([reference.reference_id for reference in refs]),
        subject=_subjects(pool, relations),
        link_role=st.sampled_from(list(LinkRole)),
        note=descriptions,
    )


def notation_bindings(
    *, pool: list[Element], relations: list[Relationship], model_id: str
) -> st.SearchStrategy[NotationBinding]:
    return st.builds(
        NotationBinding,
        binding_id=element_ids,
        model_id=st.just(model_id),
        subject=_subjects(pool, relations),
        notation=st.sampled_from(list(Notation)),
        notation_type=names,
        notation_object_id=st.text(min_size=1, max_size=40),
        view_id=st.none() | element_ids,
        mapping_profile_version=versions,
        link_target=descriptions,
    )


@st.composite
def full_models(draw: st.DrawFn) -> Model:
    """A coherent model with every one of the six collections populated.

    `coherent_models` stays as it is — elements and relationships are what the rule families
    need — and this builds on it for the properties that must cover the whole schema: W2's
    presentation invariance and stamping, W3's Arrow round trip.
    """
    model = draw(coherent_models())
    pool = list(model.elements)
    relations = list(model.relationships)
    refs = draw(
        st.lists(
            references(model_id=model.model_id),
            max_size=MAX_PER_COLLECTION,
            unique_by=lambda reference: reference.reference_id,
        )
    )
    links = (
        draw(
            st.lists(
                reference_links(pool=pool, relations=relations, refs=refs, model_id=model.model_id),
                max_size=MAX_PER_COLLECTION,
                unique_by=lambda link: link.link_id,
            )
        )
        if refs
        else []
    )
    handoffs = draw(
        st.lists(
            interactions(pool=pool, model_id=model.model_id),
            max_size=MAX_PER_COLLECTION,
            unique_by=lambda interaction: interaction.interaction_id,
        )
    )
    bindings = draw(
        st.lists(
            notation_bindings(pool=pool, relations=relations, model_id=model.model_id),
            max_size=MAX_PER_COLLECTION,
            unique_by=lambda binding: binding.binding_id,
        )
    )
    return Model.model_validate(
        dict(model)
        | {
            "interactions": tuple(handoffs),
            "references": tuple(refs),
            "reference_links": tuple(links),
            "notation_bindings": tuple(bindings),
        }
    )

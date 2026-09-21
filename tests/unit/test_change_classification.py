"""The classification table is total, has no default, and cannot quietly stop classifying.

Three failure modes this file exists for, all of which this repo has already met once:

1. **A reflection walk that finds a subset.** The dangerous version is not an empty walk — that is
   obvious — but one that never descends through `ElementDetail`, which is a discriminated union
   behind `Annotated[..., Field(discriminator=...)] | None`. The table would then be written
   against the same subset, the two would agree, and no interface field would be classified at
   all. So the walk is exercised on a synthetic model *and* the real table is pinned against named
   members from the deepest reachable records.
2. **A residual that swallows the table.** `FIELD_MODIFIED` is pinned by a ceiling *and* by a list
   of fields that must never reach it. A bare count is gameable by adding rows; count plus
   membership is not.
3. **A reserved value that is reserved only in a comment.** The two unreachable natures are
   asserted unused, in both directions.
"""

from typing import Annotated, Any, Literal, get_args

import pytest
from pydantic import BaseModel, Field

from architecture_toolkit.changes.classification import (
    CHANGE_CLASSIFICATION,
    OPTIONAL_RECORD_RULES,
    PRESENCE_RULES,
    _check_registry,
    optional_record_rule_for,
    presence_rule_for,
    rule_for,
)
from architecture_toolkit.changes.errors import ClassificationError
from architecture_toolkit.changes.kinds import (
    NARRATIVE_NATURES,
    NEVER_EMITTED,
    UNREACHABLE_NATURES,
    ChangeKind,
    ChangeNature,
    ChangeRule,
)
from architecture_toolkit.domain.details import (
    BehaviorTransition,
    InterfaceDetail,
    SchemaField,
)
from architecture_toolkit.domain.model import Element, Model, Relationship
from architecture_toolkit.domain.notation import NotationBinding
from architecture_toolkit.domain.semantics import MODEL_COLLECTIONS
from architecture_toolkit.domain.status import StatusDimensions


def _models_in(annotation: object) -> list[type[BaseModel]]:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    found: list[type[BaseModel]] = []
    for argument in get_args(annotation):
        found.extend(_models_in(argument))
    return found


def classified_fields(root: type[BaseModel]) -> set[tuple[type[BaseModel], str]]:
    """Every `(class, field)` reachable from `root`.

    Deliberately unfiltered, unlike `test_semantics.py::tuple_fields`, which looks only for
    tuple-typed annotations. Copying that filter here would reproduce its blind spot: a
    `frozenset`-typed field — `SchemaField.key_membership` is one today — is invisible to it.
    """
    found: set[tuple[type[BaseModel], str]] = set()
    seen: set[type[BaseModel]] = set()

    def visit(cls: type[BaseModel]) -> None:
        if cls in seen:
            return
        seen.add(cls)
        for name, field in cls.model_fields.items():
            found.add((cls, name))
            for nested in _models_in(field.annotation):
                visit(nested)

    visit(root)
    return found


# -- totality -------------------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.requirement("DATA-26")
def test_every_field_reachable_from_the_model_declares_what_a_change_to_it_is() -> None:
    """The wave's central guard: a new field cannot be classified by accident."""
    assert classified_fields(Model) == set(CHANGE_CLASSIFICATION)


@pytest.mark.unit
@pytest.mark.requirement("DATA-26")
def test_the_walk_reaches_the_deepest_records_and_not_only_the_shallow_ones() -> None:
    """A floor plus named members, because equality above is only as good as the walk.

    Each name is from a record the walk can only reach by descending through a discriminated
    union, a nested value object or an identity-keyed collection. If the walk lost any of those,
    equality would still hold — against a smaller table.
    """
    covered = set(CHANGE_CLASSIFICATION)
    for key in (
        (InterfaceDetail, "timeout_ms"),
        (SchemaField, "key_membership"),
        (BehaviorTransition, "guard"),
        (StatusDimensions, "evidence_review"),
        (NotationBinding, "link_target"),
        (Model, "profile_version"),
    ):
        assert key in covered, f"{key[0].__name__}.{key[1]} is unclassified"
    assert len(covered) > 120


@pytest.mark.unit
@pytest.mark.requirement("DATA-26")
def test_field_discovery_sees_through_annotated_optional_and_a_discriminated_union() -> None:
    """The walk itself, on a model whose shape is the one that would silently lose records."""

    class Left(BaseModel):
        variant: Literal["left"] = "left"
        left_only: int = 0

    class Right(BaseModel):
        variant: Literal["right"] = "right"
        right_only: int = 0

    class Outer(BaseModel):
        chosen: Annotated[Left | Right, Field(discriminator="variant")] | None = None
        maybe: Annotated[Left, "meta"] | None = None
        many: tuple[Right, ...] = ()
        frozen: frozenset[str] = frozenset()

    assert classified_fields(Outer) == {
        (Outer, "chosen"),
        (Outer, "maybe"),
        (Outer, "many"),
        (Outer, "frozen"),
        (Left, "variant"),
        (Left, "left_only"),
        (Right, "variant"),
        (Right, "right_only"),
    }


@pytest.mark.unit
@pytest.mark.requirement("DATA-26")
def test_a_record_appearing_or_vanishing_is_classified_for_every_collection() -> None:
    expected = {(name, present) for name, _ in MODEL_COLLECTIONS for present in (True, False)}

    assert set(PRESENCE_RULES) == expected
    assert presence_rule_for("elements", in_candidate=True).kind is ChangeKind.ELEMENT_ADDED
    assert presence_rule_for("elements", in_candidate=False).kind is ChangeKind.ELEMENT_REMOVED


# -- the residual is bounded ----------------------------------------------------------------------

# Fields whose change has a name in some contract. If one of these ever resolves to the residual,
# the narrative has lost a distinction the gate or DATA-26 depends on. Membership, not just count:
# a ceiling alone is satisfied by adding rows somewhere harmless.
MUST_BE_NAMED: tuple[tuple[type[BaseModel], str], ...] = (
    (Element, "name"),
    (Element, "kind_id"),
    (Element, "lifecycle_state"),
    (Element, "aliases"),
    (Relationship, "source_element_id"),
    (Relationship, "target_element_id"),
    (Relationship, "relationship_type_id"),
    (InterfaceDetail, "detail_family"),
    (StatusDimensions, "design_disposition"),
    (StatusDimensions, "implementation_state"),
    (StatusDimensions, "technical_qualification"),
    (StatusDimensions, "client_acceptance"),
    (StatusDimensions, "evidence_review"),
    (NotationBinding, "link_target"),
    (NotationBinding, "view_id"),
    (NotationBinding, "mapping_profile_version"),
    (NotationBinding, "projection_artifact_id"),
)

# Five today: `Element.description`, `Relationship.description`, `Interaction.description`,
# `Reference.authority`, `ReferenceLink.note`. Pinned at exactly that, not at a round number with
# slack in it — a ceiling with a free slot lets one field join the residual without the argument
# this pin exists to force. Raising it is a decision to be made in a commit message.
RESIDUAL_CEILING = 5


@pytest.mark.unit
@pytest.mark.requirement("DATA-26")
def test_the_residual_stays_small_and_never_takes_a_field_that_has_a_name() -> None:
    residual = {
        key for key, rule in CHANGE_CLASSIFICATION.items() if rule.kind is ChangeKind.FIELD_MODIFIED
    }

    assert len(residual) <= RESIDUAL_CEILING
    assert residual.isdisjoint(MUST_BE_NAMED)


@pytest.mark.unit
@pytest.mark.requirement("DATA-26")
def test_the_residual_is_semantic_so_an_unclassified_field_is_noisy_not_invisible() -> None:
    """Defaulting the other way would make every field a later wave adds silently absent."""
    residual = [
        rule for rule in CHANGE_CLASSIFICATION.values() if rule.kind is ChangeKind.FIELD_MODIFIED
    ]

    assert residual
    assert all(rule.nature is ChangeNature.CANONICAL_SEMANTIC for rule in residual)
    assert all(rule.in_narrative for rule in residual)


@pytest.mark.unit
@pytest.mark.requirement("DATA-26")
def test_the_table_has_no_default_so_an_unclassified_field_raises() -> None:
    """The one behaviour that makes the totality test above have consequences."""
    with pytest.raises(KeyError):
        rule_for(Element, "not_a_field")


# -- the two axes stay apart ----------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.requirement("DATA-26", "DATA-31")
def test_the_reserved_natures_are_used_by_nothing_in_both_directions() -> None:
    """A reservation nothing checks is a comment. `UNREACHABLE_NATURES` names the wave for each."""
    used = {rule.nature for rule in CHANGE_CLASSIFICATION.values()}
    used |= {rule.nature for rule in PRESENCE_RULES.values()}
    used |= {rule.nature for pair in OPTIONAL_RECORD_RULES.values() for rule in pair}

    assert used.isdisjoint(UNREACHABLE_NATURES)
    assert used | set(UNREACHABLE_NATURES) == set(ChangeNature)
    assert set(UNREACHABLE_NATURES) == {
        ChangeNature.STYLE_THEME_ONLY,
        ChangeNature.PUBLICATION_NAVIGATION_ONLY,
    }


@pytest.mark.unit
@pytest.mark.requirement("DATA-26", "DATA-31")
def test_one_record_carries_three_natures_which_is_why_the_table_is_keyed_by_field() -> None:
    """`NotationBinding` is the gate's record, and a per-record rule could not describe it."""
    natures = {
        rule.nature
        for (owner, _), rule in CHANGE_CLASSIFICATION.items()
        if owner is NotationBinding
    }

    assert ChangeNature.NOTATION_MAPPING in natures
    assert ChangeNature.VIEW_MEMBERSHIP in natures
    assert ChangeNature.LAYOUT_ONLY in natures
    assert not rule_for(NotationBinding, "link_target").in_narrative
    assert rule_for(NotationBinding, "mapping_profile_version").in_narrative


@pytest.mark.unit
@pytest.mark.requirement("DATA-26")
def test_every_declared_kind_classifies_at_least_one_real_field() -> None:
    """Otherwise the vocabulary grows past the model and nobody notices which half is fiction."""
    used = {rule.kind for rule in CHANGE_CLASSIFICATION.values()}
    used |= {rule.kind for rule in PRESENCE_RULES.values()}
    used |= {rule.kind for pair in OPTIONAL_RECORD_RULES.values() for rule in pair}
    used |= {narrowed for rule in CHANGE_CLASSIFICATION.values() for _, narrowed in rule.refine}

    assert used == set(ChangeKind)


@pytest.mark.unit
@pytest.mark.requirement("DATA-29")
def test_the_five_status_dimensions_are_five_kinds_and_not_one() -> None:
    """DATA-29's whole content is that these are independent; one kind would re-collapse them."""
    kinds = {rule_for(StatusDimensions, name).kind for name in StatusDimensions.model_fields}

    assert len(kinds) == len(StatusDimensions.model_fields) == 5


# -- value refinement -----------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.requirement("DATA-26")
def test_a_retirement_is_a_changed_record_and_names_itself() -> None:
    """`RetireElement` leaves the element in place, so a retirement is never a removal."""
    rule = rule_for(Element, "lifecycle_state")

    assert rule.resolve("retired") is ChangeKind.ELEMENT_RETIRED
    assert rule.resolve("active") is ChangeKind.ELEMENT_REACTIVATED
    assert rule.resolve("replaced") is ChangeKind.ELEMENT_REPLACED
    assert ChangeKind.ELEMENT_RETIRED not in {rule.kind for rule in PRESENCE_RULES.values()}


@pytest.mark.unit
@pytest.mark.requirement("DATA-26")
def test_only_lifecycle_state_may_narrow_its_kind_by_value() -> None:
    """A table of per-value branches would be code with extra steps, and untestable as a table."""
    refining = {key for key, rule in CHANGE_CLASSIFICATION.items() if rule.refine}

    assert refining == {(Element, "lifecycle_state")}


# -- the import-time registry check refuses a known-bad table --------------------------------------


@pytest.mark.unit
@pytest.mark.requirement("DATA-26")
def test_the_registry_check_refuses_a_rule_for_a_field_that_does_not_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Proves the guard catches a known-bad input, not only that today's table is clean."""
    broken: dict[tuple[type[BaseModel], str], ChangeRule] = dict(CHANGE_CLASSIFICATION)
    broken[(Element, "colour")] = ChangeRule(
        kind=ChangeKind.FIELD_MODIFIED, nature=ChangeNature.CANONICAL_SEMANTIC
    )
    monkeypatch.setattr("architecture_toolkit.changes.classification.CHANGE_CLASSIFICATION", broken)

    with pytest.raises(ClassificationError, match="no field 'colour'"):
        _check_registry()


@pytest.mark.unit
@pytest.mark.requirement("DATA-26")
def test_the_registry_check_refuses_a_value_refinement_on_any_other_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    widened: dict[tuple[type[BaseModel], str], Any] = dict(CHANGE_CLASSIFICATION)
    widened[(Element, "description")] = ChangeRule(
        kind=ChangeKind.FIELD_MODIFIED,
        nature=ChangeNature.CANONICAL_SEMANTIC,
        refine=(("anything", ChangeKind.ELEMENT_RENAMED),),
    )
    monkeypatch.setattr(
        "architecture_toolkit.changes.classification.CHANGE_CLASSIFICATION", widened
    )

    with pytest.raises(ClassificationError, match="value refinement"):
        _check_registry()


@pytest.mark.unit
@pytest.mark.requirement("DATA-26")
def test_the_narrative_natures_and_the_never_emitted_kinds_are_disjoint_concerns() -> None:
    """One axis is about reporting, the other about whether a field change exists at all."""
    assert NARRATIVE_NATURES < set(ChangeNature)
    assert NEVER_EMITTED < set(ChangeKind)
    assert ChangeKind.FIELD_MODIFIED not in NEVER_EMITTED


@pytest.mark.unit
@pytest.mark.requirement("DATA-26")
def test_every_optional_nested_record_says_what_its_arrival_means() -> None:
    """An element acquiring a detail is one fact, not eight field changes.

    Total by reflection rather than by list, so a second optional nested record added by a later
    wave has to be decided about instead of quietly descending.
    """
    optional_records = {
        (cls, name)
        for cls, name in classified_fields(Model)
        if type(None) in get_args(cls.model_fields[name].annotation)
        and _models_in(cls.model_fields[name].annotation)
    }

    assert optional_records == set(OPTIONAL_RECORD_RULES)
    assert optional_record_rule_for(Element, "detail", arrived=True).kind is ChangeKind.DETAIL_ADDED
    assert (
        optional_record_rule_for(Element, "detail", arrived=False).kind is ChangeKind.DETAIL_REMOVED
    )

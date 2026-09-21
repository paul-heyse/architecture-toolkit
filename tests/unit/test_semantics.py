"""Canonical semantic identity (CORE-21, DATA-27).

Two things are proven here that the contracts single out: the digest ignores presentation and
semantically unordered order, and it preserves ordered sequences. The presentation half is
completed by `tests/property/test_authoring_properties.py` once the YAML adapter exists; this
module covers everything that can be proven on validated records alone.
"""

import json
import re
from typing import Annotated, Any, Literal, get_args, get_origin

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from pydantic import BaseModel

from architecture_toolkit.domain.commands import (
    AddRelationship,
    ChangeSet,
    RemoveRelationship,
    RenameElement,
    build_candidate,
)
from architecture_toolkit.domain.details import DataSchemaDetail, SchemaField
from architecture_toolkit.domain.identifiers import DIGEST_PATTERN
from architecture_toolkit.domain.model import Element, Model, Relationship
from architecture_toolkit.domain.semantics import (
    COLLECTION_ORDER,
    EXCLUDED_FIELDS,
    MODEL_COLLECTIONS,
    PREIMAGE_PREFIX,
    SEMANTIC_HASH_VERSION,
    CollectionPolicy,
    model_digest,
    normalize_record,
    record_digest,
    semantic_delta,
    stamp_digests,
)
from tests.strategies.commands import rename_elements
from tests.strategies.relations import full_models

# The digest of `examples/minimal/model.yaml` under hash version 1. A change here means either
# the algorithm changed — a DATA-56 migration and a version bump, never a silent edit — or a
# record gained a field, which changes what the preimage covers and must be stated in the commit
# that does it.
#
# It has moved twice. At W3, when `Element` and `Relationship` gained DATA-13's `extensions`. And
# at W7a, when `Model` gained `views`: the example declares none, but the preimage now covers an
# empty `views` collection where it previously covered nothing, which is a different preimage.
# Nothing has been published in either case, so no migration was owed and `SEMANTIC_HASH_VERSION`
# stays at 1 — the first release is what makes a digest durable, and there has not been one.
EXAMPLE_DIGEST = "sha256:ec02ef56ca041dc37d87beaea52948249a23925ca7f2185f1b9b551c1c8b3d71"


def _model(source: dict[str, Any]) -> Model:
    return Model.model_validate_json(json.dumps(source))


# -- the policy table is total ------------------------------------------------------------------


def _contains_tuple(annotation: object) -> bool:
    if annotation is tuple or get_origin(annotation) is tuple:
        return True
    return any(_contains_tuple(argument) for argument in get_args(annotation))


def _models_in(annotation: object) -> list[type[BaseModel]]:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    found: list[type[BaseModel]] = []
    for argument in get_args(annotation):
        found.extend(_models_in(argument))
    return found


def tuple_fields(root: type[BaseModel]) -> set[tuple[type[BaseModel], str]]:
    """Every `(class, field)` whose annotation contains a tuple, reachable from `root`."""
    found: set[tuple[type[BaseModel], str]] = set()
    seen: set[type[BaseModel]] = set()

    def visit(cls: type[BaseModel]) -> None:
        if cls in seen:
            return
        seen.add(cls)
        for name, field in cls.model_fields.items():
            if _contains_tuple(field.annotation):
                found.add((cls, name))
            for nested in _models_in(field.annotation):
                visit(nested)

    visit(root)
    return found


@pytest.mark.unit
@pytest.mark.requirement("CORE-21", "DATA-27")
def test_every_collection_reachable_from_the_model_declares_its_order() -> None:
    """The W2 plan's risk note: order is decided per field, not globally. This makes it so."""
    assert tuple_fields(Model) == set(COLLECTION_ORDER)


@pytest.mark.unit
@pytest.mark.requirement("CORE-21", "DATA-27")
def test_model_collections_names_every_top_level_collection_and_no_other() -> None:
    """The half of `MODEL_COLLECTIONS` that is hand-written, which nothing checked.

    Its *keys* come from `COLLECTION_ORDER`, so a wrong key is an import-time `KeyError`. Its
    *names* are a literal tuple, so a collection added to `Model` and to `COLLECTION_ORDER` and
    forgotten here failed nothing at all — and `MODEL_COLLECTIONS` is what `stamp_digests`,
    `semantic_delta`, `PRESENCE_RULES` and the identity-delta recipe all iterate.

    `==` rather than `>=` on purpose: the subset direction is the one that already held.
    """
    declared = {name for cls, name in COLLECTION_ORDER if cls is Model}
    assert {name for name, _ in MODEL_COLLECTIONS} == declared


@pytest.mark.unit
@pytest.mark.requirement("DATA-27")
def test_ordinal_policies_name_real_fields() -> None:
    for (cls, name), order in COLLECTION_ORDER.items():
        if order.policy is CollectionPolicy.EXCLUDED:
            continue
        items = _models_in(cls.model_fields[name].annotation)
        if not items:
            assert order.key == (), f"{cls.__name__}.{name} holds scalars but names a key"
            continue
        for item in items:
            for key in order.key:
                assert key in item.model_fields, f"{item.__name__} has no field {key!r}"
            if order.policy is CollectionPolicy.ORDERED_BY_ORDINAL:
                assert order.key[0] == "ordinal"
                assert "ordinal" in item.model_fields


# -- the digest itself --------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.requirement("CORE-21", "DATA-27")
def test_digests_are_versioned_sha256_values(minimal_model_source: dict[str, Any]) -> None:
    model = _model(minimal_model_source)
    assert re.fullmatch(DIGEST_PATTERN, model_digest(model))
    assert re.fullmatch(DIGEST_PATTERN, record_digest(model.elements[0]))
    assert SEMANTIC_HASH_VERSION in PREIMAGE_PREFIX


@pytest.mark.unit
@pytest.mark.requirement("DATA-27")
def test_known_vector_for_the_example_fixture(minimal_model_source: dict[str, Any]) -> None:
    assert model_digest(_model(minimal_model_source)) == EXAMPLE_DIGEST


@pytest.mark.unit
@pytest.mark.requirement("CORE-21")
def test_stored_digests_never_enter_the_preimage(minimal_model_source: dict[str, Any]) -> None:
    model = _model(minimal_model_source)
    stamped = stamp_digests(model)

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value) | {key for inner in value.values() for key in keys(inner)}
        if isinstance(value, list):
            return {key for inner in value for key in keys(inner)}
        return set()

    assert not keys(normalize_record(stamped)) & EXCLUDED_FIELDS
    for before, after in zip(model.elements, stamped.elements, strict=True):
        assert after.content_hash is not None
        assert record_digest(before) == record_digest(after) == after.content_hash


@pytest.mark.property
@pytest.mark.slow
@pytest.mark.requirement("CORE-21", "DATA-27", "CORE-45")
@given(full_models())
def test_stamping_is_idempotent_and_digest_invariant(model: Model) -> None:
    stamped = stamp_digests(model)
    assert stamp_digests(stamped) == stamped
    assert model_digest(stamped) == model_digest(model)
    assert semantic_delta(model, stamped).is_empty
    assert all(element.content_hash for element in stamped.elements)
    assert all(
        element.detail.content_hash for element in stamped.elements if element.detail is not None
    )


# -- what is excluded and what is canonicalized ---------------------------------------------------


@pytest.mark.unit
@pytest.mark.requirement("CORE-21")
def test_aliases_are_not_semantic_identity() -> None:
    plain = Element(element_id="a-1", model_id="m-1", kind_id="software.system", name="A")
    aliased = plain.model_validate(dict(plain) | {"aliases": ("The A", "System A")})
    renamed = plain.model_validate(dict(plain) | {"name": "B"})
    assert record_digest(plain) == record_digest(aliased)
    assert record_digest(plain) != record_digest(renamed)


@pytest.mark.property
@pytest.mark.slow
@pytest.mark.requirement("CORE-21", "DATA-27")
@given(full_models())
def test_reordering_unordered_collections_leaves_the_digest_unchanged(model: Model) -> None:
    reordered = dict(model)
    for name in ("elements", "relationships", "interactions", "references"):
        items = list(reversed(getattr(model, name)))
        # Reversed, then rotated by one: two reorderings that differ from each other and from
        # the authored order whenever the collection has more than two members.
        reordered[name] = tuple(items[1:] + items[:1])
    assert model_digest(Model.model_validate(reordered)) == model_digest(model)


@pytest.mark.unit
@pytest.mark.requirement("DATA-27")
def test_ordinal_is_the_order_and_position_is_presentation() -> None:
    """DATA-27: preserve order for ordered sequences. The ordinal carries it, not the tuple."""
    first = SchemaField(field_id="a", field_name="a", data_type="string", ordinal=0)
    second = SchemaField(field_id="b", field_name="b", data_type="string", ordinal=1)
    authored = DataSchemaDetail(element_id="s-1", fields=(first, second))
    repositioned = DataSchemaDetail(element_id="s-1", fields=(second, first))
    assert record_digest(authored) == record_digest(repositioned)

    swapped = DataSchemaDetail(
        element_id="s-1",
        fields=(
            first.model_validate(dict(first) | {"ordinal": 1}),
            second.model_validate(dict(second) | {"ordinal": 0}),
        ),
    )
    assert record_digest(authored) != record_digest(swapped)


# -- the record-level delta ---------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.requirement("DATA-27", "CORE-20")
def test_a_rename_is_reported_as_a_change_to_one_identity(
    minimal_model_source: dict[str, Any],
) -> None:
    baseline = _model(minimal_model_source)
    candidate = build_candidate(
        baseline,
        ChangeSet(
            change_set_id="cs-1",
            model_id=baseline.model_id,
            commands=(RenameElement(element_id="process-1", new_name="Assess request"),),
        ),
    )
    delta = semantic_delta(baseline, candidate)
    assert delta.base_digest != delta.candidate_digest
    assert delta.hash_algorithm_version == SEMANTIC_HASH_VERSION
    by_name = {collection.collection: collection for collection in delta.collections}
    assert by_name["elements"].changed == ("process-1",)
    assert by_name["elements"].added == by_name["elements"].removed == ()
    assert all(by_name[name].is_empty for name in by_name if name != "elements")


@pytest.mark.unit
@pytest.mark.requirement("DATA-27")
def test_the_delta_reports_added_and_removed_identities(
    minimal_model_source: dict[str, Any],
) -> None:
    baseline = _model(minimal_model_source)
    added = Relationship(
        relationship_id="rel-9",
        model_id=baseline.model_id,
        relationship_type_id="supports",
        source_element_id="component-1",
        target_element_id="capability-1",
    )
    candidate = build_candidate(
        baseline,
        ChangeSet(
            change_set_id="cs-2",
            model_id=baseline.model_id,
            commands=(
                RemoveRelationship(relationship_id="rel-1"),
                AddRelationship(relationship=added),
            ),
        ),
    )
    relations = next(
        collection
        for collection in semantic_delta(baseline, candidate).collections
        if collection.collection == "relationships"
    )
    assert relations.added == ("rel-9",)
    assert relations.removed == ("rel-1",)
    assert relations.changed == ()


@pytest.mark.property
@pytest.mark.slow
@pytest.mark.requirement("CORE-21", "DATA-27")
@settings(max_examples=60, deadline=None)
@given(data=st.data())
def test_a_real_change_always_changes_the_digest(data: st.DataObject) -> None:
    baseline = data.draw(full_models())
    command = data.draw(rename_elements(baseline))
    current = next(e for e in baseline.elements if e.element_id == command.element_id)
    assume(current.name != command.new_name)
    candidate = build_candidate(
        baseline,
        ChangeSet(change_set_id="cs-p", model_id=baseline.model_id, commands=(command,)),
    )
    assert model_digest(candidate) != model_digest(baseline)


# -- the reflection helpers are themselves exercised ----------------------------------------------


@pytest.mark.unit
def test_tuple_field_discovery_sees_through_annotated_and_optional() -> None:
    class Inner(BaseModel):
        items: tuple[int, ...] = ()

    class Outer(BaseModel):
        kind: Literal["outer"] = "outer"
        inner: Annotated[Inner, "meta"] | None = None
        pairs: tuple[tuple[str, str], ...] = ()

    assert tuple_fields(Outer) == {(Outer, "pairs"), (Inner, "items")}

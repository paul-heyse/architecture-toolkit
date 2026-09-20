"""The controlled kind and relationship-type registries (DATA-04, DATA-05, DATA-06)."""

import pytest
from pydantic import ValidationError

from architecture_toolkit.domain.registry import (
    BASELINE_PROFILE,
    CanonicalDirection,
    DetailFamily,
    KindDefinition,
    KindLayer,
    Profile,
    RelationshipTypeDefinition,
    with_overrides,
)

NOTION_KINDS = frozenset(
    {
        "business.capability",
        "business.process",
        "organization.role",
        "software.system",
        "software.component",
        "software.interface",
        "information.object",
        "information.schema",
        "technology.deployment",
        "motivation.requirement",
    }
)

# `ARCH-TOOL-DATA-001` §2B: six types that must stay distinct.
NOTION_RELATIONSHIP_TYPES = frozenset(
    {"contains", "supports", "realizes", "exchanges_data_with", "depends_on", "justifies"}
)


@pytest.mark.unit
@pytest.mark.requirement("DATA-04")
def test_baseline_carries_the_ten_specified_kinds() -> None:
    """The prior `Kind` enum had seven and silently dropped three the specification names."""
    assert NOTION_KINDS <= set(BASELINE_PROFILE.kinds_by_id)


@pytest.mark.unit
@pytest.mark.requirement("DATA-05")
def test_baseline_carries_the_six_types_that_must_stay_distinct() -> None:
    """Collapsing these into generic connections is what `ARCH-TOOL-DATA-001` §2B forbids."""
    assert NOTION_RELATIONSHIP_TYPES <= set(BASELINE_PROFILE.relationship_types_by_id)


@pytest.mark.unit
@pytest.mark.requirement("DATA-05")
def test_every_relationship_type_declares_all_eight_properties() -> None:
    """The eighth, `validation_rule_ids`, is the one most easily dropped.

    `cardinality` is legitimately optional — §2B says "where applicable" — so it is checked for
    presence of the field rather than a value.
    """
    required = {
        "relationship_type_id",
        "permitted_source_kinds",
        "permitted_target_kinds",
        "canonical_direction",
        "inverse_display_label",
        "cardinality",
        "traversal",
        "validation_rule_ids",
    }
    assert required <= set(RelationshipTypeDefinition.model_fields)
    for entry in BASELINE_PROFILE.relationship_types:
        assert entry.permitted_source_kinds, entry.relationship_type_id
        assert entry.permitted_target_kinds, entry.relationship_type_id
        assert entry.inverse_display_label, entry.relationship_type_id
        assert entry.validation_rule_ids, entry.relationship_type_id


@pytest.mark.unit
@pytest.mark.requirement("DATA-05")
def test_no_permitted_endpoint_kind_dangles() -> None:
    """A registry naming a kind that does not exist cannot validate anything."""
    known = set(BASELINE_PROFILE.kinds_by_id)
    dangling = {
        (entry.relationship_type_id, kind)
        for entry in BASELINE_PROFILE.relationship_types
        for kind in entry.permitted_source_kinds | entry.permitted_target_kinds
        if kind not in known
    }
    assert not dangling


@pytest.mark.unit
@pytest.mark.requirement("DATA-06")
def test_direction_is_stored_once_so_a_duplicate_inverse_is_unrepresentable() -> None:
    """DATA-06 is structural here rather than validated.

    There is one `canonical_direction` field and one `inverse_display_label`. There is no second
    row to store `supported_by` in, so "derive the inverse view, never persist it" is a property
    of the shape rather than a rule that could be forgotten.
    """
    assert "inverse_display_label" in RelationshipTypeDefinition.model_fields
    supports = BASELINE_PROFILE.relationship_types_by_id["supports"]
    assert supports.canonical_direction is CanonicalDirection.SOURCE_TO_TARGET
    assert supports.inverse_display_label == "is supported by"
    assert "supported_by" not in BASELINE_PROFILE.relationship_types_by_id
    symmetric = BASELINE_PROFILE.relationship_types_by_id["exchanges_data_with"]
    assert symmetric.canonical_direction is CanonicalDirection.SYMMETRIC


@pytest.mark.unit
@pytest.mark.requirement("DATA-04")
def test_a_kind_id_must_sit_in_its_declared_layer() -> None:
    with pytest.raises(ValidationError, match="does not sit in declared layer"):
        KindDefinition(
            kind_id="software.system",
            layer=KindLayer.BUSINESS,
            display_label="Wrong",
            description="Layer disagrees with the qualified kind.",
        )


@pytest.mark.unit
@pytest.mark.requirement("DATA-04", "DATA-05")
def test_duplicate_identity_in_a_profile_is_rejected() -> None:
    kind = BASELINE_PROFILE.kinds[0]
    with pytest.raises(ValidationError, match="duplicate kind identity"):
        Profile(
            profile_id="broken",
            profile_version="1.0.0",
            kinds=(kind, kind),
            relationship_types=(),
        )


@pytest.mark.unit
@pytest.mark.requirement("DATA-04", "DATA-05")
def test_a_profile_is_overridden_without_a_loader() -> None:
    """The whole override mechanism: a pure function over a value. No file, no resolution order."""
    added = KindDefinition(
        kind_id="business.product",
        layer=KindLayer.BUSINESS,
        display_label="Product",
        description="A sellable offering; not part of the generic core.",
    )
    derived = with_overrides(
        BASELINE_PROFILE,
        profile_id="consumer",
        profile_version="1.0.0",
        kinds=(added,),
        removed_kind_ids=frozenset({"technology.deployment"}),
    )
    assert "business.product" in derived.kinds_by_id
    assert "technology.deployment" not in derived.kinds_by_id
    # The base is a frozen value and must be untouched by deriving from it.
    assert "technology.deployment" in BASELINE_PROFILE.kinds_by_id
    assert "business.product" not in BASELINE_PROFILE.kinds_by_id


@pytest.mark.unit
@pytest.mark.requirement("DATA-04")
def test_override_output_is_deterministic() -> None:
    """Two equivalent overlays must produce byte-identical schemas and digests downstream."""
    kinds = (
        KindDefinition(
            kind_id="business.product", layer=KindLayer.BUSINESS, display_label="P", description="."
        ),
        KindDefinition(
            kind_id="business.market", layer=KindLayer.BUSINESS, display_label="M", description="."
        ),
    )
    forward = with_overrides(BASELINE_PROFILE, profile_id="c", profile_version="1.0.0", kinds=kinds)
    reverse = with_overrides(
        BASELINE_PROFILE, profile_id="c", profile_version="1.0.0", kinds=tuple(reversed(kinds))
    )
    assert forward == reverse
    assert [k.kind_id for k in forward.kinds] == sorted(k.kind_id for k in forward.kinds)


@pytest.mark.unit
@pytest.mark.requirement("DATA-07")
def test_detail_families_are_the_six_the_contract_names() -> None:
    """DATA-07 names six: interface, deployment, data-schema, behavior, requirement and notation."""
    assert {family.value for family in DetailFamily} == {
        "interface",
        "deployment",
        "data_schema",
        "behavior",
        "requirement",
        "notation_binding",
    }


@pytest.mark.unit
@pytest.mark.requirement("CORE-08")
def test_a_profile_is_hashable_despite_the_cached_index() -> None:
    """`cached_property` writes to `__dict__`; Pydantic hashes field values, so the guard holds."""
    assert BASELINE_PROFILE.kinds_by_id is BASELINE_PROFILE.kinds_by_id
    assert isinstance(hash(BASELINE_PROFILE), int)

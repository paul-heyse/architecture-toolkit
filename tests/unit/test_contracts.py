"""Generated JSON Schema contracts (CORE-12, CORE-13).

`scripts/check_schema.py` checks the committed files. These check the generator, so the two are
independent: a defect that made the generator and the checker wrong in the same way would still
be caught here.
"""

import json
import re
from typing import get_args

import pytest
from jsonschema import Draft202012Validator
from pydantic import BaseModel

from architecture_toolkit.contracts import SCHEMA_FAMILIES, emit, emittable
from architecture_toolkit.domain.model import Model
from architecture_toolkit.domain.semantics import MODEL_COLLECTIONS


@pytest.mark.unit
@pytest.mark.requirement("CORE-12")
def test_every_family_is_versioned_and_declares_its_requirements() -> None:
    assert len(SCHEMA_FAMILIES) == 8
    for family in SCHEMA_FAMILIES:
        assert re.fullmatch(r"urn:architecture-toolkit:[a-z-]+:v\d+", family.schema_id)
        assert family.requirements
        assert family.path.startswith("schemas/")


@pytest.mark.unit
@pytest.mark.requirement("CORE-12", "DATA-03")
def test_every_top_level_record_type_is_a_root_a_consumer_can_reference() -> None:
    """`element-detail` lists its roots by hand, and nothing related that list to `Model`.

    `authoring-model` would still cover a forgotten record, because Pydantic emits every nested
    class into `$defs` — so the omission is invisible in the one place a reader would look. What
    breaks is the thing this family exists for: its description says the shapes are "emitted
    separately so a consumer can reference one variant without pulling in the whole model", and a
    record that is not a root cannot be referenced that way.

    Top-level collection item types only. A nested value object like `StatusDimensions` is
    legitimately `$defs`-only; a record with its own identity is not.
    """
    detail = next(f for f in SCHEMA_FAMILIES if f.family_id == "element-detail")
    items = {
        argument
        for name in {name for name, _ in MODEL_COLLECTIONS}
        for argument in get_args(Model.model_fields[name].annotation)
        if isinstance(argument, type) and issubclass(argument, BaseModel)
    }

    assert items, "no collection item types were found; the derivation stopped working"
    assert items <= set(detail.roots), sorted(
        record.__name__ for record in items - set(detail.roots)
    )


@pytest.mark.unit
@pytest.mark.requirement("CORE-12")
def test_a_deferred_family_names_the_wave_that_unblocks_it() -> None:
    """Declared-but-empty is only honest if it says what it is waiting for."""
    for family in SCHEMA_FAMILIES:
        if family in emittable():
            assert family.deferred_to is None, family.family_id
            continue
        assert family.deferred_to, family.family_id
        assert family.blocked_on, family.family_id


@pytest.mark.unit
@pytest.mark.requirement("CORE-12")
@pytest.mark.parametrize("family_id", [f.family_id for f in emittable()])
def test_each_emitted_family_is_a_usable_schema_document(family_id: str) -> None:
    family = next(f for f in SCHEMA_FAMILIES if f.family_id == family_id)
    document = emit(family)
    Draft202012Validator.check_schema(document)
    assert document["$id"] == family.schema_id
    assert document["x-toolkit"]["family"] == family_id
    # A single-root family must be able to validate a document, not merely define types.
    if len(family.roots) == 1:
        assert "$ref" in document


@pytest.mark.unit
@pytest.mark.requirement("CORE-12")
def test_the_authoring_schema_rejects_an_obviously_invalid_document() -> None:
    """The failure mode this caught during the wave.

    `models_json_schema` returns only `$defs`. Emitted as-is, the authoring schema was a bundle
    of definitions with no root, and therefore accepted any input at all while looking complete.
    """
    schema = emit(next(f for f in SCHEMA_FAMILIES if f.family_id == "authoring-model"))
    errors = list(
        Draft202012Validator(schema).iter_errors(
            {"model_id": "not a valid id", "elements": "wrong type"}
        )
    )
    assert errors


@pytest.mark.unit
@pytest.mark.requirement("CORE-12", "CORE-04")
def test_discriminated_unions_survive_into_the_generated_contract() -> None:
    """CORE-12 asks for discriminators in the machine-facing contract, not only at runtime."""
    rendered = json.dumps(emit(next(f for f in SCHEMA_FAMILIES if f.family_id == "change-set")))
    assert '"propertyName": "command"' in rendered
    detail = json.dumps(emit(next(f for f in SCHEMA_FAMILIES if f.family_id == "element-detail")))
    assert '"propertyName": "detail_family"' in detail


@pytest.mark.unit
@pytest.mark.requirement("CORE-13")
@pytest.mark.parametrize("family_id", [f.family_id for f in emittable()])
def test_validation_and_serialization_modes_do_not_differ(family_id: str) -> None:
    """CORE-13, in its strongest available form.

    The two modes diverge exactly where a computed field exists. The domain declares none, so
    they must be identical — and adding one fails this until the difference is declared on the
    family and explained.
    """
    family = next(f for f in SCHEMA_FAMILIES if f.family_id == family_id)
    assert not family.computed_fields
    assert emit(family, mode="validation") == emit(family, mode="serialization")


@pytest.mark.unit
@pytest.mark.requirement("CORE-12")
def test_generation_is_deterministic() -> None:
    """A committed snapshot is only checkable if regenerating produces identical bytes."""
    family = next(f for f in SCHEMA_FAMILIES if f.family_id == "profile")
    assert json.dumps(emit(family), indent=2) == json.dumps(emit(family), indent=2)


@pytest.mark.unit
@pytest.mark.requirement("CORE-12")
def test_no_definition_name_is_module_mangled() -> None:
    """Two same-named models in different modules produce `$defs` keys like `pkg__a__Detail`.

    Those keys move when a module is renamed, so a committed snapshot would drift for a reason
    that has nothing to do with the contract. Keeping record class names globally unique avoids
    it, and this is what notices if that stops being true.
    """
    for family in emittable():
        mangled = [key for key in emit(family)["$defs"] if "__" in key]
        assert not mangled, f"{family.family_id}: {mangled}"

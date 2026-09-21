"""Both pinned standards schema sets, through one resolver (CORE-40..CORE-42).

A resolver proven against a single standard is a special case. The BPMN set resolves everything by
sibling filename; the ArchiMate set does not, and that difference is what makes the pinned resolver
a general mechanism rather than a BPMN convenience.

These load real vendored files that `scripts/bootstrap_tools.py` fetches into gitignored
`.tools/`, so they skip rather than fail when the vendor step has not run — a missing vendor
artifact is an environment fact, not a defect, and CI bootstraps before pytest.
"""

import json
from pathlib import Path

import pytest
from lxml import etree

from architecture_toolkit.projections.schemas import SCHEMA_SETS, pinned_set
from architecture_toolkit.projections.xml import (
    NAMESPACES,
    PinnedSchemas,
    SchemaValidator,
    instance_parser,
    maker,
)

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / ".tools"
LOCK = json.loads((ROOT / "tools.lock.json").read_text())


def require(name: str) -> PinnedSchemas:
    schemas = pinned_set(name, root=TOOLS, lock=LOCK)
    missing = sorted(file for file, path in schemas.files.items() if not path.is_file())
    if missing:
        pytest.skip(f"vendored schemas absent: {missing}; run scripts/bootstrap_tools.py")
    return schemas


def named_model() -> etree._Element:
    """A minimal ArchiMate exchange model: one element, both `xml:lang` and `xsi:type` used."""
    e = maker("archimate", nsmap=("xsi", "xml"))
    title = e.name("Synthetic")
    title.set(etree.QName(NAMESPACES["xml"], "lang"), "en")
    element = e.element(e.name("Billing"), identifier="id-e1")
    # `xsi:type` takes a QName, so the value carries the prefix the root declares. An unprefixed
    # `"ApplicationComponent"` resolves against the *default* namespace, which is none here — and
    # the schema then reports both "not resolved to a type definition" and "the type definition is
    # abstract", because `element` without a concrete subtype is abstract. Worth the comment: it is
    # the first thing a generator gets wrong, and the error names the symptom rather than the cause.
    element.set(etree.QName(NAMESPACES["xsi"], "type"), "archimate:ApplicationComponent")
    return e.model(title, e.elements(element), identifier="id-m1")


@pytest.mark.interop
@pytest.mark.requirement("CORE-41")
@pytest.mark.parametrize("name", sorted(SCHEMA_SETS))
def test_every_declared_schema_set_loads_through_the_pinned_resolver(name: str) -> None:
    schemas = require(name)
    entry = SCHEMA_SETS[name].entry
    assert entry in schemas.closure(entry)
    assert SchemaValidator.load(schemas, entry).source_id == entry


@pytest.mark.interop
@pytest.mark.requirement("CORE-40", "CORE-41")
def test_the_archimate_schema_does_not_build_without_the_pinned_resolver() -> None:
    """The negative that justifies CORE-41, on a real standard rather than a contrived one.

    `archimate3_Model.xsd` imports `http://www.w3.org/2001/xml.xsd` by absolute URL and then uses
    `xml:lang`. With `no_network=True` and no resolver, libxml2 cannot fetch it, the attribute
    group is unresolvable, and the schema fails to build. Asserted so that a change quietly making
    that import resolvable over the network would be visible rather than convenient.
    """
    schemas = require("archimate")
    payload = schemas.read("archimate3_Model.xsd")
    with pytest.raises(etree.XMLSchemaParseError, match="lang"):
        etree.XMLSchema(etree.fromstring(payload, instance_parser()))


@pytest.mark.interop
@pytest.mark.requirement("CORE-41", "CORE-42")
def test_a_minimal_exchange_model_validates_against_the_pinned_archimate_schema() -> None:
    """The positive half, so the test above cannot pass by the schema being unusable."""
    schemas = require("archimate")
    validator = SchemaValidator.load(schemas, "archimate3_Model.xsd")
    assert validator.validate(named_model()) == ()


@pytest.mark.interop
@pytest.mark.requirement("CORE-42")
def test_an_exchange_model_missing_its_identifier_is_reported_not_raised() -> None:
    schemas = require("archimate")
    validator = SchemaValidator.load(schemas, "archimate3_Model.xsd")

    e = maker("archimate", nsmap=("xml",))
    title = e.name("Synthetic")
    title.set(etree.QName(NAMESPACES["xml"], "lang"), "en")
    found = validator.validate(e.model(title))

    assert found
    assert found[0].code == "CORE.SCHEMA.NOTATION_DOCUMENT_INVALID"
    assert "identifier" in found[0].message


@pytest.mark.interop
@pytest.mark.requirement("CORE-41")
def test_the_two_sets_reach_their_members_by_different_routes() -> None:
    """Why two sets are needed to call the resolver general.

    BPMN resolves every member by sibling filename. ArchiMate reaches outside its own directory
    for `xml.xsd`, by absolute URL, under a spelling the schema author chose — so the alias table
    is exercised by one set and not the other.
    """
    assert not SCHEMA_SETS["bpmn"].aliases
    aliases = SCHEMA_SETS["archimate"].aliases
    assert set(aliases.values()) == {"xml.xsd"}
    assert {url.split("://", 1)[0] for url in aliases} == {"http", "https"}, (
        "the W3C serves xml.xsd under both schemes and a schema author may have written either"
    )
    assert "xml.xsd" in require("archimate").files

"""The secure, structured, canonical XML layer (CORE-39..CORE-43).

The schema set used here is the BPMN 2.0.2 one `tools.lock.json` already pins. It is fetched by
`scripts/bootstrap_tools.py` into gitignored `.tools/`, so these tests skip rather than fail when
the vendor step has not run: on a fresh checkout a missing vendor artifact is an environment fact,
not a defect.

**A skip is not free, and this file is why.** CI ran `pytest` twelve steps before the bootstrap, so
every test below skipped on both platforms for two commits while the build stayed green. The
workflow now vendors first, and `scripts/check_evidence.py` refuses a run in which any
requirement-marked test skipped — because the earlier version of this paragraph asserted the
ordering as fact and was wrong, and nothing noticed.
"""

import hashlib
import json
from pathlib import Path

import pytest
from lxml import etree

from architecture_toolkit.projections.xml import (
    C14N_VERSION,
    NAMESPACES,
    PinnedSchemas,
    SchemaValidator,
    UnpinnedSchemaError,
    instance_parser,
    maker,
    qname,
    xml_digests,
)

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / ".tools"
LOCK = ROOT / "tools.lock.json"
BPMN = NAMESPACES["bpmn"]


def bpmn_schemas() -> PinnedSchemas:
    entries = [
        item for item in json.loads(LOCK.read_text())["artifacts"] if item["id"].startswith("bpmn-")
    ]
    files = {Path(item["path"]).name: (TOOLS / item["path"]).resolve() for item in entries}
    digests = {Path(item["path"]).name: item["sha256"] for item in entries}
    return PinnedSchemas(files=files, digests=digests)


@pytest.fixture
def pinned() -> PinnedSchemas:
    schemas = bpmn_schemas()
    missing = [name for name, path in schemas.files.items() if not path.is_file()]
    if missing:
        pytest.skip(f"vendored schemas absent: {missing}; run scripts/bootstrap_tools.py")
    return schemas


def process(*, well_formed: bool = True) -> etree._Element:
    """A minimal BPMN definitions element, valid or not, built structurally."""
    e = maker("bpmn")
    child = e.startEvent(id="s1") if well_formed else e.nonsense(id="n1")
    return e.definitions(e.process(child, id="p1"), id="d1", targetNamespace="urn:synthetic")


# -- structure (CORE-39) --------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.requirement("CORE-39")
def test_elements_are_built_structurally_from_one_namespace_registry() -> None:
    """No string is interpolated, so there is nothing to escape wrongly."""
    assert str(qname("bpmn", "task")) == f"{{{BPMN}}}task"
    element = maker("bpmn", nsmap=("bpmndi",)).definitions(id="d1")
    assert element.tag == f"{{{BPMN}}}definitions"
    assert element.nsmap == {"bpmn": BPMN, "bpmndi": NAMESPACES["bpmndi"]}
    with pytest.raises(KeyError):
        qname("no-such-prefix", "task")


# -- security (CORE-40) ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.requirement("CORE-40")
def test_an_external_entity_is_never_expanded() -> None:
    """The classic XXE payload, against the parser instance documents actually go through."""
    payload = b'<!DOCTYPE d [<!ENTITY x SYSTEM "file:///etc/passwd">]><d>&x;</d>'
    document = etree.fromstring(payload, instance_parser())
    assert document.text is None, "the entity was expanded; resolve_entities is not off"


@pytest.mark.unit
@pytest.mark.requirement("CORE-40")
def test_malformed_input_is_refused_rather_than_recovered() -> None:
    """`recover=False`, which CORE-40 names and the ast-grep rule did not cover until W7a.

    A recovering parser returns a tree for unbalanced input, so a generator defect would be
    validated, digested and published as whatever libxml2 guessed.
    """
    with pytest.raises(etree.XMLSyntaxError):
        etree.fromstring(b"<a><b></a>", instance_parser())


# -- the pinned resolver (CORE-41) ----------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.requirement("CORE-41")
def test_a_schema_set_loads_through_the_resolver_and_validates(pinned: PinnedSchemas) -> None:
    validator = SchemaValidator.load(pinned, "BPMN20.xsd")
    assert validator.validate(process()) == ()


@pytest.mark.unit
@pytest.mark.requirement("CORE-41")
def test_a_reference_outside_the_pinned_set_is_refused(
    pinned: PinnedSchemas, tmp_path: Path
) -> None:
    """The whole reason a resolver exists rather than a trust in `no_network`.

    Measured on lxml 6.1.3, twice: an unreachable remote `xsd:import` is a *silent warning* when
    the imported namespace is unused, and a *fatal parse error* when it is used. Neither says
    "this was not the schema we pinned".

    Measured a third time, and it is why the closure walk exists: an exception raised inside a
    resolver during `XMLSchema()` construction is converted by lxml into an
    `XMLSchemaParseError` reading "Failed to parse the XML resource <url>". Loud, but
    indistinguishable from a network outage — so the reference set is walked before the schema is
    built, and the refusal names the referring file.
    """
    remote = (
        b'<?xml version="1.0"?>'
        b'<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema">'
        b'<xsd:import namespace="urn:e" schemaLocation="https://example.invalid/e.xsd"/>'
        b"</xsd:schema>"
    )
    unpinned = tmp_path / "unpinned.xsd"
    unpinned.write_bytes(remote)
    schemas = PinnedSchemas(
        files=dict(pinned.files) | {"unpinned.xsd": unpinned},
        digests=dict(pinned.digests) | {"unpinned.xsd": hashlib.sha256(remote).hexdigest()},
    )
    with pytest.raises(UnpinnedSchemaError, match="which is not pinned"):
        SchemaValidator.load(schemas, "unpinned.xsd")


@pytest.mark.unit
@pytest.mark.requirement("CORE-41")
def test_the_closure_is_the_whole_reachable_schema_set(pinned: PinnedSchemas) -> None:
    """BPMN20 reaches every other file in the set, through import, include and one more import."""
    assert pinned.closure("BPMN20.xsd") == (
        "BPMN20.xsd",
        "BPMNDI.xsd",
        "DC.xsd",
        "DI.xsd",
        "Semantic.xsd",
    )


@pytest.mark.unit
@pytest.mark.requirement("CORE-41")
def test_a_vendored_file_that_changed_is_refused(pinned: PinnedSchemas) -> None:
    """The checksum is re-read on every resolve, not trusted from bootstrap time."""
    tampered = PinnedSchemas(
        files=pinned.files,
        digests=dict(pinned.digests) | {"BPMN20.xsd": "0" * 64},
    )
    with pytest.raises(UnpinnedSchemaError, match="the vendored copy has changed"):
        SchemaValidator.load(tampered, "BPMN20.xsd")


@pytest.mark.unit
@pytest.mark.requirement("CORE-41")
def test_an_alias_maps_an_absolute_uri_onto_a_pinned_file(pinned: PinnedSchemas) -> None:
    """How a schema that imports by absolute URL is served without reaching the network."""
    schemas = PinnedSchemas(
        files=pinned.files,
        digests=pinned.digests,
        aliases={"https://example.org/elsewhere/Semantic.xsd": "Semantic.xsd"},
    )
    assert schemas.name_for("https://example.org/elsewhere/Semantic.xsd") == "Semantic.xsd"
    with pytest.raises(UnpinnedSchemaError):
        schemas.name_for("https://example.org/elsewhere/Other.xsd")


# -- diagnostics (CORE-42) ------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.requirement("CORE-42")
def test_schema_findings_become_diagnostics_with_the_xpath_that_located_them(
    pinned: PinnedSchemas,
) -> None:
    """lxml's `_LogEntry.path` is an XPath, which is what `field_path` means for generated XML."""
    validator = SchemaValidator.load(pinned, "BPMN20.xsd")
    found = validator.validate(process(well_formed=False), notation_object_id="Process_p1")

    assert found, "an invalid document produced no findings"
    finding = found[0]
    assert finding.code == "CORE.SCHEMA.NOTATION_DOCUMENT_INVALID"
    assert finding.claim.value == "schema_syntax"
    assert finding.field_path is not None
    assert finding.field_path.endswith("nonsense")
    assert finding.notation_object_id == "Process_p1"
    assert dict(finding.context)["domain"] == "SCHEMASV"


@pytest.mark.unit
@pytest.mark.requirement("CORE-42")
def test_an_invalid_document_is_reported_rather_than_raised(pinned: PinnedSchemas) -> None:
    """A caller must be able to see every problem, not the first one."""
    validator = SchemaValidator.load(pinned, "BPMN20.xsd")
    assert validator.validate(process(well_formed=False)) != ()
    assert validator.validate(process()) == ()


# -- digests (CORE-43) ----------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.requirement("CORE-43")
def test_pretty_printing_moves_the_literal_digest_and_not_the_canonical_one() -> None:
    """The requirement, in one assertion pair.

    Measured while choosing the canonicalization: `method="c14n"` and plain `method="c14n2"` both
    fail this, because indentation survives as text nodes. `c14n2` with `strip_text=True` passes
    and still preserves text content, trimming only its leading and trailing whitespace.
    """
    element = process()
    flat = etree.fromstring(etree.tostring(element, pretty_print=False), instance_parser())
    pretty = etree.fromstring(etree.tostring(element, pretty_print=True), instance_parser())

    assert xml_digests(flat).canonical == xml_digests(pretty).canonical
    assert xml_digests(flat).literal != xml_digests(pretty).literal
    assert xml_digests(flat).c14n_version == C14N_VERSION


@pytest.mark.unit
@pytest.mark.requirement("CORE-43")
def test_meaningful_text_survives_canonicalization() -> None:
    """`strip_text` trims whitespace around a text node; it does not discard the node."""
    e = maker("bpmn")
    element = e.definitions(e.process(e.documentation("  keep   this  "), id="p1"), id="d1")
    canonical = etree.tostring(element, method="c14n2", strip_text=True)
    assert b"keep   this" in canonical


@pytest.mark.unit
@pytest.mark.requirement("CORE-43")
def test_a_content_change_moves_both_digests() -> None:
    """The negative control: canonicalization normalizes serialization, not architecture."""
    first = xml_digests(process())
    other = maker("bpmn").definitions(
        maker("bpmn").process(maker("bpmn").startEvent(id="s2"), id="p1"),
        id="d1",
        targetNamespace="urn:synthetic",
    )
    second = xml_digests(other)
    assert second.canonical != first.canonical
    assert second.literal != first.literal


@pytest.mark.unit
@pytest.mark.requirement("CORE-43")
def test_the_digests_are_prefixed_so_two_digest_kinds_cannot_collide() -> None:
    digests = xml_digests(process())
    assert digests.literal.startswith("sha256:")
    assert digests.canonical.startswith("sha256:")
    raw = hashlib.sha256(etree.tostring(process())).hexdigest()
    assert digests.literal != f"sha256:{raw}", "the preimage prefix is missing"

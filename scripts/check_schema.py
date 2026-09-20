"""Validate generated and hand-written contract schemas.

Six jobs where there was one, and the extra five exist because the single job could pass while
the contract was meaningless:

  1. every declared schema family has a committed file matching byte-for-byte;
  2. no committed schema is an orphan no family claims;
  3. every schema — generated or hand-written — is a valid Draft 2020-12 document;
  4. the synthetic example validates against the authoring schema, *and* Pydantic agrees with
     the schema about it;
  5. validation and serialization schema modes differ only where declared (CORE-13);
  6. the requirements index validates, and its declared patterns are exercised.

Job four is what lets `architecture validate` honestly report `schema_syntax: not_checked` at
runtime. Pydantic is the authority there; the JSON Schema is an exported contract, and running
both per invocation invites two answers to one question. Their agreement is established once,
here.

Job five is the mechanical form of CORE-13. Measured against the pinned Pydantic, the two modes
differ exactly and only where a computed field exists, and the domain declares none — so the
assertion is that they are byte-identical, and adding a computed field fails this until the
difference is declared.

The generated documents come from `architecture_toolkit.domain.contracts`, the same registry the
CLI writes from. Before it existed, this script and the CLI each called `model_json_schema()`
independently, so the first divergence between them would have gone unnoticed indefinitely.
"""

import json
import re

from _common import ROOT, load_json, report
from jsonschema import Draft202012Validator
from ruamel.yaml import YAML

from architecture_toolkit.contracts import SCHEMA_FAMILIES, emit, emittable
from architecture_toolkit.domain.model import Model

# Written by hand rather than generated, so they are exempt from the drift and orphan checks
# but not from being valid schema documents.
HAND_WRITTEN = frozenset(
    {"schemas/qualification-evidence.schema.json", "schemas/requirements.schema.json"}
)


def check_generated_snapshots() -> list[str]:
    """Intentional updates use `uv run architecture schema --write`."""
    errors: list[str] = []
    for family in emittable():
        path = ROOT / family.path
        if not path.is_file():
            errors.append(f"{family.path}: declared by family {family.family_id!r} but missing")
            continue
        expected = json.dumps(emit(family), indent=2) + "\n"
        if path.read_text() != expected:
            errors.append(f"{family.path}: snapshot is stale; run `architecture schema --write`")
    for family in SCHEMA_FAMILIES:
        if family not in emittable() and (ROOT / family.path).exists():
            errors.append(
                f"{family.path}: family {family.family_id!r} is deferred to "
                f"{family.deferred_to} but a file exists"
            )
    return errors


def check_no_orphan_schemas() -> list[str]:
    """A schema nothing generates and nothing claims is a contract nobody maintains."""
    claimed = {family.path for family in SCHEMA_FAMILIES} | HAND_WRITTEN
    found = {
        path.relative_to(ROOT).as_posix() for path in (ROOT / "schemas").rglob("*.schema.json")
    }
    return [f"{path}: no schema family claims this file" for path in sorted(found - claimed)]


def check_schemas_are_draft_2020_12() -> list[str]:
    """Self-tested below: a deliberately malformed document must be rejected."""
    errors: list[str] = []
    for path in sorted((ROOT / "schemas").rglob("*.schema.json")):
        relative = path.relative_to(ROOT).as_posix()
        document = json.loads(path.read_text())
        try:
            Draft202012Validator.check_schema(document)
        except Exception as invalid:
            errors.append(f"{relative}: not a valid Draft 2020-12 schema: {invalid}")
            continue
        if relative in HAND_WRITTEN:
            continue
        if document.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            errors.append(f"{relative}: missing or wrong $schema")
        if not re.fullmatch(r"urn:architecture-toolkit:[a-z-]+:v\d+", document.get("$id", "")):
            errors.append(f"{relative}: $id {document.get('$id')!r} is not a versioned URN")
    return errors


def check_example_agrees_with_pydantic() -> list[str]:
    """The example must be accepted by the schema and by Pydantic, or rejected by both."""
    source = ROOT / "examples" / "minimal" / "model.yaml"
    payload = json.loads(json.dumps(YAML(typ="safe").load(source.read_text())))
    schema = load_json("schemas/model.schema.json")

    by_schema = list(Draft202012Validator(schema).iter_errors(payload))
    try:
        Model.model_validate_json(json.dumps(payload))
        by_pydantic: list[str] = []
    except ValueError as rejected:
        by_pydantic = [str(rejected)]

    errors: list[str] = []
    if by_schema:
        errors.append(f"examples/minimal/model.yaml fails its own schema: {by_schema[0].message}")
    if by_pydantic:
        errors.append(f"examples/minimal/model.yaml fails Pydantic: {by_pydantic[0][:200]}")
    if bool(by_schema) != bool(by_pydantic):
        errors.append(
            "the generated schema and Pydantic disagree about the example; the exported "
            "contract no longer describes what validation does"
        )
    return errors


def check_mode_delta() -> list[str]:
    """CORE-13. No computed fields today, so the two modes must be identical."""
    errors: list[str] = []
    for family in emittable():
        validation = emit(family, mode="validation")
        serialization = emit(family, mode="serialization")
        if validation == serialization:
            continue
        if not family.computed_fields:
            errors.append(
                f"{family.family_id}: validation and serialization schemas differ but the "
                f"family declares no computed fields. Declare and document the difference."
            )
    return errors


def check_requirements_index() -> list[str]:
    schema = load_json("schemas/requirements.schema.json")
    index = load_json("reference/requirements.json")
    validator = Draft202012Validator(schema)
    errors = []
    for error in sorted(validator.iter_errors(index), key=lambda error: error.path):
        location = "".join(f"[{part!r}]" for part in error.absolute_path)
        errors.append(f"requirements.json{location}: {error.message}")

    # Stronger than the `contract` pattern: the file it names must exist.
    for family, entry in index["families"].items():
        if not (ROOT / entry["contract"]).is_file():
            errors.append(
                f"families[{family!r}].contract names a missing file: {entry['contract']}"
            )
    return errors


def check_patterns_are_exercised() -> list[str]:
    """Every declared pattern must accept the values it guards and reject a near miss."""
    schema = load_json("schemas/requirements.schema.json")
    index = load_json("reference/requirements.json")
    errors: list[str] = []

    contract_pattern = schema["$defs"]["family"]["properties"]["contract"]["pattern"]
    for family, entry in index["families"].items():
        if not re.match(contract_pattern, entry["contract"]):
            errors.append(
                f"contract pattern {contract_pattern!r} rejects the live value "
                f"{entry['contract']!r} for family {family}"
            )
    for near_miss in ("docs/contracts/nested/data.md", "docs/contracts/data.txt", "data.md"):
        if re.match(contract_pattern, near_miss):
            errors.append(f"contract pattern {contract_pattern!r} wrongly accepts {near_miss!r}")

    id_pattern = schema["$defs"]["requirement"]["properties"]["id"]["pattern"]
    for requirement in index["requirements"]:
        if not re.match(id_pattern, requirement["id"]):
            errors.append(f"id pattern {id_pattern!r} rejects the live value {requirement['id']!r}")
    for near_miss in ("CORE-1", "CORE-001", "OTHER-01", "core-01"):
        if re.match(id_pattern, near_miss):
            errors.append(f"id pattern {id_pattern!r} wrongly accepts {near_miss!r}")
    return errors


def self_test() -> list[str]:
    """The checks must reject known-bad input, not merely accept the current tree."""
    errors: list[str] = []
    try:
        Draft202012Validator.check_schema({"type": "not-a-type"})
        errors.append("the Draft 2020-12 check accepts a schema with an invalid type keyword")
    except Exception:  # noqa: S110 - rejection is the expected outcome
        pass
    if not list(
        Draft202012Validator(load_json("schemas/model.schema.json")).iter_errors(
            {"model_id": "not a valid id", "elements": "wrong type"}
        )
    ):
        errors.append("the authoring schema accepts an obviously invalid document")
    return errors


def main() -> None:
    report(
        "Schema check",
        check_generated_snapshots()
        + check_no_orphan_schemas()
        + check_schemas_are_draft_2020_12()
        + check_example_agrees_with_pydantic()
        + check_mode_delta()
        + check_requirements_index()
        + check_patterns_are_exercised()
        + self_test(),
        success=[
            f"{len(emittable())} generated schema families match their snapshots",
            "every schema is a valid Draft 2020-12 document with a versioned $id",
            "the example is accepted by both the generated schema and Pydantic",
            "validation and serialization schema modes agree",
            "Requirements index validates against its schema",
            "Declared schema patterns accept the live values and reject near misses",
        ],
    )


if __name__ == "__main__":
    main()

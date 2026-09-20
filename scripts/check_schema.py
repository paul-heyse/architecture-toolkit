"""Validate generated and hand-written contract schemas.

Three separate jobs:
  1. the generated authoring schema snapshot is not stale;
  2. reference/requirements.json validates against its schema;
  3. every pattern the schema declares is exercised against the live values.

Job three exists because a JSON Schema that nothing validates against is dead code. The
`contract` pattern carried a double-escaped `\\\\.md` for the life of the file, matching none of
the three values it guards, and no check noticed. Regexes embedded in JSON are escaped twice, so
assert what they accept rather than assuming.

Where a stronger check than a pattern exists, prefer it: `contract` names a file, so resolve it.
"""

import re

from _common import ROOT, load_json, report
from jsonschema import Draft202012Validator

from architecture_toolkit.domain.model import Model


def check_authoring_snapshot() -> list[str]:
    """Intentional updates use `architecture schema > schemas/model.schema.json`."""
    snapshot = load_json("schemas/model.schema.json")
    if snapshot != Model.model_json_schema():
        return ["Authoring schema snapshot is stale"]
    return []


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


def main() -> None:
    report(
        "Schema check",
        check_authoring_snapshot() + check_requirements_index() + check_patterns_are_exercised(),
        success=[
            "Authoring schema snapshot matches",
            "Requirements index validates against its schema",
            "Declared schema patterns accept the live values and reject near misses",
        ],
    )


if __name__ == "__main__":
    main()

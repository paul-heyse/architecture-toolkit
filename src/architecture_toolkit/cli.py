"""Small, truthful scaffold CLI. Commands never imply unimplemented qualification."""

import argparse
import json
from importlib.metadata import version
from pathlib import Path

from pydantic import ValidationError
from ruamel.yaml import YAML

from architecture_toolkit.domain.model import Model


def main() -> int:
    parser = argparse.ArgumentParser(description="Architecture toolkit foundation")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Report installed Python stack")
    check = sub.add_parser("validate", help="Check the minimal source contract only")
    check.add_argument("source", type=Path)
    sub.add_parser("schema", help="Print the current experimental authoring JSON Schema")
    sub.add_parser("build", help="Reserved: full projection pipeline is not implemented")
    args = parser.parse_args()
    if args.command == "doctor":
        print(
            json.dumps(
                {
                    n: version(n)
                    for n in ["pydantic", "pyarrow", "datafusion", "deltalake", "networkx"]
                },
                indent=2,
            )
        )
    elif args.command == "schema":
        print(json.dumps(Model.model_json_schema(), indent=2))
    elif args.command == "validate":
        try:
            raw = YAML(typ="safe").load(args.source.read_text())
            model = Model.model_validate_json(json.dumps(raw))
        except (OSError, ValueError, ValidationError) as exc:
            parser.exit(1, f"Invalid source: {exc}\n")
        print(
            json.dumps(
                {
                    "model_id": model.model_id,
                    "structural_contract": "passed",
                    "scope": "minimal identities and endpoints only",
                    "notation_validity": "not_checked",
                    "architectural_consistency": "not_fully_checked",
                    "real_world_correctness": "not_established",
                }
            )
        )
    else:
        parser.exit(2, "Not implemented: follow docs/implementation-contract.md before building.\n")
    return 0

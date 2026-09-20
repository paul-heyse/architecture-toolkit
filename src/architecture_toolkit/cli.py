"""Small, truthful scaffold CLI. Commands never imply unimplemented qualification."""

import argparse
import json
from importlib.metadata import version
from pathlib import Path

from pydantic import ValidationError
from ruamel.yaml import YAML

from architecture_toolkit.domain.model import Model
from architecture_toolkit.validation.normalize import normalize_validation_error
from architecture_toolkit.validation.pipeline import validate_model
from architecture_toolkit.validation.render import render_diagnostics, render_report

# Exit codes are part of the interface. Four, and no more:
#   0  nothing at or above the failure threshold
#   1  a hard structural error
#   2  usage, or a command that is not implemented
#   3  the source could not be read or parsed, so no rule could run
# 3 exists because "that file is not YAML" and "this model has four unresolved endpoints" are
# different operational outcomes and CI wants to branch on them.
EXIT_OK = 0
EXIT_DIAGNOSTICS = 1
EXIT_USAGE = 2
EXIT_UNREADABLE = 3


def main() -> int:
    parser = argparse.ArgumentParser(description="Architecture toolkit foundation")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Report installed Python stack")
    check = sub.add_parser("validate", help="Validate a source model and report what was checked")
    check.add_argument("source", type=Path)
    check.add_argument("--format", choices=("human", "json"), default="human")
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
        return EXIT_OK

    if args.command == "schema":
        print(json.dumps(Model.model_json_schema(), indent=2))
        return EXIT_OK

    if args.command == "validate":
        return _validate(args.source, output=args.format)

    parser.exit(EXIT_USAGE, "Not implemented: follow docs/implementation-contract.md.\n")
    return EXIT_USAGE


def _validate(source: Path, *, output: str) -> int:
    """Record validation, then cross-record validation, then an honest claim report.

    The JSON round trip is load-bearing rather than incidental. Under `strict=True` a Python
    `list` handed to a `tuple[...]` field fails with the error location collapsed to the field,
    discarding every nested error; the same payload through `model_validate_json` reports the
    full path. Diagnostics that cannot name the field that was wrong are not worth much, so the
    authoring path stays JSON until W2 supplies the proper adapter and source map.
    """
    try:
        raw = YAML(typ="safe").load(source.read_text())
        payload = json.dumps(raw)
    except (OSError, ValueError) as unreadable:
        print(f"{source}\nERROR CORE.SCHEMA.UNCLASSIFIED\n(document)\n{unreadable}")
        return EXIT_UNREADABLE

    try:
        model = Model.model_validate_json(payload)
    except ValidationError as invalid:
        # Record-local failures never reach the cross-record layer, so they are rendered on
        # their own. They are still normalized, so a reader sees the same codes either way.
        print(
            render_diagnostics(normalize_validation_error(invalid, root=Model), source=str(source))
        )
        return EXIT_DIAGNOSTICS

    report = validate_model(model)
    if output == "json":
        print(report.model_dump_json(indent=2))
    else:
        print(render_report(report, source=str(source)))
    return EXIT_DIAGNOSTICS if report.hard_errors else EXIT_OK

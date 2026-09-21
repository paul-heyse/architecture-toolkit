"""Small, truthful scaffold CLI. Commands never imply unimplemented qualification."""

import argparse
import json
from importlib.metadata import version
from pathlib import Path

from architecture_toolkit.contracts import SCHEMA_FAMILIES, emit, emittable
from architecture_toolkit.releases.archive import write_archive
from architecture_toolkit.releases.candidate import ReleaseCandidate, next_release_id
from architecture_toolkit.releases.errors import (
    ArchiveError,
    ReleaseError,
    RetentionSafetyError,
    UnknownReleaseError,
)
from architecture_toolkit.releases.manifest import ArchitectureRelease
from architecture_toolkit.releases.provenance import source_bundle, source_revision
from architecture_toolkit.releases.publication import PublicationRequest, publish
from architecture_toolkit.releases.retention import probe_readability, vacuum_table
from architecture_toolkit.releases.store import DEFAULT_STORE_ROOT, ReleaseStore
from architecture_toolkit.storage.schemas import TABLE_IDS
from architecture_toolkit.validation.authoring import validate_source_text
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

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description="Architecture toolkit foundation")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Report installed Python stack")
    check = sub.add_parser("validate", help="Validate a source model and report what was checked")
    check.add_argument("source", type=Path)
    check.add_argument("--format", choices=("human", "json"), default="human")
    schema = sub.add_parser("schema", help="Print or write the generated JSON Schema contracts")
    schema.add_argument("--family", help="Emit one family to stdout")
    schema.add_argument(
        "--write", action="store_true", help="Write every emittable family to its declared path"
    )
    release = sub.add_parser("publish", help="Publish a source model as a coherent release")
    release.add_argument("source", type=Path)
    release.add_argument("--store", type=Path, default=DEFAULT_STORE_ROOT)
    release.add_argument(
        "--expect-parent",
        default=_UNSET,
        help="The release the candidate was built against; omit only for the first release.",
    )
    release.add_argument("--release-id", help="Defaults to the next rel-NNNN in the store.")
    release.add_argument(
        "--no-source-snapshot",
        action="store_true",
        help="Do not copy the source into the release; pin only its revision and digest.",
    )

    listing = sub.add_parser("releases", help="List published releases and whether they resolve")
    listing.add_argument("--store", type=Path, default=DEFAULT_STORE_ROOT)
    listing.add_argument("--verify", action="store_true", help="Read every pinned version back")

    show = sub.add_parser("show", help="Print one release manifest")
    show.add_argument("release_id")
    show.add_argument("--store", type=Path, default=DEFAULT_STORE_ROOT)

    archive = sub.add_parser("archive", help="Write a self-contained milestone archive")
    archive.add_argument("release_id")
    archive.add_argument("--store", type=Path, default=DEFAULT_STORE_ROOT)
    archive.add_argument("--into", type=Path, default=None)

    vacuum = sub.add_parser("vacuum", help="Remove files no retained release needs")
    vacuum.add_argument("--store", type=Path, default=DEFAULT_STORE_ROOT)
    vacuum.add_argument(
        "--apply", action="store_true", help="Actually delete; the default is a dry run."
    )

    sub.add_parser("build", help="Reserved: full projection pipeline is not implemented")
    args = parser.parse_args()

    if args.command == "doctor":
        print(
            json.dumps(
                {
                    n: version(n)
                    for n in [
                        "pydantic",
                        "ruamel.yaml",
                        "pyarrow",
                        "datafusion",
                        "deltalake",
                        "networkx",
                    ]
                },
                indent=2,
            )
        )
        return EXIT_OK

    if args.command == "schema":
        return _schema(parser, family_id=args.family, write=args.write)

    if args.command == "validate":
        return _validate(args.source, output=args.format)

    if args.command == "publish":
        return _publish(
            parser,
            args.source,
            store_root=args.store,
            expected_parent=args.expect_parent,
            release_id=args.release_id,
            preserve_source=not args.no_source_snapshot,
        )

    if args.command == "releases":
        return _releases(store_root=args.store, verify=args.verify)

    if args.command == "show":
        return _show(parser, args.release_id, store_root=args.store)

    if args.command == "archive":
        return _archive(parser, args.release_id, store_root=args.store, into=args.into)

    if args.command == "vacuum":
        return _vacuum(store_root=args.store, apply=args.apply)

    parser.exit(EXIT_USAGE, "Not implemented: follow docs/implementation-contract.md.\n")
    return EXIT_USAGE


def _schema(parser: argparse.ArgumentParser, *, family_id: str | None, write: bool) -> int:
    """List, print or write. Listing is the bare behaviour because it cannot surprise anyone."""
    if write:
        for family in emittable():
            target = ROOT / family.path
            target.write_text(json.dumps(emit(family), indent=2) + "\n")
            print(f"wrote {family.path}")
        return EXIT_OK
    if family_id is not None:
        found = next((f for f in SCHEMA_FAMILIES if f.family_id == family_id), None)
        if found is None or found not in emittable():
            parser.exit(EXIT_USAGE, f"No emittable schema family named {family_id!r}.\n")
            return EXIT_USAGE
        print(json.dumps(emit(found), indent=2))
        return EXIT_OK
    for family in SCHEMA_FAMILIES:
        state = f"deferred to {family.deferred_to}" if family.deferred_to else family.path
        print(f"{family.family_id:<20} {family.schema_id:<46} {state}")
    return EXIT_OK


def _validate(source: Path, *, output: str) -> int:
    """Adapter, strict records, cross-record rules, then an honest claim report.

    Every diagnostic is source-located through the SourceMap: exact where the map has the
    position, and stated as `nearest` where the chain fell back to a parent or the document.
    """
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as unreadable:
        print(f"{source}\nERROR CORE.YAML.SYNTAX\n(document)\n{unreadable}")
        return EXIT_UNREADABLE

    result = validate_source_text(text, source_id=str(source))
    if result.outcome == "unreadable":
        print(render_diagnostics(result.diagnostics, source=str(source)))
        return EXIT_UNREADABLE
    if result.outcome == "invalid_records" or result.report is None:
        # Record-local failures never reach the cross-record layer, so they are rendered on
        # their own. They are still normalized and located, so a reader sees the same shape.
        print(render_diagnostics(result.diagnostics, source=str(source)))
        return EXIT_DIAGNOSTICS

    if output == "json":
        print(result.report.model_dump_json(indent=2))
    else:
        print(render_report(result.report, source=str(source)))
    return EXIT_DIAGNOSTICS if result.report.hard_errors else EXIT_OK


# `--expect-parent` has three states, not two: given a value, given empty for "no parent", and
# absent. Absent is a usage error for anything but the first release, because DATA-23 asks a
# publication to *say* what it was built against — and a flag that silently defaulted to the
# current release would turn the stale-parent check into a formality.
_UNSET = object()


def _store_at(root: Path) -> ReleaseStore:
    return ReleaseStore.at(root)


def _publish(
    parser: argparse.ArgumentParser,
    source: Path,
    *,
    store_root: Path,
    expected_parent: object,
    release_id: str | None,
    preserve_source: bool = True,
) -> int:
    """Validate a source, then publish it as the next release of its model."""
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as unreadable:
        print(f"{source}\nERROR CORE.YAML.SYNTAX\n(document)\n{unreadable}")
        return EXIT_UNREADABLE

    result = validate_source_text(text, source_id=str(source))
    if result.outcome != "validated" or result.model is None or result.report is None:
        print(render_diagnostics(result.diagnostics, source=str(source)))
        return EXIT_UNREADABLE if result.outcome == "unreadable" else EXIT_DIAGNOSTICS
    if result.report.hard_errors:
        print(render_report(result.report, source=str(source)))
        return EXIT_DIAGNOSTICS

    store = _store_at(store_root).initialize()
    current = store.current_id()
    if expected_parent is _UNSET:
        if current is not None:
            parser.exit(
                EXIT_USAGE,
                f"--expect-parent is required: the current release is {current!r}.\n",
            )
            return EXIT_USAGE
        parent: str | None = None
    else:
        parent = str(expected_parent) or None

    candidate = ReleaseCandidate(
        release_id=release_id or next_release_id(store.release_ids()),
        model=result.model,
        source_bundle=source_bundle(
            source_id=str(source), text=text, revision=source_revision(source)
        ),
    )
    try:
        manifest = publish(
            PublicationRequest(
                store=store,
                candidate=candidate,
                expected_parent=parent,
                source_text=text,
                preserve_source=preserve_source,
                attempt=len(store.release_ids()) + 1,
            )
        )
    except ReleaseError as refused:
        print(f"{type(refused).__name__}: {refused}")
        return EXIT_DIAGNOSTICS

    reused = sum(1 for ref in manifest.tables if _reused(store, manifest, ref.table_id))
    print(f"published {manifest.release_id} ({len(manifest.tables)} tables, {reused} reused)")
    print(f"model digest {manifest.model_digest}")
    return EXIT_OK


def _reused(store: ReleaseStore, manifest: ArchitectureRelease, table_id: str) -> bool:
    parent_id = manifest.parent_release_id
    if parent_id is None or not store.has_manifest(parent_id):
        return False
    try:
        previous = store.read_manifest(parent_id).table(table_id)
    except KeyError:
        return False
    return previous.delta_version == manifest.table(table_id).delta_version


def _releases(*, store_root: Path, verify: bool) -> int:
    """List what has been published, and optionally prove each one still resolves."""
    store = _store_at(store_root)
    current = store.current_id()
    ids = store.release_ids()
    if not ids:
        print(f"no releases in {store_root}")
        return EXIT_OK
    for release_id in ids:
        manifest = store.read_manifest(release_id)
        marker = "*" if release_id == current else " "
        print(f"{marker} {release_id}  {manifest.model_id}  {manifest.published_at.isoformat()}")
    if not verify:
        return EXIT_OK

    findings = probe_readability(store)
    if findings:
        print(render_diagnostics(findings, source=str(store_root)))
        return EXIT_DIAGNOSTICS
    print(f"every pinned version of {len(ids)} release(s) reads back")
    return EXIT_OK


def _show(parser: argparse.ArgumentParser, release_id: str, *, store_root: Path) -> int:
    try:
        manifest = _store_at(store_root).read_manifest(release_id)
    except UnknownReleaseError:
        parser.exit(EXIT_USAGE, f"No release {release_id!r} in {store_root}.\n")
        return EXIT_USAGE
    print(manifest.model_dump_json(indent=2))
    return EXIT_OK


def _archive(
    parser: argparse.ArgumentParser, release_id: str, *, store_root: Path, into: Path | None
) -> int:
    store = _store_at(store_root)
    try:
        manifest = store.read_manifest(release_id)
    except UnknownReleaseError:
        parser.exit(EXIT_USAGE, f"No release {release_id!r} in {store_root}.\n")
        return EXIT_USAGE
    try:
        result = write_archive(store, manifest, into)
    except ArchiveError as refused:
        print(f"ArchiveError: {refused}")
        return EXIT_DIAGNOSTICS
    print(f"archived {release_id} to {result.root} ({len(result.contents)} files)")
    return EXIT_OK


def _vacuum(*, store_root: Path, apply: bool) -> int:
    """Dry run by default. A destructive default would be the wrong one."""
    store = _store_at(store_root)
    total = 0
    for table_id in TABLE_IDS:
        try:
            plan = vacuum_table(store, table_id, apply=apply)
        except (RetentionSafetyError, ReleaseError) as refused:
            print(f"{table_id}: refused - {refused}")
            return EXIT_DIAGNOSTICS
        total += len(plan.removable_files)
        if plan.removable_files:
            verb = "removed" if apply else "would remove"
            kept = ", ".join(str(v) for v in plan.keep_versions)
            print(f"{table_id}: {verb} {len(plan.removable_files)} file(s); keeping [{kept}]")
    if total == 0:
        print("nothing to remove; every file is referenced by a retained release")
    elif not apply:
        print("dry run; pass --apply to remove")
    return EXIT_OK

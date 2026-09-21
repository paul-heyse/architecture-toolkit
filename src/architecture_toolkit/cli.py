"""Small, truthful scaffold CLI. Commands never imply unimplemented qualification."""

import argparse
import json
from importlib.metadata import version
from pathlib import Path

from pydantic import ValidationError

from architecture_toolkit.changes.alternatives import compare_alternative
from architecture_toolkit.changes.audit import compared_tables, storage_disagreements
from architecture_toolkit.changes.errors import ChangeError
from architecture_toolkit.changes.operations import ArchitectureOperations
from architecture_toolkit.changes.record import (
    ArchitectureChangeSet,
    AuthorKind,
    Authorship,
    ReviewDecision,
)
from architecture_toolkit.changes.records import ModelChanges
from architecture_toolkit.changes.releases import diff_releases, identity_disagreements
from architecture_toolkit.contracts import SCHEMA_FAMILIES, emit, emittable
from architecture_toolkit.domain.commands import CHANGE_SET_ADAPTER, CommandError
from architecture_toolkit.domain.semantics import MODEL_COLLECTIONS
from architecture_toolkit.queries.algorithms import (
    components,
    condensation,
    cycles,
    generations,
    minimum_equivalent,
    reachability_closure,
)
from architecture_toolkit.queries.errors import QueryError
from architecture_toolkit.queries.execution import ReleaseQueryExecutor
from architecture_toolkit.queries.graph import ArchitectureGraph
from architecture_toolkit.queries.plans import capture
from architecture_toolkit.queries.policy import POLICIES, GraphPolicy, policy_for
from architecture_toolkit.queries.recipes import RECIPES, ParameterSpec, QueryRecipe, recipe_for
from architecture_toolkit.queries.traversals import find_unverified_dependencies
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
from architecture_toolkit.releases.publication import PublicationRequest, persist, publish
from architecture_toolkit.releases.recovery import discard, orphans, resume
from architecture_toolkit.releases.retention import probe_readability, vacuum_table
from architecture_toolkit.releases.store import DEFAULT_STORE_ROOT, ReleaseStore
from architecture_toolkit.storage import delta
from architecture_toolkit.storage.constraints import apply_constraints, declared_constraints
from architecture_toolkit.storage.schemas import TABLE_IDS
from architecture_toolkit.validation.authoring import validate_source_text
from architecture_toolkit.validation.release import alternative_line_breaks, chain_breaks
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

DEFAULT_POLICY = "impact.structural"
UNVERIFIED_POLICY = "dependencies.direct"
STRUCTURAL_POLICY = "containment.descendants"
"""The `graph` default. The only baseline policy that declares cycle reporting, so it is the one
under which every analysis below is defined; the others refuse what they were not declared for."""

ANALYSES = ("cycles", "generations", "components", "condensation", "closure", "reduction")
"""The policy `find_unverified_dependencies` traverses; named here so `--unverified` can refuse to
silently replace a policy the operator asked for."""


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

    resume_parser = sub.add_parser(
        "resume", help="Finish a publication that wrote its manifest but not the pointer"
    )
    resume_parser.add_argument("release_id")
    resume_parser.add_argument("--store", type=Path, default=DEFAULT_STORE_ROOT)

    discard_parser = sub.add_parser("discard", help="Remove an orphan manifest")
    discard_parser.add_argument("release_id")
    discard_parser.add_argument("--store", type=Path, default=DEFAULT_STORE_ROOT)

    constraints = sub.add_parser(
        "constraints", help="Report or apply the row-local Delta check constraints"
    )
    constraints.add_argument("--store", type=Path, default=DEFAULT_STORE_ROOT)
    constraints.add_argument(
        "--apply", action="store_true", help="Actually add them; the default reports."
    )

    vacuum = sub.add_parser("vacuum", help="Remove files no retained release needs")
    vacuum.add_argument("--store", type=Path, default=DEFAULT_STORE_ROOT)
    vacuum.add_argument(
        "--apply", action="store_true", help="Actually delete; the default is a dry run."
    )

    recipes = sub.add_parser("recipes", help="List the versioned query recipes, or describe one")
    recipes.add_argument("recipe_id", nargs="?", help="Describe this recipe instead of listing all")

    query = sub.add_parser("query", help="Run one query recipe against a release")
    query.add_argument("recipe_id")
    query.add_argument("--store", type=Path, default=DEFAULT_STORE_ROOT)
    query.add_argument("--release", help="Defaults to the current release.")
    query.add_argument("--base", help="For a comparison recipe: the release to compare against.")
    query.add_argument("--candidate", help="For a comparison recipe: the release to compare.")
    query.add_argument(
        "--param",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="Bind one declared parameter. Values are typed by the recipe, never interpolated.",
    )
    query.add_argument("--format", choices=("table", "json"), default="table")

    plan = sub.add_parser("plan", help="Show what the engine plans for one recipe")
    plan.add_argument("recipe_id")
    plan.add_argument("--store", type=Path, default=DEFAULT_STORE_ROOT)
    plan.add_argument("--release", help="Defaults to the current release.")
    plan.add_argument("--param", action="append", default=[], metavar="NAME=VALUE")

    impact = sub.add_parser("impact", help="Bounded, explainable traversal from one object")
    impact.add_argument("element_id")
    impact.add_argument("--store", type=Path, default=DEFAULT_STORE_ROOT)
    impact.add_argument("--release", help="Defaults to the current release.")
    impact.add_argument(
        "--policy",
        default=None,
        help=f"A named policy; `--policy list` shows them. Defaults to {DEFAULT_POLICY}.",
    )
    impact.add_argument(
        "--unverified",
        action="store_true",
        help=(
            "Keep only dependencies whose qualification is not established. Uses the "
            "dependencies.direct policy, so it cannot be combined with another --policy."
        ),
    )
    impact.add_argument("--format", choices=("human", "json"), default="human")

    analysis = sub.add_parser(
        "graph", help="Structural analyses of one release under one named policy"
    )
    analysis.add_argument("analysis", choices=sorted(ANALYSES))
    analysis.add_argument("--store", type=Path, default=DEFAULT_STORE_ROOT)
    analysis.add_argument("--release", help="Defaults to the current release.")
    analysis.add_argument(
        "--policy",
        default=STRUCTURAL_POLICY,
        help=f"A named policy; `impact --policy list` shows them. Defaults to {STRUCTURAL_POLICY}.",
    )
    analysis.add_argument("--format", choices=("human", "json"), default="human")

    # -- DATA-38: the lifecycle verbs -------------------------------------------------------------
    # `validate` and `publish` are already registered above; these are the other six. Flat, like
    # every other command here, because a lifecycle whose steps sit at two different levels of the
    # command tree is harder to read than one extra name at the top.
    baseline = sub.add_parser("baseline", help="Print the model a release holds, as authored YAML")
    baseline.add_argument("--store", type=Path, default=DEFAULT_STORE_ROOT)
    baseline.add_argument("--release", help="Defaults to the current release")
    baseline.add_argument("--format", choices=("summary", "json"), default="summary")

    apply_change = sub.add_parser(
        "change", help="Apply a typed change set to a release and report what it would do"
    )
    apply_change.add_argument("change_set", type=Path, help="A JSON change set (CORE-10)")
    apply_change.add_argument("--store", type=Path, default=DEFAULT_STORE_ROOT)
    apply_change.add_argument("--release", help="Defaults to the current release")
    apply_change.add_argument("--format", choices=("human", "json"), default="human")

    difference = sub.add_parser("diff", help="Explain what changed between two releases")
    difference.add_argument("--store", type=Path, default=DEFAULT_STORE_ROOT)
    difference.add_argument("--base", required=True)
    difference.add_argument("--candidate", required=True)
    difference.add_argument(
        "--include-presentation",
        action="store_true",
        help="Also print layout and display changes, which are never part of the narrative.",
    )
    difference.add_argument(
        "--cross-check",
        action="store_true",
        help=(
            "Also check the narrative against DataFusion and the Delta change feed (DATA-57). "
            "Storage is never the narrative; disagreeing with it means one of them is wrong."
        ),
    )
    difference.add_argument("--format", choices=("human", "json"), default="human")

    comparison = sub.add_parser(
        "compare", help="Compare a design alternative with the baseline it declares"
    )
    comparison.add_argument("--baseline", required=True, help="A release on the baseline line")
    comparison.add_argument("--alternative", required=True, help="A release on a scenario line")
    comparison.add_argument(
        "--store", type=Path, default=DEFAULT_STORE_ROOT, help="Where the alternative lives"
    )
    comparison.add_argument(
        "--baseline-store",
        type=Path,
        help=(
            "Where the baseline lives. Defaults to --store; an alternative is usually published "
            "into its own store root, because one store has one current pointer."
        ),
    )
    comparison.add_argument("--format", choices=("human", "json"), default="human")

    reviewing = sub.add_parser("review", help="Record a decision on a change report")
    reviewing.add_argument("change_report", type=Path, help="A change report written by `diff`")
    reviewing.add_argument(
        "--decision", choices=tuple(item.value for item in ReviewDecision), required=True
    )
    reviewing.add_argument("--reviewer", required=True)
    reviewing.add_argument("--note")
    reviewing.add_argument("--into", type=Path, help="Where to write the reviewed report")

    staging = sub.add_parser(
        "persist", help="Stage a release and write its manifest without exposing it"
    )
    staging.add_argument("source", type=Path)
    staging.add_argument("--store", type=Path, default=DEFAULT_STORE_ROOT)
    staging.add_argument(
        "--expect-parent",
        default=_UNSET,
        help="The release the candidate was built against; omit only for the first release.",
    )
    staging.add_argument("--release-id", help="Defaults to the next rel-NNNN in the store.")
    staging.add_argument("--scenario", help="Publish as a design alternative under this id")
    staging.add_argument("--baseline", help="The release this alternative is derived from")

    outputting = sub.add_parser("output", help="Reserved: distribute a release's outputs (W8)")
    outputting.add_argument("--store", type=Path, default=DEFAULT_STORE_ROOT)
    outputting.add_argument("--release", help="Defaults to the current release")
    outputting.add_argument("--format", choices=("human", "json"), default="human")

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

    if args.command == "resume":
        return _resume(parser, args.release_id, store_root=args.store)

    if args.command == "discard":
        return _discard(parser, args.release_id, store_root=args.store)

    if args.command == "constraints":
        return _constraints(store_root=args.store, apply=args.apply)

    if args.command == "vacuum":
        return _vacuum(store_root=args.store, apply=args.apply)

    if args.command == "recipes":
        return _recipes(parser, args.recipe_id)

    if args.command == "query":
        return _query(
            parser,
            args.recipe_id,
            store_root=args.store,
            release_id=args.release,
            base=args.base,
            candidate=args.candidate,
            params=args.param,
            output=args.format,
        )

    if args.command == "plan":
        return _plan(
            parser,
            args.recipe_id,
            store_root=args.store,
            release_id=args.release,
            params=args.param,
        )

    if args.command == "graph":
        return _graph(
            parser,
            args.analysis,
            store_root=args.store,
            release_id=args.release,
            policy_id=args.policy,
            output=args.format,
        )

    if args.command == "impact":
        return _impact(
            parser,
            args.element_id,
            store_root=args.store,
            release_id=args.release,
            policy_id=args.policy,
            unverified=args.unverified,
            output=args.format,
        )

    if args.command == "baseline":
        return _baseline(parser, store_root=args.store, release_id=args.release, output=args.format)

    if args.command == "change":
        return _change(
            parser,
            args.change_set,
            store_root=args.store,
            release_id=args.release,
            output=args.format,
        )

    if args.command == "diff":
        return _diff(
            parser,
            store_root=args.store,
            base=args.base,
            candidate=args.candidate,
            include_presentation=args.include_presentation,
            cross_check=args.cross_check,
            output=args.format,
        )

    if args.command == "compare":
        return _compare(
            parser,
            baseline_id=args.baseline,
            alternative_id=args.alternative,
            store_root=args.store,
            baseline_store_root=args.baseline_store or args.store,
            output=args.format,
        )

    if args.command == "review":
        return _review(
            parser,
            args.change_report,
            decision=args.decision,
            reviewer=args.reviewer,
            note=args.note,
            into=args.into,
        )

    if args.command == "persist":
        return _persist(
            parser,
            args.source,
            store_root=args.store,
            expected_parent=args.expect_parent,
            release_id=args.release_id,
            scenario_id=args.scenario,
            baseline_release_id=args.baseline,
        )

    if args.command == "output":
        return _output(parser, store_root=args.store, release_id=args.release, output=args.format)

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
    return _stage_or_publish(
        parser,
        source,
        store_root=store_root,
        expected_parent=expected_parent,
        release_id=release_id,
        preserve_source=preserve_source,
        scenario_id=None,
        baseline_release_id=None,
        expose=True,
    )


def _stage_or_publish(
    parser: argparse.ArgumentParser,
    source: Path,
    *,
    store_root: Path,
    expected_parent: object,
    release_id: str | None,
    preserve_source: bool,
    scenario_id: str | None,
    baseline_release_id: str | None,
    expose: bool,
) -> int:
    """`publish` and `persist` differ in the eighth protocol line and in nothing else.

    One body rather than two, because two would eventually validate a source differently depending
    on which verb an operator typed — and the whole point of the split is that the *only* thing
    that differs is whether the current pointer moves.
    """
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
        scenario_id=scenario_id,
        baseline_release_id=baseline_release_id,
    )
    request = PublicationRequest(
        store=store,
        candidate=candidate,
        expected_parent=parent,
        source_text=text,
        preserve_source=preserve_source,
    )
    try:
        manifest = publish(request) if expose else persist(request)
    except (ReleaseError, ValidationError) as refused:
        print(f"{type(refused).__name__}: {refused}")
        return EXIT_DIAGNOSTICS

    reused = sum(1 for ref in manifest.tables if _reused(store, manifest, ref.table_id))
    verb = "published" if expose else "persisted"
    print(f"{verb} {manifest.release_id} ({len(manifest.tables)} tables, {reused} reused)")
    print(f"model digest {manifest.model_digest}")
    if not expose:
        print(f"not current: {store.current_id() or 'nothing'} still is; `resume` completes it")
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
    stranded = set(orphans(store))
    for release_id in ids:
        manifest = store.read_manifest(release_id)
        marker = "*" if release_id == current else ("!" if release_id in stranded else " ")
        note = "  (orphan: never became current)" if release_id in stranded else ""
        print(
            f"{marker} {release_id}  {manifest.model_id}  {manifest.published_at.isoformat()}{note}"
        )
    if stranded:
        print(f"{len(stranded)} orphan(s); `resume` completes one, `discard` removes it")
    if not verify:
        return EXIT_OK

    # Three questions, not one. Storage answers "do the pinned versions still read back";
    # `chain_breaks` answers "is the parent chain navigable" (DATA-21); `alternative_line_breaks`
    # answers "is every design alternative derived rather than descended" (DATA-28). The first two
    # were written at W4 and reachable only from their own tests until now.
    manifests = [store.read_manifest(release_id) for release_id in ids]
    findings = (
        probe_readability(store)
        + chain_breaks(
            (item.release_id, item.parent_release_id, item.model_id) for item in manifests
        )
        + alternative_line_breaks(
            (item.release_id, item.parent_release_id, item.scenario_id) for item in manifests
        )
    )
    if findings:
        print(render_diagnostics(findings, source=str(store_root)))
        return EXIT_DIAGNOSTICS
    print(f"every pinned version of {len(ids)} release(s) reads back, and the chain is navigable")
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


def _resume(parser: argparse.ArgumentParser, release_id: str, *, store_root: Path) -> int:
    """Finish a publication that got as far as writing its manifest.

    No re-staging: by the time a manifest exists its versions have been read back and verified,
    and the only thing that did not happen is the pointer move.
    """
    store = _store_at(store_root)
    try:
        manifest = resume(store, release_id)
    except UnknownReleaseError:
        parser.exit(EXIT_USAGE, f"No release {release_id!r} in {store_root}.\n")
        return EXIT_USAGE
    except ReleaseError as refused:
        print(f"{type(refused).__name__}: {refused}")
        return EXIT_DIAGNOSTICS
    print(f"resumed {manifest.release_id}; it is now the current release")
    return EXIT_OK


def _discard(parser: argparse.ArgumentParser, release_id: str, *, store_root: Path) -> int:
    store = _store_at(store_root)
    try:
        discard(store, release_id)
    except UnknownReleaseError:
        parser.exit(EXIT_USAGE, f"No release {release_id!r} in {store_root}.\n")
        return EXIT_USAGE
    except ReleaseError as refused:
        print(f"{type(refused).__name__}: {refused}")
        return EXIT_DIAGNOSTICS
    print(f"discarded {release_id}; its Delta versions are left for `vacuum` to judge")
    return EXIT_OK


def _constraints(*, store_root: Path, apply: bool) -> int:
    """Report or apply the row-local invariants (DATA-55).

    Publication deliberately does not do this: a constraint commit would make the version a
    manifest pins depend on whether the table happened to be new.
    """
    store = _store_at(store_root)
    current = store.current()
    if current is None:
        print(f"no current release in {store_root}; nothing to constrain")
        return EXIT_OK

    missing_total = 0
    for ref in current.tables:
        location = store.resolve(ref.uri)
        declared = declared_constraints(ref.table_id)
        if not declared:
            continue
        present = delta.constraints(location, version=delta.tip(location))
        missing = sorted(set(declared) - set(present))
        if not missing:
            continue
        missing_total += len(missing)
        if apply:
            apply_constraints(location, ref.table_id, version=delta.tip(location))
            print(f"{ref.table_id}: added {', '.join(missing)}")
        else:
            print(f"{ref.table_id}: missing {', '.join(missing)}")
    if missing_total == 0:
        print("every row-local constraint is in force")
    elif not apply:
        print("reporting only; pass --apply to add them")
    return EXIT_OK


def _recipes(parser: argparse.ArgumentParser, recipe_id: str | None) -> int:
    """List the recipes, or print one recipe's whole declared contract."""
    if recipe_id is None:
        for recipe in RECIPES.values():
            binds = ", ".join(spec.name for spec in recipe.parameters) or "-"
            print(
                f"{recipe.query_recipe_id:<40} v{recipe.query_recipe_version}  "
                f"{recipe.release_context:<10} {binds}"
            )
        return EXIT_OK
    try:
        recipe = recipe_for(recipe_id)
    except KeyError as unknown:
        parser.exit(EXIT_USAGE, f"{unknown.args[0]}\n")
        return EXIT_USAGE
    print(f"{recipe.query_recipe_id} v{recipe.query_recipe_version}")
    print(f"  purpose         {recipe.purpose}")
    print(f"  release context {recipe.release_context}")
    print(f"  inputs          {', '.join(_input_name(item) for item in recipe.inputs)}")
    for spec in recipe.parameters:
        state = "required" if spec.required else "optional"
        print(f"  parameter       ${spec.name} : {spec.data_type} ({state}) — {spec.purpose}")
    for column in recipe.output_schema:
        nullability = "null" if column.nullable else "not null"
        print(f"  returns         {column.name} : {column.data_type} {nullability}")
    if recipe.traversal_policy_id is not None:
        print(f"  same answer as {recipe.traversal_policy_id} (graph policy)")
    for case in recipe.qualification_cases:
        print(f"  qualified by    {case}")
    print(f"  sql             {recipe.sql}")
    return EXIT_OK


def _input_name(item: object) -> str:
    table_id = getattr(item, "table_id", "?")
    side = getattr(item, "side", None)
    return f"{side}.{table_id}" if side else str(table_id)


def _executor(
    parser: argparse.ArgumentParser, store_root: Path, release_id: str | None
) -> tuple[ReleaseQueryExecutor, str] | None:
    """One executor and the release it will read, or a usage error naming what is missing.

    Every query command needs the same two things, and each of them used to resolve them inline.
    The executor also caches the context, so `impact` builds one session rather than two when it
    queries and traverses.
    """
    executor = ReleaseQueryExecutor(_store_at(store_root))
    try:
        chosen = release_id if release_id is not None else executor.current()
        executor.context_for(chosen)
    except QueryError as missing:
        parser.exit(EXIT_USAGE, f"{missing.args[0]}.\n")
        return None
    except UnknownReleaseError as unknown:
        parser.exit(EXIT_USAGE, f"{unknown.args[0]}\n")
        return None
    return executor, chosen


def _bound(
    parser: argparse.ArgumentParser, recipe: QueryRecipe, pairs: list[str]
) -> dict[str, object] | None:
    """Type each `NAME=VALUE` by the recipe's own declaration, never by guessing.

    The command line has only strings, so something has to decide that `--param max_depth=5` is an
    integer. The recipe already says so, which is what makes this a coercion rather than an
    inference — and `bind_parameters` still refuses anything the declaration does not allow.
    """
    declared = {spec.name: spec for spec in recipe.parameters}
    bound: dict[str, object] = {}
    for pair in pairs:
        name, separator, raw = pair.partition("=")
        if not separator:
            parser.exit(EXIT_USAGE, f"--param expects NAME=VALUE, got {pair!r}.\n")
            return None
        spec = declared.get(name)
        if spec is None:
            parser.exit(
                EXIT_USAGE,
                f"{recipe.query_recipe_id} declares no parameter {name!r}; "
                f"it takes {sorted(declared) or 'none'}.\n",
            )
            return None
        value = _typed(parser, spec, raw)
        if value is None:
            return None
        bound[name] = value
    return bound


def _typed(parser: argparse.ArgumentParser, spec: ParameterSpec, raw: str) -> object | None:
    if spec.data_type == "string":
        return raw
    if spec.data_type == "integer":
        try:
            return int(raw)
        except ValueError:
            parser.exit(EXIT_USAGE, f"${spec.name} is an integer; got {raw!r}.\n")
            return None
    if spec.data_type == "boolean":
        if raw.lower() not in {"true", "false"}:
            parser.exit(EXIT_USAGE, f"${spec.name} is a boolean; got {raw!r}.\n")
            return None
        return raw.lower() == "true"
    parser.exit(EXIT_USAGE, f"${spec.name} is a {spec.data_type}, which --param cannot supply.\n")
    return None


def _query(
    parser: argparse.ArgumentParser,
    recipe_id: str,
    *,
    store_root: Path,
    release_id: str | None,
    base: str | None,
    candidate: str | None,
    params: list[str],
    output: str,
) -> int:
    """One command for both kinds of recipe, because a recipe is a recipe.

    Two sides or one release, never both: a comparison that also named a single release would be
    ambiguous about which of the three the unqualified names refer to, and DATA-47's whole point is
    that neither side is ever implicit.
    """
    try:
        recipe = recipe_for(recipe_id)
    except KeyError as unknown:
        parser.exit(EXIT_USAGE, f"{unknown.args[0]}\n")
        return EXIT_USAGE
    sides = (base, candidate)
    if any(sides) and release_id is not None:
        parser.exit(EXIT_USAGE, "Give --release or both of --base and --candidate, not both.\n")
        return EXIT_USAGE
    if any(sides) and not all(sides):
        parser.exit(EXIT_USAGE, "A comparison needs both --base and --candidate.\n")
        return EXIT_USAGE
    executor = ReleaseQueryExecutor(_store_at(store_root))
    bound = _bound(parser, recipe, params)
    if bound is None:
        return EXIT_USAGE
    try:
        result = (
            executor.compare(
                recipe_id,
                base_release_id=base,
                candidate_release_id=candidate,
                parameters=bound,
            )
            if base is not None and candidate is not None
            else executor.answer(
                recipe_id,
                release_id=release_id if release_id is not None else executor.current(),
                parameters=bound,
            )
        )
    except (QueryError, UnknownReleaseError) as refused:
        parser.exit(EXIT_USAGE, f"{refused.args[0]}\n")
        return EXIT_USAGE
    rows = result.table.to_pylist()
    if output == "json":
        print(json.dumps(rows, indent=2, default=str))
        return EXIT_OK
    print(
        f"{recipe.query_recipe_id} v{recipe.query_recipe_version} on "
        f"{', '.join(result.release_ids)}"
    )
    _print_table([column.name for column in recipe.output_schema], rows)
    return EXIT_OK


def _graph(
    parser: argparse.ArgumentParser,
    analysis: str,
    *,
    store_root: Path,
    release_id: str | None,
    policy_id: str,
    output: str,
) -> int:
    """The CORE-30 and CORE-31 analyses, which had no operator path at all until now.

    One command with a named analysis rather than six commands: they take the same two arguments
    and differ only in what they ask of the same policy view.
    """
    try:
        policy = policy_for(policy_id)
    except KeyError as unknown:
        parser.exit(EXIT_USAGE, f"{unknown.args[0]}\n")
        return EXIT_USAGE
    opened = _executor(parser, store_root, release_id)
    if opened is None:
        return EXIT_USAGE
    executor, chosen = opened
    graph = executor.graph_for(chosen)
    try:
        answer = _analyse(analysis, graph, policy)
    except QueryError as refused:
        parser.exit(EXIT_USAGE, f"{refused.args[0]}\n")
        return EXIT_USAGE
    if output == "json":
        print(json.dumps(answer, indent=2, default=str))
        return EXIT_OK
    print(f"{analysis} of {chosen} under {policy.policy_id} v{policy.policy_version}")
    if not answer:
        print("  (nothing to report)")
    for line in answer:
        print(f"  {json.dumps(line, default=str)}")
    return EXIT_OK


def _analyse(analysis: str, graph: ArchitectureGraph, policy: GraphPolicy) -> list[object]:
    """Each analysis as plain data, so one printer and one serializer cover all six."""
    if analysis == "cycles":
        return [result.model_dump() for result in cycles(graph, policy)]
    if analysis == "generations":
        return [list(generation) for generation in generations(graph, policy)]
    if analysis == "components":
        return [result.model_dump() for result in components(graph, policy)]
    if analysis == "condensation":
        return [condensation(graph, policy).model_dump()]
    if analysis == "closure":
        return [edge.model_dump() for edge in reachability_closure(graph, policy)]
    return [edge.model_dump() for edge in minimum_equivalent(graph, policy)]


def _print_table(columns: list[str], rows: list[dict[str, object]]) -> None:
    if not rows:
        print("(no rows)")
        return
    widths = {
        column: max(len(column), *(len(str(row[column])) for row in rows)) for column in columns
    }
    print("  ".join(column.ljust(widths[column]) for column in columns))
    for row in rows:
        print("  ".join(str(row[column]).ljust(widths[column]) for column in columns))


def _plan(
    parser: argparse.ArgumentParser,
    recipe_id: str,
    *,
    store_root: Path,
    release_id: str | None,
    params: list[str],
) -> int:
    """The three plans plus the provenance DATA-49 asks to be recorded alongside them."""
    try:
        recipe = recipe_for(recipe_id)
    except KeyError as unknown:
        parser.exit(EXIT_USAGE, f"{unknown.args[0]}\n")
        return EXIT_USAGE
    if recipe.release_context != "single":
        parser.exit(EXIT_USAGE, f"{recipe_id} compares two releases; the CLI plans one.\n")
        return EXIT_USAGE
    opened = _executor(parser, store_root, release_id)
    if opened is None:
        return EXIT_USAGE
    executor, chosen = opened
    bound = _bound(parser, recipe, params)
    if bound is None:
        return EXIT_USAGE
    try:
        evidence = capture(recipe, executor.context_for(chosen), bound)
    except QueryError as refused:
        parser.exit(EXIT_USAGE, f"{refused.args[0]}\n")
        return EXIT_USAGE
    print(
        f"{evidence.query_recipe_id} v{evidence.query_recipe_version} on "
        f"{', '.join(evidence.release_ids)} | datafusion {evidence.datafusion_version} | "
        f"{evidence.materialization} provider | {evidence.row_count} row(s)"
    )
    for label, plan in (
        ("logical", evidence.logical_plan),
        ("optimized", evidence.optimized_logical_plan),
        ("physical", evidence.physical_plan),
    ):
        print(f"\n--- {label} ---")
        print(plan.rstrip())
    print("\nEngine plans are diagnostics, never part of semantic identity (DATA-49).")
    return EXIT_OK


def _impact(
    parser: argparse.ArgumentParser,
    element_id: str,
    *,
    store_root: Path,
    release_id: str | None,
    policy_id: str | None,
    unverified: bool = False,
    output: str = "human",
) -> int:
    """A bounded traversal, printed with the path that justifies every result (CORE-28)."""
    if policy_id == "list":
        for policy in POLICIES.values():
            print(f"{policy.policy_id:<36} {policy.direction.value:<8} {policy.purpose}")
        return EXIT_OK
    if unverified and policy_id is not None and policy_id != UNVERIFIED_POLICY:
        # A flag that silently overrode another flag would be the quiet kind of wrong this
        # command exists to avoid: the answer would not be the policy the operator named.
        parser.exit(
            EXIT_USAGE,
            f"--unverified traverses {UNVERIFIED_POLICY}; drop --policy {policy_id} or the flag.\n",
        )
        return EXIT_USAGE
    chosen_policy = policy_id or (UNVERIFIED_POLICY if unverified else DEFAULT_POLICY)
    try:
        policy = policy_for(chosen_policy)
    except KeyError as unknown:
        parser.exit(EXIT_USAGE, f"{unknown.args[0]}\n")
        return EXIT_USAGE
    opened = _executor(parser, store_root, release_id)
    if opened is None:
        return EXIT_USAGE
    executor, chosen = opened
    try:
        graph = executor.graph_for(chosen)
        result = (
            find_unverified_dependencies(graph, executor.context_for(chosen), element_id)
            if unverified
            else graph.traverse(policy, element_id)
        )
    except QueryError as refused:
        parser.exit(EXIT_USAGE, f"{refused.args[0]}\n")
        return EXIT_USAGE
    if output == "json":
        # Validates against `schemas/query-contract.schema.json`, which
        # `tests/integration/test_query_cli.py` holds it to.
        print(result.model_dump_json(indent=2))
        return EXIT_OK
    print(
        f"{result.start} under {result.policy_id} v{result.policy_version} "
        f"on {result.release_id}: {len(result.reached)} object(s) {result.classification.value}"
    )
    for path in result.paths:
        steps = " -> ".join(
            f"{relationship} ({type_id})"
            for relationship, type_id in zip(
                path.relationship_ids, path.relationship_types, strict=True
            )
        )
        print(f"  {path.end:<24} depth {path.depth}  {steps}")
    if not result.paths:
        print("  (nothing reachable under this policy)")
    if result.truncated:
        print(f"  truncated at {result.limit_reached}; raise it on the policy to see more")
    return EXIT_OK


# -- DATA-38: the lifecycle handlers --------------------------------------------------------------


_CLI_AUTHOR = Authorship(
    author_id="architecture-cli",
    author_kind=AuthorKind.AGENT,
    tool="architecture-toolkit",
)
"""Who a change report says produced it when it came from the command line.

Named rather than left blank: DATA-26 asks for authorship, and "the CLI ran" is a true answer where
"unknown" would be an invented one.
"""


def _operations(store_root: Path) -> ArchitectureOperations:
    return ArchitectureOperations(store=_store_at(store_root))


def _baseline(
    parser: argparse.ArgumentParser, *, store_root: Path, release_id: str | None, output: str
) -> int:
    """`load baseline`. What an operator is about to change, read back from the release itself."""
    try:
        model = _operations(store_root).baseline(release_id)
    except (ChangeError, UnknownReleaseError) as refused:
        parser.exit(EXIT_USAGE, f"{refused.args[0]}\n")
        return EXIT_USAGE
    if output == "json":
        print(model.model_dump_json(indent=2))
        return EXIT_OK
    print(f"{model.model_id}  schema {model.schema_version}  profile {model.profile_version}")
    for name, _ in MODEL_COLLECTIONS:
        print(f"  {len(getattr(model, name)):4d}  {name}")
    return EXIT_OK


def _change(
    parser: argparse.ArgumentParser,
    change_set_path: Path,
    *,
    store_root: Path,
    release_id: str | None,
    output: str,
) -> int:
    """`apply typed change set` then `validate` then `preview semantic diff` — the dry run.

    Nothing is written. The whole point of the first four lifecycle steps is that an operator sees
    what a change does before deciding to keep it, so this command has no way to keep it.
    """
    operations = _operations(store_root)
    try:
        change_set = CHANGE_SET_ADAPTER.validate_json(change_set_path.read_text())
    except (OSError, ValidationError) as refused:
        parser.exit(EXIT_USAGE, f"{change_set_path}: {refused}\n")
        return EXIT_USAGE
    try:
        baseline = operations.baseline(release_id)
        candidate = operations.change(baseline, change_set)
    except (ChangeError, CommandError, UnknownReleaseError) as refused:
        parser.exit(EXIT_USAGE, f"{refused.args[0]}\n")
        return EXIT_USAGE

    report = operations.validate(candidate)
    changes = operations.diff(baseline, candidate)
    record = operations.change_set(
        change_set_id=change_set.change_set_id,
        changes=changes,
        authored_by=_CLI_AUTHOR,
        base_release_id=operations.manifest(release_id).release_id,
        command_change_set_id=change_set.change_set_id,
        validation=report,
        impact=operations.impact(changes),
    )
    if output == "json":
        print(record.model_dump_json(indent=2))
    else:
        _print_provenance(record)
        _print_changes(changes, include_presentation=True)
        _print_impact(record)
        print(render_report(report, source=str(change_set_path)))
    return EXIT_DIAGNOSTICS if report.hard_errors else EXIT_OK


def _print_provenance(record: ArchitectureChangeSet) -> None:
    """Who, why and against what — the half of DATA-26 that is not the diff.

    Printed rather than only serialized, because a field an operator never sees is a field nobody
    can act on, and "recorded" is not the same as "recorded and read".
    """
    who = record.authored_by
    origin = f" via {who.tool}" if who.tool else ""
    print(f"{record.change_set_id}  by {who.author_id} ({who.author_kind.value}{origin})")
    if record.command_change_set_id is not None:
        print(f"  applying change set {record.command_change_set_id}")
    against = record.base_release_id or "no baseline"
    print(f"  against {against} -> {record.new_release_id or 'not yet published'}")
    if record.rationale:
        print(f"  rationale: {record.rationale}")
    if record.decision_references:
        print(f"  decisions: {', '.join(record.decision_references)}")
    if record.review is not None:
        review = record.review
        print(
            f"  review: {review.decision.value} by {review.reviewer.author_id} "
            f"at {review.reviewed_at.isoformat()}"
        )


def _print_impact(record: ArchitectureChangeSet) -> None:
    """What each changed object reaches, under the policy the change layer declares (CORE-30)."""
    if not record.impact:
        return
    print(f"  -- impact, under {record.impact[0].policy_id} --")
    for result in record.impact:
        reached = result.reached
        suffix = " (truncated)" if result.truncated else ""
        print(f"      {result.start} reaches {len(reached)} object(s){suffix}")


def _diff(
    parser: argparse.ArgumentParser,
    *,
    store_root: Path,
    base: str,
    candidate: str,
    include_presentation: bool,
    cross_check: bool,
    output: str,
) -> int:
    """`preview semantic diff` between two published releases (DATA-26)."""
    store = _store_at(store_root)
    try:
        base_manifest = store.read_manifest(base)
        candidate_manifest = store.read_manifest(candidate)
        changes = diff_releases(store, base_manifest, candidate_manifest)
    except (ChangeError, ReleaseError, UnknownReleaseError) as refused:
        parser.exit(EXIT_USAGE, f"{refused.args[0]}\n")
        return EXIT_USAGE
    if output == "json":
        print(changes.model_dump_json(indent=2))
        return EXIT_OK
    print(f"{base} -> {candidate}")
    _print_changes(changes, include_presentation=include_presentation)
    if not cross_check:
        return EXIT_OK
    return _cross_check(store, base_manifest, candidate_manifest)


def _cross_check(
    store: ReleaseStore, base: ArchitectureRelease, candidate: ArchitectureRelease
) -> int:
    """Two other readings of the same pair, neither of which is the narrative (DATA-57).

    Reported separately from the diff because agreement is not part of the answer: what changed is
    what the digest says changed, and these say whether two independent surfaces still describe the
    same release pair the same way.
    """
    engine = identity_disagreements(store, base, candidate)
    storage = storage_disagreements(store, base, candidate)
    tables = compared_tables(base, candidate)
    for message in (*engine, *storage):
        print(f"  DISAGREEMENT {message}")
    if engine or storage:
        return EXIT_DIAGNOSTICS
    print(
        f"  cross-check: DataFusion agrees, and the Delta change feed agrees over "
        f"{len(tables)} rewritten table(s)"
    )
    return EXIT_OK


def _print_changes(changes: ModelChanges, *, include_presentation: bool) -> None:
    """The narrative first, and presentation below a line that says what it is.

    Never interleaved. The hard gate is that a layout edit does not read as a redesign, and a
    single list sorted by identity would put one next to the other with nothing to tell them apart.
    """
    if changes.is_empty:
        print("  no semantic change")
        return
    for record in changes.narrative:
        kinds = ", ".join(kind.value for kind in record.kinds)
        print(f"  {record.collection}.{record.identity}  {kinds}")
        for field_change in record.fields:
            print(f"      {field_change.field_path}: {field_change.before} -> {field_change.after}")
    if not changes.narrative:
        print("  no semantic change")
    if include_presentation and changes.presentation:
        print(f"  -- presentation only ({len(changes.presentation)}), not architectural change --")
        for record in changes.presentation:
            for field_change in record.fields:
                print(
                    f"      {record.collection}.{record.identity}.{field_change.field_path}: "
                    f"{field_change.nature.value}"
                )


def _compare(
    parser: argparse.ArgumentParser,
    *,
    baseline_id: str,
    alternative_id: str,
    store_root: Path,
    baseline_store_root: Path,
    output: str,
) -> int:
    """Compare an alternative with its baseline, which is not a diff (DATA-28).

    A separate verb rather than a flag on `diff`, because the two return different types on
    purpose: an `AlternativeComparison` is not a `ModelChanges` and cannot be published as a change
    set. Folding them into one command would put that distinction back into a caller's memory,
    which is where it was before this wave.
    """
    baseline_store = _store_at(baseline_store_root)
    alternative_store = _store_at(store_root)
    try:
        comparison = compare_alternative(
            baseline_store.read_manifest(baseline_id),
            alternative_store.read_manifest(alternative_id),
            baseline_store=baseline_store,
            alternative_store=alternative_store,
        )
    except (ChangeError, ReleaseError, UnknownReleaseError) as refused:
        parser.exit(EXIT_USAGE, f"{refused.args[0]}\n")
        return EXIT_USAGE
    if output == "json":
        print(comparison.model_dump_json(indent=2))
        return EXIT_OK
    print(
        f"{comparison.baseline_release_id} (baseline) vs "
        f"{comparison.alternative_release_id} (alternative {comparison.scenario_id})"
    )
    print("  an alternative is a candidate design, not a revision; neither supersedes the other")
    if comparison.is_identical:
        print("  the alternative differs from its baseline in nothing")
        return EXIT_OK
    for record in comparison.differences:
        kinds = ", ".join(kind.value for kind in record.kinds)
        print(f"  {record.collection}.{record.identity}  {kinds}")
        for field_change in record.fields:
            print(f"      {field_change.field_path}: {field_change.before} -> {field_change.after}")
    return EXIT_OK


def _review(
    parser: argparse.ArgumentParser,
    report_path: Path,
    *,
    decision: str,
    reviewer: str,
    note: str | None,
    into: Path | None,
) -> int:
    """`obtain required review`. Records a decision on a change report and writes it back."""
    try:
        change_set = ArchitectureChangeSet.model_validate_json(report_path.read_text())
    except (OSError, ValidationError) as refused:
        parser.exit(EXIT_USAGE, f"{report_path}: {refused}\n")
        return EXIT_USAGE
    reviewed = ArchitectureOperations(store=_store_at(DEFAULT_STORE_ROOT)).review(
        change_set,
        reviewer=Authorship(author_id=reviewer, author_kind=AuthorKind.PERSON),
        decision=ReviewDecision(decision),
        note=note,
    )
    destination = into or report_path
    destination.write_text(reviewed.model_dump_json(indent=2))
    _print_provenance(reviewed)
    print(f"  written to {destination}")
    return EXIT_OK


def _persist(
    parser: argparse.ArgumentParser,
    source: Path,
    *,
    store_root: Path,
    expected_parent: str | None,
    release_id: str | None,
    scenario_id: str | None,
    baseline_release_id: str | None,
) -> int:
    """`persist` — everything but the pointer move (DATA-38).

    The manifest is written and the release is not current. `resume` finishes it, `discard`
    abandons it, and `releases` marks it as an orphan until one of those happens.
    """
    if (scenario_id is None) is not (baseline_release_id is None):
        parser.exit(
            EXIT_USAGE,
            "--scenario and --baseline are set together: an alternative needs both, and a "
            "release on the baseline line needs neither.\n",
        )
        return EXIT_USAGE
    return _stage_or_publish(
        parser,
        source,
        store_root=store_root,
        expected_parent=expected_parent,
        release_id=release_id,
        preserve_source=True,
        scenario_id=scenario_id,
        baseline_release_id=baseline_release_id,
        expose=False,
    )


def _output(
    parser: argparse.ArgumentParser, *, store_root: Path, release_id: str | None, output: str
) -> int:
    """`generate outputs`. Typed and truthful until W8 implements it (PROJ-35)."""
    try:
        pending = _operations(store_root).output(release_id)
    except (ChangeError, UnknownReleaseError) as refused:
        parser.exit(EXIT_USAGE, f"{refused.args[0]}\n")
        return EXIT_USAGE
    if output == "json":
        print(json.dumps({"release_id": pending.release_id, "reason": pending.reason}, indent=2))
    else:
        print(f"{pending.release_id}: not implemented — {pending.reason}")
    return EXIT_USAGE

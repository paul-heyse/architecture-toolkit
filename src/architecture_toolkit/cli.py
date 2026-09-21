"""Small, truthful scaffold CLI. Commands never imply unimplemented qualification."""

import json
from enum import StrEnum
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Final

import typer
from pydantic import ValidationError
from rich.table import Table

from architecture_toolkit.changes.alternatives import compare_alternative
from architecture_toolkit.changes.audit import compared_tables, storage_disagreements
from architecture_toolkit.changes.diff import evidence_touched
from architecture_toolkit.changes.errors import ChangeError, ReviewError
from architecture_toolkit.changes.operations import ArchitectureOperations
from architecture_toolkit.changes.record import (
    ArchitectureChangeSet,
    AuthorKind,
    Authorship,
    ReviewDecision,
)
from architecture_toolkit.changes.records import ModelChanges
from architecture_toolkit.changes.releases import diff_releases, identity_disagreements
from architecture_toolkit.cli_errors import (
    ERR_CONSOLE,
    EXIT_DIAGNOSTICS,
    EXIT_OK,
    EXIT_UNREADABLE,
    EXIT_USAGE,
    OUT_CONSOLE,
    CommandRefused,
    DiagnosticsFound,
    OperationRefused,
    SourceUnreadable,
    UnknownName,
    UsageRefusal,
)
from architecture_toolkit.contracts import SCHEMA_FAMILIES, emit, emittable
from architecture_toolkit.domain.commands import CHANGE_SET_ADAPTER, CommandError
from architecture_toolkit.domain.model import Model
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
from architecture_toolkit.releases.publication import (
    PublicationRequest,
)
from architecture_toolkit.releases.recovery import (
    discard as discard_release,
)
from architecture_toolkit.releases.recovery import (
    orphans,
)
from architecture_toolkit.releases.recovery import (
    resume as resume_release,
)
from architecture_toolkit.releases.retention import probe_readability, vacuum_table
from architecture_toolkit.releases.store import DEFAULT_STORE_ROOT, ReleaseStore
from architecture_toolkit.storage import delta
from architecture_toolkit.storage.constraints import apply_constraints, declared_constraints
from architecture_toolkit.storage.schemas import TABLE_IDS
from architecture_toolkit.validation.authoring import validate_source_text
from architecture_toolkit.validation.release import alternative_line_breaks, chain_breaks
from architecture_toolkit.validation.render import render_diagnostics, render_report

# The four exit codes and the refusal hierarchy live in `cli_errors.py` and are re-exported here,
# because `EXIT_OK` and its siblings are what the CLI tests import and have been since W1.

ROOT = Path(__file__).resolve().parents[2]

DEFAULT_POLICY = "impact.structural"
UNVERIFIED_POLICY = "dependencies.direct"
STRUCTURAL_POLICY = "containment.descendants"
"""The `graph` default. The only baseline policy that declares cycle reporting, so it is the one
under which every analysis below is defined; the others refuse what they were not declared for."""


class Analysis(StrEnum):
    """The six structural analyses `graph` runs, as a type rather than a `choices` tuple."""

    CYCLES = "cycles"
    GENERATIONS = "generations"
    COMPONENTS = "components"
    CONDENSATION = "condensation"
    CLOSURE = "closure"
    REDUCTION = "reduction"


ANALYSES: Final[tuple[str, ...]] = tuple(item.value for item in Analysis)

_STACK: Final[tuple[str, ...]] = (
    "pydantic",
    "ruamel.yaml",
    "pyarrow",
    "datafusion",
    "deltalake",
    "networkx",
)
"""What `doctor` reports. Named so the list is one thing rather than a literal inside a print."""
"""The policy `find_unverified_dependencies` traverses; named here so `--unverified` can refuse to
silently replace a policy the operator asked for."""


app: typer.Typer = typer.Typer(
    name="architecture",
    help="Typed architecture models, coherent releases and standards projections.",
    no_args_is_help=True,
    # `--install-completion` writes into the user's shell rc files. A tool whose own contracts
    # forbid reaching outside the project should not offer that by default, and the two options it
    # adds would appear in the generated reference as though they were part of the surface.
    add_completion=False,
    # Deterministic tracebacks. Typer's pretty handler is installed process-globally on every
    # invocation, and this package is imported as a library as well as run as a command.
    pretty_exceptions_enable=False,
)


class Format(StrEnum):
    """How a command answers. Two words, and the same two everywhere.

    Before this there were three vocabularies — `human|json`, `table|json`, `summary|json` — for
    one concept, so a script had to know which of three spellings each verb took. Typer validates
    the enum at parse time and lists it in `--help`, which makes "one word means one thing" a
    property of the type rather than of review.
    """

    HUMAN = "human"
    JSON = "json"


# Shared parameter declarations. `--store` was copy-pasted into 18 parsers and `--release` into
# seven, which is how their help strings drifted apart.
StoreOption = Annotated[Path, typer.Option("--store", help="Release store root.")]
ReleaseOption = Annotated[
    str | None, typer.Option("--release", help="Defaults to the current release.")
]
FormatOption = Annotated[Format, typer.Option("--format", help="How to render the answer.")]
ParamOption = Annotated[
    list[str] | None,
    typer.Option("--param", metavar="NAME=VALUE", help="Bind one declared parameter. Repeatable."),
]


def main() -> int:
    """Run one command and answer with its exit code.

    Every refusal reaches here as a `CommandRefused`, which knows its own code and stream. That is
    the whole of the error contract: one place writes, and nothing below has to remember whether a
    given failure belongs on stdout or stderr.

    `standalone_mode=False` is what keeps `main` returning an integer rather than exiting, which is
    what `[project.scripts]` declares and what every CLI test asserts against.
    """
    try:
        # With `standalone_mode=False` a `typer.Exit` is *returned* as its code rather than
        # exiting, which is exactly the contract `[project.scripts]` and every CLI test expect.
        return int(app(standalone_mode=False) or EXIT_OK)
    except CommandRefused as refused:
        return refused.report()
    except typer.Exit as exiting:
        return exiting.exit_code
    except typer.Abort:
        ERR_CONSOLE.print("Aborted.", highlight=False, markup=False)
        return EXIT_USAGE
    except typer.TyperException as bad:
        # Typer's own parse failures: an unknown flag, a value outside an enum, a path that is not
        # there. It already carries the right code — 2 for a usage error — and rendering it through
        # the same console our refusals use means every error the tool emits wraps the same way.
        ERR_CONSOLE.print(bad.format_message(), highlight=False, markup=False)
        return bad.exit_code


@app.command()
def doctor() -> None:
    """Report the installed Python stack."""
    print(
        json.dumps(
            {name: version(name) for name in _STACK},
            indent=2,
        )
    )


@app.command()
def validate(
    source: Annotated[Path, typer.Argument(help="A YAML model to validate.")],
    output: FormatOption = Format.HUMAN,
) -> None:
    """Validate a source model and report what was checked."""
    raise typer.Exit(code=_validate(source, output=output.value))


@app.command()
def schema(
    family: Annotated[str | None, typer.Option(help="Emit one family to stdout.")] = None,
    write: Annotated[
        bool, typer.Option("--write", help="Write every emittable family to its declared path.")
    ] = False,
) -> None:
    """Print or write the generated JSON Schema contracts."""
    raise typer.Exit(code=_schema(family_id=family, write=write))


@app.command()
def publish(
    source: Annotated[Path, typer.Argument(help="A YAML model to publish.")],
    store: StoreOption = DEFAULT_STORE_ROOT,
    expect_parent: Annotated[
        str | None,
        typer.Option(
            "--expect-parent",
            help="The release the candidate was built against; pass an empty value for the first.",
        ),
    ] = None,
    release_id: Annotated[
        str | None, typer.Option("--release-id", help="Defaults to the next rel-NNNN in the store.")
    ] = None,
    no_source_snapshot: Annotated[
        bool,
        typer.Option(
            "--no-source-snapshot",
            help="Pin only the source revision and digest; do not copy it into the release.",
        ),
    ] = False,
    scenario: Annotated[
        str | None, typer.Option(help="Publish as a design alternative under this scenario id.")
    ] = None,
    baseline: Annotated[
        str | None, typer.Option(help="The release this alternative is derived from.")
    ] = None,
    change_report: Annotated[
        Path | None,
        typer.Option(help="A change report from `change --format json`, optionally reviewed."),
    ] = None,
    require_review: Annotated[
        bool,
        typer.Option(
            "--require-review", help="Refuse unless the change report carries an approval."
        ),
    ] = False,
) -> None:
    """Publish a source model as a coherent release."""
    raise typer.Exit(
        code=_stage_or_publish(
            source,
            store_root=store,
            expected_parent=expect_parent,
            release_id=release_id,
            preserve_source=not no_source_snapshot,
            scenario_id=scenario,
            baseline_release_id=baseline,
            change_report=change_report,
            require_review=require_review,
            expose=True,
        )
    )


@app.command()
def persist(
    source: Annotated[Path, typer.Argument(help="A YAML model to stage.")],
    store: StoreOption = DEFAULT_STORE_ROOT,
    expect_parent: Annotated[
        str | None,
        typer.Option(
            "--expect-parent",
            help="The release the candidate was built against; pass an empty value for the first.",
        ),
    ] = None,
    release_id: Annotated[
        str | None, typer.Option("--release-id", help="Defaults to the next rel-NNNN in the store.")
    ] = None,
    scenario: Annotated[
        str | None, typer.Option(help="Publish as a design alternative under this scenario id.")
    ] = None,
    baseline: Annotated[
        str | None, typer.Option(help="The release this alternative is derived from.")
    ] = None,
    change_report: Annotated[
        Path | None,
        typer.Option(help="A change report from `change --format json`, optionally reviewed."),
    ] = None,
) -> None:
    """Stage a release and write its manifest without exposing it."""
    raise typer.Exit(
        code=_persist(
            source,
            store_root=store,
            expected_parent=expect_parent,
            release_id=release_id,
            scenario_id=scenario,
            baseline_release_id=baseline,
            change_report=change_report,
        )
    )


@app.command()
def releases(
    store: StoreOption = DEFAULT_STORE_ROOT,
    verify: Annotated[
        bool, typer.Option("--verify", help="Read every pinned version back.")
    ] = False,
    output: FormatOption = Format.HUMAN,
) -> None:
    """List published releases and whether they resolve."""
    raise typer.Exit(code=_releases(store_root=store, verify=verify, output=output.value))


@app.command()
def show(
    release_id: Annotated[str, typer.Argument(help="The release to print.")],
    store: StoreOption = DEFAULT_STORE_ROOT,
) -> None:
    """Print one release manifest."""
    raise typer.Exit(code=_show(release_id, store_root=store))


@app.command()
def archive(
    release_id: Annotated[str, typer.Argument(help="The release to archive.")],
    store: StoreOption = DEFAULT_STORE_ROOT,
    into: Annotated[Path | None, typer.Option(help="Where to write the archive.")] = None,
) -> None:
    """Write a self-contained milestone archive."""
    raise typer.Exit(code=_archive(release_id, store_root=store, into=into))


@app.command()
def resume(
    release_id: Annotated[str, typer.Argument(help="The persisted release to expose.")],
    store: StoreOption = DEFAULT_STORE_ROOT,
) -> None:
    """Finish a publication whose manifest exists but never became current."""
    raise typer.Exit(code=_resume(release_id, store_root=store))


@app.command()
def discard(
    release_id: Annotated[str, typer.Argument(help="The orphan manifest to remove.")],
    store: StoreOption = DEFAULT_STORE_ROOT,
) -> None:
    """Remove an orphan manifest."""
    raise typer.Exit(code=_discard(release_id, store_root=store))


@app.command()
def constraints(
    store: StoreOption = DEFAULT_STORE_ROOT,
    apply: Annotated[bool, typer.Option("--apply", help="Write the declared constraints.")] = False,
) -> None:
    """Report or apply the declared Delta table constraints."""
    raise typer.Exit(code=_constraints(store_root=store, apply=apply))


@app.command()
def vacuum(
    store: StoreOption = DEFAULT_STORE_ROOT,
    apply: Annotated[bool, typer.Option("--apply", help="Actually remove the files.")] = False,
) -> None:
    """Remove files no retained release needs."""
    raise typer.Exit(code=_vacuum(store_root=store, apply=apply))


@app.command()
def recipes(
    recipe_id: Annotated[str | None, typer.Argument(help="Describe one recipe.")] = None,
    output: FormatOption = Format.HUMAN,
) -> None:
    """List the versioned query recipes, or describe one."""
    raise typer.Exit(code=_recipes(recipe_id, output=output.value))


@app.command()
def query(
    recipe_id: Annotated[str, typer.Argument(help="The recipe to run.")],
    store: StoreOption = DEFAULT_STORE_ROOT,
    release: ReleaseOption = None,
    base: Annotated[str | None, typer.Option(help="The base side of a comparison.")] = None,
    candidate: Annotated[
        str | None, typer.Option(help="The candidate side of a comparison.")
    ] = None,
    param: ParamOption = None,
    output: FormatOption = Format.HUMAN,
) -> None:
    """Run one query recipe against a release."""
    raise typer.Exit(
        code=_query(
            recipe_id,
            store_root=store,
            release_id=release,
            base=base,
            candidate=candidate,
            params=list(param or ()),
            output=output.value,
        )
    )


@app.command()
def plan(
    recipe_id: Annotated[str, typer.Argument(help="The recipe to plan.")],
    store: StoreOption = DEFAULT_STORE_ROOT,
    release: ReleaseOption = None,
    param: ParamOption = None,
) -> None:
    """Show what the engine plans for one recipe."""
    raise typer.Exit(
        code=_plan(recipe_id, store_root=store, release_id=release, params=list(param or ()))
    )


@app.command()
def impact(
    element_id: Annotated[str, typer.Argument(help="Where the traversal starts.")],
    store: StoreOption = DEFAULT_STORE_ROOT,
    release: ReleaseOption = None,
    policy: Annotated[
        str | None,
        typer.Option(
            help=f"A named policy; `impact --policy list` shows them. Default {DEFAULT_POLICY}."
        ),
    ] = None,
    unverified: Annotated[
        bool, typer.Option("--unverified", help="Report only dependencies that are not qualified.")
    ] = False,
    output: FormatOption = Format.HUMAN,
) -> None:
    """Bounded, explainable traversal from one object."""
    raise typer.Exit(
        code=_impact(
            element_id,
            store_root=store,
            release_id=release,
            policy_id=policy,
            unverified=unverified,
            output=output.value,
        )
    )


@app.command()
def graph(
    analysis: Annotated[Analysis, typer.Argument(help="Which structural analysis to run.")],
    store: StoreOption = DEFAULT_STORE_ROOT,
    release: ReleaseOption = None,
    policy: Annotated[
        str, typer.Option(help=f"A named policy. Defaults to {STRUCTURAL_POLICY}.")
    ] = STRUCTURAL_POLICY,
    output: FormatOption = Format.HUMAN,
) -> None:
    """Structural analyses over one release's graph."""
    raise typer.Exit(
        code=_graph(
            analysis.value,
            store_root=store,
            release_id=release,
            policy_id=policy,
            output=output.value,
        )
    )


@app.command()
def baseline(
    store: StoreOption = DEFAULT_STORE_ROOT,
    release: ReleaseOption = None,
    output: FormatOption = Format.HUMAN,
) -> None:
    """Print the model a release holds."""
    raise typer.Exit(code=_baseline(store_root=store, release_id=release, output=output.value))


@app.command()
def change(
    change_set: Annotated[Path, typer.Argument(help="A JSON change set (CORE-10).")],
    store: StoreOption = DEFAULT_STORE_ROOT,
    release: ReleaseOption = None,
    output: FormatOption = Format.HUMAN,
    rationale: Annotated[
        str | None,
        typer.Option(help="Why this change was made. A sentence; Notion owns the narrative."),
    ] = None,
    author: Annotated[
        str | None, typer.Option(help="Who made it. Defaults to the CLI itself.")
    ] = None,
    decision: Annotated[
        list[str] | None,
        typer.Option("--decision", help="A Reference id justifying it. Repeatable."),
    ] = None,
) -> None:
    """Apply a typed change set to a release and report what it would do."""
    raise typer.Exit(
        code=_change(
            change_set,
            store_root=store,
            release_id=release,
            output=output.value,
            rationale=rationale,
            author=author,
            decisions=tuple(decision or ()),
        )
    )


@app.command()
def diff(
    base: Annotated[str, typer.Option(help="The baseline release.")],
    candidate: Annotated[str, typer.Option(help="The candidate release.")],
    store: StoreOption = DEFAULT_STORE_ROOT,
    include_presentation: Annotated[
        bool,
        typer.Option(
            "--include-presentation",
            help="Also print layout and display changes, which are never part of the narrative.",
        ),
    ] = False,
    cross_check: Annotated[
        bool,
        typer.Option(
            "--cross-check",
            help="Check the narrative against DataFusion and the Delta change feed (DATA-57).",
        ),
    ] = False,
    output: FormatOption = Format.HUMAN,
) -> None:
    """Explain what changed between two releases."""
    raise typer.Exit(
        code=_diff(
            store_root=store,
            base=base,
            candidate=candidate,
            include_presentation=include_presentation,
            cross_check=cross_check,
            output=output.value,
        )
    )


@app.command()
def compare(
    baseline: Annotated[str, typer.Option("--baseline", help="A release on the baseline line.")],
    alternative: Annotated[str, typer.Option(help="A release on a scenario line.")],
    store: StoreOption = DEFAULT_STORE_ROOT,
    baseline_store: Annotated[
        Path | None,
        typer.Option(help="Where the baseline lives. Defaults to --store."),
    ] = None,
    output: FormatOption = Format.HUMAN,
) -> None:
    """Compare a design alternative with the baseline it declares."""
    raise typer.Exit(
        code=_compare(
            baseline_id=baseline,
            alternative_id=alternative,
            store_root=store,
            baseline_store_root=baseline_store or store,
            output=output.value,
        )
    )


@app.command()
def review(
    change_report: Annotated[
        Path, typer.Argument(help="A change report written by `change --format json`.")
    ],
    decision: Annotated[ReviewDecision, typer.Option(help="The reviewer's conclusion.")],
    reviewer: Annotated[str, typer.Option(help="Who reviewed it.")],
    note: Annotated[str | None, typer.Option(help="Why.")] = None,
    into: Annotated[Path | None, typer.Option(help="Where to write the reviewed report.")] = None,
    store: StoreOption = DEFAULT_STORE_ROOT,
) -> None:
    """Record a decision on a change report."""
    raise typer.Exit(
        code=_review(
            change_report,
            decision=decision.value,
            reviewer=reviewer,
            note=note,
            into=into,
            store_root=store,
        )
    )


@app.command()
def output(
    store: StoreOption = DEFAULT_STORE_ROOT,
    release: ReleaseOption = None,
    format: FormatOption = Format.HUMAN,
) -> None:
    """Reserved: distribute a release's outputs (W8)."""
    raise typer.Exit(code=_output(store_root=store, release_id=release, output=format.value))


@app.command()
def build() -> None:
    """Reserved: the full projection pipeline is not implemented."""
    raise UsageRefusal("Not implemented: follow docs/implementation-contract.md.")


def _schema(*, family_id: str | None, write: bool) -> int:
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
            raise UnknownName(f"No emittable schema family named {family_id!r}.")
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


def _store_at(root: Path) -> ReleaseStore:
    return ReleaseStore.at(root)


def _stage_or_publish(
    source: Path,
    *,
    store_root: Path,
    expected_parent: str | None,
    release_id: str | None,
    preserve_source: bool,
    scenario_id: str | None,
    baseline_release_id: str | None,
    change_report: Path | None,
    require_review: bool,
    expose: bool,
) -> int:
    """`publish` and `persist` differ in the eighth protocol line and in nothing else.

    One body rather than two, because two would eventually validate a source differently depending
    on which verb an operator typed — and the whole point of the split is that the *only* thing
    that differs is whether the current pointer moves.

    Both go through `ArchitectureOperations`, which is what makes DATA-38's *"through a small API
    and CLI"* true of the second half of the lifecycle. Before this they called the publication
    protocol directly, so `change_report_digest` was never written by any CLI path, the hard-error
    refusal and the review gate never ran, and `architecture review` wrote a file no verb consumed.
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
    # Three states, carried by the type rather than by a sentinel object: absent is `None`,
    # "there is no parent" is the empty string, and anything else names one. The sentinel existed
    # only because argparse could not tell absent from `None`, and `str(None)` is the literal
    # `"None"` — which is the parent id a publication would then claim to have been built against.
    if expected_parent is None:
        if current is not None:
            raise UsageRefusal(f"--expect-parent is required: the current release is {current!r}.")
        parent: str | None = None
    else:
        parent = expected_parent or None

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
    record = _change_record(change_report)
    operations = _operations(store_root)
    try:
        manifest = (
            operations.publish(request, change_set=record, require_review=require_review)
            if expose
            else operations.persist(request, change_set=record)
        )
    except (ReleaseError, ValidationError) as refused:
        raise OperationRefused(f"{type(refused).__name__}: {refused}") from refused
    except ReviewError as refused:
        raise UsageRefusal(refused.args[0]) from refused
    except ChangeError as refused:
        raise OperationRefused(refused.args[0]) from refused

    reused = sum(1 for ref in manifest.tables if _reused(store, manifest, ref.table_id))
    verb = "published" if expose else "persisted"
    print(f"{verb} {manifest.release_id} ({len(manifest.tables)} tables, {reused} reused)")
    print(f"model digest {manifest.model_digest}")
    if not expose:
        print(f"not current: {store.current_id() or 'nothing'} still is; `resume` completes it")
    return EXIT_OK


def _change_record(path: Path | None) -> ArchitectureChangeSet | None:
    """Read the change report a publication is carrying, if it was given one.

    The file `change --format json` writes and `review` annotates. Reading it here is what closes
    the lifecycle: without it `review`'s output had no consumer at all.
    """
    if path is None:
        return None
    try:
        return ArchitectureChangeSet.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as refused:
        raise SourceUnreadable(f"{path}: {refused}") from refused


def _reused(store: ReleaseStore, manifest: ArchitectureRelease, table_id: str) -> bool:
    parent_id = manifest.parent_release_id
    if parent_id is None or not store.has_manifest(parent_id):
        return False
    try:
        previous = store.read_manifest(parent_id).table(table_id)
    except KeyError:
        return False
    return previous.delta_version == manifest.table(table_id).delta_version


def _releases(*, store_root: Path, verify: bool, output: str) -> int:
    """List what has been published, and optionally prove each one still resolves.

    The JSON form exists because "which releases are here and which is current" is a question a
    script asks far more often than a person does, and parsing the `*`/`!` markers back out of the
    human rendering is exactly the kind of thing a machine-readable path is for.
    """
    store = _store_at(store_root)
    current = store.current_id()
    ids = store.release_ids()
    stranded = set(orphans(store))
    if output == "json":
        print(
            json.dumps(
                [
                    {
                        "release_id": release_id,
                        "model_id": store.read_manifest(release_id).model_id,
                        "published_at": store.read_manifest(release_id).published_at.isoformat(),
                        "is_current": release_id == current,
                        "is_orphan": release_id in stranded,
                    }
                    for release_id in ids
                ],
                indent=2,
            )
        )
        if not verify:
            return EXIT_OK
    elif not ids:
        print(f"no releases in {store_root}")
        return EXIT_OK
    else:
        for release_id in ids:
            manifest = store.read_manifest(release_id)
            marker = "*" if release_id == current else ("!" if release_id in stranded else " ")
            note = "  (orphan: never became current)" if release_id in stranded else ""
            print(
                f"{marker} {release_id}  {manifest.model_id}  "
                f"{manifest.published_at.isoformat()}{note}"
            )
        if stranded:
            print(f"{len(stranded)} orphan(s); `resume` completes one, `discard` removes it")
        if not verify:
            return EXIT_OK
    if not ids:
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
        raise DiagnosticsFound(render_diagnostics(findings, source=str(store_root)))
    if output != "json":
        print(
            f"every pinned version of {len(ids)} release(s) reads back, and the chain is navigable"
        )
    return EXIT_OK


def _show(release_id: str, *, store_root: Path) -> int:
    try:
        manifest = _store_at(store_root).read_manifest(release_id)
    except UnknownReleaseError as unknown:
        raise UnknownName(f"No release {release_id!r} in {store_root}.") from unknown
    print(manifest.model_dump_json(indent=2))
    return EXIT_OK


def _archive(release_id: str, *, store_root: Path, into: Path | None) -> int:
    store = _store_at(store_root)
    try:
        manifest = store.read_manifest(release_id)
    except UnknownReleaseError as unknown:
        raise UnknownName(f"No release {release_id!r} in {store_root}.") from unknown
    try:
        result = write_archive(store, manifest, into)
    except ArchiveError as refused:
        raise OperationRefused(f"ArchiveError: {refused}") from refused
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
            raise OperationRefused(f"{table_id}: refused - {refused}") from refused
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


def _resume(release_id: str, *, store_root: Path) -> int:
    """Finish a publication that got as far as writing its manifest.

    No re-staging: by the time a manifest exists its versions have been read back and verified,
    and the only thing that did not happen is the pointer move.
    """
    store = _store_at(store_root)
    try:
        manifest = resume_release(store, release_id)
    except UnknownReleaseError as unknown:
        raise UnknownName(f"No release {release_id!r} in {store_root}.") from unknown
    except ReleaseError as refused:
        raise OperationRefused(f"{type(refused).__name__}: {refused}") from refused
    print(f"resumed {manifest.release_id}; it is now the current release")
    return EXIT_OK


def _discard(release_id: str, *, store_root: Path) -> int:
    store = _store_at(store_root)
    try:
        discard_release(store, release_id)
    except UnknownReleaseError as unknown:
        raise UnknownName(f"No release {release_id!r} in {store_root}.") from unknown
    except ReleaseError as refused:
        raise OperationRefused(f"{type(refused).__name__}: {refused}") from refused
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


def _recipes(recipe_id: str | None, *, output: str) -> int:
    """List the recipes, or print one recipe's whole declared contract.

    The JSON form is the recipe record itself, which is already a published contract root in the
    `query-contract` family — so a consumer gets the same shape `architecture schema` describes
    rather than a second, prose-shaped rendering of it.
    """
    if output == "json":
        if recipe_id is None:
            print(json.dumps([json.loads(r.model_dump_json()) for r in RECIPES.values()], indent=2))
            return EXIT_OK
        try:
            print(recipe_for(recipe_id).model_dump_json(indent=2))
        except KeyError as unknown:
            raise UnknownName(unknown.args[0]) from unknown
        return EXIT_OK
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
        raise UnknownName(unknown.args[0]) from unknown
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


def _executor(store_root: Path, release_id: str | None) -> tuple[ReleaseQueryExecutor, str]:
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
        raise UsageRefusal(f"{missing.args[0]}.") from missing
    except UnknownReleaseError as unknown:
        raise UnknownName(unknown.args[0]) from unknown
    return executor, chosen


def _bound(recipe: QueryRecipe, pairs: list[str]) -> dict[str, object]:
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
            raise UsageRefusal(f"--param expects NAME=VALUE, got {pair!r}.")
        spec = declared.get(name)
        if spec is None:
            raise UsageRefusal(
                f"{recipe.query_recipe_id} declares no parameter {name!r}; "
                f"it takes {sorted(declared) or 'none'}."
            )
        bound[name] = _typed(spec, raw)
    return bound


def _typed(spec: ParameterSpec, raw: str) -> object:
    if spec.data_type == "string":
        return raw
    if spec.data_type == "integer":
        try:
            return int(raw)
        except ValueError as not_an_integer:
            raise UsageRefusal(f"${spec.name} is an integer; got {raw!r}.") from not_an_integer
    if spec.data_type == "boolean":
        if raw.lower() not in {"true", "false"}:
            raise UsageRefusal(f"${spec.name} is a boolean; got {raw!r}.")
        return raw.lower() == "true"
    raise UsageRefusal(f"${spec.name} is a {spec.data_type}, which --param cannot supply.")


def _query(
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
        raise UnknownName(unknown.args[0]) from unknown
    sides = (base, candidate)
    if any(sides) and release_id is not None:
        raise UsageRefusal("Give --release or both of --base and --candidate, not both.")
    if any(sides) and not all(sides):
        raise UsageRefusal("A comparison needs both --base and --candidate.")
    executor = ReleaseQueryExecutor(_store_at(store_root))
    bound = _bound(recipe, params)
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
        raise UsageRefusal(refused.args[0]) from refused
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
        raise UnknownName(unknown.args[0]) from unknown
    executor, chosen = _executor(store_root, release_id)
    graph = executor.graph_for(chosen)
    try:
        answer = _analyse(analysis, graph, policy)
    except QueryError as refused:
        raise UsageRefusal(refused.args[0]) from refused
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
    """Render a result set, letting rich do the column arithmetic.

    `box=None, pad_edge=False` reproduces what the hand-rolled printer emitted — two spaces between
    left-justified columns, no borders — so the assertions that read this output did not move. What
    it adds is a header style when a terminal is attached, and eleven fewer lines of width
    arithmetic to be wrong.
    """
    if not rows:
        OUT_CONSOLE.print("(no rows)", highlight=False, markup=False)
        return
    table = Table(box=None, pad_edge=False, header_style="bold")
    for column in columns:
        table.add_column(column, overflow="fold")
    for row in rows:
        table.add_row(*(str(row[column]) for column in columns))
    OUT_CONSOLE.print(table)


def _plan(
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
        raise UnknownName(unknown.args[0]) from unknown
    if recipe.release_context != "single":
        raise UsageRefusal(f"{recipe_id} compares two releases; the CLI plans one.")
    executor, chosen = _executor(store_root, release_id)
    bound = _bound(recipe, params)
    try:
        evidence = capture(recipe, executor.context_for(chosen), bound)
    except QueryError as refused:
        raise UsageRefusal(refused.args[0]) from refused
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
        raise UsageRefusal(
            f"--unverified traverses {UNVERIFIED_POLICY}; drop --policy {policy_id} or the flag."
        )
        return EXIT_USAGE
    chosen_policy = policy_id or (UNVERIFIED_POLICY if unverified else DEFAULT_POLICY)
    try:
        policy = policy_for(chosen_policy)
    except KeyError as unknown:
        raise UnknownName(unknown.args[0]) from unknown
    executor, chosen = _executor(store_root, release_id)
    try:
        graph = executor.graph_for(chosen)
        result = (
            find_unverified_dependencies(graph, executor.context_for(chosen), element_id)
            if unverified
            else graph.traverse(policy, element_id)
        )
    except QueryError as refused:
        raise UsageRefusal(refused.args[0]) from refused
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


def _authorship(author: str | None) -> Authorship:
    """Who a change report says produced it.

    A person when `--author` names one, the CLI itself otherwise. DATA-26 asks for authorship, and
    "the CLI ran" is a true answer where a hardcoded constant on every record is an incomplete one.
    """
    if author is None:
        return _CLI_AUTHOR
    return Authorship(author_id=author, author_kind=AuthorKind.PERSON)


def _operations(store_root: Path) -> ArchitectureOperations:
    return ArchitectureOperations(store=_store_at(store_root))


def _baseline(*, store_root: Path, release_id: str | None, output: str) -> int:
    """`load baseline`. What an operator is about to change, read back from the release itself."""
    try:
        model = _operations(store_root).baseline(release_id)
    except (ChangeError, UnknownReleaseError) as refused:
        raise UsageRefusal(refused.args[0]) from refused
    if output == "json":
        print(model.model_dump_json(indent=2))
        return EXIT_OK
    print(f"{model.model_id}  schema {model.schema_version}  profile {model.profile_version}")
    for name, _ in MODEL_COLLECTIONS:
        print(f"  {len(getattr(model, name)):4d}  {name}")
    return EXIT_OK


def _change(
    change_set_path: Path,
    *,
    store_root: Path,
    release_id: str | None,
    output: str,
    rationale: str | None,
    author: str | None,
    decisions: tuple[str, ...],
) -> int:
    """`apply typed change set` then `validate` then `preview semantic diff` — the dry run.

    Nothing is written. The whole point of the first four lifecycle steps is that an operator sees
    what a change does before deciding to keep it, so this command has no way to keep it.
    """
    operations = _operations(store_root)
    try:
        change_set = CHANGE_SET_ADAPTER.validate_json(change_set_path.read_text())
    except (OSError, ValidationError) as refused:
        raise SourceUnreadable(f"{change_set_path}: {refused}") from refused
    try:
        baseline = operations.baseline(release_id)
        candidate = operations.change(baseline, change_set)
    except (ChangeError, CommandError, UnknownReleaseError) as refused:
        raise UsageRefusal(refused.args[0]) from refused

    report = operations.validate(candidate)
    changes = operations.diff(baseline, candidate)
    record = operations.change_set(
        change_set_id=change_set.change_set_id,
        changes=changes,
        authored_by=_authorship(author),
        base_release_id=operations.manifest(release_id).release_id,
        command_change_set_id=change_set.change_set_id,
        rationale=rationale,
        decision_references=decisions,
        validation=report,
        impact=operations.impact(changes),
    )
    if output == "json":
        print(record.model_dump_json(indent=2))
    else:
        _print_provenance(record)
        _print_changes(changes, include_presentation=True)
        _print_evidence(baseline, changes)
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
    produced = "not yet published" if record.is_preview else record.new_release_id
    print(f"  against {against} -> {produced}")
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


def _print_evidence(model: Model, changes: ModelChanges) -> None:
    """Which changed fields carried evidence that now points at something that moved.

    Nothing is invalid when this fires — which is exactly why it is worth saying out loud. A
    `ReferenceLink` justifying `detail.timeout_ms` still resolves after the timeout changes, and
    it no longer justifies what it appears to.
    """
    touched = evidence_touched(model, changes)
    if not touched:
        return
    print(f"  -- evidence attached to changed fields ({len(touched)}) --")
    for path, reference_id in touched:
        print(f"      {path}  <- {reference_id}")


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
        raise UsageRefusal(refused.args[0]) from refused
    if output == "json":
        print(changes.model_dump_json(indent=2))
        # `--cross-check` used to be a silent no-op here: the JSON branch returned before reaching
        # it, including in the case where it would have reported a disagreement. A flag a CI job
        # wires in and that quietly does nothing is worse than no flag.
        if not cross_check:
            return EXIT_OK
        return _cross_check(store, base_manifest, candidate_manifest, narrate=False)
    print(f"{base} -> {candidate}")
    _print_changes(changes, include_presentation=include_presentation)
    if not cross_check:
        return EXIT_OK
    return _cross_check(store, base_manifest, candidate_manifest, narrate=True)


def _cross_check(
    store: ReleaseStore,
    base: ArchitectureRelease,
    candidate: ArchitectureRelease,
    *,
    narrate: bool,
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
        ERR_CONSOLE.print(f"DISAGREEMENT {message}", highlight=False, markup=False)
    if engine or storage:
        return EXIT_DIAGNOSTICS
    if not narrate:
        # `--format json` promises pure JSON on stdout — three tests validate it against generated
        # schemas — so the agreement line is simply not printed rather than moved somewhere a
        # consumer would have to filter out. A disagreement still reaches stderr and exit 1.
        return EXIT_OK
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
        raise UsageRefusal(refused.args[0]) from refused
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
    report_path: Path,
    *,
    decision: str,
    reviewer: str,
    note: str | None,
    into: Path | None,
    store_root: Path,
) -> int:
    """`obtain required review`. Records a decision on a change report and writes it back.

    Takes `--store` like every sibling verb. It previously bound `DEFAULT_STORE_ROOT` purely to
    reach the operations clock, which is a store binding with no reason and the only lifecycle verb
    missing the flag.
    """
    try:
        change_set = ArchitectureChangeSet.model_validate_json(report_path.read_text())
    except (OSError, ValidationError) as refused:
        raise SourceUnreadable(f"{report_path}: {refused}") from refused
    reviewed = _operations(store_root).review(
        change_set,
        reviewer=Authorship(author_id=reviewer, author_kind=AuthorKind.PERSON),
        decision=ReviewDecision(decision),
        note=note,
    )
    destination = into or report_path
    try:
        destination.write_text(reviewed.model_dump_json(indent=2))
    except OSError as unwritable:
        raise UsageRefusal(f"cannot write {destination}: {unwritable}") from unwritable
    _print_provenance(reviewed)
    print(f"  written to {destination}")
    return EXIT_OK


def _persist(
    source: Path,
    *,
    store_root: Path,
    expected_parent: str | None,
    release_id: str | None,
    scenario_id: str | None,
    baseline_release_id: str | None,
    change_report: Path | None,
) -> int:
    """`persist` — everything but the pointer move (DATA-38).

    The manifest is written and the release is not current. `resume` finishes it, `discard`
    abandons it, and `releases` marks it as an orphan until one of those happens.
    """
    if (scenario_id is None) is not (baseline_release_id is None):
        raise UsageRefusal(
            "--scenario and --baseline are set together: an alternative needs both, and a "
            "release on the baseline line needs neither."
        )
    return _stage_or_publish(
        source,
        store_root=store_root,
        expected_parent=expected_parent,
        release_id=release_id,
        preserve_source=True,
        scenario_id=scenario_id,
        baseline_release_id=baseline_release_id,
        change_report=change_report,
        require_review=False,
        expose=False,
    )


def _output(*, store_root: Path, release_id: str | None, output: str) -> int:
    """`generate outputs`. Typed and truthful until W8 implements it (PROJ-35)."""
    try:
        pending = _operations(store_root).output(release_id)
    except (ChangeError, UnknownReleaseError) as refused:
        raise UsageRefusal(refused.args[0]) from refused
    if output == "json":
        print(json.dumps({"release_id": pending.release_id, "reason": pending.reason}, indent=2))
    else:
        print(f"{pending.release_id}: not implemented — {pending.reason}")
    return EXIT_USAGE

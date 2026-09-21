"""The publication protocol, as eight individually addressable steps (DATA-23, DATA-24).

`docs/contracts/data.md` states the protocol as an eight-line fence, and `STEP_ORDER` reproduces
those eight lines in order. Each is a `Step`: a pure-ish function from one `PublicationState` to
the next, registered by name in `STEPS`, and `publish` is a fold over them.

**The shape is the point, not an implementation detail.** Two requirements need it. DATA-24's hard
gate is "fault injection after every publication stage never exposes partial state", which means a
test has to be able to fail *one named stage* and inspect what survived — not fail somewhere
inside a monolith and hope it was the right somewhere. And CORE-46 asks W9 for a
`RuleBasedStateMachine` over "stage/fail/retry/stale-parent/publish/migrate/historical-read
operations", which needs the steps to be individually callable. Designing that in later is
expensive, so it is designed in now.

**Step eight is the commit point.** Steps one to seven can all succeed and the release still not
exist, because a release exists when `CURRENT` names it. That is what makes a crash survivable:
orphan Delta versions and an orphan manifest are permitted by DATA-24, and the previous release
keeps resolving exactly as it did.

**Delta gives no cross-table atomicity and this does not pretend otherwise.** Eleven tables means
eleven commits. The lock makes them sequential, the expected-parent check makes them purposeful,
the read-back makes them verified, and the pointer makes them visible — all at the application
layer, which is what DATA-20 insists this is.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from architecture_toolkit.domain.commands import ChangeSet, build_candidate
from architecture_toolkit.domain.identifiers import ReleaseId
from architecture_toolkit.domain.model import Model
from architecture_toolkit.domain.registry import BASELINE_PROFILE, Profile
from architecture_toolkit.domain.semantics import model_digest, stamp_digests
from architecture_toolkit.releases.candidate import ReleaseCandidate
from architecture_toolkit.releases.errors import (
    ReadBackMismatchError,
    ReleaseError,
    StaleParentError,
)
from architecture_toolkit.releases.lock import publication_lock
from architecture_toolkit.releases.manifest import ArchitectureRelease, SourceBundle
from architecture_toolkit.releases.provenance import digest_bytes, generator_provenance
from architecture_toolkit.releases.reader import read_model, read_table_set
from architecture_toolkit.releases.staging import StagedTable, stage_tables
from architecture_toolkit.releases.store import ReleaseStore
from architecture_toolkit.storage.digests import table_set_digests
from architecture_toolkit.storage.mappings import TableSet, assemble_model, compile_tables
from architecture_toolkit.storage.schemas import TABLE_IDS
from architecture_toolkit.validation.claims import ValidationClaimReport
from architecture_toolkit.validation.pipeline import validate_model
from architecture_toolkit.validation.release import digest_mismatches, row_count_mismatches

__all__ = [
    "STEPS",
    "STEP_ORDER",
    "DeltaPublisher",
    "PublicationRequest",
    "PublicationState",
    "Step",
    "publish",
]

type Clock = Callable[[], datetime]


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class PublicationRequest:
    """Everything a publication needs, decided before it starts.

    `expected_parent` is required rather than defaulted. DATA-23 asks that "every change set
    specifies its expected parent release", and a default would let a caller publish against a
    parent it never looked at — which is the stale-parent failure, arrived at by omission.

    `now` is injected so a fault-injection test is deterministic (CORE-51) without the manifest
    giving up a real `published_at`.
    """

    store: ReleaseStore
    candidate: ReleaseCandidate
    expected_parent: ReleaseId | None
    source_text: str | None = None
    """The exact text the candidate was parsed from, so step seven can preserve it without
    re-reading a file that may have changed since. `None` means there is nothing to preserve —
    a model built in process rather than authored."""

    change_set: ChangeSet | None = None
    profile: Profile = BASELINE_PROFILE
    attempt: int | None = None
    now: Clock = _now
    generator_commit: str | None = None
    preserve_source: bool = True
    """Copy the authored source into the release's artifacts (DATA-37, DATA-25).

    On by default because a milestone archive is supposed to be readable without the repository
    it came from, and a git revision does not help there. Off is the "authorized snapshot" case:
    DATA-37's wording implies some sources must not be copied, and a caller that knows that has
    to be able to say so."""

    @property
    def publication_attempt_id(self) -> str:
        """Identifies one attempt across every table it writes, and across its retries.

        Derived from the release id and attempt number rather than random, so a retry of the same
        attempt produces the same id and the DATA-53 provenance in each table's history lines up.
        """
        return f"{self.candidate.release_id}/attempt-{self.attempt or 1}"


@dataclass(frozen=True, slots=True)
class PublicationState:
    """What each step has established so far. Accumulated, never mutated in place."""

    request: PublicationRequest
    parent: ArchitectureRelease | None = None
    model: Model | None = None
    report: ValidationClaimReport | None = None
    table_set: TableSet | None = None
    staged: tuple[StagedTable, ...] = ()
    read_back: TableSet | None = None
    manifest: ArchitectureRelease | None = None
    published: bool = False

    @property
    def store(self) -> ReleaseStore:
        return self.request.store

    def require_model(self) -> Model:
        if self.model is None:
            message = "no candidate model; steps run in order"
            raise ReleaseError(message)
        return self.model

    def require_table_set(self) -> TableSet:
        if self.table_set is None:
            message = "no compiled tables; steps run in order"
            raise ReleaseError(message)
        return self.table_set

    def require_manifest(self) -> ArchitectureRelease:
        if self.manifest is None:
            message = "no manifest; steps run in order"
            raise ReleaseError(message)
        return self.manifest


type Step = Callable[[PublicationState], PublicationState]


# -- the eight steps, in the contract's own words -------------------------------------------------


def load_expected_parent(state: PublicationState) -> PublicationState:
    """`load expected parent` — and refuse if it is no longer current (DATA-23).

    Compared against the pointer rather than against the newest manifest: a manifest can exist
    without being current, and what a caller built on is whatever `CURRENT` named when it looked.
    """
    store = state.store
    current_id = store.current_id()
    expected = state.request.expected_parent
    if expected != current_id:
        message = (
            f"expected parent {expected!r} but the current release is {current_id!r}; "
            "rebase the change set rather than publishing again"
        )
        raise StaleParentError(message)
    parent = None if current_id is None else store.read_manifest(current_id)
    return replace(state, parent=parent)


def apply_change_set(state: PublicationState) -> PublicationState:
    """`apply complete typed change set` — all of it, or none of it.

    With no change set the candidate's model is published as authored, which is how a first
    release and a re-authored source both work. With one, it is applied to the *parent's* model,
    read back from the versions the parent manifest pins, so the baseline is what was published
    rather than whatever is on disk.
    """
    request = state.request
    if request.change_set is None:
        return replace(state, model=stamp_digests(request.candidate.model))

    if state.parent is None:
        message = "a change set needs a parent release to apply to"
        raise ReleaseError(message)

    baseline = read_model(state.store, state.parent)
    expected_digest = request.change_set.expected_base_digest
    if expected_digest is not None and expected_digest != model_digest(baseline):
        message = (
            f"change set {request.change_set.change_set_id!r} expected a different baseline "
            "than the parent release holds"
        )
        raise StaleParentError(message)
    return replace(state, model=stamp_digests(build_candidate(baseline, request.change_set)))


def validate_candidate(state: PublicationState) -> PublicationState:
    """`validate candidate` — the cross-record layer, before anything is written.

    A model with hard errors never reaches storage. The report is retained and published beside
    the manifest, because DATA-21 asks a release to pin its validation report, and a report that
    only existed while the process ran would not be pinnable.
    """
    model = state.require_model()
    report = validate_model(model, profile=state.request.profile)
    if report.hard_errors:
        codes = sorted({diagnostic.code for diagnostic in report.hard_errors})
        message = f"the candidate has {len(report.hard_errors)} hard error(s): {codes}"
        raise ReleaseError(message)
    return replace(state, report=report)


def stage_changed_tables(state: PublicationState) -> PublicationState:
    """`stage changed table snapshots` — writing only what moved (DATA-22)."""
    request = state.request
    model = state.require_model()
    table_set = compile_tables(model)
    staged = stage_tables(
        state.store,
        table_set,
        parent=state.parent,
        attempt=request.attempt or 1,
        publication_attempt_id=request.publication_attempt_id,
        source_bundle_digest=request.candidate.source_bundle.digest,
        generator_commit=_commit(request),
        change_set_id=request.candidate.change_set_id,
    )
    return replace(state, table_set=table_set, staged=staged)


def read_back_staged_versions(state: PublicationState) -> PublicationState:
    """`read back exact staged versions` — from storage, at the versions just recorded.

    Not a formality. This is the step that turns "the write returned without raising" into "the
    bytes are there and they are the right bytes", and it is cheap: the whole eleven-table read
    and verify was measured at 0.15 s for the example model.
    """
    store = state.store
    staged = state.staged
    if not staged:
        message = "nothing was staged; steps run in order"
        raise ReleaseError(message)
    provisional = ArchitectureRelease(
        release_id=state.request.candidate.release_id,
        model_id=state.request.candidate.model_id,
        parent_release_id=None if state.parent is None else state.parent.release_id,
        change_set_id=_change_set_id(state.request),
        schema_version=state.require_table_set().schema_version,
        profile_version=state.require_table_set().profile_version,
        model_digest=model_digest(state.require_model()),
        published_at=state.request.now(),
        tables=tuple(item.as_ref(uri=store.table_uri(item.table_id)) for item in staged),
        source_bundle=state.request.candidate.source_bundle,
        generator=generator_provenance(commit=_commit(state.request)),
    )
    return replace(state, read_back=read_table_set(store, provisional), manifest=provisional)


def validate_schema_content_and_artifacts(state: PublicationState) -> PublicationState:
    """`validate schema/content/artifacts` — the last chance to refuse.

    Three independent checks, because they fail in different ways: per-table digests catch wrong
    content, row counts catch a truncation a digest collision would hide, and reassembling the
    model catches a table set that is individually fine and jointly incoherent.
    """
    read_back = state.read_back
    manifest = state.require_manifest()
    if read_back is None:
        message = "nothing was read back; steps run in order"
        raise ReleaseError(message)

    observed = table_set_digests(read_back)
    pinned = {ref.table_id: ref.semantic_digest for ref in manifest.tables}
    counts = {ref.table_id: ref.row_count for ref in manifest.tables}
    observed_counts = {table_id: read_back[table_id].num_rows for table_id in TABLE_IDS}

    findings = (
        *digest_mismatches(pinned, dict(observed)),
        *row_count_mismatches(counts, observed_counts),
    )
    if findings:
        codes = sorted({finding.code for finding in findings})
        message = f"staged versions did not read back as staged: {codes}"
        raise ReadBackMismatchError(message)

    restored = assemble_model(read_back)
    if model_digest(restored) != manifest.model_digest:
        message = "the staged tables do not reassemble into the candidate model"
        raise ReadBackMismatchError(message)
    return state


def publish_immutable_manifest(state: PublicationState) -> PublicationState:
    """`publish immutable manifest` — written, but not yet current.

    The validation report is written first and its digest pinned, so DATA-21's "validation and
    change reports" are a claim the manifest can make truthfully.
    """
    store = state.store
    manifest = state.require_manifest()
    artifact = store.artifact_dir(manifest.release_id)

    report = state.report
    if report is not None:
        artifact.mkdir(parents=True, exist_ok=True)
        payload = report.model_dump_json(indent=2) + "\n"
        (artifact / "validation-report.json").write_text(payload, encoding="utf-8")
        manifest = manifest.model_validate(
            dict(manifest) | {"validation_report_digest": digest_bytes(payload.encode("utf-8"))}
        )

    if state.request.preserve_source and state.request.source_text is not None:
        manifest = manifest.model_validate(
            dict(manifest)
            | {"source_bundle": _preserve_source(store, manifest, state.request.source_text)}
        )

    store.write_manifest(manifest)
    return replace(state, manifest=manifest)


def _preserve_source(store: ReleaseStore, manifest: ArchitectureRelease, text: str) -> SourceBundle:
    """Write the authored source beside the release and pin where it went.

    The caller supplies the revision, because it knows where the source came from; publication
    writes the copy, because only it knows the store layout. The path recorded is relative to the
    store root, so the manifest keeps meaning something after the store is copied.
    """
    bundle = manifest.source_bundle
    name = Path(bundle.source_id).name or "source"
    relative = f"artifacts/{manifest.release_id}/source/{name}"
    target = store.resolve(relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return bundle.model_validate(dict(bundle) | {"snapshot_path": relative})


def move_current_pointer(state: PublicationState) -> PublicationState:
    """`atomically move current pointer` — **the commit point**.

    One atomic replace. Before it, the release does not exist to any reader; after it, it does.
    There is no state in between, which is the whole of DATA-24's guarantee.
    """
    manifest = state.require_manifest()
    state.store.set_current(manifest)
    return replace(state, published=True)


STEP_ORDER: Final[tuple[str, ...]] = (
    "load expected parent",
    "apply complete typed change set",
    "validate candidate",
    "stage changed table snapshots",
    "read back exact staged versions",
    "validate schema/content/artifacts",
    "publish immutable manifest",
    "atomically move current pointer",
)
"""The eight lines of the protocol fence in `docs/contracts/data.md`, verbatim and in order. A
test asserts they still match the contract file, so a renamed step is a failure rather than a
divergence nobody noticed."""

STEPS: Final[Mapping[str, Step]] = {
    "load expected parent": load_expected_parent,
    "apply complete typed change set": apply_change_set,
    "validate candidate": validate_candidate,
    "stage changed table snapshots": stage_changed_tables,
    "read back exact staged versions": read_back_staged_versions,
    "validate schema/content/artifacts": validate_schema_content_and_artifacts,
    "publish immutable manifest": publish_immutable_manifest,
    "atomically move current pointer": move_current_pointer,
}


def publish(
    request: PublicationRequest, *, steps: Mapping[str, Step] | None = None
) -> ArchitectureRelease:
    """Run the protocol under the publication lock and return the published manifest.

    `steps` is injectable so a test can replace exactly one stage with a failing one. That is how
    DATA-24's hard gate is proved: fail each named stage in turn and assert the current pointer
    still resolves to the previous complete release.
    """
    chosen = STEPS if steps is None else steps
    state = PublicationState(request=request)
    with publication_lock(request.store.lock_path):
        for name in STEP_ORDER:
            state = chosen[name](state)
    return state.require_manifest()


def _change_set_id(request: PublicationRequest) -> str | None:
    """Which change set produced this release, if one did.

    An applied change set is the truth, because it is what was actually run. The candidate's own
    field is the fallback, and records a change set applied somewhere upstream — an editor that
    applied it to the source before handing over a model, say — which is a weaker claim but still
    a real one. Precedence rather than a merge, so a manifest never names two.
    """
    if request.change_set is not None:
        return request.change_set.change_set_id
    return request.candidate.change_set_id


def _commit(request: PublicationRequest) -> str:
    if request.generator_commit is not None:
        return request.generator_commit
    return generator_provenance().toolkit_commit


class DeltaPublisher:
    """The shipped `Publisher` (CORE-58, DATA-21..DATA-24).

    A thin adapter: the protocol is the eight steps, and this gives them the Protocol's shape so
    a caller can hold a `Publisher` without knowing which one it has.
    """

    def __init__(self, store: ReleaseStore, *, profile: Profile = BASELINE_PROFILE) -> None:
        self._store = store
        self._profile = profile

    def publish(
        self, candidate: ReleaseCandidate, *, expected_parent: ReleaseId | None
    ) -> ArchitectureRelease:
        return publish(
            PublicationRequest(
                store=self._store,
                candidate=candidate,
                expected_parent=expected_parent,
                profile=self._profile,
                attempt=len(self._store.release_ids()) + 1,
            )
        )

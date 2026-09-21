"""The eight lifecycle operations, through one small typed API (DATA-38).

> Load baseline -> apply typed change set -> validate -> preview semantic diff and impact ->
> obtain required review -> persist -> publish release -> generate outputs.
> — `ARCH-TOOL-DATA-001` §9C

Every method below delegates to something four earlier waves already built; what this module adds
is that the eight steps are one surface with one vocabulary, rather than eight call sites each
resolving a store, a profile and a clock for itself. That is the whole of DATA-38: *"Expose
baseline/change/validate/diff/review/persist/publish/output operations through a small API and
CLI."*

**`diff` comes before `persist`.** That ordering is why the narrative is computed from two models
and not from a query context: at the moment an operator is shown what their change does, the
candidate release does not exist. The same `model_changes` runs after publication, so what they
approved is what they get.

**No `Protocol`.** `domain/protocols.py::Publisher` is already typed against `ReleaseCandidate` and
`ArchitectureRelease`, and core.md asks for a Protocol "where implementations are replaceable".
This is a concrete composition of five packages with no second implementation in prospect;
declaring one would be a boundary with nothing on the other side of it.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from architecture_toolkit.changes.diff import model_changes
from architecture_toolkit.changes.errors import ChangeError, ReviewError
from architecture_toolkit.changes.record import (
    ArchitectureChangeSet,
    Authorship,
    Review,
    ReviewDecision,
)
from architecture_toolkit.changes.records import ModelChanges
from architecture_toolkit.changes.releases import diff_releases
from architecture_toolkit.domain.commands import ChangeSet, build_candidate
from architecture_toolkit.domain.identifiers import ElementId, ReferenceId, ReleaseId
from architecture_toolkit.domain.model import Model
from architecture_toolkit.domain.registry import BASELINE_PROFILE, Profile
from architecture_toolkit.queries.execution import ReleaseQueryExecutor
from architecture_toolkit.queries.policy import policy_for
from architecture_toolkit.queries.results import TraversalResult
from architecture_toolkit.releases.manifest import ArchitectureRelease
from architecture_toolkit.releases.publication import PublicationRequest, persist, publish
from architecture_toolkit.releases.reader import read_model
from architecture_toolkit.releases.store import ReleaseStore
from architecture_toolkit.validation.claims import ValidationClaimReport
from architecture_toolkit.validation.pipeline import validate_model

__all__ = ["IMPACT_POLICY", "ArchitectureOperations", "OutputNotImplemented"]

IMPACT_POLICY = "impact.structural"
"""Which traversal answers "what else does this touch" for a change set.

Named here rather than chosen per call, so every change record in a store was computed under the
same graph semantics and two of them are comparable. CORE-30 is explicit that a traversal has no
meaning until somebody says which relationships count.
"""


@dataclass(frozen=True, slots=True)
class OutputNotImplemented:
    """What `output` returns until W8 completes it (DATA-38, PROJ-35).

    A typed result rather than a bare exit, because `docs/plans/w8-portal-export.md` says W8 will
    *"replace the typed not-implemented diagnostic"* and expects one to exist. The `build` verb's
    older untyped stub is left alone rather than quietly normalised; that inconsistency is recorded
    in the wave plan.
    """

    release_id: ReleaseId
    reason: str = "W8 (PROJ-35): no portal bundle or export pipeline exists yet"


@dataclass(eq=False, slots=True)
class ArchitectureOperations:
    """One store, one profile, one clock — and the eight operations over them.

    Not frozen and not hashable, for the reason `ReleaseQueryExecutor` is not: it holds a cache of
    query sessions, which is state. That cache holds no architecture facts, only sessions rebuilt
    from the manifest whenever this object is.
    """

    store: ReleaseStore
    profile: Profile = BASELINE_PROFILE
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    _queries: ReleaseQueryExecutor | None = field(default=None, repr=False)

    @property
    def queries(self) -> ReleaseQueryExecutor:
        if self._queries is None:
            self._queries = ReleaseQueryExecutor(store=self.store)
        return self._queries

    # -- 1. baseline ------------------------------------------------------------------------------

    def baseline(self, release_id: ReleaseId | None = None) -> Model:
        """The model to change, read back from a release rather than re-parsed from source.

        Defaults to the current release, which is what "the baseline" means to an operator who
        names none. A store with no current release refuses rather than inventing an empty model.
        """
        return read_model(self.store, self.manifest(release_id))

    def manifest(self, release_id: ReleaseId | None = None) -> ArchitectureRelease:
        if release_id is not None:
            return self.store.read_manifest(release_id)
        current = self.store.current()
        if current is None:
            message = f"no current release in {self.store.root}; publish one first"
            raise ChangeError(message)
        return current

    # -- 2. change --------------------------------------------------------------------------------

    def change(self, baseline: Model, change_set: ChangeSet) -> Model:
        """Apply a typed command batch. All or nothing, fully revalidated (CORE-10)."""
        return build_candidate(baseline, change_set)

    # -- 3. validate ------------------------------------------------------------------------------

    def validate(self, candidate: Model) -> ValidationClaimReport:
        return validate_model(candidate, profile=self.profile)

    # -- 4. diff ----------------------------------------------------------------------------------

    def diff(self, baseline: Model, candidate: Model) -> ModelChanges:
        """The narrative, before anything is persisted."""
        return model_changes(baseline, candidate)

    def diff_published(
        self, base_release_id: ReleaseId, candidate_release_id: ReleaseId
    ) -> ModelChanges:
        """The same narrative between two releases that already exist."""
        return diff_releases(
            self.store,
            self.store.read_manifest(base_release_id),
            self.store.read_manifest(candidate_release_id),
        )

    def impact(self, changes: ModelChanges) -> tuple[TraversalResult, ...]:
        """What each changed element reaches, under one declared policy (DATA-26, CORE-30).

        Only elements: a traversal starts at a node, and a changed reference or notation binding
        is not one. Returning an empty tuple for a change set that touched no element is the
        honest answer rather than a traversal from something that cannot be traversed from.
        """
        current = self.store.current_id()
        if current is None:
            return ()
        graph = self.queries.graph_for(current)
        policy = policy_for(IMPACT_POLICY)
        starts: Iterable[ElementId] = sorted(
            {
                record.identity
                for record in changes.narrative
                if record.collection == "elements" and record.identity in set(graph.node_ids())
            }
        )
        return tuple(graph.traverse(policy, start) for start in starts)

    def change_set(
        self,
        *,
        change_set_id: str,
        changes: ModelChanges,
        authored_by: Authorship,
        base_release_id: ReleaseId | None = None,
        new_release_id: ReleaseId | None = None,
        command_change_set_id: str | None = None,
        rationale: str | None = None,
        decision_references: tuple[ReferenceId, ...] = (),
        validation: ValidationClaimReport | None = None,
        impact: tuple[TraversalResult, ...] = (),
    ) -> ArchitectureChangeSet:
        """Assemble the published record DATA-26 describes."""
        return ArchitectureChangeSet(
            change_set_id=change_set_id,
            model_id=changes.model_id,
            base_release_id=base_release_id,
            new_release_id=new_release_id,
            command_change_set_id=command_change_set_id,
            authored_by=authored_by,
            rationale=rationale,
            decision_references=decision_references,
            changes=changes,
            validation=validation,
            impact=impact,
        )

    # -- 5. review --------------------------------------------------------------------------------

    def review(
        self,
        change_set: ArchitectureChangeSet,
        *,
        reviewer: Authorship,
        decision: ReviewDecision,
        note: str | None = None,
    ) -> ArchitectureChangeSet:
        """Record a decision on a change set, returning a new record rather than mutating one."""
        recorded = Review(reviewer=reviewer, decision=decision, reviewed_at=self.now(), note=note)
        return change_set.model_validate(dict(change_set) | {"review": recorded})

    # -- 6 and 7. persist, publish -----------------------------------------------------------------

    def persist(
        self, request: PublicationRequest, *, change_set: ArchitectureChangeSet | None = None
    ) -> ArchitectureRelease:
        """Stage and write the manifest without exposing it (DATA-38)."""
        self._refuse_unready(change_set, require_review=False)
        return persist(self._carrying(request, change_set))

    def publish(
        self,
        request: PublicationRequest,
        *,
        change_set: ArchitectureChangeSet | None = None,
        require_review: bool = False,
    ) -> ArchitectureRelease:
        """Run the whole protocol and move the current pointer.

        `require_review` is a caller's decision rather than a policy record, because there is no
        record today that says which changes need one and inventing one would be a claim about
        governance that no contract makes. What the flag does establish is that when a review *is*
        required, an absent one is not an approval.
        """
        self._refuse_unready(change_set, require_review=require_review)
        return publish(self._carrying(request, change_set))

    @staticmethod
    def _carrying(
        request: PublicationRequest, change_set: ArchitectureChangeSet | None
    ) -> PublicationRequest:
        """Render the change record into the request so step seven can pin its digest.

        `new_release_id` is filled in here and nowhere else: until this moment the record is a
        preview describing a release that does not exist, and the release it describes is the one
        being published right now.
        """
        if change_set is None:
            return request
        published = change_set.model_validate(
            dict(change_set) | {"new_release_id": request.candidate.release_id}
        )
        # DATA-53 asks Delta commit metadata to bind a table commit to the change set that caused
        # it, and `publication._change_set_id` reads `request.change_set` — the *command batch*.
        # A publication carrying only the narrative left that metadata empty, so the storage log
        # could not be traced back to the change everyone else was reading.
        candidate = request.candidate
        if request.change_set is None and published.command_change_set_id is not None:
            candidate = replace(candidate, change_set_id=published.command_change_set_id)
        return replace(
            request,
            candidate=candidate,
            change_report=published.model_dump_json(indent=2),
        )

    @staticmethod
    def _refuse_unready(change_set: ArchitectureChangeSet | None, *, require_review: bool) -> None:
        if change_set is None:
            if require_review:
                message = "a review cannot be required of a publication that carries no change set"
                raise ReviewError(message)
            return
        if change_set.has_hard_errors:
            report = change_set.validation
            codes = () if report is None else sorted({item.code for item in report.hard_errors})
            message = (
                f"change set {change_set.change_set_id!r} carries hard validation errors {codes}; "
                f"they are not publishable"
            )
            raise ChangeError(message)
        if require_review and not change_set.is_approved:
            recorded = None if change_set.review is None else change_set.review.decision.value
            message = (
                f"change set {change_set.change_set_id!r} was not approved "
                f"(review: {recorded or 'none recorded'}); an absent review is not an approval"
            )
            raise ReviewError(message)

    # -- 8. output ---------------------------------------------------------------------------------

    def output(self, release_id: ReleaseId | None = None) -> OutputNotImplemented:
        """Distribute the outputs of a committed release. Not implemented until W8."""
        return OutputNotImplemented(release_id=self.manifest(release_id).release_id)

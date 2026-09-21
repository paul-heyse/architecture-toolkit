"""Comparing a design alternative with its baseline, which is not a diff (DATA-28).

> Alternatives/scenarios have separate model/scenario identity plus explicit baseline, not
> sequential release semantics. — data.md

Two releases on different lines are comparable — that is the whole point of modelling an
alternative — but the comparison is not a change narrative, and this module exists so that the
difference is carried by the *type* rather than by a caller remembering it.

`AlternativeComparison` is deliberately not a `ModelChanges` and does not contain one.
`ArchitectureChangeSet.changes` is typed `ModelChanges`, so an alternative comparison cannot be
published as a change set even by accident — the same enforcement-by-missing-field that W5 used to
keep a derived reachability edge from claiming a relationship identity. It also carries no
`narrative`: an alternative has differences, not a story about what somebody changed, because
*"its existence does not imply that it superseded or was selected over the current design"*
(`ARCH-TOOL-DATA-001` §6B).
"""

from architecture_toolkit.changes.diff import model_changes
from architecture_toolkit.changes.errors import LineageError
from architecture_toolkit.changes.kinds import ChangeKind
from architecture_toolkit.changes.records import RecordChange
from architecture_toolkit.domain.base import CompiledRecord
from architecture_toolkit.domain.identifiers import (
    ModelId,
    ReleaseId,
    ScenarioId,
    SemanticDigest,
)
from architecture_toolkit.releases.manifest import ArchitectureRelease
from architecture_toolkit.releases.reader import read_model
from architecture_toolkit.releases.store import ReleaseStore

__all__ = ["AlternativeComparison", "compare_alternative"]


class AlternativeComparison(CompiledRecord):
    """How one design alternative differs from the baseline it was derived from.

    No `narrative` property and no `ModelChanges` field, both on purpose. What is here is a list of
    differences and the two identities the comparison is between, so a reader is never invited to
    describe an alternative as something that happened.
    """

    model_id: ModelId
    scenario_id: ScenarioId
    baseline_release_id: ReleaseId
    alternative_release_id: ReleaseId
    baseline_digest: SemanticDigest
    alternative_digest: SemanticDigest
    differences: tuple[RecordChange, ...] = ()

    @property
    def is_identical(self) -> bool:
        """An alternative that differs from its baseline in nothing is worth saying out loud."""
        return not self.differences

    @property
    def kinds(self) -> frozenset[ChangeKind]:
        return frozenset(kind for record in self.differences for kind in record.kinds)


def compare_alternative(
    baseline: ArchitectureRelease,
    alternative: ArchitectureRelease,
    *,
    baseline_store: ReleaseStore,
    alternative_store: ReleaseStore,
) -> AlternativeComparison:
    """Compare an alternative against the baseline it declares.

    **Two stores, and they are usually different ones.** A store has one current pointer and
    overwrites `tables/<table_id>` wholesale, so an alternative published beside its baseline would
    overwrite it; the separation is a store root, which `--store` already provides. Taking one
    store here would silently read the baseline twice and report that the alternative differed
    from its baseline in nothing — which is the most convincing wrong answer available.

    Refuses a pair the alternative does not claim. `baseline_release_id` is an assertion the
    scenario's author made at publication, and comparing against some other release would produce a
    result that looks authoritative and answers a question nobody asked.
    """
    if alternative.scenario_id is None:
        message = (
            f"{alternative.release_id!r} is not an alternative; it is a revision on the baseline "
            f"line, so the comparison between it and {baseline.release_id!r} is a diff"
        )
        raise LineageError(message)
    if alternative.baseline_release_id != baseline.release_id:
        message = (
            f"{alternative.release_id!r} declares {alternative.baseline_release_id!r} as its "
            f"baseline, not {baseline.release_id!r}"
        )
        raise LineageError(message)
    if baseline.scenario_id is not None:
        message = (
            f"{baseline.release_id!r} is itself on line {baseline.scenario_id!r}; an alternative "
            f"is derived from a baseline release, not from another alternative"
        )
        raise LineageError(message)

    changes = model_changes(
        read_model(baseline_store, baseline), read_model(alternative_store, alternative)
    )
    return AlternativeComparison(
        model_id=baseline.model_id,
        scenario_id=alternative.scenario_id,
        baseline_release_id=baseline.release_id,
        alternative_release_id=alternative.release_id,
        baseline_digest=changes.base_digest,
        alternative_digest=changes.candidate_digest,
        differences=changes.records,
    )

"""What is offered for publication (DATA-21, DATA-23).

A candidate is everything the publication protocol needs and nothing it can derive. It is the
typed DTO the `Publisher` Protocol exchanges, which CORE-58 asks for in place of a dictionary.

**It carries the model, not a path to one.** By the time a candidate exists the source has been
parsed, the records validated and the digests stamped, so publication is about coherence and
storage rather than about parsing. A candidate holding a filename would make the protocol's third
step — validate the candidate — ambiguous about what it was validating.

**`release_id` is chosen by the caller, not generated here.** DATA-21 makes a release id part of
an immutable manifest that later manifests reference as a parent, so it is an identity somebody
commits to, not a side effect of a successful write. `next_release_id` exists for callers who want
the obvious sequence and is deliberately not called automatically.
"""

from dataclasses import dataclass

from architecture_toolkit.domain.identifiers import ChangeSetId, ReleaseId, ScenarioId
from architecture_toolkit.domain.model import Model
from architecture_toolkit.releases.manifest import SourceBundle

__all__ = ["ReleaseCandidate", "next_release_id"]

_PREFIX = "rel-"
_WIDTH = 4


@dataclass(frozen=True, slots=True)
class ReleaseCandidate:
    """A validated model offered as the next release of one architecture."""

    release_id: ReleaseId
    model: Model
    source_bundle: SourceBundle
    change_set_id: ChangeSetId | None = None

    # DATA-28. Set together or not at all; `ArchitectureRelease` refuses one without the other.
    # A candidate declares these rather than the store inferring them, because whether a release
    # is an alternative is a statement about intent that no amount of looking at the data reveals.
    scenario_id: ScenarioId | None = None
    baseline_release_id: ReleaseId | None = None

    @property
    def is_alternative(self) -> bool:
        return self.scenario_id is not None

    @property
    def model_id(self) -> str:
        return self.model.model_id


def next_release_id(existing: tuple[str, ...]) -> ReleaseId:
    """The next `rel-NNNN` after the ones a store already holds.

    Zero-padded so the ids sort lexicographically in the same order they were published, which is
    what makes `ReleaseStore.release_ids()` readable without parsing. Four digits is a shape, not
    a limit: `rel-10000` still sorts after `rel-9999` under the comparison that matters, which is
    the manifest's own `parent_release_id` chain rather than the filename.
    """
    numbered = [
        int(name.removeprefix(_PREFIX))
        for name in existing
        if name.startswith(_PREFIX) and name.removeprefix(_PREFIX).isdigit()
    ]
    return f"{_PREFIX}{max(numbered, default=0) + 1:0{_WIDTH}d}"

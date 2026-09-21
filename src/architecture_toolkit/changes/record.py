"""The published semantic change record (DATA-26).

`ARCH-TOOL-DATA-001` §6 lists what an `ArchitectureChangeSet` carries, and every field below is one
of those lines: change-set id, base and new release ids, author or agent identity, rationale,
decision references, changed objects, validation results, impact-analysis results.

**Two things are called a change set, and they are not the same thing.**
`domain/commands.py::ChangeSet` is CORE-10's *input* — a batch of typed commands somebody asks to
have applied. This is DATA-26's *output* — the narrative of what applying them actually did, which
is computed from the two models rather than read off the request. It references the command batch
by id, so a reader can get from one to the other without either pretending to be the other. The
distinction matters because the two disagree in a case the wave exists to get right: a command
batch says "rename this", and the record says which fields of which records actually moved,
including ones the author did not name.

**Rationale is bounded on purpose.** `docs/implementation-contract.md` invariant 14 gives the
design narrative to Notion, so this field is a sentence pointing at a decision rather than a place
to keep one. `decision_references` uses the `Reference` ids DATA-09 already established rather than
a second evidence mechanism.

**Impact is a W5 `TraversalResult`, which is why this package sits where it does.** `queries/`
imports `releases/`, so a record living in `releases/` could not carry one without a circular
import, and "impact-analysis results" would have become a locally-invented summary.
"""

from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from architecture_toolkit.changes.kinds import ChangeKind
from architecture_toolkit.changes.records import ModelChanges, RecordChange
from architecture_toolkit.domain.base import CompiledRecord
from architecture_toolkit.domain.identifiers import (
    ChangeSetId,
    ModelId,
    ReferenceId,
    ReleaseId,
)
from architecture_toolkit.queries.results import TraversalResult
from architecture_toolkit.validation.claims import ValidationClaimReport

__all__ = ["MAX_RATIONALE", "ArchitectureChangeSet", "AuthorKind", "Authorship"]

MAX_RATIONALE = 2000
"""Long enough for a paragraph naming the decision, short enough not to become the decision."""


class AuthorKind(StrEnum):
    """Who made the change. Agents edit this model, so "a person did it" cannot be assumed."""

    PERSON = "person"
    AGENT = "agent"


class Authorship(CompiledRecord):
    """Identity of whoever produced a change set.

    `tool` is separate from `author_id` because "an agent did this" and "which agent build did
    this" are different facts, and a release six months old is only reproducible if the second one
    was written down.
    """

    author_id: str = Field(min_length=1, max_length=200)
    author_kind: AuthorKind
    tool: str | None = Field(default=None, max_length=200)


class ArchitectureChangeSet(CompiledRecord):
    """What changed between two architecture releases, why, and with what consequences.

    Immutable once published, in this repository's sense: `CompiledRecord` forbids a mutable
    container at any depth and the hashability guard enforces it for the whole subclass tree, so
    "frozen" here means the whole graph rather than the top level.
    """

    change_set_id: ChangeSetId
    model_id: ModelId
    # `None` on a first release, which has no parent to differ from.
    base_release_id: ReleaseId | None = None
    # `None` while the change set is a *preview*. DATA-38 runs diff before persist and publish, so
    # at the moment the narrative is first computed the release it describes does not exist yet.
    new_release_id: ReleaseId | None = None
    command_change_set_id: ChangeSetId | None = None
    authored_by: Authorship
    rationale: str | None = Field(default=None, max_length=MAX_RATIONALE)
    decision_references: tuple[ReferenceId, ...] = ()
    changes: ModelChanges
    validation: ValidationClaimReport | None = None
    impact: tuple[TraversalResult, ...] = ()

    @model_validator(mode="after")
    def the_narrative_describes_this_model(self) -> Self:
        if self.changes.model_id != self.model_id:
            message = (
                f"change set {self.change_set_id!r} claims model {self.model_id!r} and carries "
                f"changes to {self.changes.model_id!r}"
            )
            raise ValueError(message)
        return self

    @model_validator(mode="after")
    def a_published_change_set_names_the_release_it_produced(self) -> Self:
        """A base without a candidate is a preview; a candidate without a base is a first release.

        Both are real. What is not real is a change set whose two ends are the same release, which
        would describe a release as a revision of itself.
        """
        if self.base_release_id is not None and self.base_release_id == self.new_release_id:
            message = (
                f"change set {self.change_set_id!r} names {self.base_release_id!r} as both its "
                f"base and its result"
            )
            raise ValueError(message)
        return self

    @property
    def is_preview(self) -> bool:
        return self.new_release_id is None

    @property
    def narrative(self) -> tuple[RecordChange, ...]:
        """The architectural story. Presentation changes are recorded and excluded from it."""
        return self.changes.narrative

    @property
    def presentation(self) -> tuple[RecordChange, ...]:
        return self.changes.presentation

    @property
    def kinds(self) -> frozenset[ChangeKind]:
        return self.changes.kinds

    @property
    def is_empty(self) -> bool:
        return self.changes.is_empty

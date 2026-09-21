"""Diffing two published releases, and the second engine that has to agree (DATA-26, DATA-57).

The narrative comes from two models. `diff_releases` reads each release back with
`releases/reader.py::read_model` and hands both to `model_changes`, which is the same function the
pre-publication preview calls — one implementation, so a diff cannot mean one thing before
publication and another after.

`engine_identity_delta` is the other half. It runs the declared `semantic_identity_delta` recipe
over a W5 `ComparisonContext`, which is the added/removed/changed-ID join §6A asks DataFusion for,
and `identity_disagreements` states the claim that ties them together: **the two surfaces answer the
same question the same way**. That is the W5 hard gate turned around — the gate says DataFusion and
NetworkX read the same release; this says that where the engine and the digest are asked the same
thing they say the same thing, which is what would drift first.

A cross-check nothing calls is not a cross-check, so `identity_disagreements` is a library
function reachable from the CLI, not an assertion living in a test.
"""

from collections.abc import Mapping

from architecture_toolkit.changes.diff import model_changes
from architecture_toolkit.changes.records import ModelChanges
from architecture_toolkit.domain.semantics import MODEL_COLLECTIONS, semantic_delta
from architecture_toolkit.queries.context import ComparisonContext
from architecture_toolkit.queries.execution import execute
from architecture_toolkit.queries.recipes import recipe_for
from architecture_toolkit.releases.lineage import require_same_line
from architecture_toolkit.releases.manifest import ArchitectureRelease
from architecture_toolkit.releases.reader import read_model
from architecture_toolkit.releases.store import ReleaseStore
from architecture_toolkit.storage.snapshot import DEFAULT_PROVIDER

__all__ = [
    "IDENTITY_DELTA_RECIPE",
    "diff_releases",
    "engine_identity_delta",
    "identity_disagreements",
]

IDENTITY_DELTA_RECIPE = "semantic_identity_delta"

# The three answers the recipe's CASE expression can give, other than "unchanged".
_ADDED, _REMOVED, _CHANGED = "added", "removed", "changed"


def diff_releases(
    store: ReleaseStore, base: ArchitectureRelease, candidate: ArchitectureRelease
) -> ModelChanges:
    """The change narrative between two published releases.

    Refuses a pair on two different lines of work: an alternative is not a later revision of its
    baseline, and `changes/alternatives.py::compare_alternative` is the operation for that pair.
    Nothing checked lineage on the read side before this — publication verified the expected parent
    and then nobody looked again — so without the refusal a baseline and a scenario would diff
    happily and the result would read as a change somebody made.

    No provider argument: `read_model` resolves each release's own pinned table versions, and the
    narrative is about records rather than about how the bytes were read. The provider choice
    belongs to the engine cross-check below, which is the part that runs a query.
    """
    require_same_line(base, candidate)
    return model_changes(read_model(store, base), read_model(store, candidate))


def engine_identity_delta(
    store: ReleaseStore,
    base: ArchitectureRelease,
    candidate: ArchitectureRelease,
    *,
    provider: str = DEFAULT_PROVIDER,
) -> Mapping[str, Mapping[str, tuple[str, ...]]]:
    """What DataFusion says changed, per collection, joined on the stamped semantic digest.

    Shaped like `SemanticDelta.collections` — `{collection: {"added": (...), ...}}` — so the
    comparison below is between two things of one shape rather than between a table and a record.
    """
    comparison = ComparisonContext.of(store, base, candidate, provider=provider)
    result = execute(recipe_for(IDENTITY_DELTA_RECIPE), comparison)
    buckets: dict[str, dict[str, list[str]]] = {
        collection: {_ADDED: [], _REMOVED: [], _CHANGED: []} for collection, _ in MODEL_COLLECTIONS
    }
    for row in result.table.to_pylist():
        change = row["change"]
        identity = row["identity"]
        if change in buckets[row["collection"]] and identity is not None:
            buckets[row["collection"]][change].append(str(identity))
    return {
        collection: {name: tuple(sorted(values)) for name, values in changes.items()}
        for collection, changes in buckets.items()
    }


def identity_disagreements(
    store: ReleaseStore,
    base: ArchitectureRelease,
    candidate: ArchitectureRelease,
    *,
    provider: str = DEFAULT_PROVIDER,
) -> tuple[str, ...]:
    """Where the engine and the digest disagree about what changed. Empty means they agree.

    Returns messages rather than raising, because the caller decides what a disagreement means: a
    CLI reports it, a qualification test fails on it, and neither should have to catch an
    exception to find out that nothing was wrong.
    """
    engine = engine_identity_delta(store, base, candidate, provider=provider)
    oracle = semantic_delta(read_model(store, base), read_model(store, candidate))
    found: list[str] = []
    for delta in oracle.collections:
        observed = engine[delta.collection]
        for name, expected in (
            (_ADDED, delta.added),
            (_REMOVED, delta.removed),
            (_CHANGED, delta.changed),
        ):
            if observed[name] != tuple(sorted(expected)):
                found.append(
                    f"{delta.collection}.{name}: the engine reports {observed[name]} and the "
                    f"semantic digest reports {tuple(sorted(expected))}"
                )
    return tuple(found)

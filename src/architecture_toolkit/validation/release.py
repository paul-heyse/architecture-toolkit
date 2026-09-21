"""Release coherence: does this manifest describe what is actually stored (DATA-21, DATA-23)?

Step six of the publication protocol — "validate schema/content/artifacts" — asks a question no
model rule can answer, because it is not about a model. It compares what a manifest *claims* with
what the storage layer *returns*, and it runs after staging and before the manifest is published,
which is the only window in which the answer can still change the outcome.

**These are not registered cross-record rules, deliberately.** A `Rule` takes a model candidate,
and `tests/unit/test_rules.py` requires every registered rule to have a known-bad model fixture
that triggers it. A digest mismatch between a manifest and a Delta table cannot be expressed as a
bad model, so forcing it into that registry would mean either a fake fixture or a weakened guard.
Diagnostics are the right output; the rule registry is not the right home.

The same functions serve two callers with different urgency. Publication treats any finding as
fatal and raises before writing a manifest. `architecture releases --verify` reports them, because
a release that has already been published and has since become unreadable is a fact to surface,
not an exception to throw at somebody listing their releases.
"""

from collections.abc import Iterable, Mapping

from architecture_toolkit.validation.diagnostics import Diagnostic, build_diagnostic

__all__ = [
    "chain_breaks",
    "digest_mismatches",
    "missing_pins",
    "row_count_mismatches",
    "storage_schema_mismatch",
    "unreadable_versions",
]


def missing_pins(pinned: Iterable[str], declared: Iterable[str]) -> tuple[Diagnostic, ...]:
    """Every declared table must be pinned. A release missing one is not a coherent revision."""
    absent = sorted(set(declared) - set(pinned))
    return tuple(
        build_diagnostic(
            "CORE.RELEASE.TABLE_NOT_PINNED",
            message=f"the manifest pins no version for table {table_id!r}",
            canonical_object_id=table_id,
            context=(("table_id", table_id),),
        )
        for table_id in absent
    )


def digest_mismatches(
    pinned: Mapping[str, str], observed: Mapping[str, str]
) -> tuple[Diagnostic, ...]:
    """What step five exists to catch: a staged version that is not what was staged."""
    return tuple(
        build_diagnostic(
            "CORE.RELEASE.DIGEST_MISMATCH",
            message=(
                f"table {table_id!r} pins {expected} but the staged version reads back as "
                f"{observed.get(table_id, 'nothing')}"
            ),
            canonical_object_id=table_id,
            context=(
                ("table_id", table_id),
                ("pinned", expected),
                ("observed", str(observed.get(table_id))),
            ),
        )
        for table_id, expected in sorted(pinned.items())
        if observed.get(table_id) != expected
    )


def row_count_mismatches(
    pinned: Mapping[str, int], observed: Mapping[str, int]
) -> tuple[Diagnostic, ...]:
    """The cheapest read-back assertion, and one a digest alone would not make."""
    return tuple(
        build_diagnostic(
            "CORE.RELEASE.ROW_COUNT_MISMATCH",
            message=(
                f"table {table_id!r} pins {expected} row(s) but the staged version holds "
                f"{observed.get(table_id)}"
            ),
            canonical_object_id=table_id,
            context=(("table_id", table_id), ("pinned", str(expected))),
        )
        for table_id, expected in sorted(pinned.items())
        if observed.get(table_id) != expected
    )


def unreadable_versions(unreadable: Mapping[str, str]) -> tuple[Diagnostic, ...]:
    """A retained release that can no longer be opened (DATA-58).

    Reported rather than raised, because by the time this is true the damage is done and the
    useful act is to say which release and which table, not to stop the caller listing releases.
    """
    return tuple(
        build_diagnostic(
            "CORE.RELEASE.VERSION_UNREADABLE",
            message=f"table {table_id!r} cannot be read at the pinned version: {reason}",
            canonical_object_id=table_id,
            context=(("table_id", table_id),),
        )
        for table_id, reason in sorted(unreadable.items())
    )


def storage_schema_mismatch(*, release_id: str, found: str, expected: str) -> Diagnostic | None:
    """A release written against another physical schema (DATA-56).

    Not an error on its own — historical releases are *supposed* to stay readable under the
    schema they were written with — so this says which migration applies rather than refusing.
    """
    if found == expected:
        return None
    return build_diagnostic(
        "CORE.RELEASE.STORAGE_SCHEMA_MISMATCH",
        message=(
            f"release {release_id!r} was written against storage schema {found}, "
            f"and this toolkit writes {expected}"
        ),
        canonical_object_id=release_id,
        context=(("found", found), ("expected", expected)),
    )


def chain_breaks(
    manifests: Iterable[tuple[str, str | None, str]],
) -> tuple[Diagnostic, ...]:
    """Is the parent chain of a release store navigable (DATA-21)?

    Takes `(release_id, parent_release_id, model_id)` triples rather than a store, so this module
    keeps depending on nothing but `validation/` — the same reason `storage/catalog.py` takes pins
    rather than a manifest.

    Three ways a chain fails, and they fail differently. A missing parent means a link was removed
    or a manifest was copied out of another store. A cycle means no release is the first, so
    nothing can be replayed in order. Two roots for one model means two histories in one store,
    which no reader can order — and which is exactly what a manifest that silently left
    `parent_release_id` unset would produce on every publication.
    """
    entries = list(manifests)
    known = {release_id for release_id, _, _ in entries}
    findings: list[Diagnostic] = []

    for release_id, parent, _model_id in sorted(entries):
        if parent is not None and parent not in known:
            findings.append(
                build_diagnostic(
                    "CORE.RELEASE.PARENT_NOT_FOUND",
                    message=f"release {release_id!r} names parent {parent!r}, which is not here",
                    canonical_object_id=release_id,
                    context=(("parent_release_id", parent),),
                )
            )

    parents = {release_id: parent for release_id, parent, _ in entries}
    for release_id in sorted(known):
        if _reaches_itself(release_id, parents):
            findings.append(
                build_diagnostic(
                    "CORE.RELEASE.CHAIN_CYCLE",
                    message=f"release {release_id!r} is its own ancestor",
                    canonical_object_id=release_id,
                )
            )

    roots_by_model: dict[str, list[str]] = {}
    for release_id, parent, model_id in entries:
        if parent is None:
            roots_by_model.setdefault(model_id, []).append(release_id)
    for model_id, roots in sorted(roots_by_model.items()):
        if len(roots) > 1:
            findings.append(
                build_diagnostic(
                    "CORE.RELEASE.MULTIPLE_ROOTS",
                    message=f"model {model_id!r} has {len(roots)} releases with no parent",
                    canonical_object_id=model_id,
                    context=(("roots", ", ".join(sorted(roots))),),
                )
            )
    return tuple(findings)


def _reaches_itself(start: str, parents: Mapping[str, str | None]) -> bool:
    """Walk the parent chain from `start`, stopping at a repeat or at the root."""
    seen: set[str] = set()
    current: str | None = start
    while current is not None:
        if current in seen:
            return True
        seen.add(current)
        current = parents.get(current)
        if current == start:
            return True
    return False

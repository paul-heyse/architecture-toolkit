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

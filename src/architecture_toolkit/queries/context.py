"""One query session per release, and nothing the engine lets mutate (DATA-46, DATA-47, DATA-18).

`data.md § DataFusion`: "Build one fresh `SessionContext` from one `ArchitectureRelease`. Register
only manifest-pinned versions. Cross-release comparisons use explicit namespaces/sides such as
`base.*` and `candidate.*`; never mix independently resolved latest state."

Three library capabilities do most of the work here, so this module is small on purpose.

**The read-only surface is the engine's, not ours.** `SQLOptions` with DDL, DML and statements all
disallowed makes `CREATE TABLE`, `INSERT`, `DROP` and `SET` fail at *planning* time, before any
data is touched. DATA-18's "DataFusion is the query surface, not the mutation API" is therefore a
configuration rather than a statement allow-list of our own, which we would have had to keep
correct against every SQL form DataFusion 54 accepts. `sql_with_options` also takes the bound
`param_values`, so the read-only surface and DATA-18's bound parameters arrive in one call and
there is no unguarded path to the engine on this type.

**Named sides are real DataFusion schemas.** `Catalog.register_schema` plus a qualified
registration name gives literally `base.elements` and `candidate.elements` — the contract's own
wording rather than an approximation of it. Every `SessionContext.register_*` helper resolves a
qualified name, so `storage.catalog.register_pins` reaches them with the `prefix=` it has had
since W3 and the storage layer needs no change for DATA-47. Registering into a schema nobody
created is refused by the engine (`failed to resolve schema`), so a misspelled side name fails
loudly instead of quietly landing in `public` where a query would then find it under the wrong
name.

**The engine can be asked what it registered.** With `information_schema` enabled, `registered()`
reads the inventory out of DataFusion rather than reporting our own bookkeeping back to us. That
is what makes DATA-46's "only the manifest-pinned versions" checkable: the assertion compares the
manifest against the engine, and no amount of drift in this module can make it agree by accident.

`target_partitions` is pinned to 1 because the physical plan otherwise carries the host's CPU
count (`RepartitionExec: partitioning=RoundRobinBatch(10)`), and DATA-49's plan evidence would
then differ between two machines running the same release. These tables are small enough that the
parallelism is not worth the nondeterminism.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

import pyarrow as pa
from datafusion import DataFrame, SessionConfig, SessionContext, SQLOptions
from datafusion.catalog import Schema

from architecture_toolkit.domain.identifiers import ModelId, ReleaseId, TableId
from architecture_toolkit.queries.errors import QueryError
from architecture_toolkit.queries.sides import SIDES, Side
from architecture_toolkit.releases.manifest import ArchitectureRelease
from architecture_toolkit.releases.reader import table_locations
from architecture_toolkit.releases.store import ReleaseStore
from architecture_toolkit.storage.catalog import register_pins
from architecture_toolkit.storage.snapshot import (
    DEFAULT_PROVIDER,
    MaterializedPyArrowSnapshotProvider,
    provider_named,
)

__all__ = [
    "SIDES",
    "ComparisonContext",
    "ReleaseContext",
    "ReleaseScope",
    "Side",
    "read_only_options",
    "session_config",
]

TARGET_PARTITIONS: Final[int] = 1
"""Pinned so a physical plan is a property of the query rather than of the host's CPU count."""

_INVENTORY: Final[str] = (
    "SELECT table_schema, table_name FROM information_schema.tables "
    "WHERE table_schema <> 'information_schema' ORDER BY table_schema, table_name"
)


def session_config() -> SessionConfig:
    """The one configuration every release session is built with."""
    return SessionConfig().with_information_schema(True).with_target_partitions(TARGET_PARTITIONS)


def read_only_options() -> SQLOptions:
    """A fresh read-only `SQLOptions` (DATA-18).

    Fresh rather than a module constant because the `with_*` builders mutate in place and return
    `self` — measured against datafusion 54.0.0 — so a shared instance would be a mutable global
    that any caller could re-enable DDL on.
    """
    return SQLOptions().with_allow_ddl(False).with_allow_dml(False).with_allow_statements(False)


def _run(session: SessionContext, text: str, parameters: Mapping[str, object] | None) -> DataFrame:
    values = dict(parameters) if parameters is not None else None
    return session.sql_with_options(text, read_only_options(), param_values=values)


def _inventory(session: SessionContext) -> tuple[tuple[str, str], ...]:
    rows = _run(session, _INVENTORY, None).to_arrow_table().to_pylist()
    return tuple((str(row["table_schema"]), str(row["table_name"])) for row in rows)


@dataclass(frozen=True, slots=True)
class ReleaseScope:
    """One release's tables inside a session: which release, and how to name its tables in SQL.

    The qualifier is `""` for a single-release context and `"base."` or `"candidate."` inside a
    comparison. Nothing else in the query layer builds a table name, so a recipe written against a
    scope reads the same release the graph does.
    """

    release_id: ReleaseId
    model_id: ModelId
    qualifier: str
    pins: tuple[tuple[TableId, int], ...]

    def table(self, table_id: str) -> str:
        return f"{self.qualifier}{table_id}"

    @property
    def namespace(self) -> str:
        """The schema name, or `public` where the scope is unqualified."""
        return self.qualifier.rstrip(".") or "public"


@dataclass(frozen=True, slots=True)
class ReleaseContext:
    """A DataFusion session holding exactly one release's pinned table versions (DATA-46)."""

    session: SessionContext
    scope: ReleaseScope
    provider: MaterializedPyArrowSnapshotProvider

    @classmethod
    def for_release(
        cls,
        store: ReleaseStore,
        manifest: ArchitectureRelease,
        *,
        provider: str = DEFAULT_PROVIDER,
    ) -> ReleaseContext:
        """Register the manifest's pinned versions into a fresh session, and nothing else."""
        reader = provider_named(provider, table_locations(store, manifest))
        session = SessionContext(session_config())
        pins = dict(manifest.pinned_versions)
        register_pins(session, reader, pins)
        return cls(session=session, scope=_scope(manifest, qualifier=""), provider=reader)

    def sql(self, text: str, parameters: Mapping[str, object] | None = None) -> DataFrame:
        """Run read-only SQL with bound parameters (DATA-18)."""
        return _run(self.session, text, parameters)

    def arrow(self, text: str, parameters: Mapping[str, object] | None = None) -> pa.Table:
        return self.sql(text, parameters).to_arrow_table()

    def table(self, table_id: str) -> DataFrame:
        """One of this release's tables as a DataFrame, under this scope's qualified name.

        The expression API rather than SQL, because a table name that varies by side would have to
        be interpolated into a query string — which `ruff`'s `S608` flags, correctly, and which
        `data.md` already answers: "DataFrame/expression APIs for programmatic construction".
        """
        return self.session.table(self.scope.table(table_id))

    def registered(self) -> tuple[tuple[str, str], ...]:
        """What the engine says is registered, as `(schema, table)` pairs."""
        return _inventory(self.session)


@dataclass(frozen=True, slots=True)
class ComparisonContext:
    """Two releases in one session under explicit named sides (DATA-47).

    One session rather than two, because the point of a comparison is a join across the sides, and
    a join is only possible where both are registered. Neither side is ever resolved to latest:
    each is registered from its own manifest's pins, under its own schema.
    """

    session: SessionContext
    base: ReleaseScope
    candidate: ReleaseScope
    providers: tuple[tuple[Side, MaterializedPyArrowSnapshotProvider], ...]

    @classmethod
    def of(
        cls,
        store: ReleaseStore,
        base: ArchitectureRelease,
        candidate: ArchitectureRelease,
        *,
        provider: str = DEFAULT_PROVIDER,
    ) -> ComparisonContext:
        if base.release_id == candidate.release_id:
            message = f"a comparison needs two releases; both sides are {base.release_id!r}"
            raise QueryError(message)
        session = SessionContext(session_config())
        catalog = session.catalog()
        readers: dict[Side, MaterializedPyArrowSnapshotProvider] = {}
        for side, manifest in (("base", base), ("candidate", candidate)):
            catalog.register_schema(side, Schema.memory_schema())
            reader = provider_named(provider, table_locations(store, manifest))
            register_pins(session, reader, dict(manifest.pinned_versions), prefix=f"{side}.")
            readers[side] = reader
        return cls(
            session=session,
            base=_scope(base, qualifier="base."),
            candidate=_scope(candidate, qualifier="candidate."),
            providers=tuple(sorted(readers.items())),
        )

    def side(self, name: Side) -> ReleaseContext:
        """A single-release view of one side, sharing this comparison's session.

        Sharing rather than rebuilding is the point: a graph built from a side and a recipe run
        against the same side are reading one session, so they cannot disagree about the release.
        """
        scope = self.base if name == "base" else self.candidate
        readers = dict(self.providers)
        return ReleaseContext(session=self.session, scope=scope, provider=readers[name])

    def sql(self, text: str, parameters: Mapping[str, object] | None = None) -> DataFrame:
        return _run(self.session, text, parameters)

    def arrow(self, text: str, parameters: Mapping[str, object] | None = None) -> pa.Table:
        return self.sql(text, parameters).to_arrow_table()

    def registered(self) -> tuple[tuple[str, str], ...]:
        return _inventory(self.session)


def _scope(manifest: ArchitectureRelease, *, qualifier: str) -> ReleaseScope:
    return ReleaseScope(
        release_id=manifest.release_id,
        model_id=manifest.model_id,
        qualifier=qualifier,
        pins=manifest.pinned_versions,
    )

"""Provider implementations are checked against their Protocols statically (CORE-58).

`isinstance` on a `runtime_checkable` Protocol compares method names only. Signature conformance
is a static property, so it is asserted here where Pyrefly can see it rather than in a runtime
test that would silently pass.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa

from architecture_toolkit.domain.authoring import YamlSourceLoader
from architecture_toolkit.domain.capsules import (
    ArrowArrayExportable,
    ArrowSchemaExportable,
    ArrowStreamExportable,
)
from architecture_toolkit.domain.identifiers import ReleaseId
from architecture_toolkit.domain.model import Model
from architecture_toolkit.domain.protocols import (
    Publisher,
    SnapshotProvider,
    SourceLoader,
    ValidatorAdapter,
)
from architecture_toolkit.domain.providers import Materialization, SnapshotProviderDescription
from architecture_toolkit.releases.candidate import ReleaseCandidate
from architecture_toolkit.releases.manifest import (
    ArchitectureRelease,
    GeneratorProvenance,
    SourceBundle,
)
from architecture_toolkit.storage.snapshot import MaterializedPyArrowSnapshotProvider
from architecture_toolkit.validation.context import ValidationContext
from architecture_toolkit.validation.diagnostics import Diagnostic
from architecture_toolkit.validation.pipeline import CrossRecordValidator


class MaterializedProvider:
    """A minimal conformer, so `SnapshotProvider` is not shaped around one implementation.

    The shipped provider is asserted against the same Protocol in `storage/snapshot.py`'s own
    conformance line below; this one exists to keep the Protocol describable by something that
    is not it.
    """

    def describe(self) -> SnapshotProviderDescription:
        return SnapshotProviderDescription(
            provider_type="fixture",
            materialization=Materialization.MATERIALIZED,
            preserves_typed_empties=True,
        )

    def schema_for(self, table_id: str, *, version: int) -> ArrowSchemaExportable:
        del table_id, version
        return pa.schema([])

    def open(self, table_id: str, *, version: int) -> ArrowStreamExportable:
        del table_id, version
        return pa.table({})


class RecordingValidator:
    """A second, minimal conformer, so the Protocol is not accidentally shaped around one class."""

    def validate(self, candidate: Model, *, context: ValidationContext) -> tuple[Diagnostic, ...]:
        del candidate, context
        return ()


# Assignment is the assertion: a signature mismatch fails `pyrefly check`.
_provider: SnapshotProvider = MaterializedProvider()
_validator: ValidatorAdapter = RecordingValidator()
# The one that matters, now that `ValidatorAdapter` is typed: the shipped implementation is
# checked against the boundary it claims to implement, not just a fixture written to match it.
_real_validator: ValidatorAdapter = CrossRecordValidator()
# W2: the shipped loader against the boundary it fills in. `LoadedSource` is the typed DTO
# CORE-58 asks for, and its absence of any ruamel type is CORE-17 as a return annotation.
_loader: SourceLoader = YamlSourceLoader(root=Path())


# The capsule Protocols are structural descriptions of foreign objects, so the assertion that
# matters is that real ones satisfy them. arro3 objects are asserted in
# `tests/qualification/test_arrow_interchange.py`, where obtaining one needs a Delta table.
# The one that matters: the shipped provider against the boundary it claims to implement, not
# only the fixture written to match it.
_real_provider: SnapshotProvider = MaterializedPyArrowSnapshotProvider({})

_pa_schema: ArrowSchemaExportable = pa.schema([])
_pa_field: ArrowSchemaExportable = pa.field("x", pa.string())
_pa_table: ArrowStreamExportable = pa.table({})
_pa_reader: ArrowStreamExportable = pa.RecordBatchReader.from_batches(pa.schema([]), iter(()))
_pa_batch: ArrowArrayExportable = pa.RecordBatch.from_pylist([], schema=pa.schema([]))


_MANIFEST = ArchitectureRelease(
    release_id="rel-0001",
    model_id="sample-service",
    schema_version="1.0.0",
    profile_version="1.0.0",
    model_digest="sha256:" + "0" * 64,
    published_at=datetime(2026, 1, 1, tzinfo=UTC),
    tables=(),
    source_bundle=SourceBundle(source_id="s", digest="sha256:" + "1" * 64),
    generator=GeneratorProvenance(
        toolkit_version="0.1.0",
        toolkit_commit="0" * 40,
        storage_schema_version="1.0.0",
        hash_algorithm_version="1",
    ),
)


class RecordingPublisher:
    """A minimal `Publisher` (W4, DATA-21..DATA-24).

    The shipped `DeltaPublisher` is asserted against the same Protocol below; this one exists so
    the boundary is described by something that is not it. `expected_parent` is keyword-only with
    no default here for the same reason it has none on the Protocol: a caller must say which
    parent it built against, including saying `None` for the first release.
    """

    def publish(
        self, candidate: ReleaseCandidate, *, expected_parent: ReleaseId | None
    ) -> ArchitectureRelease:
        del candidate, expected_parent
        return _MANIFEST


_publisher: Publisher = RecordingPublisher()

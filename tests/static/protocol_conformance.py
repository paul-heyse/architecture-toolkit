"""Provider implementations are checked against their Protocols statically (CORE-58).

`isinstance` on a `runtime_checkable` Protocol compares method names only. Signature conformance
is a static property, so it is asserted here where Pyrefly can see it rather than in a runtime
test that would silently pass.
"""

from __future__ import annotations

from architecture_toolkit.domain.protocols import SnapshotProvider, ValidatorAdapter


class MaterializedProvider:
    def schema_for(self, table: str, *, version: int) -> object:
        return (table, version)


class RecordingValidator:
    def validate(self, candidate: object) -> list[object]:
        return [candidate]


# Assignment is the assertion: a signature mismatch fails `pyrefly check`.
_provider: SnapshotProvider = MaterializedProvider()
_validator: ValidatorAdapter = RecordingValidator()

"""Provider implementations are checked against their Protocols statically (CORE-58).

`isinstance` on a `runtime_checkable` Protocol compares method names only. Signature conformance
is a static property, so it is asserted here where Pyrefly can see it rather than in a runtime
test that would silently pass.
"""

from __future__ import annotations

from pathlib import Path

from architecture_toolkit.domain.authoring import YamlSourceLoader
from architecture_toolkit.domain.model import Model
from architecture_toolkit.domain.protocols import SnapshotProvider, SourceLoader, ValidatorAdapter
from architecture_toolkit.validation.context import ValidationContext
from architecture_toolkit.validation.diagnostics import Diagnostic
from architecture_toolkit.validation.pipeline import CrossRecordValidator


class MaterializedProvider:
    def schema_for(self, table: str, *, version: int) -> object:
        return (table, version)


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

"""Rebuilding a query catalog from the versions a release pins (DATA-39, DATA-46's floor).

`ARCH-TOOL-DATA-001` §11D: "Create one DataFusion `SessionContext` from one selected
ArchitectureRelease manifest. A release query context registers only the manifest-pinned table
versions. It must not combine independently resolved latest versions."

This module is the registration half of that and nothing more. **Query recipes are W5** — DATA-46
through DATA-50 own the release-scoped context type, the parameter and result schemas and the plan
evidence — so what lives here is the primitive those build on: given pins and a provider, register
exactly those versions under exactly those names.

It takes **pins, not a manifest**. `releases/` depends on `storage/`, so a manifest type here
would invert that and make a cycle out of a convenience. The caller reads pins off a manifest,
which keeps DATA-39's "rebuild the query catalog from the manifest" true where it matters — at
the call site, where somebody can see which manifest.

No partitioning, no Z-ordering, no compaction tuning and no custom indexes (DATA-39, DATA-59).
DataFusion's default catalog is in-memory, which suits a rebuild-per-release design: there is no
persistent catalog to drift from the manifests.
"""

from collections.abc import Mapping

import pyarrow as pa
from datafusion import SessionContext

from architecture_toolkit.domain.identifiers import TableId
from architecture_toolkit.storage.snapshot import MaterializedPyArrowSnapshotProvider

__all__ = ["register_pins"]


def register_pins(
    context: SessionContext,
    provider: MaterializedPyArrowSnapshotProvider,
    pins: Mapping[TableId, int],
    *,
    prefix: str = "",
) -> Mapping[TableId, pa.Schema]:
    """Register each pinned table version under its table id, and report the schemas registered.

    `prefix` supports §11D's cross-release comparison shape — `base.elements` against
    `candidate.elements` — without this module knowing what a comparison is. Registering two
    releases is two calls with two prefixes and two providers, which is what keeps independently
    resolved latest state from ever being one of the sides.
    """
    return {
        table_id: provider.register(context, f"{prefix}{table_id}", table_id, version=version)
        for table_id, version in pins.items()
    }

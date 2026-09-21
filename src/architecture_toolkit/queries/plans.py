"""What the engine actually did, captured as qualification evidence (DATA-49).

`data.md`: "Qualification may capture logical, optimized logical and physical plans plus
EXPLAIN/metrics. Engine plans are diagnostic evidence, not semantic architecture identity." Both
halves matter. A plan tells you whether a comparison really read two releases, whether a filter was
pushed down, and whether a provider that is supposed to be lazy quietly materialized everything —
and none of that belongs anywhere near a model digest.

**Evidence, not snapshots.** The artifact is written under `.runtime/`, ignored like
`requirement-evidence.json`, and what the test suite asserts are *properties* of a plan rather than
its bytes: which tables were scanned, whether both sides of a comparison appear, whether the
projection was pruned. A byte comparison against committed fixtures would turn every DataFusion
upgrade into a failed string equality that says nothing about whether the new plan is worse.
Properties say what we actually care about, and survive a plan being rewritten for the better.

**The result digest is over rows, not over Arrow bytes**, for the reason `storage/digests.py`
gives at length: a digest of serialized Arrow depends on Arrow's serialization, its dictionary
encoding and its metadata, and would move under a pyarrow release that changed none of the data.
Every recipe declares a scalar-only output schema and orders its rows, so canonical JSON over
`to_pylist()` is both stable and readable in the artifact.
"""

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

import datafusion
import pyarrow as pa

from architecture_toolkit.domain.base import CompiledRecord
from architecture_toolkit.domain.identifiers import (
    Digest,
    QueryRecipeId,
    ReleaseId,
    SchemaVersion,
)
from architecture_toolkit.queries.context import ComparisonContext, ReleaseContext
from architecture_toolkit.queries.execution import execute
from architecture_toolkit.queries.recipes import QueryRecipe
from architecture_toolkit.releases.provenance import digest_bytes

__all__ = [
    "EVIDENCE_PATH",
    "PlanEvidence",
    "capture",
    "scan_projections",
    "scanned_tables",
    "write_evidence",
]

EVIDENCE_PATH: Final[Path] = Path(".runtime") / "qualification" / "query-plan-evidence.json"
"""Beside `requirement-evidence.json`, under the ignored runtime directory and never committed."""

RESULT_PREIMAGE: Final[str] = "architecture-toolkit/query-result/v1\n"

_SCAN = re.compile(r"TableScan: (?P<name>[A-Za-z0-9_.]+)(?: projection=\[(?P<columns>[^\]]*)\])?")


class PlanEvidence(CompiledRecord):
    """One recipe's engine diagnostics, with enough provenance to say what produced them."""

    query_recipe_id: QueryRecipeId
    query_recipe_version: SchemaVersion
    release_ids: tuple[ReleaseId, ...]
    parameters: tuple[tuple[str, str], ...]
    datafusion_version: str
    provider_type: str
    materialization: str
    output_schema: tuple[tuple[str, str], ...]
    logical_plan: str
    optimized_logical_plan: str
    physical_plan: str
    row_count: int
    result_digest: Digest


def scanned_tables(plan: str) -> tuple[str, ...]:
    """Every name the plan scans, in the order the plan names them.

    A recursive CTE scans its own working table, so this reports names a recipe never declared as
    an input. The caller decides which of those are persisted tables; this only reads the plan.
    """
    return tuple(match.group("name") for match in _SCAN.finditer(plan))


def scan_projections(plan: str) -> Mapping[str, tuple[str, ...] | None]:
    """Which columns each scan reads, or `None` where the plan pruned nothing.

    `None` is the interesting value: it means the scan reads every column of the table, which is
    what DATA-49 asks the evidence to be able to show.
    """
    found: dict[str, tuple[str, ...] | None] = {}
    for match in _SCAN.finditer(plan):
        columns = match.group("columns")
        found[match.group("name")] = (
            tuple(part.strip() for part in columns.split(",")) if columns else None
        )
    return found


def result_digest(table: pa.Table) -> Digest:
    """A deterministic digest of the rows a recipe returned."""
    payload = json.dumps(table.to_pylist(), sort_keys=True, separators=(",", ":"), default=str)
    return digest_bytes(RESULT_PREIMAGE.encode() + payload.encode())


def capture(
    recipe: QueryRecipe,
    context: ReleaseContext | ComparisonContext,
    parameters: Mapping[str, object] | None = None,
) -> PlanEvidence:
    """Run one recipe and record what the engine planned, alongside the answer it produced."""
    answer = execute(recipe, context, parameters)
    frame = context.sql(recipe.sql, dict(parameters) if parameters else None)
    description = context.describe()
    return PlanEvidence(
        query_recipe_id=recipe.query_recipe_id,
        query_recipe_version=recipe.query_recipe_version,
        release_ids=answer.release_ids,
        parameters=tuple(sorted((name, str(value)) for name, value in (parameters or {}).items())),
        datafusion_version=datafusion.__version__,
        provider_type=description.provider_type,
        materialization=description.materialization.value,
        output_schema=tuple((field.name, str(field.type)) for field in answer.table.schema),
        logical_plan=frame.logical_plan().display_indent(),
        optimized_logical_plan=frame.optimized_logical_plan().display_indent(),
        physical_plan=frame.execution_plan().display_indent(),
        row_count=answer.table.num_rows,
        result_digest=result_digest(answer.table),
    )


def write_evidence(evidence: Sequence[PlanEvidence], path: Path = EVIDENCE_PATH) -> Path:
    """Write the artifact, creating its directory. Returns where it landed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "schema_version": 1,
        "datafusion_version": datafusion.__version__,
        "recipes": [json.loads(item.model_dump_json()) for item in evidence],
    }
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    return path

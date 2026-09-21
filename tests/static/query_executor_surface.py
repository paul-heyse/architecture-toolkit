"""`ReleaseQueryExecutor` satisfies `QueryExecutor`, checked by the type checker (CORE-58, CORE-59).

The same job `tests/static/pyarrow_surface.py` and `networkx_surface.py` do for third-party
boundaries, applied to one of our own. A structural Protocol nothing is ever assigned to is a
Protocol nobody finds out has drifted: the declaration and the implementation can diverge for a
whole wave and every test still passes, which is precisely what happened to `QueryExecutor` between
W5 and W5.1.

The assignment on the last line is the assertion. `pa.Table` exports the Arrow C data interface, so
a concrete pyarrow return satisfies a capsule-typed protocol without `domain/` ever importing
pyarrow — the arrangement `SnapshotProvider` established at W3.

Not collected by pytest: the filename does not start with `test_`.
"""

from pathlib import Path
from typing import assert_type

import pyarrow as pa

from architecture_toolkit.domain.protocols import QueryExecutor
from architecture_toolkit.queries.context import ReleaseContext
from architecture_toolkit.queries.execution import QueryResult, ReleaseQueryExecutor
from architecture_toolkit.queries.graph import ArchitectureGraph
from architecture_toolkit.releases.store import ReleaseStore

_executor = ReleaseQueryExecutor(ReleaseStore.at(Path(".runtime") / "releases"))

assert_type(_executor.context_for("rel-0001"), ReleaseContext)
assert_type(_executor.graph_for("rel-0001"), ArchitectureGraph)
assert_type(_executor.current(), str)
assert_type(_executor.answer("capability_coverage_matrix", release_id="rel-0001"), QueryResult)
assert_type(
    _executor.compare(
        "application_ownership_across_releases",
        base_release_id="rel-0001",
        candidate_release_id="rel-0002",
    ),
    QueryResult,
)
assert_type(_executor.execute("capability_coverage_matrix", release_id="rel-0001"), pa.Table)

# The conformance assertion. A drift in either the protocol or the implementation fails here.
_protocol: QueryExecutor = _executor

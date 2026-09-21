"""Semantic change records, the lifecycle API and the layout gate (DATA-26, DATA-28, DATA-38).

The composition layer. It is the one package that may import `domain`, `storage`, `validation`,
`releases` and `queries` together, which is why it exists at all: `queries/` already imports
`releases/`, so a change record living in `releases/` could not carry a `TraversalResult` without a
circular import, and DATA-26 requires it to carry impact-analysis results.

Nothing below imports this package — `rules/changes-not-imported-by-lower-layers.yml` and
`tests/unit/test_layering.py` hold the two halves of that, since an `ignores` glob is the half
`ast-grep test` cannot exercise.

The narrative is computed from **models**, never from a release. DATA-38 previews the diff before
persist and publish, and CORE-20 presents one after a round-trip edit; in both the candidate is
unpublished, so a release-scoped engine cannot be the source. DataFusion and the Delta change feed
are cross-checks on that answer, which is what `ARCH-TOOL-DATA-001` §11H already says of the feed:
"Do not use them as the architectural change narrative."
"""

from architecture_toolkit.changes.classification import (
    CHANGE_CLASSIFICATION,
    PRESENCE_RULES,
    presence_rule_for,
    rule_for,
)
from architecture_toolkit.changes.diff import (
    PRESENTATION_FIELDS,
    field_changes,
    model_changes,
    presentation_changes,
)
from architecture_toolkit.changes.errors import (
    ChangeError,
    ClassificationError,
    DiffError,
    LineageError,
    ReviewError,
)
from architecture_toolkit.changes.kinds import (
    NARRATIVE_NATURES,
    NEVER_EMITTED,
    UNREACHABLE_NATURES,
    ChangeKind,
    ChangeNature,
    ChangeRule,
    Traversal,
)
from architecture_toolkit.changes.records import FieldChange, ModelChanges, RecordChange

__all__ = [
    "CHANGE_CLASSIFICATION",
    "NARRATIVE_NATURES",
    "NEVER_EMITTED",
    "PRESENCE_RULES",
    "PRESENTATION_FIELDS",
    "UNREACHABLE_NATURES",
    "ChangeError",
    "ChangeKind",
    "ChangeNature",
    "ChangeRule",
    "ClassificationError",
    "DiffError",
    "FieldChange",
    "LineageError",
    "ModelChanges",
    "RecordChange",
    "ReviewError",
    "Traversal",
    "field_changes",
    "model_changes",
    "presence_rule_for",
    "presentation_changes",
    "rule_for",
]

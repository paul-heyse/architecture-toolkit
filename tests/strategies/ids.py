"""One strategy per semantic alias, built from the alias's own pattern constant (CORE-45)."""

from typing import Any

from hypothesis import strategies as st

from architecture_toolkit.domain import identifiers

__all__ = [
    "STRATEGY_BY_ALIAS",
    "digests",
    "element_ids",
    "extension_namespaces",
    "model_ids",
    "qualified_kinds",
    "table_ids",
]


def _from(pattern: str) -> st.SearchStrategy[str]:
    """`fullmatch=True` against the anchored constant the alias itself declares.

    Importing the constant rather than retyping the expression is the whole point: a tightened
    constraint cannot leave its generator behind.
    """
    return st.from_regex(pattern, fullmatch=True)


identifiers_ = _from(identifiers.IDENTIFIER_PATTERN)
qualified_kinds = _from(identifiers.QUALIFIED_KIND_PATTERN)
digests = _from(identifiers.DIGEST_PATTERN)
versions = _from(identifiers.VERSION_PATTERN)
table_ids = _from(identifiers.TABLE_ID_PATTERN)
extension_namespaces = _from(identifiers.EXTENSION_NAMESPACE_PATTERN)

element_ids = identifiers_
model_ids = identifiers_

# Every alias the module exports, mapped to the strategy that generates it. The totality test in
# `tests/unit/test_strategies.py` asserts this covers all of them, so a new alias without a
# strategy fails rather than silently going ungenerated.
STRATEGY_BY_ALIAS: dict[str, st.SearchStrategy[Any]] = {
    "ArtifactId": identifiers_,
    "BindingId": identifiers_,
    "ChangeSetId": identifiers_,
    "ContextId": identifiers_,
    "Digest": digests,
    "ElementId": identifiers_,
    "ExtensionNamespace": extension_namespaces,
    "InteractionId": identifiers_,
    "LayoutDigest": digests,
    "LinkId": identifiers_,
    "ModelId": identifiers_,
    "NotationObjectId": st.text(min_size=1, max_size=255),
    "PolicyId": identifiers_,
    "ProfileVersion": versions,
    "QualifiedKind": qualified_kinds,
    "QueryRecipeId": identifiers_,
    "ReferenceId": identifiers_,
    "RelationshipId": identifiers_,
    "RelationshipTypeId": identifiers_,
    "ReleaseId": identifiers_,
    "RuleId": identifiers_,
    "SchemaVersion": versions,
    "SemanticDigest": digests,
    "TableId": table_ids,
    "ViewId": identifiers_,
}

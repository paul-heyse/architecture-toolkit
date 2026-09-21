"""Centralized semantic scalar aliases (CORE-03).

`ARCH-TOOL-CORE-001` §3C requires reusable ID, version and digest concepts to be constrained
`Annotated` aliases declared once, not raw-string rules repeated at each field. Constraints
declared here flow into generated JSON Schema for free, so CORE-12's `pattern` keywords and the
runtime rule are the same rule rather than two that drift.

**The patterns are exported deliberately.** `tests/strategies/ids.py` builds every ID strategy
with `st.from_regex(PATTERN, fullmatch=True)` against these same constants. Hypothesis cannot read
a Pydantic constraint — `st.from_type` silently ignores `StringConstraints`, warns, and yields the
empty string — so the strategy has to restate the rule. Restating it *from the constant* is what
stops a tightened pattern from silently leaving its generator behind.

Anchors are load-bearing. Pydantic's `pattern` is a search, not a full match: the unanchored form
of `IDENTIFIER_PATTERN` accepts `"XX abc XX"`. Every pattern here is anchored, and
`st.from_regex(..., fullmatch=True)` reads the anchored form correctly.
"""

from typing import Annotated

from pydantic import StringConstraints

__all__ = [
    "DIGEST_PATTERN",
    "EXTENSION_NAMESPACE_PATTERN",
    "IDENTIFIER_PATTERN",
    "QUALIFIED_KIND_PATTERN",
    "TABLE_ID_PATTERN",
    "VERSION_PATTERN",
    "ArtifactId",
    "BindingId",
    "ChangeSetId",
    "ContextId",
    "Digest",
    "ElementId",
    "ExtensionNamespace",
    "InteractionId",
    "LayoutDigest",
    "LinkId",
    "ModelId",
    "NotationObjectId",
    "PolicyId",
    "ProfileVersion",
    "QualifiedKind",
    "QueryRecipeId",
    "ReferenceId",
    "RelationshipId",
    "RelationshipTypeId",
    "ReleaseId",
    "RuleId",
    "ScenarioId",
    "SchemaVersion",
    "SemanticDigest",
    "TableId",
    "ViewId",
]

# A stable identity: lowercase, starts with a letter, 3..64 characters. Dots, dashes and
# underscores are permitted so that `software.system.billing` and `req-1` are both expressible.
IDENTIFIER_PATTERN = r"^[a-z][a-z0-9_.-]{2,63}$"

# A qualified kind is exactly two dotted segments: `software.interface`, `motivation.requirement`.
# Two, not "at least two", because the registry is keyed on the pair and a third segment would
# make `software.interface.http` look like a sibling of `software.interface` rather than a detail.
QUALIFIED_KIND_PATTERN = r"^[a-z][a-z0-9]*\.[a-z][a-z0-9_]*$"

# The algorithm is part of the value. A bare hex string cannot say what produced it, and W4 pins
# these into immutable manifests where that ambiguity would be permanent.
DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"

VERSION_PATTERN = r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"

# A physical table name. Narrower than `IDENTIFIER_PATTERN` on purpose: dots and dashes are legal
# in an architecture identifier and are not legal in a SQL identifier, and W5 registers these
# names in a DataFusion catalog where a dotted name would read as a schema qualifier.
TABLE_ID_PATTERN = r"^[a-z][a-z0-9_]{2,63}$"

# An extension namespace is at least two dotted segments, so `acme.finance` is expressible and a
# bare `acme` is not. DATA-13's point is that an extension is somebody else's vocabulary; a
# single-segment namespace would collide with the toolkit's own `architecture_toolkit` keys the
# moment two consumers picked the same word.
EXTENSION_NAMESPACE_PATTERN = r"^[a-z][a-z0-9]*(\.[a-z][a-z0-9]*)+$"

_Identifier = StringConstraints(pattern=IDENTIFIER_PATTERN, strict=True)
_Digest = StringConstraints(pattern=DIGEST_PATTERN, strict=True)
_Version = StringConstraints(pattern=VERSION_PATTERN, strict=True)

# -- identities -------------------------------------------------------------------------------
# Distinct aliases over one pattern. They are not interchangeable to a reader or a type checker
# even though they are interchangeable to a regex, which is the whole point of CORE-03.

ModelId = Annotated[str, _Identifier]
BindingId = Annotated[str, _Identifier]
LinkId = Annotated[str, _Identifier]
ElementId = Annotated[str, _Identifier]
RelationshipId = Annotated[str, _Identifier]
RelationshipTypeId = Annotated[str, _Identifier]
InteractionId = Annotated[str, _Identifier]
ContextId = Annotated[str, _Identifier]
ReferenceId = Annotated[str, _Identifier]
ReleaseId = Annotated[str, _Identifier]
ChangeSetId = Annotated[str, _Identifier]
# DATA-28. A design alternative is not a later revision of its baseline, and the way to make that
# sayable is to give it an identity of its own rather than a place in the release chain. Distinct
# from `ModelId` because an alternative *is* a variant of the same architecture — its element ids
# are the baseline's — and collapsing the two would make every alternative a separate model with
# no comparable objects.
ScenarioId = Annotated[str, _Identifier]
ViewId = Annotated[str, _Identifier]
ArtifactId = Annotated[str, _Identifier]
RuleId = Annotated[str, _Identifier]
QueryRecipeId = Annotated[str, _Identifier]
PolicyId = Annotated[str, _Identifier]

QualifiedKind = Annotated[str, StringConstraints(pattern=QUALIFIED_KIND_PATTERN, strict=True)]

TableId = Annotated[str, StringConstraints(pattern=TABLE_ID_PATTERN, strict=True)]
ExtensionNamespace = Annotated[
    str, StringConstraints(pattern=EXTENSION_NAMESPACE_PATTERN, strict=True)
]

# An identifier inside a foreign notation — a BPMN `Task_1`, an ArchiMate element id. Deliberately
# looser than `IDENTIFIER_PATTERN`: the notation owns that namespace and the toolkit does not get
# to impose its casing on it. `ARCH-TOOL-CORE-001` §3C reserves exactly this as the thirteenth
# alias, "notation-specific stable identifiers where useful".
NotationObjectId = Annotated[
    str, StringConstraints(min_length=1, max_length=255, strip_whitespace=False, strict=True)
]

# -- digests ----------------------------------------------------------------------------------
# DATA-31 requires semantic and layout identity to be separable. One `Digest` alias would let a
# layout hash be assigned to a semantic field, which is exactly the confusion the requirement
# exists to prevent: moving a diagram box must not read as an architectural redesign.

Digest = Annotated[str, _Digest]
SemanticDigest = Annotated[str, _Digest]
LayoutDigest = Annotated[str, _Digest]

# -- versions ---------------------------------------------------------------------------------

SchemaVersion = Annotated[str, _Version]
ProfileVersion = Annotated[str, _Version]

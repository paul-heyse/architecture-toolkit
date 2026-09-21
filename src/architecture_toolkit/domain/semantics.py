"""Canonical semantic identity of a validated model (CORE-21, DATA-27).

The digest is computed over the **validated, normalized record**, never over source text. That is
what makes CORE-21 hold by construction: comments, quote style, whitespace and key order never
reach a Pydantic record, so they cannot reach the preimage. What *can* reach it and must be
canonicalized is collection order, and the rule there is the one `ARCH-TOOL-DATA-001` §6A states:
sort unordered sets before hashing and preserve order for ordered sequences.

**Order is decided per field, never globally.** `COLLECTION_ORDER` names every tuple-typed field
reachable from `Model` and states whether it is unordered (canonicalized by an identity key),
ordered by an `ordinal` field (the tuple order is presentation; the ordinal is the semantic
order, which is why W1 gave behaviour nodes and schema fields one), or excluded from identity
altogether. `tests/unit/test_semantics.py` asserts the table is exhaustive, so a new collection
field must declare its policy before it can be hashed.

**The algorithm is versioned in the preimage.** `SEMANTIC_HASH_VERSION` is folded into every
digest through `PREIMAGE_PREFIX`, so a later change to normalization or algorithm is a DATA-56
migration with a new version rather than a silent digest shift under an old manifest. Only the
standard library is used for hashing and JSON (`ARCH-TOOL-DATA-001` §8B). No Unicode
normalization is applied: a normalization change would itself be a hash-version change.

`content_hash` fields are excluded at every depth, which is what lets `stamp_digests` be
idempotent and lets a stamped record hash equal to its unstamped form. The model-level digest is
computed and never stored; W4's manifest records it.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from types import MappingProxyType
from typing import Final

from pydantic import BaseModel

from architecture_toolkit.domain.base import CompiledRecord
from architecture_toolkit.domain.details import (
    BehaviorDetail,
    DataSchemaDetail,
    RequirementDetail,
)
from architecture_toolkit.domain.identifiers import SemanticDigest
from architecture_toolkit.domain.model import Element, Interaction, Model, Relationship
from architecture_toolkit.domain.views import ViewDefinition, ViewFilter

__all__ = [
    "COLLECTION_ORDER",
    "EXCLUDED_FIELDS",
    "MODEL_COLLECTIONS",
    "PREIMAGE_PREFIX",
    "SEMANTIC_HASH_VERSION",
    "CollectionDelta",
    "CollectionOrder",
    "CollectionPolicy",
    "SemanticDelta",
    "canonical_json",
    "canonical_value",
    "collection_digest",
    "model_digest",
    "normalize_record",
    "record_digest",
    "semantic_delta",
    "stamp_digests",
]

SEMANTIC_HASH_VERSION: Final[str] = "1"
"""Bump only with a DATA-56 migration; W4 pins digests carrying this version into manifests."""

PREIMAGE_PREFIX: Final[str] = f"architecture-toolkit/semantic/v{SEMANTIC_HASH_VERSION}\n"

EXCLUDED_FIELDS: Final[frozenset[str]] = frozenset({"content_hash"})
"""Removed at every depth: a digest must not depend on a previously stored digest."""


class CollectionPolicy(StrEnum):
    UNORDERED = "unordered"
    ORDERED_BY_ORDINAL = "ordered_by_ordinal"
    AUTHORED_ORDER = "authored_order"
    EXCLUDED = "excluded"


@dataclass(frozen=True, slots=True)
class CollectionOrder:
    """How one tuple-typed field enters the preimage.

    `key` names the item fields that define canonical order for `UNORDERED` and
    `ORDERED_BY_ORDINAL`; empty means the items are scalars sorted by value. The canonical JSON of
    the item is always the final tiebreaker, so the order is total.
    """

    policy: CollectionPolicy
    key: tuple[str, ...] = ()


_UNORDERED = CollectionPolicy.UNORDERED
_BY_ORDINAL = CollectionPolicy.ORDERED_BY_ORDINAL

COLLECTION_ORDER: Final[Mapping[tuple[type[BaseModel], str], CollectionOrder]] = MappingProxyType(
    {
        (Model, "elements"): CollectionOrder(_UNORDERED, ("element_id",)),
        (Model, "relationships"): CollectionOrder(_UNORDERED, ("relationship_id",)),
        (Model, "interactions"): CollectionOrder(_UNORDERED, ("interaction_id",)),
        (Model, "references"): CollectionOrder(_UNORDERED, ("reference_id",)),
        (Model, "reference_links"): CollectionOrder(_UNORDERED, ("link_id",)),
        (Model, "notation_bindings"): CollectionOrder(_UNORDERED, ("binding_id",)),
        (Model, "views"): CollectionOrder(_UNORDERED, ("view_id",)),
        # PROJ-03: membership is a *set* of objects. A view that listed the same members in
        # another order is the same view, and treating the order as identity would make
        # reordering a YAML list read as a membership change.
        (ViewDefinition, "included_element_ids"): CollectionOrder(_UNORDERED),
        (ViewDefinition, "included_relationship_ids"): CollectionOrder(_UNORDERED),
        # Filters compose by intersection, so their order does not change what is selected.
        (ViewDefinition, "filter"): CollectionOrder(_UNORDERED, ("filter_mode", "dimension")),
        (ViewFilter, "values"): CollectionOrder(_UNORDERED),
        # DATA-04: readable aliases coexist with the stable identity and are not part of it.
        (Element, "aliases"): CollectionOrder(CollectionPolicy.EXCLUDED),
        # DATA-13: extensions are part of identity — a consumer annotation is content the author
        # wrote — but their order is not, because nothing reads them positionally.
        (Element, "extensions"): CollectionOrder(_UNORDERED, ("namespace", "key")),
        (Relationship, "extensions"): CollectionOrder(_UNORDERED, ("namespace", "key")),
        (Interaction, "participants"): CollectionOrder(
            _BY_ORDINAL, ("ordinal", "element_id", "participant_role")
        ),
        (Interaction, "moved_object_ids"): CollectionOrder(_UNORDERED),
        (DataSchemaDetail, "fields"): CollectionOrder(_BY_ORDINAL, ("ordinal", "field_id")),
        (BehaviorDetail, "nodes"): CollectionOrder(_BY_ORDINAL, ("ordinal", "node_id")),
        (BehaviorDetail, "transitions"): CollectionOrder(_BY_ORDINAL, ("ordinal", "transition_id")),
        (RequirementDetail, "acceptance_criterion_ids"): CollectionOrder(_UNORDERED),
    }
)
"""Every tuple-typed field reachable from `Model`, and how it is canonicalized. Total by test."""

# The six top-level collections and the identity field of each, in `Model` field order. Used by
# `stamp_digests` and `semantic_delta`, cross-checked against `COLLECTION_ORDER` by test, and
# public because W6's diff and its DataFusion cross-check both need exactly this list — three
# copies of it would be three chances for one of them to miss a seventh collection.
MODEL_COLLECTIONS: Final[tuple[tuple[str, str], ...]] = tuple(
    (name, COLLECTION_ORDER[(Model, name)].key[0])
    for name in (
        "elements",
        "relationships",
        "interactions",
        "references",
        "reference_links",
        "notation_bindings",
        "views",
    )
)


# -- normalization -------------------------------------------------------------------------------


def canonical_value(value: object) -> str:
    """The canonical JSON spelling of one normalized value.

    Public because W6's field diff renders the before and after of a change, and rendering them
    any other way would be a second canonicalization — two spellings of the same value that agree
    today and would eventually disagree about something the digest cares about.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sort_key(order: CollectionOrder) -> Callable[[object], tuple[str, ...]]:
    def key(item: object) -> tuple[str, ...]:
        parts: list[str] = []
        if isinstance(item, dict):
            for name in order.key:
                parts.append(canonical_value(item.get(name)))
        parts.append(canonical_value(item))
        return tuple(parts)

    return key


def _normalize_value(value: object, dumped: object, order: CollectionOrder | None) -> object:
    if isinstance(value, BaseModel) and isinstance(dumped, dict):
        return _normalize_fields(value, dumped)
    if isinstance(value, frozenset) and isinstance(dumped, list):
        # A frozenset is unordered by type; its dump order is whatever iteration produced.
        return sorted(dumped, key=canonical_value)
    if isinstance(value, tuple) and isinstance(dumped, list):
        items = [
            _normalize_value(inner, inner_dump, None)
            for inner, inner_dump in zip(value, dumped, strict=True)
        ]
        if order is None or order.policy is CollectionPolicy.AUTHORED_ORDER:
            return items
        return sorted(items, key=_sort_key(order))
    return dumped


def _normalize_fields(record: BaseModel, dumped: dict[str, object]) -> dict[str, object]:
    cls = type(record)
    normalized: dict[str, object] = {}
    for name in cls.model_fields:
        if name in EXCLUDED_FIELDS:
            continue
        order = COLLECTION_ORDER.get((cls, name))
        if order is not None and order.policy is CollectionPolicy.EXCLUDED:
            continue
        normalized[name] = _normalize_value(getattr(record, name), dumped[name], order)
    return normalized


def normalize_record(record: BaseModel) -> dict[str, object]:
    """The canonical form of a record: JSON-mode values, policies applied, digests removed."""
    dumped: dict[str, object] = record.model_dump(mode="json")
    return _normalize_fields(record, dumped)


def canonical_json(record: BaseModel) -> bytes:
    """Deterministic UTF-8 bytes of the canonical form. Keys sorted, no whitespace."""
    return canonical_value(normalize_record(record)).encode("utf-8")


# -- digests -------------------------------------------------------------------------------------


def _digest(kind: str, payload: bytes) -> SemanticDigest:
    preimage = PREIMAGE_PREFIX.encode("utf-8") + kind.encode("utf-8") + b"\n" + payload
    return f"sha256:{sha256(preimage).hexdigest()}"


def record_digest(record: BaseModel) -> SemanticDigest:
    """Digest of one record. The record's class name is part of the preimage."""
    return _digest(type(record).__name__, canonical_json(record))


def collection_digest(records: Iterable[BaseModel]) -> SemanticDigest:
    """Digest of an unordered collection: sorted record digests, so batch order cannot matter.

    W3 defines a table's digest as this function over the records the table encodes, which is how
    chunk layout, dictionary encoding and metadata stay outside semantic identity (DATA-45).
    """
    members = sorted(record_digest(record) for record in records)
    return _digest("collection", "\n".join(members).encode("utf-8"))


def model_digest(model: Model) -> SemanticDigest:
    """Digest of the whole canonical model. Computed, never stored (W4's manifest records it)."""
    return record_digest(model)


# -- stamping ------------------------------------------------------------------------------------


def _stamp_element(element: Element) -> Element:
    detail = element.detail
    if detail is not None:
        detail = type(detail).model_validate(dict(detail) | {"content_hash": record_digest(detail)})
    with_detail = Element.model_validate(dict(element) | {"detail": detail})
    return Element.model_validate(dict(with_detail) | {"content_hash": record_digest(with_detail)})


def _stamp_record[R: CompiledRecord](record: R) -> R:
    return record.model_validate(dict(record) | {"content_hash": record_digest(record)})


def stamp_digests(model: Model) -> Model:
    """Fill every record's `content_hash` through `model_validate`. Idempotent.

    Details are stamped before the element that owns them; the element's preimage covers the
    detail's canonical form, not its stamped hash, so the element digest is the same either way.
    """
    elements = tuple(_stamp_element(element) for element in model.elements)
    relationships = tuple(_stamp_record(record) for record in model.relationships)
    interactions = tuple(_stamp_record(record) for record in model.interactions)
    references = tuple(_stamp_record(record) for record in model.references)
    reference_links = tuple(_stamp_record(record) for record in model.reference_links)
    notation_bindings = tuple(_stamp_record(record) for record in model.notation_bindings)
    views = tuple(_stamp_record(record) for record in model.views)
    return Model.model_validate(
        dict(model)
        | {
            "elements": elements,
            "relationships": relationships,
            "interactions": interactions,
            "references": references,
            "reference_links": reference_links,
            "notation_bindings": notation_bindings,
            "views": views,
        }
    )


# -- record-level delta --------------------------------------------------------------------------


class CollectionDelta(CompiledRecord):
    """Identities added, removed and changed in one top-level collection, sorted."""

    collection: str
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed)


class SemanticDelta(CompiledRecord):
    """What changed between two models at record granularity.

    Classification — rename versus retire, endpoint versus contract change — is W6's semantic
    change record (DATA-26, DATA-28). This is the primitive it is computed from, and the
    "semantic diff" CORE-20 presents after a round-trip edit.
    """

    base_digest: SemanticDigest
    candidate_digest: SemanticDigest
    hash_algorithm_version: str
    collections: tuple[CollectionDelta, ...]

    @property
    def is_empty(self) -> bool:
        return all(delta.is_empty for delta in self.collections)


def _by_identity(records: Iterable[CompiledRecord], key: str) -> dict[str, SemanticDigest]:
    """Digest every record in one collection, keyed by its identity.

    Typed as `CompiledRecord` rather than as a union of the six collection item types. There used
    to be a `_Records` union here, and it was decoration: its only caller passes
    `getattr(base, name)`, whose type is `Any`, so no checker ever compared an argument against
    it. A union that cannot fail is a comment, and this one would have gone stale the first time
    a seventh collection arrived without anybody noticing.
    """
    return {str(getattr(record, key)): record_digest(record) for record in records}


def semantic_delta(base: Model, candidate: Model) -> SemanticDelta:
    """Per-collection added/removed/changed identities, by record digest."""
    collections: list[CollectionDelta] = []
    for name, key in MODEL_COLLECTIONS:
        before = _by_identity(getattr(base, name), key)
        after = _by_identity(getattr(candidate, name), key)
        collections.append(
            CollectionDelta(
                collection=name,
                added=tuple(sorted(set(after) - set(before))),
                removed=tuple(sorted(set(before) - set(after))),
                changed=tuple(
                    sorted(
                        identity
                        for identity in set(before) & set(after)
                        if before[identity] != after[identity]
                    )
                ),
            )
        )
    return SemanticDelta(
        base_digest=model_digest(base),
        candidate_digest=model_digest(candidate),
        hash_algorithm_version=SEMANTIC_HASH_VERSION,
        collections=tuple(collections),
    )

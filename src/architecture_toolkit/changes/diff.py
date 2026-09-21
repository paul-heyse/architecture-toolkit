"""The semantic diff: what changed between two models, at typed-field granularity (DATA-26).

**Two models, not two releases.** DATA-38's lifecycle previews the diff *before* persist and
publish, and CORE-20 presents one after a round-trip authoring edit; in both the candidate is
unpublished, so a release-scoped engine cannot be the narrative's source without making the
preview impossible. DataFusion and the Delta change feed cross-check this answer instead, which is
what `ARCH-TOOL-DATA-001` §11H already says of the feed: *"Do not use them as the architectural
change narrative."*

**The field diff runs over `normalize_record`, never `model_dump`.** The normalized form *is* the
digest preimage, so the two are the same function and the property that pins them —
`field changes are empty ⟺ record digests are equal` — can be asserted in both directions. Three
concrete things a `model_dump` diff gets wrong, all reachable today: `content_hash` is restamped on
every changed record and would be reported as a change on all of them; `Element.aliases` is visible
to it and invisible to the digest, which is the presentation-masquerading-as-semantics failure at
record scale; and a reordered `extensions` tuple would read as a change the digest says is not one.

**What the normal form cannot see gets its own pass.** `aliases` is excluded from the preimage, so
an alias-only edit moves no digest and `semantic_delta` reports nothing at all. The presentation
pass walks every identity present on *both* sides — not only the changed ones, since gating it on
`changed` is the obvious optimisation and would make the pass structurally incapable of ever
firing — and compares exactly the fields `COLLECTION_ORDER` marks excluded.
"""

from collections.abc import Iterator, Mapping, Sequence
from typing import Final, Literal, get_args, get_origin

from pydantic import BaseModel

from architecture_toolkit.changes.classification import (
    optional_record_rule_for,
    presence_rule_for,
    rule_for,
)
from architecture_toolkit.changes.errors import DiffError
from architecture_toolkit.changes.kinds import ChangeRule, Traversal
from architecture_toolkit.changes.records import FieldChange, ModelChanges, RecordChange
from architecture_toolkit.domain.authoring.plain import IDENTITY_KEYS
from architecture_toolkit.domain.model import Model
from architecture_toolkit.domain.semantics import (
    COLLECTION_ORDER,
    SEMANTIC_HASH_VERSION,
    CollectionPolicy,
    canonical_value,
    model_digest,
    normalize_record,
    record_digest,
)

__all__ = [
    "PRESENTATION_FIELDS",
    "field_changes",
    "model_changes",
    "presentation_changes",
]


class _Absent:
    """Distinct from `None`, which is a real value a field can hold."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<absent>"


_ABSENT: Final[_Absent] = _Absent()

PRESENTATION_FIELDS: Final[frozenset[tuple[type[BaseModel], str]]] = frozenset(
    key for key, order in COLLECTION_ORDER.items() if order.policy is CollectionPolicy.EXCLUDED
)
"""Fields the digest cannot see, derived from `COLLECTION_ORDER` rather than listed.

Exactly `{(Element, "aliases")}` today. Deriving it means a field a later wave excludes from the
preimage becomes visible to the presentation pass automatically, instead of becoming invisible to
everything — a hand-written literal would be a second source of truth for a fact `COLLECTION_ORDER`
already states, and the two would drift.
"""

# The six top-level collections and the field naming each record's identity, in `Model` order.
_COLLECTIONS: Final[tuple[tuple[str, str], ...]] = tuple(
    (name, COLLECTION_ORDER[(Model, name)].key[0])
    for name in (
        "elements",
        "relationships",
        "interactions",
        "references",
        "reference_links",
        "notation_bindings",
    )
)


def _records_in(annotation: object) -> list[type[BaseModel]]:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    found: list[type[BaseModel]] = []
    for argument in get_args(annotation):
        found.extend(_records_in(argument))
    return found


def _identity_key(cls: type[BaseModel]) -> str:
    """The field naming an item's identity, by the declared priority in `IDENTITY_KEYS`.

    Resolved from the class rather than from whichever key appears first in a mapping, which is
    what `domain/authoring/plain.py::_item_identity` does — that one reads document order while
    its own comment claims this priority. Harmless there today; not something to inherit.
    """
    for key in IDENTITY_KEYS:
        if key in cls.model_fields:
            return key
    message = f"{cls.__name__} has no identity key; it cannot be descended into"
    raise DiffError(message)


def _variant_for(
    classes: Sequence[type[BaseModel]], value: Mapping[str, object]
) -> type[BaseModel]:
    """Which member of a discriminated union this normalized mapping is."""
    if len(classes) == 1:
        return classes[0]
    for cls in classes:
        if all(
            value.get(name) == get_args(field.annotation)[0]
            for name, field in cls.model_fields.items()
            if get_origin(field.annotation) is Literal
        ):
            return cls
    message = f"no variant of {[cls.__name__ for cls in classes]} matches {sorted(value)}"
    raise DiffError(message)


def _discriminator(cls: type[BaseModel]) -> str:
    for name, field in cls.model_fields.items():
        if get_origin(field.annotation) is Literal:
            return name
    message = f"{cls.__name__} is a union member with no discriminator"  # pragma: no cover
    raise DiffError(message)  # pragma: no cover


def _mapping(owner: type[BaseModel], name: str, value: object) -> Mapping[str, object]:
    """Narrow a normalized nested record, refusing anything else rather than asserting.

    `normalize_record` produces a mapping for every record-valued field, so a non-mapping here
    means the annotation and the normal form disagree — a real failure, and one worth naming.
    """
    if isinstance(value, Mapping):
        return value
    message = f"{owner.__name__}.{name} normalized to {type(value).__name__}, not a record"
    raise DiffError(message)


def _canon(value: object) -> str | None:
    return None if isinstance(value, _Absent) else canonical_value(value)


def _emit(
    collection: str, identity: str, path: str, rule: ChangeRule, before: object, after: object
) -> FieldChange:
    return FieldChange(
        collection=collection,
        identity=identity,
        field_path=path,
        kind=rule.resolve(after),
        nature=rule.nature,
        before=_canon(before),
        after=_canon(after),
    )


def _walk(
    owner: type[BaseModel],
    before: Mapping[str, object],
    after: Mapping[str, object],
    *,
    collection: str,
    identity: str,
    prefix: str,
) -> Iterator[FieldChange]:
    for name, field in owner.model_fields.items():
        old = before.get(name, _ABSENT)
        new = after.get(name, _ABSENT)
        if old == new:
            continue
        rule = rule_for(owner, name)
        path = f"{prefix}{name}"
        if rule.traversal is Traversal.NEVER:
            message = (
                f"{owner.__name__}.{name} differs between two versions of "
                f"{collection}.{identity}, and it is declared as a field that cannot: "
                f"{rule.kind.value}"
            )
            raise DiffError(message)
        if rule.traversal is Traversal.LEAF:
            yield _emit(collection, identity, path, rule, old, new)
            continue
        yield from _descend(
            owner,
            name,
            field.annotation,
            old,
            new,
            rule,
            collection=collection,
            identity=identity,
            path=path,
        )


def _descend(
    owner: type[BaseModel],
    name: str,
    annotation: object,
    old: object,
    new: object,
    rule: ChangeRule,
    *,
    collection: str,
    identity: str,
    path: str,
) -> Iterator[FieldChange]:
    classes = _records_in(annotation)
    if isinstance(old, tuple | list) or isinstance(new, tuple | list):
        yield from _descend_items(
            classes[0],
            old if isinstance(old, tuple | list) else (),
            new if isinstance(new, tuple | list) else (),
            rule,
            collection=collection,
            identity=identity,
            path=path,
        )
        return
    # An optional nested record: arriving or leaving is one fact about the whole, never a field
    # change for each of its fields.
    if old is None or isinstance(old, _Absent) or new is None or isinstance(new, _Absent):
        arrived = new is not None and not isinstance(new, _Absent)
        yield _emit(
            collection,
            identity,
            path,
            optional_record_rule_for(owner, name, arrived=arrived),
            old,
            new,
        )
        return
    old, new = _mapping(owner, name, old), _mapping(owner, name, new)
    old_class = _variant_for(classes, old)
    new_class = _variant_for(classes, new)
    if old_class is not new_class:
        # A retype. Descending would narrate it as "lost eight fields, gained six", which is a
        # field-level story for something that is not a field-level change — the same reasoning
        # `domain/commands.py` gives for why retyping an element is deliberately inexpressible.
        field_name = _discriminator(old_class)
        yield _emit(
            collection,
            identity,
            f"{path}.{field_name}",
            rule,
            old.get(field_name),
            new.get(field_name),
        )
        return
    yield from _walk(
        old_class, old, new, collection=collection, identity=identity, prefix=f"{path}."
    )


def _descend_items(
    item_class: type[BaseModel],
    old: Sequence[object],
    new: Sequence[object],
    rule: ChangeRule,
    *,
    collection: str,
    identity: str,
    path: str,
) -> Iterator[FieldChange]:
    """Pair an identity-keyed collection by key, never by position.

    Zipping positionally would report one insertion at ordinal 0 as N changes, which is the noisy
    publication the wave plan names as its first risk.
    """
    key = _identity_key(item_class)
    before = {str(item[key]): item for item in old if isinstance(item, Mapping)}
    after = {str(item[key]): item for item in new if isinstance(item, Mapping)}
    for item_id in sorted(set(before) | set(after)):
        was, now = before.get(item_id, _ABSENT), after.get(item_id, _ABSENT)
        if was == now:
            continue
        if isinstance(was, _Absent) or isinstance(now, _Absent):
            yield _emit(collection, identity, f"{path}.{item_id}", rule, was, now)
            continue
        was, now = _mapping(item_class, key, was), _mapping(item_class, key, now)
        yield from _walk(
            item_class,
            was,
            now,
            collection=collection,
            identity=identity,
            prefix=f"{path}.{item_id}.",
        )


def field_changes(
    collection: str, identity: str, base: BaseModel, candidate: BaseModel
) -> tuple[FieldChange, ...]:
    """Which typed fields differ between two versions of one record.

    Empty exactly when `record_digest(base) == record_digest(candidate)`, which
    `tests/property/test_change_properties.py` asserts in both directions. That equivalence is
    what makes the differ neither blind nor inventive, and it holds because both sides read the
    same normalized form.
    """
    if type(base) is not type(candidate):
        message = f"cannot diff {type(base).__name__} against {type(candidate).__name__}"
        raise DiffError(message)
    return tuple(
        _walk(
            type(base),
            normalize_record(base),
            normalize_record(candidate),
            collection=collection,
            identity=identity,
            prefix="",
        )
    )


def presentation_changes(
    collection: str, identity: str, base: BaseModel, candidate: BaseModel
) -> tuple[FieldChange, ...]:
    """Fields the digest cannot see, compared on the raw records.

    `normalize_record` has already dropped these, so they are read straight off the records. This
    is the only place in the change layer that looks at anything outside the preimage, and it is
    deliberate: DATA-04 says an alias is not part of identity, and that is exactly why an alias
    edit must be *reported* as the presentation change it is rather than silently vanish.
    """
    found: list[FieldChange] = []
    for owner, name in sorted(PRESENTATION_FIELDS, key=lambda item: (item[0].__name__, item[1])):
        if not isinstance(base, owner):
            continue
        old = getattr(base, name)
        new = getattr(candidate, name)
        if old == new:
            continue
        found.append(_emit(collection, identity, name, rule_for(owner, name), old, new))
    return tuple(found)


def _record_change(collection: str, identity: str, changes: Sequence[FieldChange]) -> RecordChange:
    return RecordChange(
        collection=collection,
        identity=identity,
        kinds=tuple(sorted({change.kind for change in changes})),
        natures=tuple(sorted({change.nature for change in changes})),
        fields=tuple(changes),
    )


def _presence(collection: str, identity: str, *, in_candidate: bool) -> RecordChange:
    rule = presence_rule_for(collection, in_candidate=in_candidate)
    return RecordChange(
        collection=collection,
        identity=identity,
        kinds=(rule.kind,),
        natures=(rule.nature,),
    )


def model_changes(base: Model, candidate: Model) -> ModelChanges:
    """Every change between two models, classified, semantic and presentational together.

    Takes two models and nothing else — no store, no release, no change set. A change set would
    report the author's *intent*; this reports the model's *content*, and DATA-27 avoids the first
    for the same reason it hashes validated records rather than source text.
    """
    if base.model_id != candidate.model_id:
        message = (
            f"{base.model_id!r} and {candidate.model_id!r} are different models; a scenario is "
            f"compared against its baseline with an alternative comparison, not a diff"
        )
        raise DiffError(message)
    records: list[RecordChange] = []
    for collection, key in _COLLECTIONS:
        before = {str(getattr(item, key)): item for item in getattr(base, collection)}
        after = {str(getattr(item, key)): item for item in getattr(candidate, collection)}
        for identity in sorted(set(before) - set(after)):
            records.append(_presence(collection, identity, in_candidate=False))
        for identity in sorted(set(after) - set(before)):
            records.append(_presence(collection, identity, in_candidate=True))
        for identity in sorted(set(before) & set(after)):
            was, now = before[identity], after[identity]
            changes = presentation_changes(collection, identity, was, now)
            if record_digest(was) != record_digest(now):
                changes = (*field_changes(collection, identity, was, now), *changes)
            if changes:
                records.append(_record_change(collection, identity, changes))
    records.extend(_model_level_changes(base, candidate))
    return ModelChanges(
        model_id=base.model_id,
        base_digest=model_digest(base),
        candidate_digest=model_digest(candidate),
        hash_algorithm_version=SEMANTIC_HASH_VERSION,
        records=tuple(records),
    )


def _model_level_changes(base: Model, candidate: Model) -> Iterator[RecordChange]:
    """`schema_version` and `profile_version`, which belong to no collection.

    A profile-version change is the difference between re-mapping and re-authoring, which
    `domain/notation.py` says DATA-31 requires stay separable — leaving `Model`'s own fields out of
    the diff is how that distinction would have gone unreported.
    """
    changes = [
        _emit("model", base.model_id, name, rule_for(Model, name), old, new)
        for name in ("schema_version", "profile_version")
        for old, new in [(getattr(base, name), getattr(candidate, name))]
        if old != new
    ]
    if changes:
        yield _record_change("model", base.model_id, changes)

"""What a diff reports: one field, one record, one model (DATA-26).

The addressing is three parts — collection, identity, field path — and not one string, because
`domain/source.py::split_path` already refuses to tokenize the identity grammar: identifiers
contain dots, and `elements.software.system.billing.detail.request_schema_id` cannot be split back
into "which element" and "which field" without knowing where the identifier ends. Storing one
string would make every consumer re-solve that, and one of them would get it wrong.

`field_path` is spelled the way `domain/references.py::FieldReference.field_path` is already
spelled in the model — record-relative, `detail.transport.protocol` — so a change can be turned
into a `FieldReference` by construction. That is what makes "which evidence supports the field
that changed" a join rather than a string transform, which DATA-26's decision references need.

**No positional indices anywhere.** A tuple position is presentation under `COLLECTION_ORDER`,
which sorts before a diff ever sees it, so index 3 on one side and index 3 on the other are not
the same object. A positional path would lie in exactly the dimension this wave exists to protect.
"""

from architecture_toolkit.changes.kinds import NARRATIVE_NATURES, ChangeKind, ChangeNature
from architecture_toolkit.domain.base import CompiledRecord
from architecture_toolkit.domain.identifiers import ModelId, SemanticDigest
from architecture_toolkit.domain.references import FieldReference

__all__ = ["FieldChange", "ModelChanges", "RecordChange"]


class FieldChange(CompiledRecord):
    """One field of one record, and what changing it means.

    `before` and `after` are canonical JSON strings rather than `object`, for two reasons that
    happen to agree: `CompiledRecord` forbids a mutable container at any depth, and rendering the
    values any other way would be a second canonicalization competing with the digest's. They are
    `domain.semantics.canonical_value` output, which is the digest's own spelling.
    """

    collection: str
    identity: str
    field_path: str
    kind: ChangeKind
    nature: ChangeNature
    before: str | None = None
    after: str | None = None

    @property
    def identity_path(self) -> str:
        """The address `validation/locate.py` uses: `elements.schema-1.detail.fields.x.ordinal`."""
        return f"{self.collection}.{self.identity}.{self.field_path}"

    @property
    def in_narrative(self) -> bool:
        return self.nature in NARRATIVE_NATURES

    def as_field_reference(self) -> FieldReference | None:
        """The existing address type, where one exists for this collection.

        `ReferenceTarget` has a field-granular variant for elements only, so this is `None` for
        the other five collections. Minting a fifth variant to make the join total would be a
        domain change no requirement in this wave asks for.
        """
        if self.collection != "elements":
            return None
        return FieldReference(element_id=self.identity, field_path=self.field_path)


class RecordChange(CompiledRecord):
    """One record that appeared, vanished or changed, and every kind that describes it.

    `kinds` is a tuple, not a single value. `UpdateElement` can move `name` and `description`
    together, and that is two facts rather than an argument about which one wins: a total order
    over kinds is something no contract establishes, and the first time somebody edits `name` and
    `source_element_id` together a precedence rule would hide an endpoint change behind a rename.
    That is the shape of reasoning that turns a rename into a retire-plus-add, so there is none.

    `natures` is stored rather than derived from `fields`, because an added or removed record has
    no changed fields and still has a nature — a notation binding appearing is a mapping change.
    Deriving would make the presence case a special case at every reader.
    """

    collection: str
    identity: str
    kinds: tuple[ChangeKind, ...]
    natures: tuple[ChangeNature, ...]
    fields: tuple[FieldChange, ...] = ()

    @property
    def in_narrative(self) -> bool:
        """One semantic field change among ten presentational ones is a semantic change.

        A binary question, answered with `any`, so nobody has to believe in a total order over
        natures.
        """
        return any(nature in NARRATIVE_NATURES for nature in self.natures)


class ModelChanges(CompiledRecord):
    """Every change between two models, semantic and presentational.

    Both digests are carried so a reader can tell apart the two cases that look alike from
    outside: "nothing changed" and "only what the digest cannot see changed". An alias edit is the
    second, and it is the purest layout-only case the current schema can express.
    """

    model_id: ModelId
    base_digest: SemanticDigest
    candidate_digest: SemanticDigest
    hash_algorithm_version: str
    records: tuple[RecordChange, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.records

    @property
    def narrative(self) -> tuple[RecordChange, ...]:
        """The architectural story, and the gate.

        Expressed once, here, so a renderer cannot drift from the classification it renders. The
        layout gate is the statement that this is empty while `records` is not.
        """
        return tuple(record for record in self.records if record.in_narrative)

    @property
    def presentation(self) -> tuple[RecordChange, ...]:
        return tuple(record for record in self.records if not record.in_narrative)

    @property
    def kinds(self) -> frozenset[ChangeKind]:
        return frozenset(kind for record in self.records for kind in record.kinds)

"""References, evidence links and the canonical-object address (DATA-09, CORE-04).

DATA-09's boundary is the important part: this stores links to approved modelling inputs. It is
not a second document-ingestion or evidence-extraction platform, and nothing here holds document
content.

The point of `ReferenceTarget` is precision about *what* a piece of evidence supports.
`ARCH-TOOL-DATA-001` §2E: a link should be able to support an interface's authentication
mechanism specifically, rather than appearing to validate an entire application. So a subject is
addressed as a discriminated union rather than a loose `(kind, id)` pair — the four variants
carry different fields because they genuinely need different fields, and only `FieldReference`
has a `field_path`.

`ARCH-TOOL-CORE-001` §3D names this as a domain union alongside details and commands. It is the
one the W1 plan document omitted.
"""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from architecture_toolkit.domain.base import CompiledRecord
from architecture_toolkit.domain.identifiers import (
    Digest,
    ElementId,
    LinkId,
    ModelId,
    ReferenceId,
    RelationshipId,
    ReleaseId,
)

__all__ = [
    "REFERENCE_TARGET_ADAPTER",
    "ElementReference",
    "FieldReference",
    "LinkRole",
    "Reference",
    "ReferenceKind",
    "ReferenceLink",
    "ReferenceTarget",
    "RelationshipReference",
    "ReleaseReference",
    "SubjectKind",
]


class SubjectKind(StrEnum):
    """What a reference link can point at. DATA-09 names exactly these four."""

    ELEMENT = "element"
    RELATIONSHIP = "relationship"
    FIELD = "field"
    RELEASE = "release"


class LinkRole(StrEnum):
    """How the reference bears on the subject. DATA-09 names exactly these four.

    `CONTRADICTS` is not an error state. Recording that a source disagrees with the model is
    evidence, and DATA-41 requires it be preserved rather than resolved away.
    """

    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    JUSTIFIES = "justifies"
    QUALIFIES = "qualifies"


class ReferenceKind(StrEnum):
    DOCUMENT = "document"
    DECISION = "decision"
    MEASUREMENT = "measurement"
    INTERVIEW = "interview"
    SOURCE_CODE = "source_code"
    EXTERNAL_SYSTEM = "external_system"


class ElementReference(CompiledRecord):
    subject_kind: Literal[SubjectKind.ELEMENT] = SubjectKind.ELEMENT
    element_id: ElementId


class RelationshipReference(CompiledRecord):
    subject_kind: Literal[SubjectKind.RELATIONSHIP] = SubjectKind.RELATIONSHIP
    relationship_id: RelationshipId


class FieldReference(CompiledRecord):
    """The variant that earns the union. A field path is meaningless on the other three."""

    subject_kind: Literal[SubjectKind.FIELD] = SubjectKind.FIELD
    element_id: ElementId
    field_path: str = Field(min_length=1)


class ReleaseReference(CompiledRecord):
    subject_kind: Literal[SubjectKind.RELEASE] = SubjectKind.RELEASE
    release_id: ReleaseId


ReferenceTarget = Annotated[
    ElementReference | RelationshipReference | FieldReference | ReleaseReference,
    Field(discriminator="subject_kind"),
]
"""One address type for every canonical object, used by links, notation bindings and diagnostics."""

REFERENCE_TARGET_ADAPTER: TypeAdapter[ReferenceTarget] = TypeAdapter(ReferenceTarget)


class Reference(CompiledRecord):
    """An approved modelling input. A pointer and its provenance, never the content."""

    reference_id: ReferenceId
    model_id: ModelId
    reference_kind: ReferenceKind
    title: str = Field(min_length=1)
    # Nullable on purpose: an interview has no locator, and inventing one to satisfy a
    # structural rule is what DATA-41 forbids.
    locator: str | None = None
    authority: str | None = None
    content_hash: Digest | None = None


class ReferenceLink(CompiledRecord):
    """Binds one reference to one precisely addressed subject."""

    link_id: LinkId
    model_id: ModelId
    reference_id: ReferenceId
    subject: ReferenceTarget
    link_role: LinkRole
    note: str | None = None
    content_hash: Digest | None = None

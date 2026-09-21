"""Generated, versioned JSON Schema contracts (CORE-12, CORE-13).

One registry, used by the CLI that writes the files and by `scripts/check_schema.py` that checks
them. That is the point of the module: before it, `cli.py` and `check_schema.py` each called
`Model.model_json_schema()` independently, so the first argument added to one of them would have
made the drift check compare a different document from the one the CLI writes — and report
"matches" forever.

Versioning lives in `$id` as `urn:architecture-toolkit:<family>:v<n>`, the convention already in
the tree at `schemas/qualification-evidence.schema.json`. Nothing new is invented.

Only validation mode is emitted. `ARCH-TOOL-CORE-001` §4 asks that validation and serialization
schemas differ only deliberately; measured against the pinned Pydantic they differ exactly and
only where a computed field exists, and this domain declares none. So `check_schema.py` asserts
the two modes are byte-identical, which is the strongest available form of CORE-13 — and if a
computed field is ever added, that check fails until the difference is declared and explained.

No timestamp, no commit hash, no generator version derived from the environment. Any
nondeterministic key would make the snapshot drift on every run and the check worthless.

**This module sits above both `domain` and `validation`, not inside either.** It began under
`domain/` and the layering guard rejected it: emitting the validation-report contract requires
importing `validation`, and the domain must not. A generator of machine-facing contracts is a
consumer of both layers rather than a peer of one, so it lives here and the dependency runs the
right way.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, TypeAdapter
from pydantic.json_schema import GenerateJsonSchema, JsonSchemaMode, models_json_schema

from architecture_toolkit.domain.commands import ChangeSet
from architecture_toolkit.domain.details import (
    BehaviorDetail,
    DataSchemaDetail,
    DeploymentDetail,
    InterfaceDetail,
    RequirementDetail,
)
from architecture_toolkit.domain.model import Element, Interaction, Model, Relationship
from architecture_toolkit.domain.notation import NotationBinding
from architecture_toolkit.domain.references import Reference, ReferenceLink
from architecture_toolkit.domain.registry import Profile
from architecture_toolkit.queries.recipes import QueryRecipe
from architecture_toolkit.queries.results import (
    ComponentResult,
    CondensationResult,
    CycleResult,
    GraphPathResult,
    ReachabilityEdge,
    ReductionEdge,
    ReleaseComparison,
    TraversalResult,
)
from architecture_toolkit.releases.manifest import ArchitectureRelease
from architecture_toolkit.validation.claims import ValidationClaimReport
from architecture_toolkit.validation.diagnostics import Diagnostic

__all__ = ["SCHEMA_FAMILIES", "SchemaFamily", "ToolkitJsonSchema", "emit"]

DIALECT = "https://json-schema.org/draft/2020-12/schema"


class ToolkitJsonSchema(GenerateJsonSchema):
    schema_dialect = DIALECT


@dataclass(frozen=True, slots=True)
class SchemaFamily:
    """One machine-facing contract. `roots=()` means declared but not yet emittable."""

    family_id: str
    version: int
    title: str
    description: str
    path: str
    requirements: frozenset[str]
    roots: tuple[type[BaseModel], ...] = ()
    deferred_to: str | None = None
    blocked_on: str | None = None
    computed_fields: frozenset[str] = field(default_factory=frozenset)

    @property
    def schema_id(self) -> str:
        return f"urn:architecture-toolkit:{self.family_id}:v{self.version}"


SCHEMA_FAMILIES: tuple[SchemaFamily, ...] = (
    SchemaFamily(
        family_id="authoring-model",
        version=1,
        title="Architecture authoring model",
        description="The canonical typed model a person authors.",
        path="schemas/model.schema.json",
        requirements=frozenset({"CORE-12", "DATA-03"}),
        roots=(Model,),
    ),
    SchemaFamily(
        family_id="element-detail",
        version=1,
        title="Element records and typed detail variants",
        description=(
            "The reusable record and detail shapes, emitted separately so a consumer can "
            "reference one variant without pulling in the whole model."
        ),
        path="schemas/element-detail.schema.json",
        requirements=frozenset({"CORE-12", "DATA-07", "DATA-09"}),
        roots=(
            Element,
            Relationship,
            Interaction,
            Reference,
            ReferenceLink,
            NotationBinding,
            InterfaceDetail,
            DeploymentDetail,
            DataSchemaDetail,
            BehaviorDetail,
            RequirementDetail,
        ),
    ),
    SchemaFamily(
        family_id="change-set",
        version=1,
        title="Typed architecture change commands",
        description="The only sanctioned mutation channel (CORE-10).",
        path="schemas/change-set.schema.json",
        requirements=frozenset({"CORE-10", "CORE-12"}),
        roots=(ChangeSet,),
    ),
    SchemaFamily(
        family_id="profile",
        version=1,
        title="Kind and relationship-type profile",
        description="The controlled vocabulary a model is validated against (DATA-04, DATA-05).",
        path="schemas/profile.schema.json",
        requirements=frozenset({"CORE-12", "DATA-04", "DATA-05"}),
        roots=(Profile,),
    ),
    SchemaFamily(
        family_id="validation-report",
        version=1,
        title="Diagnostics and validation claim report",
        description=(
            "What `architecture validate --format json` emits. A machine-facing contract under "
            "CORE-12's own wording, so it is schematised rather than left implicit."
        ),
        path="schemas/validation-report.schema.json",
        requirements=frozenset({"CORE-07", "CORE-11", "CORE-12"}),
        roots=(ValidationClaimReport, Diagnostic),
    ),
    SchemaFamily(
        family_id="release-manifest",
        version=1,
        title="Architecture release manifest",
        description=(
            "The immutable coherent multi-table revision (DATA-20, DATA-21). A Delta table "
            "version is not an architecture release; this is what one is."
        ),
        path="schemas/release-manifest.schema.json",
        requirements=frozenset({"CORE-12", "DATA-20", "DATA-21"}),
        roots=(ArchitectureRelease,),
    ),
    SchemaFamily(
        family_id="query-contract",
        version=1,
        title="Query parameters and results",
        description=(
            "What a query asks and what it answers: the versioned recipe with its parameter and "
            "result declarations, and the typed results a graph query returns (DATA-48, CORE-28)."
        ),
        path="schemas/query-contract.schema.json",
        requirements=frozenset({"CORE-12", "CORE-28", "DATA-48"}),
        roots=(
            QueryRecipe,
            TraversalResult,
            GraphPathResult,
            CycleResult,
            ComponentResult,
            CondensationResult,
            ReachabilityEdge,
            ReductionEdge,
            ReleaseComparison,
        ),
    ),
)


def _roots(family: SchemaFamily) -> tuple[type[BaseModel], ...]:
    return family.roots


def emit(family: SchemaFamily, *, mode: JsonSchemaMode = "validation") -> dict[str, Any]:
    """Render one family. `$schema` and `$id` lead, because a reader looks for them first."""
    roots = _roots(family)
    if not roots:
        message = f"schema family {family.family_id!r} has no roots; it is deferred"
        raise ValueError(message)
    keys, generated = models_json_schema(
        [(root, mode) for root in roots],
        title=family.title,
        ref_template="#/$defs/{model}",
        schema_generator=ToolkitJsonSchema,
    )
    document: dict[str, Any] = {
        "$schema": DIALECT,
        "$id": family.schema_id,
        "title": family.title,
        "description": family.description,
        "x-toolkit": {
            "family": family.family_id,
            "version": family.version,
            "requirements": sorted(family.requirements),
        },
    }
    # A single-root family is a *document* schema and needs a root to validate against.
    # `models_json_schema` returns only `$defs`, so without this the file would be a bundle of
    # definitions that accepts literally any input — which is how the authoring schema briefly
    # started accepting `{"model_id": "not a valid id", "elements": "wrong type"}`. Caught by
    # this script's own self-test. Multi-root families stay definition libraries by design;
    # there is no single document they describe.
    if len(roots) == 1:
        document["$ref"] = keys[roots[0], mode]["$ref"]
    return document | generated


def emittable() -> tuple[SchemaFamily, ...]:
    return tuple(family for family in SCHEMA_FAMILIES if _roots(family))


ADAPTERS: Mapping[str, TypeAdapter[Any]] = {
    "change-set": TypeAdapter(ChangeSet),
    "profile": TypeAdapter(Profile),
}
"""CORE-05, the fourth boundary §3E names: reusable scalar and collection schema generation."""

"""Minimal qualification contract; expand against the requirements before production use."""

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Kind(StrEnum):
    REQUIREMENT = "motivation.requirement"
    PROCESS = "business.process"
    SYSTEM = "software.system"
    COMPONENT = "software.component"
    INTERFACE = "software.interface"
    SCHEMA = "information.schema"
    ROLE = "organization.role"


class StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class StatusDimensions(StrictRecord):
    design_disposition: str = "proposed"
    implementation_state: str = "not_implemented"
    technical_qualification: str = "not_qualified"
    client_acceptance: str = "not_requested"
    evidence_review: str = "unreviewed"


class Element(StrictRecord):
    element_id: str = Field(min_length=1)
    kind: Kind
    name: str = Field(min_length=1)
    status: StatusDimensions = Field(default_factory=StatusDimensions)


class Relationship(StrictRecord):
    relationship_id: str = Field(min_length=1)
    source_element_id: str
    target_element_id: str
    relationship_type_id: str = Field(min_length=1)


class Model(StrictRecord):
    schema_version: str = "0.1.0"
    model_id: str = Field(min_length=1)
    elements: list[Element]
    relationships: list[Relationship]

    @model_validator(mode="after")
    def structural_invariants(self) -> Self:
        ids = [e.element_id for e in self.elements]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate element identity")
        relationship_ids = [e.relationship_id for e in self.relationships]
        if len(relationship_ids) != len(set(relationship_ids)):
            raise ValueError("duplicate relationship identity")
        for relation in self.relationships:
            if relation.source_element_id not in ids or relation.target_element_id not in ids:
                raise ValueError(f"unresolved endpoint: {relation.relationship_id}")
        return self

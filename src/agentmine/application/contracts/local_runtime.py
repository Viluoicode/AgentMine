"""Operator-approved local input/export contracts; paths are opaque locators to adapters."""

from dataclasses import dataclass
from datetime import datetime

from agentmine.application.contracts.data import DataColumn, DataFormat, RowConstraint
from agentmine.application.contracts.eligibility import EligibilityCheckRequest
from agentmine.application.contracts.runtime import InputEvidence
from agentmine.domain.eligibility import EligibilityPolicy
from agentmine.domain.values import Reference, require_aware_timestamp, require_reference


@dataclass(frozen=True, slots=True)
class ApprovedDataInput:
    reference: Reference
    relative_path: str
    format: DataFormat
    locator: str
    collected_at: datetime
    content_reference: Reference

    def __post_init__(self) -> None:
        InputEvidence(self.reference, self.content_reference)
        require_aware_timestamp(self.collected_at)
        if (
            not isinstance(self.relative_path, str)
            or not self.relative_path.strip()
            or not isinstance(self.format, DataFormat)
            or not isinstance(self.locator, str)
            or not self.locator.strip()
        ):
            raise ValueError("Explicit input path, format and provenance required")


@dataclass(frozen=True, slots=True)
class PrepareDataRequest:
    reference: Reference
    opportunity_reference: Reference
    evaluation_reference: Reference
    eligibility: EligibilityCheckRequest
    policy: EligibilityPolicy
    inputs: tuple[ApprovedDataInput, ...]
    columns: tuple[DataColumn, ...]
    unique_by: tuple[str, ...] = ()
    min_records: int = 1
    max_records: int = 1000
    constraints: tuple[RowConstraint, ...] = ()
    eligibility_review_reference: Reference | None = None

    def __post_init__(self) -> None:
        for value in (self.reference, self.opportunity_reference, self.evaluation_reference):
            require_reference(value, "prepare")
        if (
            not isinstance(self.inputs, tuple)
            or not 1 <= len(self.inputs) <= 10
            or any(not isinstance(item, ApprovedDataInput) for item in self.inputs)
        ):
            raise ValueError("1-10 approved input snapshots required")


@dataclass(frozen=True, slots=True)
class ExportedArtifact:
    name: str
    digest: str
    byte_count: int


@dataclass(frozen=True, slots=True)
class ArtifactExport:
    execution_reference: Reference
    content_reference: Reference
    artifacts: tuple[ExportedArtifact, ...]

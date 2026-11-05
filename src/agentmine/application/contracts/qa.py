"""Version-bound QA inputs, declared acceptance criteria and portable bundle binding."""

import json
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256

from agentmine.application.contracts.ai import QARequest, ReferencedText
from agentmine.application.contracts.data import DataPlan, DataResult
from agentmine.application.contracts.data import PartitionAcceptance as PartitionAcceptance
from agentmine.application.contracts.research import ResearchResult, TaskPlan
from agentmine.domain.budget import BudgetAuthorization
from agentmine.domain.errors import DomainError, ErrorCode
from agentmine.domain.qa import QAOutcome, QAReport
from agentmine.domain.values import Reference, require_reference
from agentmine.domain.work import Deliverable, QAResult, QAStatus


class ArtifactFormat(StrEnum):
    JSON = "application/json"
    CSV = "text/csv"
    MARKDOWN = "text/markdown"


class CoverageKind(StrEnum):
    COLUMN = "column"
    FIELD_PRESENT = "field_present"
    SECTION = "section"
    LITERAL = "literal"
    SEMANTIC = "semantic"


@dataclass(frozen=True, slots=True)
class RequiredArtifact:
    name: str
    format: ArtifactFormat

    def __post_init__(self) -> None:
        if not self.name.strip() or not isinstance(self.format, ArtifactFormat):
            raise DomainError(ErrorCode.INVALID_VALUE, "qa_format", "Named format required")


@dataclass(frozen=True, slots=True)
class QARequirement:
    reference: Reference
    artifact: str
    kind: CoverageKind
    criterion: str

    def __post_init__(self) -> None:
        require_reference(self.reference, "requirement")
        if (
            not self.artifact.strip()
            or not isinstance(self.kind, CoverageKind)
            or not self.criterion.strip()
            or len(self.criterion) > 2000
        ):
            raise DomainError(
                ErrorCode.INVALID_VALUE, "qa_requirement", "Bounded criterion required"
            )


@dataclass(frozen=True, slots=True)
class DataAcceptanceCriteria:
    """Frozen operator criteria, never synthesized from the generated deliverable."""

    formats: tuple[RequiredArtifact, ...]
    requirements: tuple[QARequirement, ...]
    partition_acceptance: PartitionAcceptance | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.formats, tuple)
            or not 1 <= len(self.formats) <= 20
            or any(
                not isinstance(item, RequiredArtifact)
                or item.name
                not in (
                    ("data.csv", "data.json", "validation.json")
                    if self.partition_acceptance is None
                    else ("clean.csv", "clean.json", "rejected.json", "validation.json")
                )
                or item.format not in (ArtifactFormat.CSV, ArtifactFormat.JSON)
                for item in self.formats
            )
            or len({item.name for item in self.formats}) != len(self.formats)
            or not isinstance(self.requirements, tuple)
            or not 1 <= len(self.requirements) <= 50
            or any(not isinstance(item, QARequirement) for item in self.requirements)
            or len({item.reference for item in self.requirements}) != len(self.requirements)
        ):
            raise DomainError(
                ErrorCode.INVALID_VALUE,
                "acceptance_criteria",
                "Explicit typed Data acceptance criteria required",
            )

        if self.partition_acceptance is None:
            if any(item.kind == CoverageKind.FIELD_PRESENT for item in self.requirements):
                raise DomainError(
                    ErrorCode.INVALID_VALUE, "acceptance", "FIELD_PRESENT requires v2"
                )
        else:
            if not isinstance(self.partition_acceptance, PartitionAcceptance):
                raise DomainError(
                    ErrorCode.INVALID_VALUE, "acceptance", "Typed v2 acceptance required"
                )
            self.partition_acceptance.__post_init__()
            expected = {
                "clean.csv": ArtifactFormat.CSV,
                "clean.json": ArtifactFormat.JSON,
                "rejected.json": ArtifactFormat.JSON,
                "validation.json": ArtifactFormat.JSON,
            }
            if {item.name: item.format for item in self.formats} != expected or any(
                item.artifact not in expected for item in self.requirements
            ):
                raise DomainError(
                    ErrorCode.INVALID_VALUE, "acceptance", "Exact v2 artifact contract required"
                )


def lifecycle_qa_result(report: QAReport) -> QAResult | None:
    """Existing QA-to-lifecycle mapping, shared by legacy and guarded completion."""
    if report.outcome == QAOutcome.REQUIRES_HUMAN_REVIEW:
        return None
    status = QAStatus.PASSED if report.outcome == QAOutcome.PASS else QAStatus.FAILED
    findings = json.dumps(
        {
            "report": report.reference.value,
            "outcome": report.outcome.value,
            "checks": [
                {
                    "stage": item.stage.value,
                    "code": item.code,
                    "outcome": item.outcome.value,
                    "explanation": item.explanation,
                    "evidence": [ref.value for ref in item.evidence],
                }
                for item in report.findings
            ],
        },
        sort_keys=True,
    )
    return QAResult(report.deliverable, status, findings)


def bundle_content(result: DataResult | ResearchResult) -> ReferencedText:
    names = [artifact.name for artifact in result.artifacts]
    if not names or len(set(names)) != len(names):
        raise DomainError(ErrorCode.INVALID_VALUE, "artifacts", "Unique named artifacts required")
    payload = json.dumps(
        {
            artifact.name: {"media_type": artifact.media_type, "content": artifact.content}
            for artifact in result.artifacts
        },
        ensure_ascii=True,
        sort_keys=True,
    )
    return ReferencedText(
        Reference("sha256:" + sha256(payload.encode("utf-8")).hexdigest()), payload
    )


@dataclass(frozen=True, slots=True)
class QAInspection:
    reference: Reference
    deliverable: Deliverable
    plan: DataPlan | TaskPlan
    result: DataResult | ResearchResult
    formats: tuple[RequiredArtifact, ...]
    requirements: tuple[QARequirement, ...]
    min_verified_sources: int = 1
    ai_authorization: BudgetAuthorization | None = None
    partition_acceptance: PartitionAcceptance | None = None

    def __post_init__(self) -> None:
        require_reference(self.reference, "qa_inspection")
        if not (
            (isinstance(self.plan, DataPlan) and isinstance(self.result, DataResult))
            or (isinstance(self.plan, TaskPlan) and isinstance(self.result, ResearchResult))
        ):
            raise DomainError(
                ErrorCode.INVALID_VALUE, "qa_type", "Matching worker plan/result required"
            )
        if (
            self.deliverable.execution_reference != self.plan.execution.reference
            or self.result.execution_reference != self.plan.execution.reference
        ):
            raise DomainError(ErrorCode.EVIDENCE_MISMATCH, "qa_scope", "Execution mismatch")
        if (
            not isinstance(self.formats, tuple)
            or not 1 <= len(self.formats) <= 20
            or any(not isinstance(item, RequiredArtifact) for item in self.formats)
        ):
            raise DomainError(
                ErrorCode.INVALID_VALUE, "qa_formats", "Explicit required formats needed"
            )
        if len({item.name for item in self.formats}) != len(self.formats):
            raise DomainError(ErrorCode.DUPLICATE_REFERENCE, "qa_formats", "Duplicate artifact")
        if (
            not isinstance(self.requirements, tuple)
            or not 1 <= len(self.requirements) <= 50
            or any(not isinstance(item, QARequirement) for item in self.requirements)
        ):
            raise DomainError(
                ErrorCode.INVALID_VALUE, "qa_requirements", "Explicit criteria needed"
            )
        if len({item.reference for item in self.requirements}) != len(self.requirements):
            raise DomainError(ErrorCode.DUPLICATE_REFERENCE, "requirements", "Duplicate criterion")
        if type(self.min_verified_sources) is not int or not 0 <= self.min_verified_sources <= 10:
            raise DomainError(
                ErrorCode.INVALID_VALUE, "source_limit", "Bounded source count required"
            )
        if isinstance(self.plan, DataPlan) and isinstance(self.result, DataResult):
            if self.partition_acceptance != self.plan.partition_acceptance:
                raise DomainError(
                    ErrorCode.EVIDENCE_MISMATCH, "qa_partition", "Frozen thresholds mismatch"
                )
            if self.plan.output_policy is not None:
                if (
                    self.result.partition is None
                    or self.result.partition.policy != self.plan.output_policy
                ):
                    raise DomainError(
                        ErrorCode.EVIDENCE_MISMATCH,
                        "qa_partition",
                        "Retained v2 assessment required",
                    )
                DataAcceptanceCriteria(self.formats, self.requirements, self.partition_acceptance)
            elif self.result.partition is not None or any(
                item.kind == CoverageKind.FIELD_PRESENT for item in self.requirements
            ):
                raise DomainError(
                    ErrorCode.INVALID_VALUE, "qa_partition", "Legacy inspection cannot enable v2"
                )
        elif self.partition_acceptance is not None or any(
            item.kind == CoverageKind.FIELD_PRESENT for item in self.requirements
        ):
            raise DomainError(ErrorCode.INVALID_VALUE, "qa_partition", "Data-only contract")
        if self.ai_authorization is not None:
            QARequest(
                self.plan.execution,
                self.deliverable,
                ReferencedText(self.deliverable.content_reference, ""),
                "Scope validation",
                self.ai_authorization,
                deterministic_insufficient=True,
            )

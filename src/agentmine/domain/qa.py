"""Explainable QA outcomes; passing QA never grants submission approval."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from agentmine.domain.errors import DomainError, ErrorCode
from agentmine.domain.values import Reference, require_aware_timestamp, require_reference
from agentmine.domain.work import Deliverable


class QAOutcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NEEDS_REVISION = "NEEDS_REVISION"
    REQUIRES_HUMAN_REVIEW = "REQUIRES_HUMAN_REVIEW"


class QAStage(StrEnum):
    DETERMINISTIC = "deterministic"
    DOMAIN_SPECIFIC = "domain_specific"
    AI = "ai"


@dataclass(frozen=True, slots=True)
class QAFinding:
    stage: QAStage
    code: str
    outcome: QAOutcome
    explanation: str
    evidence: tuple[Reference, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.stage, QAStage)
            or not isinstance(self.outcome, QAOutcome)
            or not self.code.strip()
            or not self.explanation.strip()
            or not isinstance(self.evidence, tuple)
            or not self.evidence
        ):
            raise DomainError(ErrorCode.INVALID_VALUE, "qa_finding", "Explained evidence required")
        for reference in self.evidence:
            require_reference(reference, "qa_evidence")


@dataclass(frozen=True, slots=True)
class QAReport:
    reference: Reference
    deliverable: Deliverable
    checked_at: datetime
    findings: tuple[QAFinding, ...]

    def __post_init__(self) -> None:
        require_reference(self.reference, "qa_report")
        require_aware_timestamp(self.checked_at)
        if (
            not isinstance(self.deliverable, Deliverable)
            or not isinstance(self.findings, tuple)
            or not self.findings
        ):
            raise DomainError(
                ErrorCode.INVALID_VALUE, "qa_report", "Deliverable and findings required"
            )
        stages = {QAStage.DETERMINISTIC: 0, QAStage.DOMAIN_SPECIFIC: 1, QAStage.AI: 2}
        if any(not isinstance(item, QAFinding) for item in self.findings):
            raise DomainError(ErrorCode.INVALID_VALUE, "qa_report", "Typed findings required")
        order = [stages[item.stage] for item in self.findings]
        if order != sorted(order) or order[0] != 0:
            raise DomainError(
                ErrorCode.INVALID_VALUE, "qa_order", "Deterministic checks must run first"
            )
        if 2 in order and (
            1 not in order
            or any(
                item.outcome != QAOutcome.PASS for item in self.findings if item.stage != QAStage.AI
            )
        ):
            raise DomainError(
                ErrorCode.INVALID_VALUE, "qa_order", "AI cannot override failed free checks"
            )

    @property
    def outcome(self) -> QAOutcome:
        for outcome in (QAOutcome.FAIL, QAOutcome.NEEDS_REVISION, QAOutcome.REQUIRES_HUMAN_REVIEW):
            if any(finding.outcome == outcome for finding in self.findings):
                return outcome
        return QAOutcome.PASS

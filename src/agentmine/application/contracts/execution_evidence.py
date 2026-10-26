"""Operator-retained inputs for deterministic runtime preflight, not new permission."""

from dataclasses import dataclass

from agentmine.application.contracts.eligibility import EligibilityCheckRequest
from agentmine.application.contracts.records import EvaluationRecord
from agentmine.domain.eligibility import EligibilityPolicy
from agentmine.domain.eligibility_rules import EligibilityEngine
from agentmine.domain.errors import DomainError, ErrorCode
from agentmine.domain.values import Reference, require_aware_timestamp, require_reference


@dataclass(frozen=True, slots=True)
class DataExecutionEvidence:
    eligibility_request: EligibilityCheckRequest
    eligibility_policy: EligibilityPolicy
    evaluation: EvaluationRecord
    eligibility_review_reference: Reference | None = None
    rules_version: str = EligibilityEngine.VERSION

    def __post_init__(self) -> None:
        if (
            not isinstance(self.eligibility_request, EligibilityCheckRequest)
            or not isinstance(self.eligibility_policy, EligibilityPolicy)
            or not isinstance(self.evaluation, EvaluationRecord)
            or self.rules_version != EligibilityEngine.VERSION
        ):
            raise DomainError(
                ErrorCode.EVIDENCE_MISMATCH,
                "execution_evidence",
                "Supported typed evidence required",
            )
        require_aware_timestamp(self.evaluation.evaluated_at)
        if self.eligibility_review_reference is not None:
            require_reference(self.eligibility_review_reference, "eligibility_review")

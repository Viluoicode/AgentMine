"""Explicit operator decisions bound to one reviewed action; never blanket consent."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from agentmine.domain.errors import DomainError, ErrorCode
from agentmine.domain.spending import SpendingRequest
from agentmine.domain.values import Reference, require_aware_timestamp, require_reference
from agentmine.domain.work import Deliverable


class ApprovalAction(StrEnum):
    EXTERNAL_SUBMISSION = "external_submission"
    WALLET_FINANCIAL = "wallet_financial"
    SENSITIVE_ACCOUNT = "sensitive_account"
    SPENDING = "spending"


class OperatorDecision(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_REVISION = "REQUEST_REVISION"


@dataclass(frozen=True, slots=True)
class ApprovalScope:
    action: ApprovalAction
    destination: Reference
    payload_reference: Reference
    deliverable: Deliverable | None = None
    spending: SpendingRequest | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.action, ApprovalAction):
            raise DomainError(ErrorCode.INVALID_VALUE, "action", "Known action required")
        require_reference(self.destination, "destination")
        require_reference(self.payload_reference, "payload")
        if self.action == ApprovalAction.EXTERNAL_SUBMISSION:
            if (
                not isinstance(self.deliverable, Deliverable)
                or self.payload_reference != self.deliverable.content_reference
            ):
                raise DomainError(
                    ErrorCode.EVIDENCE_MISMATCH, "scope", "Exact deliverable required"
                )
        elif self.deliverable is not None:
            raise DomainError(
                ErrorCode.INVALID_VALUE, "scope", "Deliverable belongs to submission scope"
            )
        if self.action == ApprovalAction.SPENDING:
            if (
                not isinstance(self.spending, SpendingRequest)
                or self.spending.context.human_approval is not None
                or self.payload_reference != self.spending.context.operation_reference
            ):
                raise DomainError(
                    ErrorCode.EVIDENCE_MISMATCH, "scope", "Unapproved spending request required"
                )
        elif self.spending is not None:
            raise DomainError(
                ErrorCode.INVALID_VALUE, "scope", "Spending belongs to spending scope"
            )


@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    review_reference: Reference
    actor: Reference
    decided_at: datetime
    decision: OperatorDecision
    reason: str | None = None

    def __post_init__(self) -> None:
        require_reference(self.review_reference, "review")
        require_reference(self.actor, "operator")
        require_aware_timestamp(self.decided_at)
        if not isinstance(self.decision, OperatorDecision):
            raise DomainError(
                ErrorCode.INVALID_VALUE, "decision", "Known operator decision required"
            )
        if self.reason is not None and (
            not isinstance(self.reason, str) or not self.reason.strip() or len(self.reason) > 4000
        ):
            raise DomainError(ErrorCode.INVALID_VALUE, "reason", "Nonblank bounded reason required")

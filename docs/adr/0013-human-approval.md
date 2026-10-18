# ADR 0013: One-operator approval snapshots and scoped consent

Status: Implemented for the requested Milestone 5A scope.

## Context

Submission already requires HumanApproval, while the review package is minimal and
spending accepts an unverified approval reference. Rejection/revision decisions need an
immutable audit and must never grant external-action permission.

## Decision

Add explicit ApprovalScope, ApprovalDecision and three operator decisions. Application
builds a retained OperatorReview from authoritative opportunity/content and ledger snapshots.
One configured operator records decisions through a trusted local entry point. Application
owns ApprovalRepository and ApprovalGuard; SQLite implements immutable storage. Validate
spend references at BudgetManager, and route ExecuteTask through that manager. Preserve
domain spending accounting and all existing budget caps.

Add READY_FOR_HUMAN_REVIEW -> IN_PROGRESS for explicit revision; require a newer deliverable
and repeat QA. Rejecting submission maps to SKIPPED. APPROVE grants no automatic submit.
Retain existing HumanApproval persistence compatibility and trusted manual submission API.
Model financial/account consent boundaries without implementing out-of-scope executors.

## Consequences

Reviews/decisions are auditable and scope-bound; concurrent conflicting choices fail.
Decision-first persistence allows transition recovery without changing who/when decided.
No remote identity authentication, multiple roles, new dependency or cloud resource appears.
The local caller/store remain trusted. Future public interfaces must authenticate the
operator, and future protected executors must enforce consent immediately before dispatch.

## Alternatives

Bare approval IDs permit unverified spending. A boolean flag loses scope, actor and evidence.
Building IAM or wallet/account executors would expand V1. Replacing all persisted approval
models would require migration without improving this local milestone's boundary.

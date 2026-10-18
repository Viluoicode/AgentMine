# Human approval boundary (Milestone 5A)

V1 has one local operator identity, supplied explicitly to `DecideOperatorReview` by
trusted composition. Operator commands must not be exposed as LLM tools or populated
from marketplace content. This is an application authorization boundary and local audit,
not an authentication service or multi-user IAM system. A reference by itself does not
prove a human identity. The local operator entry point and SQLite store are trusted.

## Operator workflow

1. Build an ApprovalScope for the exact action. Submission binds the full deliverable
   version/content digest and destination. Spending binds operation ID, purpose,
   task/opportunity, category, maximum amount/currency and ledger destination.
   Wallet/financial and sensitive-account scopes bind destination and an exact action
   payload reference; these categories have no execution adapter in V1.
2. `PrepareOperatorReview.execute(review_id, opportunity_id, ledger_id, scope)` loads
   authoritative opportunity/content/budget snapshots and persists an immutable review.
3. Render its opportunity, potential reward, eligibility, score, expected value, estimated
   cost, measured actual costs so far, deliverable/content, QA result, risks and destination.
   Also display `scope.spending` when requesting spend approval. Missing forecasts remain
   None; actual totals are per currency, with the underlying records and outstanding
   estimates retained. Empty measured totals never assert all execution costs were zero.
4. The operator explicitly calls `DecideOperatorReview.execute(review_id, decision, reason)`.
   The configured actor, clock timestamp, decision and optional reason are persisted.
   There is no default APPROVE, implicit approval from QA, notification send or submission.

| Decision | Submission review | Spending / other protected action |
| --- | --- | --- |
| APPROVE | APPROVED_FOR_SUBMISSION; later explicit SubmitTask still required | Scope-specific consent only; other policies still apply |
| REJECT | SKIPPED with operator reason (not a marketplace rejection) | No execution permission |
| REQUEST_REVISION | IN_PROGRESS; clear current deliverable/approval | No permission; prepare a revised request under a new review ID |

Rework requires a strictly newer deliverable version and fresh QA/human approval. A new
operator review is required after opportunity or ledger revision changes. APPROVE for
submission also refreshes source availability/deadline and rechecks exact stored content.
A different destination, changed content, cost scope or conflicting decision is rejected.
One decision wins atomically per review. Changed decisions require a new review; there is
no revocation/edit history API in this milestone.

## Enforced spending boundary

BudgetManager validates every supplied approval reference against ApprovalRepository,
including decision, timestamps, scope and amount. Missing repository, invented reference,
REJECT, REQUEST_REVISION or mismatched scope fails closed. ExecuteTask now uses this same
manager; workers and Bedrock already use it. Composition must inject the approval repository
into each manager that may dispatch approved paid operations. No dependency is implicit.

Above-threshold estimates without approval return REQUIRES_HUMAN_APPROVAL; equality does
not require approval. Current thresholds are checked even for outstanding authorizations.
Approval never overrides daily/monthly/task/SAVER/SCOUT_ONLY limits. Actual overruns are
still recorded honestly; approval cannot retrospectively prevent an already incurred
provider charge. A previously reserved operation whose threshold becomes stricter may
need release and a new approved operation ID, rather than changing its immutable context.

ApprovalGuard.require validates exact recorded consent for protected actions. There are no
wallet, financial-transfer or sensitive-account executors in V1, so this milestone neither
adds nor enables those actions. Future executors must check the guard immediately before
dispatch and enforce their own scope/idempotency policies. Approval does not expand V1.
Read-only payment verification/outcome tracking does not transfer money.

## Existing submission contract and persistence

SubmitTask continues to require the domain's exact HumanApproval plus current passing QA,
content digest and destination; it cannot submit from READY_FOR_HUMAN_REVIEW. The new review
workflow creates that HumanApproval only after persisting APPROVE. The pre-existing
ApproveSubmission entry point remains a trusted explicit human command, storing actor,
time, target and deliverable in the Opportunity; it is not a model decision endpoint.
Use the new workflow for the full economic review and three-decision audit. Neither entry
point authenticates a remote user; adding a public API would require an authentication ADR.

Application owns ApprovalRepository. SQLiteApprovalRepository stores immutable review and
first-writer decision snapshots using existing storage and codec facilities. No existing
persisted dataclass shape changes or schema migration is required. Decisions persist before
opportunity transitions; identical retries repair a failed transition using the original
timestamp. A stale conflicting opportunity cannot be overwritten. The record proves the
operator's decision, not that an action executed. Cross-repository transactions, notification
UI, approval revocation and external-action reconciliation are not added.

## Checks

Offline unit and SQLite tests cover all decisions, review fields, new-version enforcement,
stale snapshots/content/deadlines, atomic conflicting choices, reopen/retry, invented or
mismatched spending approvals, threshold equality/change and unchanged budget caps.
No dependencies, real paid calls, wallet actions or account actions are introduced.

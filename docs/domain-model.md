# Core Domain Model — Milestones 1B/1C

The domain uses immutable dataclasses, explicit enums and structured `DomainError`
failures. All dependencies are standard-library modules or other domain modules.
No I/O, process configuration, system clock, AI, marketplace or persistence is used.

## Models

- `Money`: finite `Decimal` and three uppercase ASCII currency letters. Signed
  values can represent negative net estimates; no currency conversion is implicit.
- `Reference`: nonblank caller-supplied identity/evidence reference.
- `Reward`: potential, accepted, or verified-payment stage. Accepted and verified
  payment rewards carry evidence and a submission reference.
- `ExpectedValue`: a separate, signed estimate with a rationale. No probability or
  valuation formula is assumed. Its meaning and computation belong to later policy.
- `Cost`: nonnegative recorded amount, unique reference and one of the four North
  Star cost categories.
- `Budget`: estimated commitments and separate actual records. Authorization denies
  proposed overspend; actual overruns are retained and explicitly flagged.
- `BudgetPolicy`: daily/monthly AI ceilings, task/approval limits, configurable SAVER
  settings and calendar timezone. See [budget domain](budget-domain.md).
- `Task`/`TaskType`: only RESEARCH and DATA_PROCESSING are supported.
- `Execution`: supported READY task, matching authorization and aware start timestamp.
  Zero-cost deterministic execution can run in SCOUT_ONLY.
- `Deliverable`: execution reference, positive version and immutable content reference.
- `QAResult`: passed/failed findings bound to a complete deliverable version.
- `HumanApproval`: actor, timestamp, target and complete deliverable version.
- `Submission`: current passing QA, approval, target, receipt and submission time.
- `Outcome`: accepted/rejected evidence, optionally with an accepted reward.
- `Opportunity`: lifecycle owner with immutable snapshots and state history.

## Lifecycle

```text
DISCOVERED → NORMALIZED → ELIGIBILITY_CHECK → ELIGIBLE → EVALUATED → SCORED
  → PLANNED → IN_PROGRESS → QA_PENDING → READY_FOR_HUMAN_REVIEW
  → APPROVED_FOR_SUBMISSION → SUBMITTED → ACCEPTED → PAID
```

Alternative branches:

- ELIGIBILITY_CHECK → INELIGIBLE, with a resolved eligibility assessment.
- UNKNOWN/REQUIRES_HUMAN_REVIEW remain in ELIGIBILITY_CHECK with machine reasons;
  later resolved facts may advance. See [eligibility engine](eligibility-engine.md).
- DISCOVERED, NORMALIZED, ELIGIBLE, EVALUATED, SCORED, PLANNED,
  READY_FOR_HUMAN_REVIEW or APPROVED_FOR_SUBMISSION → SKIPPED, with a reason.
- Failed QA: QA_PENDING → IN_PROGRESS; current deliverable/approval are cleared.
  Another finish and passing QA are required before human review.
- SUBMITTED → REJECTED, with outcome evidence.
- PLANNED/IN_PROGRESS/QA_PENDING → WAITING_FOR_BUDGET for denied paid execution/QA.
  Fresh status, deadline, eligibility and scoring precede restoring the saved phase
  with authorization; regular lifecycle actions cannot bypass revalidation.
  Expired/closed work is SKIPPED; newly ineligible work is INELIGIBLE.
- INELIGIBLE, SKIPPED, REJECTED and PAID are terminal in this milestone.

Use public domain actions to obtain new snapshots. State/history and all workflow
fields are excluded from constructor arguments and normal assignment. Internal `_move` validates the graph;
public actions additionally validate the required evidence. Generic dataclass copying
is not a persistence rehydration API. Rehydration is deferred to later design.

## Financial semantics

Potential reward, expected value, accepted reward and verified revenue are distinct.
Their amounts need not match. An accepted submission contributes zero verified
revenue. Only the PAID snapshot exposes its verified-payment amount as revenue.
Payment must match the submitted reference and opportunity currency.

Evidence references record a caller's verification assertion. They do not verify
payment with an external provider. Evidence authenticity remains a future boundary.
Zero rewards/costs are allowed; no maximum score or profitability formula is imposed.

## Limitations

Budgets are local immutable accounting/reservation models. Application orchestration
must atomically persist snapshots before external actions. Actual overruns are retained
with issues; billing reconciliation remains future adapter work.

This lifecycle represents one submission outcome and one verified payment, which
may differ from the accepted amount. Partial-payment accumulation, reversals,
general expiration, retries, unknown external results, acceptance revisions and persistence
are not implemented. Expiration at execution start and during budget revalidation is
enforced in 1C. State history has no transition timestamps; execution, approval
and submission timestamps are caller supplied. Full audit persistence remains future work.

Reference formats and currency syntax do not imply validation against any external
registry, currency precision rule or API contract.

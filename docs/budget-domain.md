# Budget and Operating Modes — Milestone 1C

Budget is an immutable domain aggregate. All money, timestamps, policies and
operation identities are supplied explicitly; it performs no billing/provider I/O.
Milestone 1C replaces the simple 1B ceiling/ledger API.

## Policy

Required, nonnegative Money values, all in one currency:

- `monthly_ai_budget`: calendar-month AI ceiling.
- `daily_ai_budget`: calendar-day AI ceiling.
- `max_cost_per_task`: cumulative task ceiling across all cost categories and periods.
- `human_approval_cost_threshold`: estimates strictly above this need a spending
  approval evidence reference. Approval cannot override limits.

Additional configurable inputs:

- `calendar_timezone`: defaults to UTC; callers can provide an explicit timezone.
- `saver_remaining_ratio`: defaults to 0.2. At or below 20% remaining in either AI
  period, mode becomes SAVER. Valid ratios are strictly between 0 and 1.
- `saver_ai_cost_factor`: defaults to 0.5. In SAVER, each AI request is also capped
  at 50% of `max_cost_per_task`; the cumulative task ceiling still applies.

Defaults are initial domain choices, not provider/pricing assumptions. Limits are
explicit constructor inputs; no environment loading occurs in Domain.

## Authorization and recording

```python
decision = budget.authorize(estimated_cost, category, context)
# Use/persist decision.budget; it includes commitments if AUTHORIZED.
# Only AUTHORIZED decisions contain a BudgetAuthorization.
recording = decision.budget.record(actual_cost, category, measurement_context)
# Use/persist recording.budget and audit recording.issues.
```

Authorization returns AUTHORIZED, DENIED or REQUIRES_HUMAN_APPROVAL, with a reason.
Denied/review-required requests reserve nothing. Authorized estimates are outstanding
commitments, not actual costs. Authorizations retain the policy under which they were granted.

`ai_spent(at, monthly=...)` reports actual AI costs only; `ai_committed(at, monthly=...)`
includes outstanding estimates as well.

CostContext contains operation identity/purpose, task/opportunity scope, an explicit
aware timestamp and optional approval evidence. Execution/QA require both task and
opportunity references. Operation references are caller-supplied idempotency keys.
Retries of outstanding authorization do not reserve twice. Conflicting reuse and
reauthorization of settled/released operations fail explicitly.

Actual recording settles the corresponding estimate and stores estimate, actual
amount and signed variance separately. Actual costs exceeding estimates or ceilings
are retained, with explicit ESTIMATE_EXCEEDED / limit-exceeded issues. Paid costs
without authorization, or after release, are recorded and flagged UNAUTHORIZED_COST.
Authorization prevents proposed overspend; accounting does not hide observed overrun.
Negative costs and incompatible identities/currencies fail.

Identical actual records are idempotent; conflicting records fail. Measurement time
can differ from authorization time but cannot predate it; scope/category/approval
must match. Actuals count in their measurement period. Outstanding estimates carry
conservatively into every evaluated period until settled or explicitly released.
Period rollover never discards cost history or pending commitments.

## Modes and continuity

- FULL: normal authorization limits.
- SAVER: signals preference for deterministic/cheap processing and applies the
  stricter AI request ceiling. Engine selection remains future application work.
- SCOUT_ONLY: denies new positive-cost requests, including non-AI paid requests.
  Zero-cost deterministic operations remain allowed.

Exhaustion of either AI ceiling derives SCOUT_ONLY; it does not shut down the agent.
Ingestion, normalization, deterministic eligibility, free scoring and outcome tracking
remain possible. Free deterministic task execution is also permitted. Execution needs
a matching authorization and READY Task.

An outstanding authorization is already funded. An identical retry returns the same
commitment, rather than permission for an additional operation. Explicit SCOUT_ONLY
or commitments above current AI ceilings deny even a pending paid retry until restored.
Execution idempotency must use operation identity too. Future application callers must
check current Budget before dispatch, rather than reuse a cached authorization blindly.

Lower actuals, releasing unused commitments, raising limits or a new calendar period
can restore budget. Requested SAVER/SCOUT_ONLY restrictions remain until explicitly
changed. Per-task totals never reset at calendar boundaries.

## Waiting and resumption

Denied paid execution can move PLANNED or IN_PROGRESS → WAITING_FOR_BUDGET;
denied paid QA can move QA_PENDING → WAITING_FOR_BUDGET. Opportunity and Task
both represent the wait, preserving the request, timestamp, prior phase, execution
and any deliverable. Human approval requests are separate from budget denial.

`resume_after_budget(assessment, budget, at)` requires refreshed status and an explicit
checked deadline (None means checked with no deadline). Refresh must be no earlier
than the wait and no later than resume time. Open, unexpired work additionally needs
resolved fresh eligibility, evaluation and score. References/currencies must match.

Checks precede a new authorization:

- Deadline at or before `at`: Task EXPIRED, Opportunity SKIPPED, no reservation.
- Closed: Task CANCELLED, Opportunity SKIPPED, no reservation.
- Ineligible: Task CANCELLED, Opportunity INELIGIBLE, no reservation.
- Still denied or awaiting spending approval: remains WAITING_FOR_BUDGET.
- Authorized: Task READY, Opportunity restored to its saved PLANNED/IN_PROGRESS/
  QA_PENDING phase with updated deadline/eligibility/evaluation/score. The result
  contains the new authorization and Budget snapshot; prior work is preserved.

Regular plan/start/finish/QA actions cannot exit WAITING_FOR_BUDGET. Only guarded
resume can restore an active phase. Manual skip cancels the nested waiting Task.
Execution checks deadline and authorization scope/time again. Spending approval and
deliverable approval are separate.

## Boundaries and limitations

Evidence, actual measurements and refreshed facts are caller assertions, not externally
verified data. No staleness TTL, automatic scheduler, pricing refresh or revised-estimate
policy is assumed. Resume uses the saved execution estimate; production orchestration
must refresh estimates or replan when cost assumptions change.

Waiting preserves domain execution/deliverable references; it does not checkpoint a
running external process. This is a domain capability, not a background worker. Atomic
snapshot persistence, concurrent reservations and provider execution idempotency remain future
application/adapter work; competing stale Budget snapshots are not coordinated here.
Callers must retain decision/recording results for audit.

Recording issues reflect the policy/commitments in the returned snapshot. There is no
billing synchronization, currency conversion or provider-enforced hard spending ceiling.

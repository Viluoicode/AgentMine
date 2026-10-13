# ADR 0002: Budget authorization, accounting and continuity

Status: Accepted for Milestone 1C under the project owner's request.
Supersedes ADR 0001's simple Budget API and blanket SCOUT_ONLY execution restriction.

## Context

AgentMine needs daily/monthly AI ceilings, task and approval thresholds. Actual cost
can differ from estimates. AI exhaustion must preserve free operations. Deferred
tasks need fresh checks before resuming.

## Decision

Separate estimated commitments from actual records. Return structured authorization
decisions and updated Budget snapshots. Retain observed overruns with explicit issues.
Use operation identity for idempotency and caller-supplied timestamps.

AI periods use configurable calendar timezone. Outstanding commitments carry across
periods until settlement/release; task totals include all categories and never reset.
Human approval does not override limits.

Derive operating mode from committed AI budget, allowing manual restrictions. Initial
configurable SAVER defaults are 20% remaining and a 50%-of-task-cap AI request ceiling.
SCOUT_ONLY denies new paid operations while preserving zero-cost deterministic work.

Add WAITING_FOR_BUDGET to Opportunity and Task. Revalidation checks refreshed status,
deadline, eligibility and score before reauthorization. Closed, expired or newly
ineligible work cannot resume. Waiting preserves PLANNED/IN_PROGRESS/QA_PENDING phase
and existing execution/deliverable data; only guarded resume restores those phases.

## Consequences

The 1B Budget API and Execution constructor change; application callers/adapters do
not exist yet. Execution now requires matching budget authorization. Spending is
limited without disabling free functions. Evidence authenticity, atomic persistence,
concurrency, billing reconciliation and scheduling remain deferred.

## Alternatives

Rejecting actual overruns would hide incurred costs. Counting estimates as actuals
would corrupt financial reporting. Resetting pending commitments at midnight could
permit overspend. Resuming without fresh checks could execute expired/ineligible work.

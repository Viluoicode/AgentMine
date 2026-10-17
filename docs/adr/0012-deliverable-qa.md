# ADR 0012: Ordered evidence-bearing deliverable QA

Status: Implemented for Milestone 4D.

## Context

Existing RunQA records an already-resolved binary assessment. Research/Data workers now
produce structured evidence that can be checked before optional paid semantic review.
Passing QA must preserve the explicit human approval boundary.

## Decision

Add domain QAOutcome/QAFinding/QAReport and application DeliverableQA with deterministic,
domain-specific and optional AI stages. Keep existing binary lifecycle QAResult compatible;
map PASS to PASSED, FAIL/NEEDS_REVISION to FAILED, and retain unresolved reports separately
without a terminal lifecycle assessment. Bind every inspection to exact persisted bundle
bytes, execution and deliverable version. Require explicit criteria from trusted callers.

Application owns QAJournal. SQLite implements immutable inspection/report/AI checkpoints.
Use the existing LLMProvider and BudgetManager only after free checks pass and semantic
review is required. Report persistence precedes lifecycle transition. Never submit or
create human approval from a QA outcome.

## Consequences

Existing persisted model shapes remain readable. Reports expose richer outcomes and
machine-readable evidence. Retained responses and operation claims protect paid retries.
Unknown outcomes remain pending for reconciliation. Explicit criteria and trusted plan
loading remain caller responsibilities; QA does not prove external source truth.

## Alternatives

Replacing the persisted binary QAResult would require migration and change the established
approval/submission contract. Always using AI increases cost and lets subjective review
mask reproducible failures. Both are unnecessary for this milestone.

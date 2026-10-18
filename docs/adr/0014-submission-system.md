# ADR 0014: Explicit submission modes and durable receipt evidence

Status: Implemented for the requested Milestone 5B scope.

## Context

The existing SubmitTask supports a gateway and one claim per submission ID. It lacks manual
packages, unsupported-mode results and response metadata. A different ID could claim the
same deliverable version, and a persisted response could be missed after a receipt-save error.

## Decision

Keep domain approval/QA/submission/acceptance/payment invariants. Add application submission
modes and optional response metadata. API uses SubmissionGateway; MANUAL creates an immutable
operator package and records an explicit operator receipt later; UNSUPPORTED does no external
work. Persist responses before lifecycle writes and recover cached confirmations first.

Strengthen the repository contract to one intent per ID and deliverable reference/version,
plus one immutable confirmation per intent. SQLite enforces both in write transactions.
Reconcile is observation-only. Never automatically switch modes or redispatch after failure.
Support exact legacy request/result shapes with additive codec defaults, without changing
stored domain aggregates or assuming vendor APIs.

## Consequences

All modes remain approval-bound and auditable. Local retries cannot obtain another send by
changing IDs. Manual external actions and provider idempotency still require operator/vendor
cooperation; local transactions cannot guarantee external exactly-once behavior. Production
marketplace gateways, failed-intent release, GUI/export tooling and downgrade migrations are
outside this milestone. No dependency, paid call or infrastructure service is added.

## Alternatives

Treating a package as submitted invents an external effect. Retrying POST after timeout risks
duplicates. Using another submission ID bypasses the previous lock. Guessing marketplace
receipt/reconciliation behavior violates the established external-contract rule.

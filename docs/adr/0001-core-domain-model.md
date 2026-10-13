# ADR 0001: Core domain model and guarded lifecycle

Status: Accepted for Milestone 1B implementation under the project owner's request.

## Context

AgentMine needs explicit V1 models without infrastructure. Acceptance cannot be
treated as payment, unsupported work must not execute, and overspend/state errors
must be visible.

## Decision

Use standard-library immutable dataclasses and enums. Money uses finite Decimal
values and explicit currency. Reward stages, ExpectedValue and verified revenue
remain separate. Opportunity owns a guarded lifecycle exposed through named actions.
Payment evidence is bound to a submission. Human approval and QA bind to the full
deliverable version; submission also checks target and temporal ordering.

Budgets enforce local ceilings and idempotent cost recording. FULL/SAVER limits are
explicit policy inputs; SCOUT_ONLY forbids work execution. No economics thresholds,
external verification contracts, repositories or services are introduced.

## Consequences

Domain tests need no paid calls, credentials or external systems. Snapshots preserve
prior state, and structured failures identify invariant violations. External evidence
authenticity, concurrency, reservations, rehydration and full auditability remain
future work. The initial lifecycle has one submission and one payment, with terminal
INELIGIBLE/SKIPPED/REJECTED/PAID states.

## Alternatives

Mutable public status fields would allow invalid transitions. A single undifferentiated
reward amount would conflate forecasts, acceptance and revenue. Framework-backed
models would introduce a dependency that the domain does not currently need.

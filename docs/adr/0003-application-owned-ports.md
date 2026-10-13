# ADR 0003: Application-owned business ports

## Status

Accepted for Milestone 2A under the requested scope. External API contracts and
concrete persistence/verification mechanisms remain unresolved.

## Context

The domain implements lifecycle and local budget policies. Future workflows need
discovery, durable evidence, AI assistance, submission, payment observations and time
without importing cloud, marketplace or SDK interfaces into the inner layers.

## Decision

Use synchronous structural Python Protocols owned by Application, with immutable
typed request/response records reusing domain models. Keep AI outputs advisory,
actual cost unknown explicitly, and submission/payment evidence distinct from
acceptance. Define conditional Opportunity writes and atomic conditional ledger/audit
commits to prevent silent lost updates. Require a submission intent/attempt journal
and observation-only reconciliation for uncertain external side effects.

Adapters translate failures into application-owned PortError codes. Domain remains
unchanged. No use cases, implementations, provider dependencies or unused fakes are
added. See [port responsibilities and semantics](../application-ports.md).

## Consequences

The boundary is vendor-neutral and statically typed. Protocol declarations cannot
prove atomicity, authenticity, idempotency or complete rehydration: future adapter
contract tests must verify those guarantees. Application must coordinate correlation,
authorization persistence, retries and recovery. There is no cross-repository unit
of work yet. Runtime async requirements may lead to a separate future ADR.

## Alternatives

SDK-shaped ports would couple workflows to vendors. Generic CRUD dictionaries would
hide identity/evidence and concurrency requirements. Concrete in-memory production
repositories or a general transaction framework would exceed this milestone.

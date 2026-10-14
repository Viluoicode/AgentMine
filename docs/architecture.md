# Architecture

## Dependency direction

Presentation → Application → Domain.
Infrastructure implements ports defined by the inner layer that needs them.
Bootstrap is the composition root and may wire all layers.

Domain is independent of frameworks, cloud SDKs, marketplaces, HTTP clients,
databases and external AI SDKs. Application must not import concrete adapters.

## Package responsibilities

| Package | Responsibility |
| --- | --- |
| domain | Explicit models, invariants and business policies |
| application | Use cases, orchestration and required ports |
| infrastructure | Replaceable adapters |
| presentation | Input/output boundaries calling use cases |
| bootstrap | Configuration and dependency wiring |

## Milestone 1A

All layers are empty package skeletons except bootstrap configuration and startup.
Settings are immutable, validated and loaded from an explicitly supplied mapping.
Only the entry point reads the process environment. No cached settings or adapters
exist. No framework or runtime dependency is required.

## Deferred decisions

Concrete persistence consistency, budget reservations, evidence authenticity,
structured logging and external contracts require later milestone design.
Milestone 1B implements the initial lifecycle and local accounting rules described
below. See `adr/README.md` for the scope of recorded decisions.

## Milestone 1B

Domain now contains pure immutable models, a guarded Opportunity lifecycle, distinct
financial stages, local budget accounting and V1 work restrictions. See
[domain model](domain-model.md) and [ADR 0001](adr/0001-core-domain-model.md).
Domain dependency direction is enforced by a unit test scanning imports.
At Milestone 1B, Application, infrastructure and presentation remained package skeletons.
Detailed economics, persistence, orchestration and external verification remain deferred.

## Milestone 1C

Budget owns local estimated commitments, actual recording and mode decisions.
Opportunity owns waiting/resumption using caller-supplied revalidation facts.
Execution requires authorization; free execution can run in SCOUT_ONLY.
Policies remain in Domain, without provider/persistence imports. See
[budget domain](budget-domain.md) and [ADR 0002](adr/0002-budget-authorization-and-continuity.md).
Cross-process reservation consistency and orchestration remain deferred.

## Milestone 2A

Application owns business-facing repository/service Protocols, typed immutable
contracts and structured PortError failures. Domain is unchanged; infrastructure
and presentation remain skeletons. Static tests enforce inner-layer imports.
Conditional ledger/audit writes and submission reconciliation are requirements for
future adapters, not implemented persistence or external operations. See
[application ports](application-ports.md) and
[ADR 0003](adr/0003-application-owned-ports.md).

## Milestone 2B

Application now coordinates thirteen injected use cases using public Domain actions
and business ports. Test-only fakes exercise orchestration without external calls.
Provenance/content journals and atomic submission claiming extend existing ports;
no concrete infrastructure or domain dependency changes are introduced. See
[use cases](application-use-cases.md) and
[ADR 0004](adr/0004-core-application-orchestration.md) for recovery boundaries and
explicitly supplied assessment policies.

## Milestone 2C

Domain owns the pure deterministic EligibilityEngine with explicit knowledge,
profile/policy and reason-code models. Application refreshes availability through
ports and applies engine results, retaining unknown/human-review assessments in
ELIGIBILITY_CHECK. No SDK, framework, LLM or infrastructure dependency is added.
See [eligibility engine](eligibility-engine.md) and
[ADR 0005](adr/0005-deterministic-eligibility.md).

## Milestone 2D

Domain owns economic forecasts and configurable explainable scoring. Application
replaces caller-selected values/scores with calculated assessments and retains the
complete policy/components in aggregates and EvaluationRecord through existing ports.
Dependency direction is unchanged. No infrastructure or runtime dependency is added.
See [economic scoring](economic-scoring.md) and [ADR 0006](adr/0006-economic-scoring-policy.md).

## Milestone 3A

SQLite adapters implement the existing repository ports. Bootstrap explicitly composes
them from a supplied file path. Domain and Application source are unchanged. Complete
versioned snapshots, conditional writes, atomic budget/audit persistence and submission
claims now have local implementations. Additional local reporting methods remain on
adapters until future Application use cases need read ports. See [local persistence](local-persistence.md)
and [ADR 0007](adr/0007-local-sqlite-persistence.md).

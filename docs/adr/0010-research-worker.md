# ADR 0010: Evidence-first ResearchWorker with durable operation claims

Status: Accepted for the requested Milestone 4B scope.

## Context

ExecuteTask calls LLMProvider directly. Worker and TaskPlan did not yet exist. Research
needs approved evidence collection, provenance, distinct facts/analysis/uncertainties,
accounting and recovery without marketplace or cloud behavior in Application.

## Decision

Add application-owned Worker, ResearchTool and ResearchJournal ports with typed plans,
observations/results. Implement ResearchWorker orchestration in Application. Require exact
configured tool/target approval and persisted budget authorization. Generalize existing
BudgetManager to TOOL as well as AI without changing Domain policy.

Build source inventories and attributed excerpts from captured tool evidence only. Keep
all LLM synthesis unverified; validate its existing research schema and bound citations.
Return portable report/source/findings text artifacts, without external submission.

Use immutable plans/checkpoints and one-owner operation claims in the existing SQLite
snapshot adapter. Reuse measured costs idempotently. Unknown dispatch outcomes require
reconciliation rather than an automatic paid retry.

## Consequences

Domain and existing workflows remain unchanged; callers invoke the new Worker explicitly.
No dependency or real research API is added. Source capture verification is an adapter
assertion, not proof of every factual claim. Journal/ledger are not one transaction; a
crash before response persistence requires manual reconciliation. Retained research text
needs appropriate local access controls. Lifecycle integration/export UI remain outside 4B.

## Alternatives

Letting models generate trusted sources or select arbitrary URLs would lose provenance
and tool approval. Automatically retrying unknown calls risks duplicate cost. Adding a
search API or generic workflow framework without a verified contract expands scope.

See [ResearchWorker](../research-worker.md) for contracts, setup and recovery limitations.

# ADR 0011: Deterministic DataWorker and constrained semantic field updates

Status: Accepted for the requested Milestone 4C scope.

## Context

AgentMine has a ResearchWorker and structured LLM data drafts but no executable data
processing pipeline. Data work needs predictable transformations, provenance, validation,
per-execution cost and recovery without using LLMs for deterministic operations.

## Decision

Add application-owned DataPlan/DataResult and DataJournal. Parameterize Worker by its
plan/result types so both ResearchWorker and DataWorker implement the same capability.
Keep business processing and deterministic CSV/JSON rendering in Application. Domain,
marketplaces and existing ExecuteTask/lifecycle behavior remain unchanged.

Use explicit extraction paths, normalization, evidence-backed lookup enrichment and bounded
declarative constraints. Preserve all rows; validation failures export a report, not a
successful dataset. Source/provenance comes from supplied snapshots rather than models.

AI is opt-in per semantic TEXT field with a stated reason. Use the existing LLMProvider;
validate exact row identity/field scope and run ordinary validation again after synthesis.
Reserve/check budget before dispatch, journal ownership/results and record actual usage,
including costs of invalid responses. Deterministic work records zero AI usage and can run
in SCOUT_ONLY; infrastructure cost remains explicitly unmeasured.

## Consequences

No dependencies or external data-source contracts are added. Local lookup enrichment is
supported; browsing/search/live enrichment remains outside scope. Worker type annotations
now need plan/result parameters. SQLite adds snapshot kinds through its existing codec.
Generated artifacts are returned as text, without filesystem/export UI or submission.
Source authenticity and semantic correctness remain unverified; human review is required.
Unknown model outcomes require manual reconciliation; journal and ledger are not atomic
with external billing. CSV formula escaping changes displayed lexical values, so JSON is
the canonical lossless representation.

## Alternatives

Pandas/ETL frameworks are unnecessary for bounded V1 records. LLM-first normalization adds
cost and uncertainty to deterministic work. Arbitrary scripts/expressions or unverified
live enrichment APIs would expand scope and weaken auditability.

See [DataWorker](../data-worker.md) for exact rules, limits, output shapes and tests.

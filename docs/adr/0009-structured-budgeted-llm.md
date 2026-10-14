# ADR 0009: Structured, budget-authorized LLM adapters

Status: Accepted for Milestone 4A implementation scope.

## Decision

Keep LLMProvider application-owned and AWS confined to infrastructure. Implement
Bedrock Converse and a deterministic offline Mock with identical local output validation.
Use existing evaluation/work/QA ports; embed planning assistance in work drafts.
Add an application BudgetManager to coordinate existing domain authorization and ledger
CAS commits. Require an explicit deterministic-QA-insufficient flag before AI QA.

Use operator-supplied model/region/tariffs, optional boto3, and explicit composition.
Treat marketplace input as untrusted user data, expose no tools or runtime secrets,
and reject schema-invalid or known-sensitive output. Never advance lifecycle from advice.

Persist dispatch ownership before calling Bedrock; disable SDK retries. Record observed
usage even when output fails validation. Unknown usage remains unresolved, not free.

## Consequences

Domain and existing service port signatures remain unchanged; Application adds only
vendor-neutral budget coordination and the QA fallback flag. Base/mock need no dependency.
SQLite journal and ledger cannot commit atomically; failures require manual reconciliation.
Token estimates are not hard spend caps. Flat tariffs do not price cache/tier dimensions.
Security filters cannot prove semantic correctness; human approval remains mandatory.
No live call, AWS resources, automatic bootstrap selection or model-specific output API
is introduced. See ../llm-infrastructure.md for contracts, setup and recovery limits.

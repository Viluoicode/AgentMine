# ResearchWorker — Milestone 4B

## Scope and composition

Application owns `Worker.execute(TaskPlan) -> ResearchResult`, `ResearchTool.collect`
and `ResearchJournal`. `ResearchWorker` implements Worker using injected tools, the
existing LLMProvider, BudgetManager and a journal. There were no Worker/TaskPlan types
before 4B. Domain, lifecycle and marketplace adapters are unchanged. No dependency,
live research API, browser/search client, external submission or background job is added.

Create a TaskPlan from a previously validated Research Execution, 1–20 explicit questions
and 1–10 ResearchSteps. Each step binds a globally unique operation reference, tool ID,
exact locator, nonnegative estimate and optional spending approval. The plan checks
Research-only task type, AI scope, currency, bounded text, duplicate targets and operation
identity. This structural validation does not establish marketplace eligibility: the
caller must retain the existing open/deadline/eligibility/scoring checks before execution
and budget resumption. Never convert arbitrary model plans directly into approved steps.

Configure each ApprovedResearchTool with its implementation, exact allowed locators and
minimum estimated cost. Approval comes from trusted composition, not task descriptions
or model output. All targets are checked before collection. A tool must perform only the
approved read, respect source terms, avoid automatic retries and unapproved redirects,
and return observed provenance/cost. No concrete external research contract is invented.
Adapters remain responsible for size limits, credential handling, safe network access and
truthful verification assertions. Supply public/approved research material only.

Example composition (all objects are supplied explicitly):

```python
worker = ResearchWorker(
    tools=(ApprovedResearchTool(tool_id, research_tool, approved_targets, minimum_cost),),
    llm=llm_provider,
    budget=budget_manager,
    journal=SQLiteResearchJournal(database),
)
result = worker.execute(TaskPlan(execution, questions, research_steps))
# result.artifacts contains name, media_type, content and SHA-256 digest.
```

Use MockLLMProvider and fake research tools offline. Bedrock remains an optional 4A
adapter with its own tariff/auth checks. Existing ExecuteTask still uses its original
LLMProvider path: 4B exposes an explicitly invoked worker, not automatic lifecycle wiring.
The worker does not approve QA, advance Opportunity, submit, or create verified revenue.
A future orchestrator can persist the returned package as a deliverable for QA/human review.

## Evidence and findings

Each SourceEvidence preserves tool ID, requested locator, title, exact source text,
collection time, verification status/note, verification reference and computed SHA-256.
The worker correlates source identity, target and collection time to the approved request.
It does not follow URLs suggested by the model. The checksum detects content changes;
it does not establish source authenticity by itself.

`VERIFIED_CONTENT` requires a tool-provided verification evidence reference. It means
that the tool verified the captured content's provenance, not that all assertions in the
source are objectively true. Facts are exact attributed excerpts of such captures.
Unverified sources stay explicitly UNVERIFIED, retain their explanation, and never enter
facts. Sources may still inform analysis, which always remains labeled unverified.

LLM research output must match the 4A schema: exact plan/content/evidence keys, bounded
nonempty plan/text, no duplicate keys, and source aliases bound to captured evidence.
The worker validates this again even with fake/replacement providers. The model's plan
is never executed. Analysis is extracted from the draft's content, not promoted to facts.
Source inventory is built exclusively from tool observations. Narrative hallucinations
can still occur; they remain unverified analysis and require human review.

Returned artifacts:

- `report.md`: questions, attributed facts, unverified analysis and uncertainties.
- `sources.json`: captured text, locator, tool, timestamp, verification and digest.
- `findings.json`: questions, structured facts, analysis, uncertainties and warning codes.

Artifacts are deterministic UTF-8 text values, not arbitrary filesystem writes. The caller
chooses where to export them. Source/model text in Markdown is rendered as indented literal
blocks to avoid creating active links/HTML. Journaled inputs/results allow regeneration.

Warnings are machine-readable: MODEL_ANALYSIS_UNVERIFIED, UNVERIFIED_SOURCE,
NO_VERIFIED_SOURCES, UNKNOWN_COST and COST_ESTIMATE_EXCEEDED (enum values lowercase).
The result includes known CostRecords; no guessed actuals or invented sources are added.

## Budget and recovery

BudgetManager now supports an explicit category (AI by default for backward compatibility).
The worker checks persisted AI authorization, authorizes/commits each TOOL estimate before
collection and rechecks AI before synthesis. Approved tool minimum estimates prevent an
underfunded request from pretending to be free. Domain task limits aggregate TOOL and AI.
Tool denial or required spending approval raises UNRESOLVED without dispatch. Current
SCOUT_ONLY blocks paid work; independent free AgentMine use cases continue unaffected.
The caller owns WAITING_FOR_BUDGET lifecycle transitions and required fresh revalidation.

Each tool/model operation obtains an atomic immutable claim before dispatch. One owner
may call it. SQLiteResearchJournal uses existing snapshot transactions and the allowlisted
codec; repeated identical saves are idempotent and conflicting plans/identities fail.
The production journal must be durable and shared across all workers using those IDs.

Source/model responses are checkpointed before worker ledger recording. Costs are correlated
by operation, scope, category, currency, estimate and measurement time. Recording is
idempotent; a retry after ledger failure reuses the checkpoint rather than calling providers.
Source/schema failures still retain known costs. Unknown cost retains its reservation and
warning. Real Bedrock may already have recorded usage; replaying the same record is harmless.

A claim with no saved response reports OUTCOME_UNKNOWN and never automatically retries,
even if the failure may have happened before dispatch. Provider errors are translated to
safe messages without raw exception details. Reconcile using independently recovered
response/billing evidence and the original IDs; do not clear claims or invent new IDs to
force retry. No recovery scheduler or provider reconciliation API is invented.

Journal and ledger writes are separate transactions. A process death between provider
response and checkpoint cannot be recovered automatically. Cached complete results can
be regenerated after the deadline without new provider calls; incomplete expired plans
cannot continue. An uncertain outcome may need manual intervention. A changed/replanned
scope requires a new reviewed plan, not mutation of existing immutable evidence.

Keep the local database private: unlike the 4A dispatch-only journal, research checkpoints
intentionally retain approved source text and drafts for provenance/recovery. There is no
new encryption/retention policy. No credentials/environment values are collected by Worker.

## Validation

Offline tests use fake research/LLM providers and both memory and real SQLite journals.
They cover contracts, exact provenance, verified/unverified captures, output schema,
unknown/overrun costs, target approval, task/deadline/budget rejection, duplicate execution,
ledger failures, ambiguous tool/model calls, process-reopen recovery and competing claims.
No automated test invokes a production research tool or paid model.

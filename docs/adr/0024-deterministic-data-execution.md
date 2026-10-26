# ADR 0024: Explicit deterministic Data execution and original-identity recovery

## Status

Implemented for the requested F02-B2 checkpoint. Extends ADR 0023's persistence
foundation under the approved F02-A plan. The current request explicitly excludes
CLI expansion, budget resume/policy changes, paid providers, Research and revisions.

## Context

B1 can atomically start/finish a run, but does not execute a worker or retain full
eligibility/economic evidence. A stored ELIGIBLE assessment alone cannot authorize
new work after source terms, deadline or participation conditions change.

## Decision

Add a focused ExecuteWorkerTask application use case and a small WorkerPreflight
helper. Construct the existing DataWorker with llm=None and use existing
BudgetManager, WorkerRuntimeRepository, DataJournal and Domain transitions.
There is no provider selection, workflow framework or bootstrap/CLI change.

Append optional DataExecutionEvidence to immutable WorkSpecification. Retain typed
eligibility facts/profile/policy/rules version, complete EvaluationRecord and an
optional F04 eligibility-review reference. Older snapshots load the field as None
and remain readable; B2 fails closed until a new immutable specification contains
the required evidence. No facts, permission or policy are guessed/migrated in.

Before new execution or replay without a retained result:

- Validate approved actor/time, immutable input digests and exact task/spec binding.
- Require the current Opportunity revision/phase, fresh authoritative source
  identity/open/deadline/requirements/version, and unchanged reviewed terms.
- Recompute all deterministic eligibility rules at current time. For MANUAL,
  inspect the actual F04 record/decision and require matching actor, facts/profile,
  policy and source context; use only its existing narrow domain resolution policy.
  No new approval, UNKNOWN override or submission consent is created.
- Require the retained evaluation to match the evaluation repository and current
  aggregate; recalculate its economics/scoring from frozen inputs/policy. These
  remain subjective forecasts, never verified revenue.
- Authorize exactly zero AI cost through BudgetManager, persist start before
  DataWorker invocation, and retain the existing first-run ownership/CAS guarantees.
  No applicable positive-cost spending threshold is bypassed: B2 cannot request
  positive-cost execution at all. Explicit denial/review-required results block.

Add a narrow read capability for existing Data AI claims/responses, including
orphan evidence without a run. Surface it in RuntimeStatus and reject its adoption
at SQLite start. Such evidence blocks deterministic dispatch; no AI replay, release,
mode switch or new operation ID is used to resolve an unknown outcome.

Use typed command/outcome/reason contracts, not exception-string interpretation.
Log only stable execution/operation IDs and outcome/reason codes. Domain and
Application import no concrete infrastructure. Legacy ExecuteTask, DataWorker and
BudgetManager behavior remain unchanged.

## Recovery

Keep execution/operation/deliverable identities and original frozen plan/time.
A started run without a result may repeat only the same deterministic computation,
after new preflight and existing budget checks. A start with an uncertain commit
acknowledgement performs no work in that call; inspect original IDs on retry.

DataWorker's existing journal stores its real DataResult before cost recording.
If result evidence exists, recover measured cost idempotently through BudgetManager
and finish atomically through B1 without another worker invocation, refresh or
reservation. This is completion of already-performed work, not fresh eligibility
permission. Retained zero AI cost is an actual deterministic measurement, not a
guessed substitute for unknown usage. Missing/future/incompatible cost evidence
blocks completion. Completed retry is historical readback, never a later-state rewind.

Hold no transaction over source reads or worker execution. If state changes while
work runs, retain the result and let the original finish CAS fail; recover against
the authoritative same-run state rather than silently overwriting it. Preserve all
existing actual costs and unknown commitments. Do not automatically release anything.

## Consequences

Execution finishes at QA_PENDING even if deterministic validation reports issues.
It does not execute QA, grant approval, submit, accept or verify payment. No new
dependencies, database schema, AWS service, operational entry point or paid call.
The configured local actor/store remain trusted. Adapter assertions and hashes are
not proof of source truth; the source can change after refresh. Later protected
steps retain their own freshness/approval requirements. No general F07/F08 closure.

Budget/source/journal/runtime repositories must share the authoritative workspace
and ledger. Application DI cannot authenticate arbitrary nonconforming ports or
host/database writers. No cross-file billing/backup reconciliation is introduced.
CLI wiring, full operator input preparation/export, waiting/resume, rework (F05)
and external settlement (F03) remain separately authorized work.

## Alternatives

Calling legacy ExecuteTask would invoke an LLM draft instead of DataWorker. Blind
replay could reuse stale terms or ambiguous AI identities. Reauthorizing a completed
result risks conflicting settled operations; changing IDs loses idempotency.
Treating validation success as QA/submission consent crosses authorization boundaries.
A new orchestrator service or generic workflow engine is unnecessary for one typed
first-version deterministic operation.

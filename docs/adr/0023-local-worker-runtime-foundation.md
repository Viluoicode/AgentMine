# ADR 0023: Immutable Data runtime evidence and atomic lifecycle persistence

## Status

Implemented for the explicitly authorized F02-B1 checkpoint of the approved
[F02-A plan](../audits/remediation-03-runtime-plan.md). Execution orchestration,
freshness preflight and CLI work commands remain deferred to F02-B2.

## Context

Workers and SQLite journals exist, but only test composition coordinates their
plans/results with Opportunity.start/finish. A durable local runtime needs stable
identities, reviewed input evidence and atomic lifecycle persistence before an
operator can safely execute bounded deterministic Data work. Persisting an
Execution, task owner and Opportunity separately would leave partial authority.

## Decision

Application owns immutable WorkSpecification, InputEvidence, ExecutionBinding,
WorkerRun, internal WorkerRunStart/WorkerResult/WorkerRunFinish commands and a
derived RuntimeStatus view. WorkSpecification binds an authoritative Task identity,
operator/time, ledger, known source status/requirements/version, ordered local data
snapshots and exact SHA-256 references, columns and bounded declarative constraints.
Only deterministic DATA_PROCESSING is supported; semantic columns/Research fail.
No SDK/database type, executable expression, lifecycle selector, or externally
supplied budget authorization belongs to the input specification.

Start is an internal application persistence command containing Opportunity/Budget
snapshots, stable IDs and a start time. Resolve the existing zero-AI-cost commitment
by operation ID from that Budget and reuse Execution/DataPlan/Opportunity invariants.
The adapter must compare both complete snapshots/revisions to authoritative storage
and require the exact retained specification. This command is not an operator JSON
schema or permission to omit future source/eligibility checks.

Application's WorkerRuntimeRepository declares these atomic persistence boundaries:

- Start commits the permanent first-version task owner, immutable run, Execution,
  DataPlan and Opportunity IN_PROGRESS transition in one transaction. Ownership is
  global per Task reference; even different execution IDs cannot claim twice.
  Existing execution/plan/result/legacy-work/deliverable identities cannot be adopted.
- Result retention checks the bound run and remains immutable. Reuse DataJournal's
  existing data_result kind; do not introduce another copy or accounting ledger.
- Finish requires the exact retained run/result and reviewed Opportunity revision;
  atomically store digest-bound bundle content, deliverable version 1, QA_PENDING
  Opportunity and a completion marker. Result retention precedes finish so a crash
  can preserve evidence without asserting lifecycle completion.

Use the existing SQLite snapshot schema/codec and BEGIN IMMEDIATE. No database
schema change, new service, new dependency or generic UnitOfWork is required.
All domain calculations/transition construction stay in Application contracts and
Domain; the adapter implements identity/revision/transaction guarantees only.
No transaction spans a tool/provider/file read or worker invocation.

Same-ID identical operations return False after the first successful write; changed
content conflicts. Start/finish readback never grants another dispatch or rewinds a
later lifecycle. A committed operation with a lost acknowledgement can be inspected
after reopen. Missing/retained results and finish markers yield recovery reasons;
Opportunity.state is still the only business lifecycle, not a second run state graph.

Budget authorization and actual recording remain separate responsibilities of the
existing BudgetManager/worker flow. Runtime persistence never creates reservations,
settles unknown cost, changes policy or releases commitments. B1 accepts only an
already-persisted zero-cost AI authorization. Start/finish leave ledger/audit intact.
No QA assessment, submission approval, external submission, outcome or revenue is
created by finishing a result.

## Consequences

Acceptance tests verify real SQLite reopen, strict input bindings, permanent task
ownership, concurrent different-ID starts, stale Opportunity/Budget rejection,
rollback after every start/finish write, retained-result recovery and idempotency.
The new runtime types are explicitly allowlisted in the existing snapshot codec.
Existing data/readers retain their format; older binaries do not know these new
snapshot kinds and must not run this runtime.

This is a persistence foundation, not an operational runner or safety sandbox for
host/database writers. Source context/profile authenticity, refresh immediately
before work, full eligibility/economics/QA criteria, worker dispatch, restart
coordination, filesystem input approval/export and cost reconciliation remain B2
work under the plan. Storing a structurally bound result does not prove that a
worker executed it or that its assertions are true. Unknown costs stay unknown.
No new command or bootstrap wiring exposes these internal contracts to users.

Research/paid execution, budget wait/resume/policy updates, v2/rework (F05), external
settlement (F03), cloud/shared journals (F06) and generic recovery are not implemented.
No automatic claim release or lease expiry is allowed to manufacture retry authority.

## Alternatives

Direct snapshot writes in CLI or a test-only runner would bypass application
contracts. Separate writes for start/finish create partial state. An execution ID
alone does not stop different IDs owning the same task. A generic workflow engine,
mutable independent run state machine or transaction framework adds machinery
without strengthening these specific bounded local guarantees.

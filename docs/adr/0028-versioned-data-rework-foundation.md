# ADR 0028: Immutable linear Data revision ownership and exact-version persistence

## Status

Implemented for the approved **F05-B1 foundation** on 2026-10-28. Extends ADRs
0023–0027 and the approved decisions in
[F05-A](../audits/remediation-05-versioned-rework-plan.md). Revision orchestration,
source refresh orchestration, CLI and operational version-aware QA remain deferred.

## Context

QA FAIL/NEEDS_REVISION and operator REQUEST_REVISION retain parent QA/execution
while returning the Opportunity to IN_PROGRESS. First-version execution deliberately
cannot create rework: its Task owner is permanent and its finish version is 1.
Deleting ownership, overwriting cached results or selecting a new Task would lose
audit and duplicate-action protection. ExecutionRepository already has immutable
deliverable and QA keys by reference/version.

## Decision

Application owns DataRevisionRequest, DataRevisionApproval, RevisionAllocation,
RevisionRun, internal RevisionStart/RevisionFinish commands and derived typed views.
The narrow RevisionRuntimeRepository port specifies persistence consistency only.
No use case, provider dispatch or CLI command is added in this checkpoint.

The same Task value and deliverable lineage reference remain. Each revision has a
new specification, evaluation, execution and budget operation identity. Version is
derived as parent.version+1, never supplied by a caller. Future QA/review must use
new identities; this foundation does not run them. Consent is separately retained,
confirmed and bound to the original immutable request/actor. A proposal is not
authorization. Original acceptance requirements/artifacts must remain exactly;
additions are allowed. Existing columns, uniqueness and constraints cannot be
relaxed; record limits may only narrow. Changed source terms or Task fail closed.

SQLite verifies the completed parent run/result/content/deliverable, applied QA
inspection/report and recorded actual cost on the same authoritative workspace.
For a QA trigger it requires the exact failed QA completion snapshot/revision.
For an operator trigger it requires the retained parent PASS, exact review,
REQUEST_REVISION decision and its applied Opportunity transition. Decision-only
partial writes cannot create a successor. Retrying the existing decision remains
the existing workflow; no new repair/reconciliation command is introduced.

Preparation retains request, proposed specification and new evaluation evidence
atomically. Approval atomically writes consent, parent-successor ownership,
lineage/version ownership and allocation using BEGIN IMMEDIATE. Execution/operation
identity collisions, old costs/authorizations/releases and conflicting allocations
are rejected. Same-ID equal retries recover the original allocation even after
later lifecycle progress. No cancellation, supersession, lease or automatic reuse.

Start resolves an already persisted zero-AI authorization from the supplied Budget
snapshot and compares it to the actual ledger. It atomically writes revision run,
Execution, DataPlan and the Domain-updated Opportunity. Original `runtime_owner`
and v1 records remain untouched. New executions retain normal opportunity-history
indexes. No transaction spans filesystem, network or worker operations.

Domain adds guarded `Opportunity.begin_rework`: matching retained parent QA and
execution, same Task, new authorized execution/operation, eligible assessment and
no incompatible outcome/approval. It performs a private same-phase update without
adding a broad IN_PROGRESS successor or altering lifecycle history. Domain finish
keeps its version-order check, then clears old current QA/approval when entering
QA_PENDING. Old QA remains immutable in its journal.

Result retention reuses `data_result` and validates the existing WorkerResult
contract. Finish requires exact retained evidence and actual cost already present
in the authoritative ledger, then atomically writes content, exact allocated
deliverable/version, Opportunity and completion marker. The adapter neither
authorizes nor records costs. Missing/unknown costs are not changed to zero.
Inspection returns typed historical/recovery evidence; local ambiguous Data AI
claims block new start/result completion. Completed readback never mutates a later
version or grants renewed execution permission.

Reuse the existing snapshot schema/codec allowlist. Source-context equality moves
unchanged into the application opportunity contracts so revision contracts do not
depend on a use case. Domain/Application remain independent of concrete adapters.

## Consequences and limits

This foundation can store and test v2 evidence but is not an operational v2 runner.
Future F05-B2 must refresh authoritative source/eligibility/economics, validate
operator consent, authorize through BudgetManager, invoke the real DataWorker and
recover original identities. A structurally valid proposal or start command cannot
replace that orchestration. Host/store/port callers remain trusted internal actors.

The existing version-aware ExecutionRepository is reused. Version-aware operational
QA lookup/CLI, revisions of local export manifests and bootstrap wiring are not
enabled. Legacy/incomplete parent evidence remains unsupported. Changed MANUAL
eligibility requiring a new resolution, stale allocated proposals and ambiguous
paid claims remain blocked; no F04 extension or F08 reconciliation is added.

No paid Research, semantic Data, Bedrock, submission/payment, AWS, budget resume,
new dependency or generic workflow/transaction framework. New snapshot kinds need
the updated binary; no reset, downgrade conversion or cloud implementation.

## Alternatives

Weakening first-run ownership permits duplicate execution. Reusing execution or
cost IDs overwrites or confuses history. Selecting max(version)+1 outside a write
transaction races. Reusing old QA or submission consent gives changed content
unearned authority. A generic workflow engine is unnecessary for these bounded
immutable boundaries.

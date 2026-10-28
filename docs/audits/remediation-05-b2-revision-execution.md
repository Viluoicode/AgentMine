# F05-B2: Deterministic revision execution and recovery

Date: 2026-10-28 (Asia/Bangkok). Base commit:
`380d54b7d702e560f578e4e815a116dd4468377e`.

## Scope and implementation

Implements Application orchestration for the approved F05-A/B1 deterministic local
Data revision design. Reviewed AGENTS.md, Product Constitution, F05-A, the B1 report
and ADR 0028, F02-B2/B5 reports and current revision/runtime, budget, worker and
recovery source. The worktree was clean at this checkpoint's start.

B1 already owned immutable request/consent/allocation and atomic start/finish.
First-version ExecuteWorkerTask remains unchanged. New explicit use cases are:

- PrepareDataRevision: load a completed authoritative parent; refresh the configured
  source; run deterministic eligibility; calculate economics/scoring using existing
  Domain models; capture bounded local input bytes/digests through DataInputReader;
  retain the request through B1's trigger/state checks and atomic prepare.
- GetDataRevision: inspect the retained request/allocation under the configured
  operator and ledger; returns the exact immutable inputs and reviewed evidence.
- ApproveDataRevision: require confirmation and the exact retained reviewed request;
  revalidate fresh evidence; invoke atomic B1 approval/allocation. Identical applied
  retries return the original allocation rather than create new consent/IDs.
- ExecuteDataRevision: accept only revision ID and explicit confirmation; validate
  consent/workspace/scope; perform fresh preflight before new computation; authorize
  the allocated zero-AI operation with BudgetManager; persist start; invoke the real
  DataWorker with llm=None; retain its DataResult and measured cost; finish exactly
  the allocated version through B1.
- RecoverDataRevision: delegate to the same executor and original allocation. It
  neither allocates nor generates replacement identities.

No revision CLI, bootstrap composition, version-aware operational QA, automatic
approval, source bypass or next-version loop was added. Successful execution stops
at QA_PENDING. No external submission, acceptance, payment or revenue action exists
in these use cases.

## Changed files and architectural decisions

| File | Change |
| --- | --- |
| `src/agentmine/application/contracts/revision_execution.py` (new) | Typed proposal inputs using existing local-input, eligibility and forecast contracts |
| `src/agentmine/application/use_cases/data_revision.py` (new) | Preparation, exact review and explicit approval |
| `src/agentmine/application/use_cases/revision_preflight.py` (new) | Shared live revision checks; no lifecycle mutation or forecast replacement |
| `src/agentmine/application/use_cases/revision_execution.py` (new) | Execute/recover, typed outcomes and ID-only structured logs |
| `src/agentmine/application/contracts/data_revision.py` | Completed-parent read contract and exact started-snapshot derivation via Domain.begin_rework |
| `src/agentmine/application/ports/data_revision.py` | Narrow consistent completed-parent read, covering v1 and revision parents |
| `src/agentmine/infrastructure/sqlite/data_revision.py` | Implementation of that read on the authoritative connection; no new write boundary |
| `tests/integration/test_data_revision_execution.py` (new) | Offline Application execution, consent, fault, concurrency and recovery acceptance |
| This report (new) | Evidence and limitations |

Presentation → Application → Domain remains intact. Application imports no SQLite,
AWS, marketplace or external AI implementation. DataInputReader/OpportunitySource
are injected ports. Existing Domain lifecycle, DataWorker/QA algorithms, B1 write
transactions and original runtime_owner are preserved. The expected active snapshot
is derived by a Domain operation, never by mutating lifecycle fields in Application.

The parent read is needed because first-version runtime lookup alone cannot load a
completed revision parent. It checks retained plan/execution/result/content/finish
identity consistently in one SQLite read transaction. Applied QA/operator trigger
authenticity and exact parent revision remain checked by B1's prepare/approve/start
boundaries. A decision-only REQUEST_REVISION cannot become dispatch permission.

No new ADR is necessary: these are the orchestration and narrow read capabilities
already required by the approved plan and ADR 0028, with no new ownership or
transaction model. No dependency was introduced or installed.

## Financial, approval and freshness invariants

- Preparation is not consent, allocation or execution. Approval requires the exact
  immutable reviewed request and trusted configured actor. Conflicting payloads,
  missing confirmation and stale parent snapshots fail closed.
- Same Task/source terms and B1 non-relaxing scope rules remain enforced. Original
  acceptance requirements cannot be removed or weakened. Approved input files are
  captured once; later filesystem edits cannot alter retained execution bytes.
- Before new work/replay, source observations must be fresh under existing
  observe_status checks and agree with the retained terms/deadline. The actual
  deterministic EligibilityEngine runs at current time; UNKNOWN, ineligible and
  unsupported human/manual resolutions block. No ELIGIBLE flag is permanent consent.
- New forecast inputs/signals are explicit operator assertions with evidence and
  rationale. Existing Domain economic/scoring models calculate their components.
  Preflight recalculates the reviewed forecast and checks repository equality;
  changed evidence cannot silently replace the approved forecast. Subjective
  probability/signals remain subjective; this is not independent prediction truth.
- BudgetManager authorizes exactly zero AI under the allocated operation before
  durable start and worker dispatch. The current ledger/Opportunity are checked at
  atomic start. SCOUT_ONLY permits this deterministic work. No positive-cost worker
  or paid WAITING_FOR_BUDGET behavior is manufactured.
- A ledger race preserves the commitment and original IDs. Actual costs are recorded
  from the real retained DataResult using the original authorization/context, never
  a new estimate or a guessed zero. Missing/incompatible cost evidence blocks.
- Parent and child identities remain separate; retries never allocate another
  version. Completed readback cannot rewrite later QA or lifecycle state. Potential
  reward and expected value never become verified revenue.

## Transaction and recovery behavior

No transaction spans source reads, local input processing or worker execution.
The existing B1 transactions remain authoritative; Application coordinates their
durable boundaries and BudgetManager rather than adding UnitOfWork/framework code.

| Window | Behavior |
| --- | --- |
| Prepare/approval before dispatch | Fresh checks and immutable evidence; B1 verifies complete trigger and parent; no worker/cost reservation from a mere proposal |
| Authorization committed, start fails | Preserve commitment; retry original allocation after fresh checks; no release/reset/new operation |
| Start acknowledgement unknown | Return typed RECOVERABLE; do not dispatch in that call. Inspect original run IDs on retry |
| Started, result missing | Replay only the original frozen deterministic plan after fresh source/eligibility/economic checks and exact active snapshot validation |
| Result retained, accounting not committed | Use the actual retained cost record; repair original BudgetManager operation idempotently; no worker/source rerun |
| Actual cost committed, finish fails | Reuse the result and cost; atomically finish exact allocated version; no duplicate actual cost |
| Finish committed, acknowledgement lost | Original completion is read back; no new start, allocation or lifecycle write |
| State/revision changed while incomplete | Block rather than rebase. The expected start snapshot and revision remain fixed even if the changed aggregate has the same execution ID |
| Unknown local AI claim/response | Block; never reinterpret it as deterministic zero or retry an external/paid operation |
| Concurrent calls | B1 ownership/CAS and immutable result/cost identity contain races; a losing call may require same-ID retry. Deterministic CPU recomputation is not an external exactly-once claim |

Retained-result completion during source outage is recovery of already-performed
local work, not renewed execution/submission permission. No paid provider is used
or retried. No in-flight claim is released to make progress.

## Test-first and acceptance evidence

The initial acceptance tests were written before production changes. Their first
execution failed collection with ModuleNotFoundError for
`agentmine.application.contracts.revision_execution` (exit 1). This establishes
missing capability, not separate reproduction of every later fault scenario.

Tests use real file-backed SQLite, real BudgetManager/DataWorker and existing
Domain/QA components. Source and clock fakes are explicitly test-only. QA FAIL
uses the existing coherent-corruption fixture followed by the real QA engine;
operator revision uses the existing real review/decide workflows. One later-state
test composes existing DeliverableQA directly for v2; this is test composition,
not a new operational version-aware QA command or fabricated QA result.

An interim expanded run had 23 passes and one test expectation failure: changed
input bytes correctly produced a structured PortError from the input adapter while
the test expected only ValueError/DomainError. The assertion was corrected without
weakening production validation. Formatting and test typing feedback were resolved.

| Acceptance area | Executed coverage |
| --- | --- |
| FAIL / NEEDS_REVISION / operator revision | Three complete prepare/approve/execute/recover paths with real retained results |
| Invalid triggers / human pending | Missing applied trigger and real REQUIRES_HUMAN_REVIEW rejection; B1 regression also covers decision-only partial transition |
| Immutable preparation / exact consent | Same-ID proposal, changed reason/scope, no confirmation/no approval and reviewed-request mismatch |
| Concurrent approvals / collisions | Same/different bindings through approval use case; original allocation recovered; B1 collision/version ownership regressions |
| Fresh source / deadline / eligibility | Source unavailable/changed terms/expiry; actual ineligible, UNKNOWN and MANUAL preparation; missing-result replay rechecks source |
| Input/forecast change | Changed input digest rejected before preparation; frozen retained bytes survive later edit; changed evaluation evidence blocks dispatch |
| Budget order / SCOUT_ONLY | Worker spy checks persisted run and outstanding zero authorization before delegating to real worker; SCOUT_ONLY execution; ledger race preserves commitment |
| Start / worker / result / finish failures | Before/after start, worker interruption, result-before-accounting, before/after finish and file reopen recovery |
| Retry / concurrency / history | Same-ID recovery; concurrent execution; original cost count/version/allocation; completed retry preserves later real QA state |
| Ambiguous effects | Retained local Data AI claim blocks recovery without a worker call |
| Parent preservation / external safety | Parent run/deliverable/costs retained; B1 raw evidence preservation regressions; no external submission/payment; verified revenue remains zero |

## Executed verification

Commands use `.\.venv\Scripts\python.exe`; pytest uses the repository network guard.
No live marketplace, production workspace, paid provider or AWS account was used.

| Command/check | Actual result |
| --- | --- |
| `-m pytest tests/integration/test_data_revision_execution.py -q --tb=short -p no:cacheprovider` | 31 passed in 75.18s; final full suite additionally includes the last v2-parent read assertion |
| B1/runtime/QA/budget/architecture group below | 218 passed in 119.78s |
| `-m pytest tests/unit/test_architecture.py -q --tb=short -p no:cacheprovider` | 29 passed in 1.00s |
| `-m pytest -q -ra --tb=short -p no:cacheprovider` | **1287 passed in 225.78s**, exit 0; no skips reported |
| `-m ruff check .` | All checks passed |
| `-m ruff format --check .` | 307 files already formatted, including final report |
| `-m mypy` (strict project configuration) | Success, 230 source/test files |

Regression selection: `tests/integration/test_data_revision_foundation.py`,
`test_worker_execution_runtime.py`, `test_runtime_foundation.py`,
`test_operational_deliverable_qa.py`, `test_budget_control.py`,
`test_budget_control_persistence.py` (all under `tests/integration/`) and
`tests/unit/test_architecture.py`, with `-q --tb=short -p no:cacheprovider`.

The full suite includes the final v2-parent read assertion, F01/F04 and all existing
regressions. All listed test commands completed; no pending command is represented
as passed. `git diff --check` and the new report's whitespace/code-fence checks
passed; Git emitted only Windows LF/CRLF conversion notices.

## Remaining blockers and disposition

- Programmatic Application API only. No revision CLI/composition or version-aware
  operational QA/export/review interface was added; those remain F05-B3. Execution
  completes at QA_PENDING and does not grant submission approval.
- This B2 path accepts deterministic ELIGIBLE results; it does not adopt MANUAL
  resolutions for revised requests. MANUAL/human eligibility remains blocked;
  no new F04 resolution in IN_PROGRESS or human-QA override is invented. Changed
  source terms/Task and stale approved allocation remain blocked without supersession.
- Facts/profile, local provenance locators and forecasts remain trusted operator
  assertions. Fresh source metadata does not authenticate all account/geographic
  facts, lock remote changes or make subjective forecasts objectively current (F07).
- Cost repair is limited to exact measured deterministic retained evidence. Unknown
  paid effects, abandoned claims, generic stale-state reconciliation and coordinated
  backup/restore remain F08. No automatic cleanup or policy increase/resume.
- Host/SQLite/port implementations are trusted internal authorities. Hashes detect
  inconsistency, not malicious authorized host rewriting. No general billing or
  complete infrastructure/tool/transaction cost claim follows from AI actual zero.
- Injected repositories, journal and BudgetManager must share the authoritative
  workspace/ledger. B1 compares stored snapshots and recorded costs; Application
  does not authenticate arbitrary port implementations or inspect database paths.
  Production composition of these services remains the next approved checkpoint.
- F02-C Research/semantic/paid capabilities, B4-2 paid resume, F03 settlement,
  F06 AWS deployment and F05-B4 independent audit remain separate gates.

**PASS_WITH_LIMITATIONS** for deterministic local revision Application execution
and recovery. All executed final gates passed. This does not close F05 overall,
provide an operator CLI for revision, or establish production/live-provider readiness.

Offline verification requires no operator action or credentials. No commit or push.
F05-B3 and F05-B4 were not started. Stop here for operator review.

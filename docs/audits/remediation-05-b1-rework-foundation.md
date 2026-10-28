# F05-B1: Versioned rework contracts, Domain and persistence foundation

Date: 2026-10-28 (Asia/Bangkok). Base commit:
`7f1bcc967df09dcb24baebd1e97f79f144fcb891`.

## Scope and existing behavior

Implements only the approved F05-B1 slice of
[F05-A](remediation-05-versioned-rework-plan.md). Before changes, failed QA and
operator revision returned IN_PROGRESS but first-run ownership, start contracts
and fixed version 1 prevented v2. The existing ExecutionRepository already supported
versioned deliverables/QA. Source, AGENTS.md, Constitution, F02-B5 and ADRs 0023–0027
were reviewed before choosing a separate foundation rather than weakening v1.

Pre-existing untracked reports `remediation-03-b5-operational-e2e-audit.md` and
`remediation-05-versioned-rework-plan.md` were preserved. They are not new B1 work.
No commit or push. F05-B2 has not been started.

## Changed files

| File | Purpose |
| --- | --- |
| `src/agentmine/application/contracts/data_revision.py` (new) | Immutable request/consent/allocation/run, start/finish commands and typed status/reasons |
| `src/agentmine/application/ports/data_revision.py` (new) | Narrow atomic revision persistence boundary |
| `src/agentmine/infrastructure/sqlite/data_revision.py` (new) | Same-workspace immutable evidence, parent/trigger verification, transactional allocation/start/finish/readback |
| `src/agentmine/domain/opportunity.py` | Guarded begin_rework; finish clears prior current QA after its newer-version check |
| `src/agentmine/application/contracts/opportunities.py` | Existing unchanged source-context comparison moved to the contract layer |
| `src/agentmine/application/use_cases/worker_preflight.py` | Reuses/re-exports that comparison; existing preflight behavior retained |
| `src/agentmine/infrastructure/snapshots.py` | Explicit allowlist of revision snapshot types |
| `tests/integration/test_data_revision_foundation.py` (new) | File-backed acceptance, Domain guards, fault injection, immutable history and concurrency |
| `docs/adr/0028-versioned-data-rework-foundation.md` (new) | Ownership, consent and atomicity decision |
| `docs/adr/README.md` | ADR index |
| This report (new) | Scope, evidence and limitations |

No dependency introduced or installed. No bootstrap, CLI, worker algorithm, QA
algorithm, first-run repository ownership or external provider implementation changed.

## Implemented boundaries and invariants

- Same Task and source terms, linear lineage, exact next version. Parent and child
  execution/operation/specification/evaluation identities differ. Original v1
  ownership/result/QA/review/content are retained.
- Frozen input snapshots/digests and acceptance criteria. Existing requirements and
  artifacts must remain; additions allowed. Processing validation changes are
  conservatively non-relaxing: existing columns, uniqueness and constraints stay,
  record bounds may narrow. Unsupported corrections fail explicitly.
- Preparation persists evidence only. Explicit confirmed consent is required for
  allocation, and allocation alone does not call a worker. Trusted actor must match
  the proposed immutable scope. Conflicting payload/consent/identity fails.
- A complete parent needs real retained run/plan/result/content, versioned deliverable,
  applied QA evidence and actual cost already recorded. QA FAIL/NEEDS_REVISION or
  applied operator REQUEST_REVISION are the only supported triggers. Human-pending,
  submitted or incompatible external states do not qualify.
- A saved REQUEST_REVISION decision without its Opportunity transition is rejected.
  A guessed future snapshot cannot override the actual SQLite state.
- Only one approved successor per completed parent; no client-selected version,
  no skipped version, conflicting owner or reallocation after uncertain acknowledgement.
- Domain owns the guarded current execution/assessment replacement and lifecycle
  finish. Parent QA remains until version validation, then is cleared from current
  QA at QA_PENDING. First-version start guards and state successor graph stay intact.
- Start requires an already persisted zero-AI commitment, current ledger snapshot
  and exact parent revision. Result storage never invokes DataWorker. Finish requires
  matching retained result and measured cost already in the ledger. Unknown costs
  are never synthesized as zero; no commitment or actual record is released/reset.
- Completed readback returns original evidence without rewinding newer state.
  Incomplete views distinguish missing result, pending finish, changed parent and
  local ambiguous Data AI evidence through typed reasons.

## Atomicity and recovery

All write boundaries use SQLiteDatabase BEGIN IMMEDIATE on the authoritative file;
no transaction spans worker execution, network or filesystem processing.

| Boundary | Writes/checks and recovery |
| --- | --- |
| Prepare | Proposed specification, new evaluation and immutable request commit together; no owner or budget mutation |
| Approve/allocate | Original request and applied parent verified; consent, parent successor, lineage/version ownership and allocation commit together |
| Start | Approved allocation, parent and persisted ledger snapshot checked; run, Execution, DataPlan and Domain-updated Opportunity commit together |
| Retain result | Existing data_result identity reused; WorkerResult binding/provenance validated; changed payload rejected |
| Finish | Run/result/allocation/current revision/cost checked; content, exact deliverable version, Opportunity QA_PENDING and marker commit together |
| Lost acknowledgement | Same-ID readback after reopen returns original allocation/start/finish; no identity generation or reallocation |

Allocation/start/finish failures roll back all writes in that boundary. A committed
authorization before a failed start stays in the budget. Worker result and accounting
remain separately recoverable existing journal/ledger responsibilities. This adapter
does not implement authorization, cost recording, replay dispatch or reconciliation.

## Test-first evidence

Seven initial acceptance cases were written before production changes. Their first
execution stopped at collection with ModuleNotFoundError for
`agentmine.application.contracts.data_revision` (exit 1). This is evidence of missing
capability, not seven independently reproduced runtime defects. Later cases added
the required fault/trigger/identity coverage.

Tests use real file-backed SQLite, actual first-run DataWorker/DeliverableQA and
existing operator commands to prepare parent evidence. Fake source/clock are
explicit test-only dependencies. A revision worker is invoked directly only by test
composition to create real retained results; no production revision orchestrator
is added. The QA FAIL case reuses an existing coherent-corruption fixture followed
by the real QA engine. The submitted-parent negative test uses a domain-only
synthetic receipt in its isolated test database; no gateway sends anything.

Interim verification exposed a temporary-directory permission error, an ineffective
content-write fault fixture (warnings do not change bundle content), and a malformed
submitted-state fixture rejected by snapshot history validation. Tests were corrected
to exercise new artifact bytes and a real Domain submission transition; production
guards were not weakened. Ruff/type feedback was also resolved.

Coverage includes FAIL/NEEDS_REVISION/operator triggers, decision-only partial
transition, human/submitted rejection, immutable scope/consent, same-ID conflicts,
concurrent same/different approvals, concurrent starts, exact next-version ownership,
rollback after every allocation/start/finish write, reopen/readback, v1 evidence
preservation, original costs, missing approval, stale parent, unknown Data AI claims,
and no dispatch during proposal/approval.

## Executed verification

Commands use `.\.venv\Scripts\python.exe`. All tests are offline with the existing
network guard; no provider or production marketplace was exercised.

| Command/check | Actual result |
| --- | --- |
| Initial focused test-first run | Exit 1, missing revision module at collection before production changes |
| `-m pytest tests/integration/test_data_revision_foundation.py -q --tb=short -p no:cacheprovider` after fixture correction | **37 passed in 50.05s** |
| Existing runtime/QA/budget/F01/architecture group below | **209 passed in 163.01s** |
| `-m pytest tests/unit/test_architecture.py -q --tb=short -p no:cacheprovider` | **29 passed in 9.88s** |
| Interim full suite with the already-imported malformed submitted fixture | 1255 passed, 1 failed in 242.98s; this is not the final gate |
| Full suite after fixture correction, before final Application trigger guard | 1256 passed in 166.33s |
| `-m pytest -q -ra --tb=short -p no:cacheprovider` after final guard/assertions | **1256 passed in 191.63s**, exit 0; no skips reported |
| `-m ruff check .` | All checks passed |
| `-m ruff format --check .` | 301 files already formatted |
| `-m mypy` with strict project configuration | Success, 225 source/test files |
| `git diff --check` | Passed; existing Windows LF/CRLF conversion notice on ADR index only |
| New report/ADR whitespace, code fences and local links | Passed |

The 209-test command selected `tests/integration/test_runtime_foundation.py`,
`test_worker_execution_runtime.py`, `test_operational_deliverable_qa.py`,
`test_operator_approval_sqlite.py`, `test_budget_control.py`,
`test_budget_control_persistence.py`, `test_submission_cancellation.py` (all under
`tests/integration/`) and `tests/unit/test_architecture.py`, using
`-q --tb=short -p no:cacheprovider`. The final full suite includes F04 and all other
existing regressions. The final run includes the Application contract's explicit
trigger-to-parent-QA status policy and negative assertions for mismatched trigger
types. The source/refactor guard does not delegate that policy solely to SQLite.
All final checks above completed; no pending command is counted as passed.

## Limitations and disposition

This is a persistence/Domain foundation, not an operational revision runner.
Source/facts/economic evidence are immutable internal application assertions; B2
must perform authoritative refresh, current eligibility/economic review and budget
authorization before invoking any new work. Stored consent does not prove source
freshness or authenticity. Hashes do not authenticate a malicious authorized host.

No revision CLI, use-case orchestration, v2 source refresh, version-aware operational
QA command, automatic approval/execution, paid provider, Research, Bedrock, paid
resume, submission/payment, AWS, cancellation/supersession, backup/restore or F08
reconciliation. Old first-run ownership is not deleted or reassigned. New snapshot
kinds require the updated binary; no downgrade/reset conversion is provided.

Local Data AI claims are checked as retained ambiguity; this does not reconcile
separate Bedrock/billing stores. Full infrastructure/tool/transaction cost is still
not established by a recorded deterministic AI zero. Future QA/review IDs are not
allocated here because those operations are outside B1; they must be new and bound
to the exact child version in their future checkpoint.

**PASS_WITH_LIMITATIONS** for F05-B1. Final focused/regression/full/static gates
passed. Dependency direction remains unchanged; no architectural deviation from
the approved bounded foundation was introduced. This does not close F05 overall
or establish a usable production rework runner.

No operator action or credentials were required for offline verification. No commit
or push. Stop here for operator review; F05-B2 has not been started.

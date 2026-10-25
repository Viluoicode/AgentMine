# F02-B1: Runtime contracts and persistence foundation

Date: 2026-10-25 (Asia/Bangkok). Scope: first checkpoint of F02-B only.

## 1. Implemented scope

Added immutable application contracts, a narrow WorkerRuntimeRepository port and
its real SQLite adapter for future operator-controlled deterministic Data work.
Specifications, first-run ownership, authorized execution/plan bindings, retained
results, digest-bound deliverables and incomplete-run inspection survive reopen.
No worker is invoked by these APIs or tests. Test results are explicit synthetic
worker-output assertions used to verify persistence, not evidence of actual work.

The existing repository already supplied Opportunity/Execution/Budget invariants,
SQLite transactions/CAS, snapshot codecs and DataJournal. B1 reuses these rather
than introducing a runtime framework. Domain, BudgetManager, workers, existing
repository implementations, bootstrap and CLI behavior are unchanged.

No dependencies, paid services, real marketplace calls, submission/payment behavior,
AWS deployment, policy update, budget resume or QA orchestration were introduced.
F02 is still open; this is not a runnable operator execution milestone.

## 2. ADR decisions

See [ADR 0023](../adr/0023-local-worker-runtime-foundation.md), scoped to the
[approved F02-A plan](remediation-03-runtime-plan.md).

- Immutable approved input snapshots/references/digests, task/ledger, source context
  and operator/time are retained in WorkSpecification.
- WorkerRun binds existing types; Opportunity remains the business lifecycle.
  RuntimeStatus derives checkpoint/recovery information rather than owning another
  mutable run state machine.
- Start and finish use narrow atomic persistence contracts and permanent first-run
  task ownership. No generic UnitOfWork, lease or workflow engine is needed.
- Budget authorization is obtained separately. The internal start command resolves
  a zero-cost AI commitment from an authoritative Budget snapshot; the adapter
  checks that complete snapshot/revision against storage. It never accepts a bare
  caller-provided BudgetAuthorization as sufficient evidence.
- Result retention is distinct from completion. A completion marker allows exact
  historical retries without reapplying state after later QA/review activity.
- Source context binding preserves observed evidence; B1 does not perform network
  refresh, authenticate operator assertions or declare the evidence current forever.

## 3. Changed files

| File | Change |
| --- | --- |
| `src/agentmine/application/contracts/runtime.py` | New deterministic Data specifications, input evidence, identity/run/start/result/finish contracts and derived read/recovery view |
| `src/agentmine/application/ports/runtime.py` | New application-owned persistence protocol and explicit transaction/idempotency responsibilities |
| `src/agentmine/infrastructure/sqlite/runtime.py` | New SQLite implementation; no dispatch or external I/O |
| `src/agentmine/infrastructure/snapshots.py` | Two-line addition importing/allowlisting runtime contract types; existing snapshot version and compatibility unchanged |
| `tests/integration/test_runtime_foundation.py` | New offline contract/persistence/concurrency/reopen/fault-injection acceptance tests |
| `docs/adr/0023-local-worker-runtime-foundation.md` | New focused architecture decision |
| `docs/adr/README.md` | Index entry for ADR 0023 |
| `docs/audits/remediation-03-b1-runtime-foundation.md` | This report |

`docs/audits/remediation-03-runtime-plan.md` already existed as an untracked file at
task start and was preserved without editing. No commit or push was performed.

## 4. New contracts and ownership

| Contract | Enforced binding/responsibility |
| --- | --- |
| InputEvidence | Source ID and canonical lowercase `sha256:` reference; order/count/identity/digest must match exact retained DataSource bytes |
| WorkSpecification | Nonblank IDs/actor, aware approval time, DATA_PROCESSING Task, known open/deadline/source terms and requirements, source/task identity/deadline agreement, bounded immutable sources/columns/constraints and no semantic fields |
| ExecutionBinding | Stable specification, execution, operation and deliverable references; no caller-selected lifecycle or authorization |
| WorkerRun | Exact binding, specification and DataPlan/Execution scope; reconstructable from authoritative stored references |
| WorkerRunStart | Internal application command with reviewed Opportunity/Budget snapshots and start time; resolves existing outstanding zero-AI-cost authorization; reuses Domain Execution/start and DataPlan rules |
| WorkerResult | Typed DataResult bound to run/execution, retained source provenance and nonsemantic evidence; fixed artifact inventory and compatible zero-cost measurement where supplied |
| WorkerRunFinish | Exact active execution/task and reviewed Opportunity snapshot; derives version-1 deliverable and existing Domain finish transition |
| RuntimeStatus / RecoveryReason | Read view with authoritative Opportunity snapshot, optional retained result and completion evidence; reasons NONE, RESULT_MISSING, FINISH_PENDING or STATE_CHANGED |
| WorkerRuntimeRepository | Save/get spec, get run, conditional start, retain result, conditional finish, inspect one run and inspect incomplete runs |

Specification parameters are declarative extraction/validation configuration, never
scripts or expressions. No SQLite/AWS type enters Application. WorkSpecification
does not contain an Execution, authorization, lifecycle selector, QA result,
submission consent or revenue. Internal start/finish commands deliberately carry
trusted Domain snapshots; they are not schemas to deserialize from arbitrary JSON.

Validation runs before storing a new identity. Identical saves/readback do not
renew source freshness or human consent. Constructor validity and content digests
do not prove source truth, successful transformation, real execution or passing QA.
Those remain separate application/worker/QA responsibilities.

## 5. SQLite transaction semantics

All operations reuse SQLiteDatabase and its existing snapshot table, primary keys,
indexes, checksum codec, synchronous writes and BEGIN IMMEDIATE write transactions.
No schema migration or existing data reset is needed.

| Operation | Atomic behavior |
| --- | --- |
| Save specification | Check immutable ID first; for a new spec require the authoritative planned Task and source-provenance identity to match; insert immutable specification |
| Start | Require retained exact spec and exact current Opportunity/Budget snapshots/revisions; reject an existing task owner and reused execution/plan/result/legacy-work/deliverable identities; commit owner, binding, Execution, DataPlan and IN_PROGRESS Opportunity together |
| Retain result | Require bound stored run and matching active execution; immutable insert into existing `data_result` kind; identical retained result is readback |
| Finish | Require stored run/result match and current Opportunity revision; store content, version-1 deliverable, QA_PENDING Opportunity and completion marker together |
| Inspect | Read run/spec/plan, Opportunity, result and marker in one consistent read transaction; no repair, dispatch or accounting side effect |
| Incomplete | Read all local run bindings and corresponding evidence consistently; completed runs excluded, incompatible/blocked phases remain inspectable |

New kinds: `work_specification`, `runtime_owner`, `runtime_run`, `runtime_finish`.
Existing kinds reused: `opportunity`, `budget`, `observation`, `execution`,
`data_plan`, `data_result`, `content`, `deliverable`.

`runtime_owner` is keyed by Task reference; `runtime_run` by Execution reference
and stores only ExecutionBinding. The read view reconstructs WorkerRun from the
retained specification and existing DataPlan; it does not copy source bodies into
another run checkpoint. DataPlan still contains its existing complete source
snapshots, as its established contract requires. The result has one canonical
`data_result`; finish adds references/content rather than another result history.

No transaction crosses a worker/provider invocation, file read or network call.
Runtime never commits Budget changes or cost records. A separate BudgetManager
reservation may predate start; failure/stale start does not silently release it.

## 6. Concurrency, idempotency and failure evidence

The initial **17-case acceptance suite was added before production code**. Running
it failed collection with ModuleNotFoundError for
`agentmine.application.contracts.runtime` (exit 1, one collection error). This
demonstrated an initially missing capability, not a reproduced historical defect.
No claim is made that its individual transactional assertions executed before the
contracts existed.

| New invariant | Acceptance evidence |
| --- | --- |
| Immutable specification and input binding | Reload after reopen, same-ID save False, changed actor conflict; wrong source ID/digest/count, source provenance and unsupported capability tests |
| Same-ID start/readback | First True, exact retry False, unchanged Opportunity revision and ledger snapshot; changed deliverable binding conflicts |
| One first-run owner despite different IDs | Two threads with a Barrier immediately before start, independent SQLite adapters; exactly one True and one CONFLICT; one incomplete run retained |
| Stale authorization/state cannot start | Independent Opportunity revision and Budget revision changes rejected; missing or forged/unpersisted authorization rejected; no runtime run created |
| Atomic start | Fault after each of owner, binding, Execution, DataPlan and Opportunity writes; compare every stored snapshot row to pre-call state; retry succeeds with no leaked owner |
| Result identity/retention | Missing run, mismatched execution and conflicting result rejected; simulated SQLite disk failure becomes UNAVAILABLE and rolls back; reopened adapter can retain same result |
| Atomic finish | Fault after each content, deliverable, Opportunity and marker write; all rows equal pre-call state; retained result survives and finish retry succeeds |
| Stale finish / no state rewind | Stale Opportunity revision rejected; exact completed retry after later passing-QA transition is False and leaves later snapshot/revision intact |
| Restart and incomplete inspection | Reopened adapter loads original spec/run/result; RESULT_MISSING → FINISH_PENDING → completion evidence; phase mismatch reports STATE_CHANGED without repair |
| Concurrent same-ID operations | Aligned independent adapters return one True and one False for both start and finish |
| Deterministic-only boundary | Research, semantic columns and paid authorization rejected; persisted zero-cost SCOUT_ONLY authorization remains supported |
| No dependency-direction violation | Existing architecture guards run with the full integration and regression gates; protocol-typed adapter assignment checked by strict mypy |

During development an additional acceptance test found the first B1 implementation
could adopt a pre-existing orphan `data_result` under a new start identity. It failed
with DID NOT RAISE PortError. The adapter was corrected to reject reused evidence
identities before any start writes, and the test passes. This was a defect in the
new implementation during development, not a pre-existing F02 defect reproduction.

Same-ID operations require identical frozen content, including original execution
time/bindings. A retry after acknowledgement loss must inspect retained identities;
changing time/content or generating new IDs is not an idempotent retry. A successful
start persistence return is not permission to skip future B2 preflight or dispatch
workers a second time. Ownership is never timed out or automatically released.

## 7. Verification results

All commands use the configured repository environment, with the existing network
block and temporary file-backed SQLite. No dependencies were installed.

| Command | Actual result |
| --- | --- |
| `.\.venv\Scripts\python.exe -m pytest tests/integration/test_runtime_foundation.py -q --tb=short -p no:cacheprovider` before production edits | Exit 1: one collection error, missing runtime contract module; new acceptance capability absent |
| Same command, final focused suite | Exit 0: **38 passed in 2.57s** |
| `.\.venv\Scripts\python.exe -m pytest -q -ra --tb=short -p no:cacheprovider` after final production/test changes | Exit 0: **1079 passed in 42.17s**; no skips or warning summary |
| `.\.venv\Scripts\python.exe -m pytest tests/integration tests/unit/test_architecture.py -q --tb=short -p no:cacheprovider` | Exit 0: **254 passed in 34.14s**, including existing SQLite/concurrency/Moto and architecture coverage; before final lean binding representation and three added tests |
| `.\.venv\Scripts\python.exe -m ruff check .` | Exit 0: all checks passed |
| `.\.venv\Scripts\python.exe -m ruff format --check .` | Exit 0: 257 files already formatted |
| `.\.venv\Scripts\python.exe -m mypy` | Exit 0: no issues in 195 source/test files |
| `git diff --check` | Exit 0; only Git Windows line-ending conversion warning observed |

The final full suite includes the integration and architecture tests. Interim checks found
formatting/lint and intentionally invalid test-input typing issues; these were
fixed without weakening assertions or skipping tests. The integration-only count
above is not represented as a final post-change rerun; the final full suite covers
the same tests plus the final changes.

## 8. Remaining limitations

- B1 supplies persistence primitives only. There is no command to execute Data,
  load approved files, refresh terms, orchestrate QA or recover/redispatch a worker.
- Source status/requirements/version, actor and inputs are trusted application
  assertions. B1 does not authenticate remote evidence or perform current complete
  eligibility/economic/scoring review. B2 must add the approved preflight before
  operational work; no already-ELIGIBLE flag is timeless permission.
- Result storage validates binding/shape/provenance, not transformation truth. Test
  DataResults are synthetic assertions; finishing means QA_PENDING, never PASS,
  approval, submission, acceptance, payment or verified revenue.
- Runtime persists no actual cost changes; unknown result cost remains unknown.
  Reservations and Budget audit remain authoritative and unchanged. Cost settlement
  and recovery must use existing worker/BudgetManager behavior in B2.
- The local read of incomplete runs is intentionally bounded by local dataset size,
  not a paginated scheduler. Full snapshot source storage has existing disk/size
  costs; no cloud adapter, compaction/offload or migration framework is added.
- Only first-version Data persistence is supported. Rework/v2 is F05; Research and
  paid runtime are outside B1. No general lease, abandoned-claim release or billing
  reconciliation mechanism is added.
- Host/database writers remain trusted. Hashes detect corruption, not hostile
  authorized rewriting. Multi-file backup/restore and cloud consistency remain
  separate operational gates. No paid or external exactly-once effect is claimed.
- New kinds/types need the new binary; no supported runtime downgrade or reset of
  old workspaces is introduced.

## 9. Deferred work for F02-B2

After operator approval only: bounded operator input parsing and full retained
eligibility/economics/QA criteria, fresh source/context validation, actual
DataWorker/lifecycle orchestration, explicit dependency injection, supported
restart coordination and CLI execution/read/export steps under the approved plan.
Use these ports and original identities; do not bypass them with raw snapshots.

Budget wait/resume and policy updates require their separately scoped approved
checkpoint; B1 does not implement or expose them. Research/Bedrock capabilities,
F03 submission/payment, F05 revisions and F06 deployment are not implicitly
authorized by this foundation. No mock fallback or auto-orchestration is proposed.

## 10. Verdict

**PASS_WITH_LIMITATIONS** for the B1 persistence foundation; all final gates above
passed. This is not an operational runtime or production-ready
verdict. F02-B2 was not started. Stop here for operator review; no commit or push.

# F02-B2: Deterministic Data worker execution

Date: 2026-10-25 (Asia/Bangkok). **PASS_WITH_LIMITATIONS** for this application
checkpoint only. F02 overall remains open. No F02-B3 implementation, commit or push.

## Implemented scope and prior behavior

B1 supplied immutable runtime contracts and atomic SQLite start/result/finish
persistence. Workers already existed, but production application orchestration
still used legacy ExecuteTask's direct LLM draft path. WorkSpecification did not
retain the full eligibility/economic evidence required for operational preflight.

ExecuteWorkerTask now orchestrates the existing real DataWorker with llm=None,
using approved retained deterministic Data specifications, BudgetManager and the
B1 runtime repository. It supports first-version execution and explicit
original-identity recovery, ending at QA_PENDING. It returns typed blocked or
recoverable outcomes and sanitized structured result logs.

There is no Research, Bedrock, semantic Data, AI QA, CLI command expansion, policy
update, budget resume, submission, payment, AWS deployment, mock fallback, v2/rework
or automatic orchestration. Domain, BudgetManager, DataWorker and legacy ExecuteTask
were not changed. No dependency was introduced or installed.

## Changed files

| File | Responsibility |
| --- | --- |
| `src/agentmine/application/contracts/execution_evidence.py` | New immutable DataExecutionEvidence: facts/profile, policy/rules version, EvaluationRecord and optional F04 review reference |
| `src/agentmine/application/contracts/worker_execution.py` | New ExecuteWorkerRequest and typed status/reason/outcome contracts |
| `src/agentmine/application/contracts/runtime.py` | Optional execution evidence on WorkSpecification; derived AI-evidence inspection field/reason |
| `src/agentmine/application/ports/runtime.py` | Narrow has_ai_evidence capability for existing claims/responses, including orphan identities |
| `src/agentmine/application/use_cases/worker_execution.py` | ExecuteWorkerTask; budget-first start, real deterministic work, retained result/finish and local recovery |
| `src/agentmine/application/use_cases/worker_preflight.py` | Current source/eligibility/approval/economic/scoring validation without changing the planned/active lifecycle |
| `src/agentmine/infrastructure/sqlite/runtime.py` | Inspect existing Data AI evidence and fail closed on identity adoption at start; existing transactions reused |
| `src/agentmine/infrastructure/snapshots.py` | Explicit allowlist for evidence and narrow legacy WorkSpecification default None |
| `tests/integration/test_worker_execution_runtime.py` | 41 offline application/SQLite/real-worker acceptance cases |
| `docs/adr/0024-deterministic-data-execution.md` | Focused architecture/recovery decision |
| `docs/adr/README.md` | ADR index entry |
| `docs/audits/remediation-03-b2-data-execution.md` | This report |

No bootstrap, presentation, Domain or existing test file was edited. No schema
migration/reset, fixture-money product command or live integration was added.

## Architectural decisions and preflight

See [ADR 0024](../adr/0024-deterministic-data-execution.md), building on
[ADR 0023](../adr/0023-local-worker-runtime-foundation.md) and the
[F02-A plan](remediation-03-runtime-plan.md).

Application coordinates business ports and pure Domain calculations; infrastructure
only reads/writes authoritative evidence. The separate small preflight helper keeps
source/eligibility/economic checks cohesive without growing a generic service.
No AWS/database type or concrete adapter is imported into Application.

1. Load the retained specification by stable ID; revalidate its immutable input
   digests/scope. The configured single operator must match the recorded approving
   actor; approval time cannot be in the future. No caller-supplied source snapshot,
   authorization, result, lifecycle selector or paid estimate is accepted in the
   execution command.
2. For a new run require the requested initial Opportunity revision, PLANNED phase
   and exact Task identity. Recovery requires the exact stored binding/spec/run;
   the initial revision parameter never authorizes rebinding an active run.
3. Require authoritative source refresh through CheckEligibility.inspect. Compare
   known source identity, open status, deadline knowledge/date, requirements text
   and terms/version to the approved context. Unavailable, unknown, malformed or
   changed source context blocks; no saved observation is relabeled as fresh.
4. Recompute eligibility at the current clock instant using retained complete
   facts/profile/policy and supported rules version. Expired, prohibited, unknown
   or now insufficient time cannot run despite historical ELIGIBLE state.
5. For MANUAL, load the actual recorded F04 review/resolution. Require matching
   review IDs, approving actor/time, facts/profile, policy and source context;
   only the original narrow MANUAL domain policy can resolve the current result.
   This is continuing first-run work under unchanged reviewed terms, not a new
   eligibility override, budget-wait reapproval or submission approval.
6. Match the retained EvaluationRecord to the repository and current Opportunity.
   Recalculate EconomicAssessment and ScoringAssessment from its frozen inputs,
   signals and policy; require matching reward/expected value/score/components and
   zero predicted AI cost for this deterministic scope. These assumptions remain
   subjective forecasts, not independently calibrated success probabilities.
7. Recheck Opportunity revision after refresh. Inspect Data AI claims/responses;
   any such evidence blocks deterministic execution. Authorize exactly zero AI
   cost through BudgetManager, reload the authoritative ledger and atomically
   start through B1 before invoking DataWorker. B1 rejects state/ledger revision
   races, conflicting first-run identities or adopted existing evidence.

WorkSpecification's new evidence field is optional for snapshot compatibility,
not for B2 permission. Legacy B1 snapshots load None and are blocked; no eligibility
facts/policy are manufactured. A new reviewed specification must use a new immutable
ID. Source/profile/evidence assertions still belong to the trusted local operator
and adapters; matching hashes do not prove remote truth.

## Execution, accounting and approval safety

DataWorker consumes the retained DataPlan/DataSource bytes only. It cannot reread
edited files, follow locators, execute expressions or select tools. The use case
constructs it with llm=None. Supported scope excludes semantic columns and positive
AI estimates, so no model, external action or paid dispatch path is reachable.

BudgetManager commits authorization first; runtime.start commits Execution/plan/
ownership/IN_PROGRESS before work. DataWorker retains its real DataResult in the
shared DataJournal before recording actual cost. The coordinator validates/binds
that real result via WorkerResult, retains it through the runtime port and finishes
with the existing atomic WorkerRunFinish operation. Completion is QA_PENDING even
when Data validation fails and returns only validation.json. No QA PASS is invented.

The measured AI cost of deterministic work is zero. Infrastructure cost remains
explicitly unmeasured in worker warnings. Existing positive actual costs and unknown
commitments are preserved; no authorization, cost, policy or claim is silently
released/reset. Duplicate recording uses the original measured context/time and
Domain's idempotent accounting.

Budget/spending outcomes remain distinct typed reasons. Since B2 requests only
zero cost and configured thresholds are nonnegative, real budget exhaustion does
not deny this path: it still runs in SCOUT_ONLY. The denial tests deliberately
fault-inject typed DENIED / REQUIRES_HUMAN_APPROVAL decisions to verify fail-closed
handling, not to claim a natural zero-cost denial. No spending-approval reference
can authorize positive-cost B2 work; that capability is absent. Operator approval
identity denial is also tested directly. No artificial WAITING_FOR_BUDGET transition
is created for a zero-cost denial.

## Recovery behavior

| Retained state | Behavior |
| --- | --- |
| Spec/no run | Require complete current preflight and original requested revision; authorize/start normally |
| Authorization committed, start fails | Retain commitment and original IDs; return typed recovery/conflict outcome; no worker call |
| Start committed, acknowledgement lost | Do not call worker in that attempt; retry inspects the existing original run |
| IN_PROGRESS/no result | Revalidate source/eligibility/economics and current revision; replay only the same bounded deterministic plan, with existing budget checks |
| AI claim or response evidence | BLOCKED / EXTERNAL_OUTCOME_UNKNOWN; no clearing, AI retry, mock fallback or replacement IDs |
| Result saved, cost write failed | Use retained actual cost; idempotently repair recording, then finish without recomputation or reauthorization |
| Result saved, finish failed | Reuse result and atomically finish against the authoritative same-run snapshot; no worker/source call needed for completion-only recovery |
| Opportunity changes during worker | Retain the result; original finish CAS fails without overwriting the newer revision; an explicit same-run recovery can finish if its current phase still permits it |
| Already finished, later QA/review advanced | Return historical completed run/result; never replay work or rewind current Opportunity |
| Failed QA/revision or incompatible active phase | No new execution/version; first-run state/binding checks block rework. F05 remains separate |

Completion-only recovery does not assert current source eligibility. It publishes
already-retained work/cost into the existing local lifecycle and grants no external
permission. Later QA/review/submission boundaries keep their own checks. Without a
result, an expired or unavailable source prevents any new computation.

COMPLETED/BLOCKED/RECOVERABLE are command outcomes, not a second business state
machine. Structured reason enums and PortError codes drive behavior; exception text
is never parsed or logged as a decision. Generic worker failures are sanitized.
Persistence acknowledgement ambiguity is distinguished from observed AI evidence.

## Test-first evidence and verification

The initial acceptance tests were written before production edits. Their first
execution failed collection with one ModuleNotFoundError for
`agentmine.application.contracts.execution_evidence` (exit 1). This demonstrates a
missing capability, not reproduction of an existing orchestration defect.

The final 41 cases use real DataWorker, BudgetManager, SQLite repositories/journals
and normal discovery/eligibility/evaluation/scoring/planning in setup. Only source
observations/clock and injected failure/denial cases are fake. They do not use an
LLM, fake payment or successful synthetic external submission.

Coverage includes:

- Real deterministic normalization/artifacts, durable start before worker, result
  validation failure, QA_PENDING and zero external submission/revenue.
- Source version/text/open/deadline/unknown/unavailable conditions, expiry/time
  remaining, recomputed prohibited/unknown facts and matching recorded MANUAL review.
- Missing or mismatched economics/evaluation, B1 legacy evidence compatibility,
  immutable input tampering, operator identity and stale requested/current revisions.
- Budget/approval denial branches, zero-cost SCOUT_ONLY execution, preservation of
  prior actual costs and unknown commitments, duplicate-cost prevention.
- Conflicting execution/operation/deliverable/spec identities; no F05 rework.
- Worker failure, committed-start acknowledgement loss, result-before-accounting
  crash, result/finish crash, reopen recovery, state races and no recomputation when
  results already exist; orphan and active AI claims block.
- Historical completion retries preserve later QA state.

Commands used the configured environment and the repository's network block:

| Command | Actual result |
| --- | --- |
| `.\.venv\Scripts\python.exe -m pytest tests/integration/test_worker_execution_runtime.py -q --tb=short -p no:cacheprovider` before production edits | Exit 1: missing evidence module; one collection error |
| Same command, final focused suite | Exit 0: **41 passed in 10.18s** |
| `.\.venv\Scripts\python.exe -m pytest tests/integration/test_worker_execution_runtime.py tests/integration/test_runtime_foundation.py tests/unit/test_architecture.py -q --tb=short -p no:cacheprovider` | Exit 0: **100 passed in 9.59s**, before eight additional B2 cases; final full suite includes them all |
| `.\.venv\Scripts\python.exe -m pytest -q -ra --tb=short -p no:cacheprovider` | Exit 0: **1120 passed in 49.78s**, no skips or warning summary |
| `.\.venv\Scripts\python.exe -m ruff check .` | Exit 0: all checks passed |
| `.\.venv\Scripts\python.exe -m ruff format --check .` | Exit 0: 263 files already formatted |
| `.\.venv\Scripts\python.exe -m mypy` | Exit 0: no issues in 200 source/test files |
| `git diff --check` | Exit 0: no whitespace errors; Windows LF/CRLF conversion warnings only |

Documentation links/whitespace and the complete changed-file scope were also
validated with a local read-only Python check (exit 0).

Interim type-check issues in optional-value narrowing and test fixture construction
were corrected; tests/assertions were not weakened or skipped. Full regression
coverage includes B1 SQLite/concurrency, F01/F04, architecture and unchanged legacy
execution. No production source/API, paid model, AWS account or reward was tested.

## Limitations and verdict

**PASS_WITH_LIMITATIONS** for safe first-version deterministic Data application
execution and its documented local recovery boundary. This does not close F02
overall or certify production readiness.

- There is no new operator CLI/bootstrap wiring or input-preparation UI. The
  application use case is exercised through explicit dependency injection.
- Runtime, DataJournal, evaluation/opportunity repositories and BudgetManager must
  use the same authoritative workspace/ledger. Trusted composition is not a
  sandbox against malicious host/database writers or nonconforming ports.
- Source content cannot be locked while work runs. Matching reviewed source terms
  binds retained normalized facts; profile assertions and subjective economic/
  scoring signals are not independently verified or automatically recalibrated.
- Retained-result completion is deliberately possible during source outage/expiry
  without new work; it grants no approval or external effect.
- Unknown/incompatible costs are never guessed, and existing ambiguous AI evidence
  stays blocked. This is not a general billing/incident reconciliation system.
- No new positive-cost path, manual budget-wait reapproval, budget policy/resume,
  semantic/research execution, QA orchestration, revision, submission or payment
  integration is enabled. F03/F05/F06 remain separate gates.

No operator action or credentials are required for the offline tests. No commit or
push was performed. F02-B3 was not started. Stop for operator review.

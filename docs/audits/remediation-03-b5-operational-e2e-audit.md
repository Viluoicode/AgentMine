# F02-B5: Local operational end-to-end audit

## 1. Scope, revision and recommendation

Audit date: **2026-10-27**, Asia/Bangkok. Audited commit:
`7f1bcc967df09dcb24baebd1e97f79f144fcb891`
(`feat(budget): add audited local budget policy control`). The tracked worktree
was clean at the beginning and after execution of the verification commands.
This report is the only deliverable added to the repository. No production code,
tests, architecture or existing ADRs were changed. No commit or push was performed.

**Recommendation: CLOSE_WITH_EXPLICIT_EXCLUSIONS.** The implemented first-version,
deterministic local Data scope can close: explicit preparation/execution, retained
results, deterministic QA, operator review, original-identity recovery and audited
budget policy control. This does **not** close all of F02-A, paid budget wait/resume,
F02-C, production readiness, real marketplace compatibility or real reward earning.
Operator review of this disposition is required before another checkpoint.

Evidence precedence: current source and tests executed during this audit, then
historical reports. Reviewed AGENTS.md, Product Constitution, full repository audit,
F01/F04 reports, F02-A plan, B1/B2/B3-A/B3-B/B4-A/B4-1 reports and ADRs 0023–0027.
The earlier reports' test counts are not used as this audit's results.

## 2. Evidence boundaries

Two isolated workspaces were used under ignored `.tmp/b5-evidence-20261027/`:

- `offline.sqlite3`: continuous CLI walkthrough with explicitly injected test-only
  FakeSource and FakeClock. Synthetic opportunity, eligibility assertions and
  forecasts were introduced through normal CLI/application workflows, never by
  inserting fabricated authority into an operator's production database.
- `entrypoint.sqlite3`: real module entrypoint, empty initialized workspace,
  inspection and default-disabled discovery. No synthetic opportunity was loaded.

The continuous walkthrough used real `compose_operator`, `run_cli`, SQLite
repositories/journals, BudgetManager, DataWorker and DeliverableQA. Composition was
reopened for each command. A call-count wrapper delegated to the original real
DataWorker implementation; it did not fabricate a result. Socket connect/connect_ex
were blocked. Automated pytest additionally used the existing network guard.

The temporary audit harness `.tmp/b5_probe.py`, input JSON files and
`audit-transcript.json`/`entrypoint-transcript.json` are local audit evidence, not
production commands or committed test additions. The harness exited 0 after its
final assertions. An earlier scratch attempt failed on directory permissions
before producing a transcript; it is not counted as successful evidence.

**Real-world evidence: BLOCKED.** No Superteam credential was present in the process
when checked (presence only; no secret value read or printed). No genuine eligible
Data opportunity or authorized live-source walkthrough was supplied. No live API,
Bedrock, submission, acceptance, payment or provider billing was verified. Passing
saved contract fixtures does not verify today's production API.

In particular, the walkthrough's `workspace discover --source superteam` selector
was paired with explicitly injected **FakeSource**, not the Superteam HTTP adapter.
The module entrypoint has no such fallback. Existing fixture-based Superteam tests
exercise the concrete adapter separately. This distinction is essential: the
continuous walkthrough proves local orchestration, not live discovery.

## 3. Actual CLI commands and observations

Executable: `.\.venv\Scripts\python.exe` (Python **3.14.2**).
The actual module-entrypoint commands used:

```powershell
$python = '.\.venv\Scripts\python.exe'
$base = @('-m', 'agentmine.bootstrap.operator', '--db', '.tmp/b5-evidence-20261027/entrypoint.sqlite3', '--ledger', 'entrypoint')
& $python -m agentmine.bootstrap.operator --help
& $python @base work --help
& $python @base work qa --help
& $python @base budget policy apply --help
& $python @base workspace init --currency USD --monthly-ai-budget 20 --daily-ai-budget 5 --max-cost-per-task 3 --human-approval-cost-threshold 1
& $python @base budget show
& $python @base dashboard
& $python @base workspace discover --source superteam --limit 1
```

Help, initialization and inspection exited 0. Initialization returned
`workspace_initialized`, revision 1. Dashboard showed FULL, monthly AI limit 20 USD,
spent/reserved 0, remaining 20, daily remaining 5. Discovery without live opt-in
exited **2** with `invalid_configuration` and:
`Superteam reads are disabled by default; pass --live and a configured API key`.
This expected refusal is a safety PASS, not a live discovery success.

The following are the actual argument suffixes passed to the real `run_cli` parser
in the isolated offline harness. Each included `--db` pointing to the absolute
`offline.sqlite3` path and `--ledger audit-local`. File names below abbreviate
absolute paths under the isolated audit directory; `inputs` and `export` also
refer to that directory. Actor was explicitly injected as `audit-operator`.

| Command suffix | Observed result |
| --- | --- |
| `workspace init --currency USD --monthly-ai-budget 20 --daily-ai-budget 5 --max-cost-per-task 3 --human-approval-cost-threshold 1` | Exit 0, initialized revision 1 |
| `workspace discover --source superteam --limit 1` | Exit 0, `discovery_ingested`; TEST FakeSource only |
| `opportunity eligibility --opportunity audit:data --facts facts.json --minimum-time-seconds 3600` | Exit 0, ELIGIBLE |
| `opportunity evaluate --opportunity audit:data --inputs economics.json` | Exit 0, EVALUATED |
| `opportunity score --opportunity audit:data --inputs scoring.json --evaluation audit-evaluation` | Exit 0, SCORED |
| `opportunity plan --opportunity audit:data --task audit-task --description "Normalize synthetic names"` | Exit 0, PLANNED |
| `budget show` | Exit 0, revision 1, derived full |
| `budget policy prepare --change-id audit-policy --inputs policy.json --expected-revision 1 --reason "OFFLINE explicit zero-limit continuity audit"` | Exit 0, retained proposal |
| `budget policy show --change-id audit-policy` | Exit 0 |
| `budget policy apply --change-id audit-policy` | Exit 1, `confirmation_required` |
| `budget policy apply --change-id audit-policy --confirm` | Exit 0 |
| `budget show` | Revision 2, derived scout_only after approved zero monthly/daily limits |
| `work prepare --opportunity audit:data --spec-id audit-spec --inputs spec.json --input-root inputs --facts facts.json --minimum-time-seconds 3600 --evaluation audit-evaluation --approve-inputs` | Exit 0, immutable specification retained |
| `work show --spec-id audit-spec` | Exit 0 |
| `work execute --spec-id audit-spec --execution-id audit-execution --operation-id audit-operation --deliverable-id audit-deliverable --expected-revision REV --confirm` | With DisabledOpportunitySource: exit 1, BLOCKED/SOURCE_UNAVAILABLE; REV was the actual planning response revision |
| Same execution arguments | Changed fixture requirements: exit 1, BLOCKED/SOURCE_CHANGED |
| Same execution arguments | Original source restored; approved local file subsequently edited: exit 0, COMPLETED/QA_PENDING using the retained snapshot |
| `work recover --execution-id audit-execution --confirm` | Exit 0, COMPLETED/QA_PENDING, no second worker call |
| `work qa --execution-id audit-execution --inspection-id audit-inspection --confirm` | Exit 0, PASS/READY_FOR_HUMAN_REVIEW |
| `work status --execution-id audit-execution` | Exit 0, READY_FOR_HUMAN_REVIEW |
| `review --opportunity audit:data --review-id audit-review --destination operator:offline-only-no-send` | Exit 0, operator review rendered |
| `show-review --review-id audit-review` | Exit 0, retained review rendered |
| `work export --execution-id audit-execution --directory export` | Exit 0, external_submission=false |
| `budget show` | Exit 0, revision 5, derived scout_only |
| `dashboard` | Exit 0 |

The synthetic input was two name records, with approved SHA-256, explicit name
column, min/max record count 2 and frozen CSV/name-column acceptance criteria.
Potential reward was a synthetic USD 20; probability 0.5 and all scoring signals
0.5 were explicitly subjective fixtures. Estimated costs were fixture forecasts,
not billing claims. Final repository assertions: READY_FOR_HUMAN_REVIEW, **one real
worker invocation**, nine fake source refreshes, one actual-cost record, verified
revenue **0**, and no approval, submission, outcome or payment. The separate
approval tests, not this unsent walkthrough, exercise approve/reject/revision.

## 4. Feature assessment

PASS means verified within the stated offline/local boundary, not universal proof.

| Capability | Result | Evidence and limitation |
| --- | --- | --- |
| Discovery and normalization via use cases | PASS offline / BLOCKED live | Continuous CLI fixture flow; concrete saved Superteam fixtures in suite; no authorized live observation |
| Eligibility, economics, scoring and planning | PASS | Real CLI/use cases; forecasts remain subjective; missing/ineligible/expired evidence tests |
| Fresh source preflight | PASS bounded | SOURCE_UNAVAILABLE/SOURCE_CHANGED observed; deadline/version tests; profile truth is not independently authenticated |
| Immutable approved inputs and criteria | PASS | Frozen snapshot execution after local edit; tampering, identity and criteria-conflict tests |
| Authorization before dispatch | PASS | BudgetManager before durable start; denial/approval tests; no positive-cost capability exposed |
| Real worker and retained result | PASS | Real DataWorker with llm=None; actual returned DataResult and SQLite journals |
| Stable execution/operation/deliverable identity | PASS | Retry/reopen/conflict tests; same-ID walkthrough recovery |
| QA PASS | PASS | Real DeliverableQA; READY_FOR_HUMAN_REVIEW, no approval/send |
| QA FAIL / NEEDS_REVISION | PASS safe blocking | Tests preserve evidence and IN_PROGRESS; first-run replay blocked pending F05 |
| QA REQUIRES_HUMAN_REVIEW | PASS safe pending | Semantic criterion leaves QA_PENDING; human QA resolution remains unavailable |
| Separate submission approval | PASS | Existing review/decide tests; QA does not grant consent |
| Local artifact export | PASS | Actual export; no-clobber/retry tests; export is not submission |
| Budget inspect / prepare / show / confirmed apply | PASS | CLI walkthrough and transaction tests |
| Commitments, actuals and original receipts | PASS | Preservation, lowered-limit, lost-ack, later-change and concurrency tests |
| SCOUT_ONLY deterministic continuity | PASS | Actual execution with monthly/daily limits zero |
| Paid WAITING_FOR_BUDGET and resume | BLOCKED / excluded | No approved paid worker; B4-1 intentionally inspect-only, not fake paid execution |
| Unknown paid outcomes | PASS containment / BLOCKED reconciliation | Unknown evidence remains blocked; no retry, zero-cost substitution or release |
| No mock fallback / paid calls / external actions | PASS local | Explicit composition, network guard, negative tests and absent submission/payment records |
| Real reward / net verified value | BLOCKED | No independent payment evidence; local zero AI cost is not complete system cost |

No new CRITICAL/HIGH defect was confirmed in the audited local scope. This matrix
does not convert excluded or untested capabilities into PASS.

## 5. Crash, retry, concurrency and financial safety

| Failure window | Verified behavior / evidence |
| --- | --- |
| Authorization committed, start not committed | Commitment retained; no silent release; atomic start rejects stale ledger/opportunity. B2 ledger-race test |
| Failure during start transaction | Owner/run/execution/plan/lifecycle roll back together. Foundation fault injection at every write |
| Start committed, acknowledgement lost | No work dispatched in uncertain-start call; original IDs retained for recovery. B2 crash-after-start test |
| Worker fails before result | Same frozen deterministic plan may replay only after fresh preflight; no permission to replay paid/external operations |
| Result persisted before cost record | Recover cost from retained real result idempotently, then finish; no recomputation or invented zero. B2 journal-before-ledger test |
| Failure during finish | Result remains retained; content/deliverable/lifecycle/completion marker atomic. Foundation rollback and B2 recovery tests |
| Concurrent starts / conflicting IDs | Permanent first-version task ownership and CAS; no second independent run ownership. Deterministic recomputation is not an external exactly-once claim |
| QA report saved before lifecycle completion | Original inspection/report retained; retry conditional completion; no reinspection when report exists |
| Stale/concurrent QA | Exact binding/revision checked; different inspection cannot replace version owner; completed readback cannot rewind later approval |
| Policy failure after each write | Budget, audit, decision and receipt roll back together; original proposal survives |
| Policy applied, acknowledgement lost | Same ID returns original receipt even after later changes; never reapplies old policy |
| Same/different concurrent policy proposals | One CAS winner per revision; same identity readback or safe retry; conflicting/stale payload rejected |
| Ambiguous paid claim / legacy wait | Inspect-only unresolved evidence; no new ID, release, dispatch or automatic resume |

These are executed exception/fault-injection and file-backed SQLite reopen tests,
not a power-loss, disk-controller durability, multi-host or backup restoration drill.
No transaction spans source I/O or worker execution. Budget authorization, worker
result and settlement intentionally have separate durable recovery points. One
recorded deterministic AI zero does not claim zero infrastructure/tool/transaction
cost or reconcile a real provider bill.

## 6. Architecture findings and residual risks

Source references below are relative to repository root at the audited commit.

**Boundary assessment: PASS.** Architecture tests cover imports across all layers,
including nested/type-guard imports and dependency cycles. Application owns ports,
runtime contracts and orchestration; Domain owns lifecycle/financial rules.
`src/agentmine/bootstrap/local_runtime.py:48` wires shared SQLite authority,
BudgetManager, real execution and zero-AI QA. `bootstrap/operator.py:66` supplies the
same ledger/operator/source; module-entrypoint workspace validation is explicit.
Presentation invokes use cases; it does not directly move lifecycle states.
No AWS, database schema, Superteam or Bedrock model was found defining inner-layer
business semantics in this runtime. Typed errors/reasons are used, not exception
message parsing. No new hidden service locator or provider fallback was found.

| Severity | Finding | Evidence, implication and disposition |
| --- | --- | --- |
| MEDIUM, existing limitation | Source freshness is narrower than independent truth | `application/contracts/eligibility.py:28` refreshes availability/deadline; other facts/profile are operator assertions. `application/use_cases/worker_preflight.py:61` rechecks rules and exact reviewed context; `infrastructure/marketplaces/superteam.py:105` rejects unconfirmed AI policy and hashes response bytes. This substantially narrows F07 locally but cannot validate changed off-source identity/account facts or lock remote changes. Keep F07 open; no bypass reproduced |
| MEDIUM, existing operations gap | Unknown paid evidence and cross-store restore remain unresolved | `application/use_cases/budget_control.py:36` classifies reconciliation/unsupported waits conservatively. No reconciliation or coordinated backup drill was performed. Keep F08 open; do not manually delete claims or turn unknown cost into zero |
| LOW, maintainability | Budget read adapter calls another adapter's private inspection helper | `infrastructure/sqlite/budget_control.py:76` calls runtime `_inspect` on the shared connection. Keeps a consistent read and does not reverse dependency direction, but couples adapter internals. No correctness failure found; no refactor authorized here |
| LOW, operator retry semantics | Successful policy apply can be followed by a failed view refresh | `presentation/budget_cli.py:104` applies then reads the view; `application/use_cases/budget_control.py` checks revisions across reads. A concurrent change/read failure can produce a nonzero command after commit. Receipt idempotency makes same-ID recovery safe; operators must inspect/retry the original ID, not infer rollback from exit status |

Other limitations: exact response-body hashing can conservatively block harmless
source changes; re-scoring recomputes frozen subjective signals rather than proving
current success probability. QA validates approved declared requirements, not the
completeness/truth of the operator's specification. Hashes protect consistency,
not malicious authorized database writers. The local actor/host/store are trusted;
this is not remote IAM or a host sandbox. Filesystem hard-link export support is
required; hostile mapped-drive/host changes were not independently tested here.

Historical-plan contradiction resolved explicitly: F02-A's original paid wait/resume
acceptance is **not implemented** by zero-cost SCOUT_ONLY continuity. The approved
B4-A/B4-1 split defers it. Closing this bounded local scope must not mark those
original acceptance items complete. Likewise QA human-pending and F05 rework are
safe stop states, not operationally completed revisions.

## 7. Executed verification

All following results were obtained in this audit, without code/test changes.

| Command | Result |
| --- | --- |
| Focused integration selection below, `-q --tb=short -p no:cacheprovider` | **238 passed in 82.74s** |
| `.\.venv\Scripts\python.exe -m pytest tests/unit/test_architecture.py -q --tb=short -p no:cacheprovider` | **29 passed in 4.30s** |
| `.\.venv\Scripts\python.exe -m pytest -q -ra --tb=short -p no:cacheprovider` | **1219 passed in 147.92s**, exit 0; no skips reported |
| `.\.venv\Scripts\python.exe -m ruff check .` | All checks passed |
| `.\.venv\Scripts\python.exe -m ruff format --check .` | 293 files already formatted |
| `.\.venv\Scripts\python.exe -m mypy` | Success, 221 source files; project configuration has strict=true |
| `.\.venv\Scripts\python.exe .tmp/b5_probe.py` | Exit 0; continuous isolated CLI walkthrough and final assertions above |
| Module CLI subprocess checks in section 3 | Expected exits 0 except deliberate non-live discovery exit 2 |
| `git diff --check` | Exit 0; tracked code/test worktree unchanged |
| Separate new-report whitespace/code-fence check | Passed; necessary because the new untracked report is not included in ordinary git diff |

Focused selection after `python -m pytest`:

```text
tests/integration/test_workspace_bootstrap.py
tests/integration/test_runtime_foundation.py
tests/integration/test_worker_execution_runtime.py
tests/integration/test_runtime_operator_cli.py
tests/integration/test_operational_deliverable_qa.py
tests/integration/test_budget_control.py
tests/integration/test_budget_control_persistence.py
tests/integration/test_operator_approval_sqlite.py
tests/integration/test_eligibility_review_persistence.py
```

These tests include real SQLite/DataWorker/QA; test-only clocks, sources, deliberate
corruption and fault injection are explicitly distinguished from production ports.
The QA FAIL test deliberately corrupts retained values coherently after real worker
execution to exercise detection; it is not a naturally occurring live bounty failure.
Budget denial/spending-review branches use controlled test conditions because the
current operational worker only requests zero AI cost. No positive-cost production
capability was invented to manufacture budget-wait evidence.

A later optional transcript reread was not executed: automatic approval review hit
its usage limit. That was a review-service failure, not an unsafe-action judgment.
It does not replace or invalidate the already returned successful command outputs.
No bypass or additional live verification was attempted.

## 8. Dependencies and closure exclusions

| Item | Remaining gate |
| --- | --- |
| F02-C | Separately approved bounded Research tools/evidence and optional paid/semantic capabilities, explicit composition and budget/cost contracts; no implicit provider activation |
| B4-2 | A real approved paid capability first; durable wait ownership, fresh source/eligibility/economics/approval, atomic resume and current-policy authorization semantics. Legacy/MANUAL waits remain inspect-only |
| F03 | Verified supported send/receipt/outcome and independent payment contracts/adapters; separate operator consent. No fabricated gateway/payment to complete the story |
| F05 | Explicit versioned rework after QA failure or REQUEST_REVISION; retain v1 history, fresh QA/approval, no first-run identity replacement |
| F06 | Shared durable cloud claims/raw archives and deployment validation; local SQLite audit does not authorize Lambda paid execution |
| F07 | Broader fact authenticity/freshness and source-contract validation; current exact-context checks do not independently authenticate all eligibility assertions |
| F08 | Evidence-driven reconciliation, abandoned/ambiguous claims and consistent backup/restore across authorities; retain unknown costs and commitments |

Real-world follow-up requires an operator-selected legitimate Data opportunity,
authorized read-only source access, truthful profile/facts/forecasts and genuinely
approved local inputs/acceptance criteria. No credentials need to be pasted into
chat. This audit neither requests a submission nor authorizes paid execution.

**Final disposition: CLOSE_WITH_EXPLICIT_EXCLUSIONS**, subject to operator review.
Close only the implemented deterministic local F02-B scope described above.
Keep all listed blocked capabilities open. No further implementation is started.

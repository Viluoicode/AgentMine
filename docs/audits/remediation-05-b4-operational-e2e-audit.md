# F05-B4: Independent versioned rework operational audit

Date: 2026-10-28, Asia/Bangkok. Recommendation: **CLOSE_WITH_EXPLICIT_EXCLUSIONS**,
subject to operator review.

## 1. Scope, baseline and evidence

Audited commit: `ca8faa0cd2c237d0fcab90536112dc6ca7fb3de9`.
The tracked/untracked working tree was clean at audit start. Only this report is
added to the repository. Production code, tests, architecture, existing ADRs and
implementation behavior are unchanged. No dependency installation, commit or push.
Disposable audit harnesses, transcripts and file-backed databases are under ignored
`.tmp/`; these are explicitly synthetic audit workspaces, never production data.

Read AGENTS.md, Product Constitution, original audit/F05, F05-A, B1/B2/B3 reports,
ADR 0028 and F02-B5; inspected current Domain, revision contracts/use cases, runtime
composition, SQLite transactions, CLI, QA and review paths. Source and the executed
checks below take precedence over historical milestone claims. Python 3.14.2 was
used; this is not an independent compatibility matrix for every Python 3.12+ release.

Three evidence classes are distinguished:

- Continuous audit walkthroughs: real `run_cli` parser and production
  `compose_operator`, a new composition per command, actual file-backed SQLite,
  BudgetManager, deterministic DataWorker and DeliverableQA. Explicit test-only
  FakeSource/FakeClock supply synthetic observations and time. Socket connect and
  connect_ex are blocked. No direct opportunity seeding bypasses discovery in these
  successful continuous flows.
- Separate automated coverage: existing B1/B2/B3 and regression tests, rerun without
  editing them. Some construct a planned fixture parent directly, inject faults or
  corrupt evidence. They are not represented as continuous discovery walkthroughs.
- Real module entrypoint: separate Python subprocess commands, no source injection;
  safe initialization/help/inspection and expected live-source refusals only.

No authenticated live marketplace, paid LLM, AWS deployment, external submission,
acceptance, payment, billing reconciliation or independently verified reward was
attempted. Synthetic USD 20 potential reward and 0.5 probability/signals are declared
fixture forecasts. Recorded deterministic AI zero is not proof of zero host/tool/
infrastructure/transaction cost or profit.

## 2. Continuous offline CLI walkthroughs

Executed disposable harnesses:

```powershell
.\.venv\Scripts\python.exe .tmp/f05_b4_probe.py
.\.venv\Scripts\python.exe .tmp/f05_b4_fail_probe.py
.\.venv\Scripts\python.exe .tmp/f05_b4_fail_pass_probe.py
```

Successful final transcripts respectively reside under:

- `.tmp/f05-b4-evidence-20261028-final/audit-transcript.json`
- `.tmp/f05-b4-fail-evidence-20261028-final/audit-transcript.json`
- `.tmp/f05-b4-fail-pass-evidence-20261028/audit-transcript.json`

These are local audit artifacts, not shipped fixtures or production workspace
instructions. All commands below carry global `--db ABSOLUTE_ISOLATED_PATH --ledger
audit-local`; actor `audit-operator`, clock and source are explicitly injected at
composition. Paths in this table abbreviate files under the corresponding isolated
root, with input root `inputs`. Full argv and outputs are in each transcript.

| Actual command suffix | Observed result |
| --- | --- |
| `workspace init --currency USD --monthly-ai-budget 20 --daily-ai-budget 5 --max-cost-per-task 3 --human-approval-cost-threshold 1` | Exit 0, workspace revision 1 |
| `workspace discover --source superteam --limit 1` | Exit 0, discovery_ingested via TEST FakeSource, not Superteam HTTP |
| `opportunity eligibility --opportunity audit:data --facts facts.json --minimum-time-seconds 3600` | ELIGIBLE |
| `opportunity evaluate --opportunity audit:data --inputs economics.json` | EVALUATED |
| `opportunity score --opportunity audit:data --inputs scoring.json --evaluation audit-evaluation` | SCORED |
| `opportunity plan --opportunity audit:data --task audit-task --description "Normalize synthetic names"` | PLANNED; actual returned revision used below |
| `work prepare --opportunity audit:data --spec-id audit-spec --inputs spec.json --input-root inputs --facts facts.json --minimum-time-seconds 3600 --evaluation audit-evaluation --approve-inputs` | Retained approved snapshot/criteria |
| `work execute --spec-id audit-spec --execution-id audit-execution --operation-id audit-operation --deliverable-id audit-deliverable --expected-revision REV --confirm` | COMPLETED, QA_PENDING; real DataWorker |
| `work qa --execution-id audit-execution --inspection-id audit-inspection --confirm` | NEEDS_REVISION in first flow; FAIL in deliberate bad-value flows |
| `work revision prepare --revision-id audit-revision-2 --parent-execution audit-execution --trigger qa --trigger-id audit-inspection --spec-id audit-spec-2 --evaluation audit-evaluation-2 --inputs spec.json --input-root inputs --facts facts.json --minimum-time-seconds 3600 --economics economics.json --scoring scoring.json --forecast-evidence operator:forecast-2 --reason "Explicit offline correction"` | PREPARED |
| `work revision show --revision-id audit-revision-2` | Immutable parent, scope differences, criteria, forecasts and absence of consent displayed |
| `work revision execute --revision-id audit-revision-2 --confirm` before approval | Exit 1, BLOCKED/APPROVAL_DENIED |
| `work revision approve --revision-id audit-revision-2 --execution-id audit-execution-2 --operation-id audit-operation-2 --approve-inputs --confirm` | APPROVED_NOT_STARTED, allocated version 2 |
| `work revision execute --revision-id audit-revision-2 --confirm` | COMPLETED, QA_PENDING |
| `work revision recover --revision-id audit-revision-2 --confirm` | Same completed allocation, no additional worker invocation |
| `work qa --execution-id audit-execution-2 --inspection-id audit-inspection-2 --confirm` | PASS in first/third flow; real FAIL after deliberate corruption in second |
| `review --opportunity audit:data --review-id audit-review-2 --destination operator:offline-no-send`, then `show-review --review-id audit-review-2` | New v2 review rendered in first flow |
| `decide --review-id audit-review-2 --decision REQUEST_REVISION` | Applied operator transition to IN_PROGRESS in first flow |
| Revision prepare/show/approve/execute/recover with suffix 3 and parent `audit-execution-2` | Version 3; trigger operator/audit-review-2 in first flow, qa/audit-inspection-2 in second |
| `work qa --execution-id audit-execution-3 --inspection-id audit-inspection-3 --confirm` | Fresh PASS, READY_FOR_HUMAN_REVIEW |
| Retry old `work qa --execution-id audit-execution-2 --inspection-id audit-inspection-2 --confirm` | Original report returned; current v3 snapshot unchanged |
| `decide --review-id audit-review-2 --decision APPROVE` after its revision decision | Exit 1, conflict; no transferred authority |
| New `review ... --review-id audit-review-3`, then `decide --review-id audit-review-3 --decision APPROVE` | Explicit v3 approval; no submission |
| `work status --execution-id` for each retained execution | Requested historical completion separated from current execution/version |
| `work export --execution-id audit-execution-3 --directory export`, repeated | Exit 0 twice; manifest exact lineage/version/execution, external_submission=false |
| Export v1 into the occupied v3 directory | Exit 1, no-clobber conflict |

First continuous flow: v1 NEEDS_REVISION -> approved v2 PASS -> applied operator
REQUEST_REVISION -> approved v3 PASS -> separately approved v3. V2 and v3 output
content digests are identical, yet execution/specification/operation/QA/review
identities differ. All three versions keep Task `audit-task` and lineage
`audit-deliverable`. Final worker calls=3, actual records=3, verified revenue=0,
submission/outcome/payment absent. Existing v1 evidence rows and its actual cost
remain unchanged; new successor links are append-only evidence, not parent edits.

Second continuous flow: real retained v1 -> deliberately corrupted bad-value
fixture -> real QA FAIL -> approved v2 -> deliberate bad-value fixture -> real QA
FAIL -> approved v3 -> fresh PASS and separate review/approval. Third flow separately
proves FAIL -> approved v2 -> QA PASS. These FAIL fixtures change retained cells,
artifacts, content and matching bindings coherently in the isolated database after
real worker execution. They test the real QA engine's unsupported-value detection;
they are not natural marketplace failures, caller-supplied QA outcomes, or evidence
that an authorized hostile database writer is sandboxed.

Audit harness corrections are disclosed: an initial history assertion incorrectly
included a newly added `revision_successor` row in the immutable-parent comparison;
comparison was corrected to preserve every original row while permitting append-only
links. A first corruption fixture used dataclasses.replace on an aggregate with
init=False lifecycle state and was safely rejected as invalid_state; it was
corrected using a copy preserving lifecycle. Production/test code was not changed.
Only successful final transcripts support the walkthrough conclusions.

Human-pending rejection is separately executed automated coverage, not one of the
three discovery-to-review continuous walkthroughs.

## 3. Real module entrypoint and strict CLI boundary

Independently executed `.venv/Scripts/python.exe -m agentmine.bootstrap.operator`
subprocesses with isolated `entrypoint.sqlite3`, ledger `entrypoint`. A child-process
environment explicitly removes AGENTMINE_SUPERTEAM_API_KEY and sets a local audit
actor; no secret value is read or printed. Transcript:
`.tmp/f05-b4-evidence-20261028/entrypoint-transcript.json`.

| Arguments after global db/ledger | Observed exit/output |
| --- | --- |
| `--help`, `work revision --help`, `work revision approve --help`, `work qa --help` | 0, actual argparse help |
| `workspace init` with limits 20/5/3/1 USD | 0 |
| `budget show`, `dashboard` | 0; FULL, zero recorded/reserved AI, monthly remaining 20 |
| `workspace discover --source superteam --limit 1` | 2, invalid_configuration: source disabled by default; requires --live and key |
| Same discovery with `--live` | 2, live source requires AGENTMINE_SUPERTEAM_API_KEY |

B3 entrypoint regression separately verifies missing/wrong actor and ledger,
SOURCE_UNAVAILABLE without refresh, and missing key with explicit refresh. No
MockLLM/FakeSource fallback exists in production composition. Strict bounded JSON
rejects unknown fields, duplicate keys, non-finite constants, oversized input and
changed input digests. Execution accepts retained revision ID, never a caller-selected
version, QA result, lifecycle state or replacement Budget. Consent requires both
--approve-inputs and --confirm; execute/recover require --confirm.

## 4. Feature assessment

PASS is limited to the audited local deterministic boundary.

| Capability | Assessment | Evidence / exclusion |
| --- | --- | --- |
| Discovery through approved v1 execution | PASS offline / BLOCKED live | Continuous CLI paths, real persistence/worker; synthetic source only |
| FAIL -> approved v2 -> PASS | PASS | Third continuous walkthrough plus parametrized B3 regression |
| NEEDS_REVISION -> approved v2 | PASS | First walkthrough; original missing-column requirement retained, column added |
| PASS -> applied REQUEST_REVISION -> v2 | PASS | Automated B3 path; first walkthrough exercises same transition from v2 to v3 |
| v2 FAIL -> v3 fresh QA | PASS | Second continuous walkthrough and B3 test |
| Human-pending does not authorize revision | PASS containment | B2/B3 tests; human QA resolution unavailable |
| Same Task/lineage, sequential unique identities | PASS | Contracts, atomic allocation, continuous v1/v2/v3 evidence |
| One approved successor; no branches/reuse/supersession | PASS | Serialized ownership and collision/concurrent approval tests; stale allocations remain blocked |
| Identical bytes do not transfer QA/review | PASS | First walkthrough v2/v3; B3 v1/v2 test rejects old inspection/review and requires new approval |
| Immutable inputs, criteria, original history/cost | PASS | Retained snapshots; additive-only contracts; original-row/cost comparison; tampering tests |
| Source, deadline, eligibility/economic/scoring checks | PASS bounded | Recomputed Domain rules and exact source terms; unknown/ineligible/expired/changed evidence blocks; F07 excluded |
| Budget before dispatch; zero-AI SCOUT_ONLY continuity | PASS | B2 worker spy and real B3 policy/CLI tests; paid resume excluded |
| Original-ID crash/retry and concurrency | PASS bounded | Fault-injection/reopen tests and same-ID walkthrough recoveries; details below |
| Unknown paid claims | PASS containment / BLOCKED reconciliation | No replay/zero substitution/release; F08 remains open |
| Exact-version QA and stale/historical readback | PASS | Persisted finish/allocation lookup, report owner/CAS, historical walkthrough and regressions |
| Retained-result v2 status regression | PASS corrected | Current work status handles parent QA and expected start revision; final regression tests executed |
| Revision show stale snapshot diagnostic | FAIL, LOW | Independently reproduced discrepancy, section 6; dispatch remains blocked |
| Separate operator approval, no automatic send/payment | PASS | Explicit reviews; no gateway/payment verifier in composition; zero revenue |
| No-clobber versioned export | PASS | Actual repeated export and cross-version directory conflict |
| Real reward / production/live provider readiness | BLOCKED / excluded | No live or independent settlement evidence |

## 5. Identity, financial and crash-safety assessment

| Boundary | Current guarantee and independently executed evidence |
| --- | --- |
| Prepare | Immutable request/spec/evaluation transaction; no dispatch/consent. Identical proposal readback and changed-payload rejection. Distinct draft proposals may coexist until one approval wins |
| Approve/allocate | BEGIN IMMEDIATE retains consent, successor owner, version owner and allocation together. Fault after each write rolls back; lost acknowledgement reopens original allocation; same/different concurrent approvals cannot branch |
| Authorization before start | Existing BudgetManager persists original operation authorization. Start compares current ledger and parent snapshot. Ledger-race test preserves commitment and blocks stale start |
| Durable start | Run/execution/plan/Domain-updated Opportunity commit atomically. Failures/lost acknowledgement inspect original IDs; no new version to evade commitment |
| Worker failure/missing result | Replay only identical frozen deterministic work after fresh source/eligibility/economic checks. No exactly-once CPU claim; concurrent deterministic recomputation can converge or conflict |
| Result before accounting | Real retained DataResult carries actual zero-AI evidence; same BudgetManager operation settles idempotently. No worker rerun or invented cost required |
| Accounting before finish | Actual record survives; original run/result finishes atomically with content, exact deliverable/version, lifecycle and marker |
| Finish acknowledgement lost | Completed original allocation read back, no new cost/version or lifecycle rewind |
| QA claim/report/application | Original inspection evidence and report retained; completion checks exact bound revision/version. Report-before-transition crash can resume only its original snapshot; historical applied report is read-only |
| Operator decision/lifecycle split | Existing save_decision precedes Opportunity save. F05 repository requires the applied matching transition, not decision alone. Injected partial-write test blocks successor; original decide retry completes only matching state |
| Unknown paid/external claim | Remains blocked even if deterministic-looking inputs exist; no release, new ID or fabricated actual zero |

No outstanding commitment, actual cost or released-operation identity is reset by
revision workflows. New versions use distinct zero-AI operations; budget-policy,
eligibility, revision-input consent and submission approval remain separate.
Stale parent/ledger conflicts fail closed. No automatic policy increase or task
resume occurs. Forecasts never enter verified revenue. Tests demonstrate application
exception/transaction fault injection and file reopen, not power-loss, storage
controller, backup restore, multi-host or live-provider durability certification.

An additional isolated two-thread CLI probe prepared two distinct proposals for the
same completed parent: both exited 0. Approval of the first exited 0; approval of
the second exited 1 with successor_owned. Drafts create no dispatch authority.
This used a clearly test-only planned fixture parent rather than a continuous
discovery walkthrough; evidence is `.tmp/f05-b4-prepare-race/summary.json`.

## 6. Source and architecture findings

No CRITICAL or HIGH finding was confirmed within this bounded local path.
References are relative to repository root at the audited commit.

| Severity | Finding and evidence | Impact / disposition |
| --- | --- | --- |
| LOW, confirmed diagnostic defect | `src/agentmine/infrastructure/sqlite/data_revision.py:558` inspect checks active execution but omits exact started snapshot revision. `presentation/revision_cli.py:88` displays that view. In isolated fixture, worker interruption followed by a same-value Opportunity revision bump yields revision show IN_PROGRESS/RESULT_MISSING while work status is BLOCKED/STATE_CHANGED and recover BLOCKED/STATE_CONFLICT | Misleading revision-family status; no dispatch or financial bypass. Align read projection with authoritative started snapshot in a separately approved focused fix. Evidence `.tmp/f05-b4-status-probe/summary.json` |
| MEDIUM, existing excluded trust/freshness limit | `application/use_cases/revision_preflight.py:41` refreshes source and recomputes eligibility/economics; facts/profile/locators and forecasts remain trusted assertions. `application/contracts/opportunities.py` compares frozen terms; remote changes cannot be locked | Keep F07 open; no claim of independent fact authenticity or live contract compatibility |
| MEDIUM, existing excluded operations gap | Ambiguous paid claims and stale allocated versions remain blocked; no coordinated reconciliation/backup/supersession capability | Keep F08 open; inspect original IDs, never clear claims or allocate around them |
| LOW, contained existing transaction window | `application/use_cases/operator.py:169` records decision before lifecycle save; `infrastructure/sqlite/data_revision.py:122` checks exact applied QA/review transition and revision | Partial decision is visible but cannot authorize rework. Original-decision retry or safe block required; no global atomic approval redesign is implied |

The v2 retained-result status regression reported in B3 is corrected in current
source: `application/use_cases/data_history.py:36` passes expected parent QA and
started revision to `application/contracts/runtime.py:RuntimeStatus.reason`.
RESULT_MISSING and FINISH_PENDING no longer reject legitimate retained parent QA;
a changed Opportunity revision still blocks. B3 tests execute both retained-result
recovery and stale active revision. The remaining revision-show discrepancy above
is a different read projection, not evidence that the dispatch fix failed.

Clean Architecture assessment: PASS within static/source evidence. Domain owns
begin_rework/finish/QA/approval transitions (`domain/opportunity.py:398`); Application
owns orchestration and typed contracts/ports. SQLite enforces port atomicity and
identity/evidence consistency; it does not choose eligibility/scoring policy.
`bootstrap/local_runtime.py:68` wires the same database, ledger, source, clock,
BudgetManager and deterministic journals, DataWorker llm=None and existing QA
without paid AI. Presentation parses/delegates/displays, without lifecycle mutation.
AWS/Bedrock/Superteam SDK or database models do not define Domain semantics.
Read-only history does not route revisions through legacy first-run dispatch.

The SQLite revision adapter is large and calls private runtime inspection helpers;
this is maintenance coupling inside Infrastructure, not a confirmed layer violation
or demonstrated god-class defect. No new framework, service locator or mutable
provider global was found. Trusted host/store/DI callers can write evidence; hashes
are consistency checks, not hostile-host authentication. Architecture tests are
static import/cycle guards and do not prove every dynamic behavior.

## 7. Executed verification

All results below are from this independent audit, without editing production or
tests. Pytest uses the repository socket guard. Commands use
`.\.venv\Scripts\python.exe`.

| Check | Executed result |
| --- | --- |
| Focused selection below, `-q -ra --tb=short -p no:cacheprovider` | 292 passed in 196.87s |
| `-m pytest tests/unit/test_architecture.py -q --tb=short -p no:cacheprovider` | 29 passed in 0.68s |
| `-m pytest -q -ra --tb=short -p no:cacheprovider` | 1310 passed in 219.96s, exit 0; no skips reported |
| `-m ruff check .` | All checks passed |
| `-m ruff format --check .` | 312 files already formatted |
| `-m mypy` with strict project configuration | Success, 234 source files |
| Three successful continuous audit harnesses | Exit 0, described above |
| Real module subprocess commands | Expected exit 0 or deliberate safe refusal 2 |
| Independent stale-status probe | Exit 0, reproduced LOW finding without worker redispatch |
| Concurrent distinct-proposal CLI prepare probe | Exit 0; both drafts retained, second approval refused with successor_owned |
| `git diff --check` | Exit 0; no tracked source/test/ADR modifications |

Focused selection after `-m pytest`:

```text
tests/integration/test_data_revision_foundation.py
tests/integration/test_data_revision_execution.py
tests/integration/test_revision_operator_qa.py
tests/integration/test_runtime_operator_cli.py
tests/integration/test_operational_deliverable_qa.py
tests/integration/test_budget_control.py
tests/integration/test_budget_control_persistence.py
tests/integration/test_submission_cancellation.py
tests/integration/test_eligibility_review_persistence.py
tests/integration/test_eligibility_operator.py
tests/unit/test_architecture.py
```

Full suite also covers first-run foundations/execution, all other approval/payment
invariants and remaining regressions. No live-provider verification follows from
saved fixture contracts. No unexecuted command is counted as passed.

## 8. Closure exclusions and operator decision

| Dependency | Remaining requirement |
| --- | --- |
| F03 | Verified permitted submission/receipt/outcome and independent payment contracts/adapters; separate human consent and genuine settlement evidence |
| F06 | Shared durable cloud claims/raw evidence and deployment/test-environment validation; local SQLite does not enable paid Lambda workloads |
| F07 | Authenticate/refresh broader source/account/profile facts and verify live source compatibility; trusted local assertions remain explicit |
| F08 | Evidence-driven unknown-cost/effect reconciliation, stale allocation supersession where approved, coordinated backup/restore and operational drill |
| F02-C | Separately approved Research tools, semantic/paid capabilities and explicit provider composition |
| F02-B4-2 | Real approved paid capability before durable WAITING_FOR_BUDGET/resume; no inference from zero-AI SCOUT_ONLY continuity |

Local deterministic rework supports unchanged Task/source terms, retained real local
parents, additive/non-relaxing criteria, explicit input consent and exact version QA.
Legacy/incomplete parents, new MANUAL eligibility in IN_PROGRESS, human-QA resolution,
criteria weakening, changed bounty terms, supersession/cancellation of allocations,
Research/semantic Data/paid AI, automatic submission, settlement and AWS remain
excluded. Approved allocations that become stale can remain inspectable but blocked.
Export remains local; old incompatible manifests require a fresh destination.

Recommendation: **CLOSE_WITH_EXPLICIT_EXCLUSIONS** for deterministic local F05 only,
subject to operator review. The LOW status-display
finding is a focused follow-up, not an authorization bypass. Keep the listed gates
open. No production readiness, live compatibility or verified earning claim is made.
No operator action/credentials were needed for offline evidence. A genuine later
walkthrough needs an authorized source, legitimate opportunity and truthful approved
inputs. No commit or push. Stop here for operator review.

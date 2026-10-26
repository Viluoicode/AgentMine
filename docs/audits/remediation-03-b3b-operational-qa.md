# F02-B3-B: Operational deliverable QA integration

Date: 2026-10-26 (Asia/Bangkok). Scope: local deterministic Data QA through existing
operator review. Verdict: **PASS_WITH_LIMITATIONS**; verification evidence is below.
No commit or push. F02-B4 is not started; F02 overall is not declared closed.

## Implementation summary

The new explicit `work qa` command loads a retained first-version execution and
delegates to existing DeliverableQA, SQLiteQAJournal and Domain transitions.
Application constructs QAInspection from authoritative evidence: frozen DataPlan,
DataResult, Execution, exact deliverable/content bytes and operator-approved
acceptance criteria. No caller supplies a QA outcome, replacement result or URL.

Acceptance criteria are now optional immutable specification fields, parsed during
`work prepare` and covered by its existing actor/time/input approval. The field is
optional for old snapshot compatibility, **not** for operational QA authorization.
Old runs without approved criteria remain blocked; there is no inferred checklist,
retrospective weakening, fabricated provenance or automatic re-execution.

All operational components share the existing local SQLite workspace and selected
ledger. The QA validator has neither LLM nor paid budget configured. The existing
QA engine's deterministic/domain stages are unchanged; semantic requirements can
only remain explicitly human-review pending when the evaluator is unavailable.
No model, tool, filesystem or arbitrary URL access is added to QA.

## Architectural decisions and changed files

[ADR 0026](../adr/0026-operational-qa-completion.md) records the genuinely new
inspection-ownership/conditional-completion boundary. It extends ADR 0012 and the
approved runtime plan rather than introducing another engine or approval system.

| Files | Change |
| --- | --- |
| `application/contracts/qa.py` | Immutable DataAcceptanceCriteria; shared extraction of the exact existing lifecycle-result mapping |
| `application/contracts/operational_qa.py` | Original-revision binding, completion and status records |
| `application/contracts/runtime.py`, `local_runtime.py` | Carry approved acceptance in specification/preparation |
| `application/contracts/worker_execution.py`, `application/use_cases/worker_execution.py` | Explicit REWORK_REQUIRED block for a completed first-run execution now in IN_PROGRESS after QA/revision |
| `application/ports/operational_qa.py` | Narrow atomic claim/completion and inspection-read requirements |
| `application/use_cases/operational_qa.py` | Authoritative inspection preparation, preflight, retained-report recovery/readback and status reads |
| `application/use_cases/deliverable_qa.py` | Optional conditional operational application path; original checks and legacy call behavior retained |
| `application/use_cases/local_runtime.py` | Persist acceptance when preparing the immutable specification |
| `infrastructure/sqlite/operational_qa.py` | Version ownership, original-revision checks and atomic QAResult/Opportunity/marker writes |
| `infrastructure/snapshots.py` | Explicit contract allowlist; narrow optional legacy defaults without fabricated criteria |
| `bootstrap/local_runtime.py`, `bootstrap/operator.py` | Shared-file dependencies, operator identity and permitted explicit live refresh for QA |
| `presentation/runtime_inputs.py`, `presentation/runtime_cli.py` | Parse/display criteria, work qa command and QA evidence/actions in work status; no lifecycle mutation |
| `tests/integration/test_operational_deliverable_qa.py` | New acceptance, corruption, crash, revision, approval and concurrency tests |
| `docs/adr/0026-operational-qa-completion.md`, `docs/adr/README.md`, `docs/operator-interface.md` | Decision/index/current operator guide |
| This report | Commands, evidence, recovery limits and disposition |

Production paths in the table are relative to `src/agentmine/`. Domain, DataWorker,
BudgetManager, QA algorithms, marketplace contracts and existing test files were
not changed. No dependency, service, database schema migration, mock fallback,
second approval workflow or orchestration framework was introduced.

## Authoritative checks and transitions

For a new inspection the application requires:

- Correct local approving actor/ledger, a completed deterministic WorkerRun and
  canonical retained DataResult, with no ambiguous AI evidence.
- Exact plan/execution/task/deliverable identity and stored version-1 deliverable.
- Actual stored content whose SHA-256 and bundle agree with the retained result.
  Missing/corrupt identity or bytes block before producing a QA report.
- Frozen acceptance formats/requirements from the approved specification, never
  newly supplied at `work qa` or derived from a successful output.
- Existing B2 source/eligibility/economic preflight and unchanged Opportunity
  snapshot through claim. A disabled/unavailable/changed source cannot be treated
  as fresh. Sources remain adapters, not Domain dependencies.

| QA outcome | Existing Domain behavior | Required action |
| --- | --- | --- |
| PASS | QA_PENDING → READY_FOR_HUMAN_REVIEW | Existing operator review/approval; no automatic submission |
| FAIL | QA_PENDING → IN_PROGRESS, clears current deliverable/approval | F05_REWORK_REQUIRED; first-run execute/recover cannot produce v2 |
| NEEDS_REVISION | Same existing FAILED lifecycle assessment → IN_PROGRESS | F05_REWORK_REQUIRED; retained artifacts/reasons remain inspectable |
| REQUIRES_HUMAN_REVIEW | Remains QA_PENDING; no resolved lifecycle QAResult | HUMAN_QA_ACTION_REQUIRED; no forced PASS or submission review bypass |

Data source warnings/provenance are retained. PASS verifies declared formats,
requirements and reproducibility against retained inputs; it does not authenticate
all outside assertions, guarantee bounty acceptance or establish verified revenue.
Eligibility, input approval, spending consent and external-submission approval stay
separate. QA writes no Budget authorization/cost record and creates zero revenue.

`work status` now includes inspection ID, applied marker, report outcome/time,
findings and evidence/content references, plus required action. A retained but
unapplied report is shown as requiring retry with the original inspection ID.
Completed execution history, current Opportunity state and QA outcome are distinct.

## Persistence, crash and concurrent behavior

The existing snapshot schema is reused. New kinds are `operational_qa_owner`,
`operational_qa_binding`, `operational_qa_applied`; existing `qa_inspection`,
`qa_report`, `qa` and `opportunity` kinds remain canonical.

Claim uses one BEGIN IMMEDIATE transaction to bind a single inspection to a
deliverable/version, original Opportunity snapshot/revision, actor and requested
time. It also retains the exact QAInspection. Same identity is immutable readback;
changed identity and competing version owners conflict. Unbound legacy inspection,
report/QA evidence is not silently adopted into this operational authority.

DeliverableQA computes/saves its real report before completion, as before. The
operational adapter then requires that exact report/inspection/binding and the
original Opportunity snapshot; it atomically saves the existing QAResult, applies
the Domain transition and records the applied marker. Human-review reports only
record the marker while keeping QA_PENDING. No transaction spans source HTTP or
QA computation.

| Interruption/race | Safe behavior |
| --- | --- |
| Claim exists, report absent | Preserve claim; explicitly retry same deterministic inspection after preflight; never invent a successful result |
| Report saved, acknowledgement/application fails | Original report survives; same-ID retry applies it without recomputing, paid call or new inspection |
| Failure after QAResult/Opportunity/marker write | Whole completion transaction rolls back; report remains available for same-ID recovery |
| Stale Opportunity revision before application | Preserve report/binding, reject transition; do not automatically rebase original evidence |
| Applied inspection retried after approval/revision | Read original report/marker, never rewrite later lifecycle or duplicate cost |
| Concurrent same ID | Immutable evidence/application wins; a competing read may conflict and retry same ID |
| Concurrent different IDs for same version | One version owner; loser cannot create a replacement report or overwrite the decision |
| Missing/corrupt evidence | Fail closed; no fabricated report or forced PASS |

The exact legacy JSON mapping of QA reports to QAResult is shared, not duplicated.
Legacy direct DeliverableQA callers retain their existing path unless a binding
and operational repository are configured. This checkpoint implements the shared
local operational boundary, not an unrequested cloud QA deployment.

## Operator commands

Add acceptance to the **approved input manifest before first execution**. Example
schema only: choose requirements that actually cover the bounty, not merely those
the current output happens to satisfy.

```json
{
  "acceptance": {
    "formats": [
      {"name": "data.csv", "format": "text/csv"},
      {"name": "data.json", "format": "application/json"}
    ],
    "requirements": [
      {"id": "required-name", "artifact": "data.csv", "kind": "column", "criterion": "name"}
    ]
  }
}
```

This is an addition to the existing sources/columns/constraints manifest; it is not
a complete input file. It is frozen by `work prepare --approve-inputs` and visible
in `work show`. Formats/requirements are nonempty, bounded, unique typed values;
extra fields or supplied QA outcomes are rejected. Accepted requirement kinds are
the existing column/section/literal/semantic values. A semantic requirement does
not enable AI: with no reviewer it remains human-review pending. No provenance is
relabelled verified to satisfy criteria.

With actual actor/key/input prerequisites already configured as described in
[the B3-A guide](remediation-03-b3a-operator-cli.md#commands-and-inputs):

```powershell
$python = ".\.venv\Scripts\python.exe"
$base = @("-m", "agentmine.bootstrap.operator", "--db", ".tmp/agentmine.sqlite3", "--ledger", "local")
$live = @("--live-superteam-refresh", "--archive", ".tmp/agentmine.sqlite3.raw.sqlite3")
# Set AGENTMINE_OPERATOR_ID and the authorized read key securely beforehand.
& $python @base @live work qa --execution-id exec-001 --inspection-id qa-001 --confirm
& $python @base work status --execution-id exec-001
```

Use the real existing execution ID. New inspections require authoritative refresh.
If the report was already retained, retry the same command/inspection ID; report
completion/readback can run without @live because it does not recompute QA or grant
fresh external permission. No arbitrary file/URL is read by `work qa`.

After PASS only, reuse the existing commands:

```powershell
& $python @base review --opportunity YOUR_OPPORTUNITY_ID --review-id review-001 --destination YOUR_SUPPORTED_DESTINATION
& $python @base show-review --review-id review-001
& $python @base @live decide --review-id review-001 --decision APPROVE --reason "Reviewed exact deliverable, QA evidence and risks"
```

Replace uppercase ID/destination examples with actual values; they are not
PowerShell angle-bracket placeholders. Review/decide support APPROVE, REJECT and
REQUEST_REVISION as before. Approval is retained scoped consent, never a send.
REQUEST_REVISION requires the separate F05 workflow; it does not rerun the worker.
FAIL/human-review results cannot be submitted merely by requesting approval.

## Test-first evidence and verification

Before production changes, the new suite failed **12 cases**: acceptance was not
recognized by preparation and `work qa` did not exist. This is missing-capability
acceptance evidence, not a claim that old transactional bugs were reproduced by
those individual assertions.

The final new suite uses real SQLite, DataWorker, DeliverableQA, runtime composition
and existing review/decide commands. Source/clock fakes are explicitly injected by
test composition only. Fault injection includes disk/acknowledgement errors and
test-only database corruption; no QAReport is fabricated to select an outcome.
The coherent-corruption FAIL case first executes the real worker, then alters
stored values/bundle consistently so the real QA domain checks detect unsupported
changes against original input. No real marketplace, LLM, submission or payment.

Coverage includes PASS, FAIL, validation/revision, semantic-human pending; missing/
corrupt result/content and mismatched execution; immutable criteria; stale revision;
same/conflicting inspection IDs; report-before-completion crash; rollback at every
completion write; reopen recovery; retries after approval; aligned concurrent QA;
cost preservation, separate operator approval and zero verified revenue/submission.

Commands use `.\.venv\Scripts\python.exe` and run entirely offline:

| Check | Result |
| --- | --- |
| Initial acceptance tests before production changes | 12 failed, as expected: missing capability |
| `-m pytest tests/integration/test_operational_deliverable_qa.py -q --tb=short -p no:cacheprovider` | 25 passed in 25.36s |
| QA/runtime/CLI/foundation/operator approval/legacy QA/architecture regression group | 204 passed in 44.98s |
| `-m pytest -q -ra --tb=short -p no:cacheprovider` | 1171 passed in 99.62s |
| `-m ruff check .` | Passed |
| `-m ruff format --check .` | 283 files already formatted |
| `-m mypy` (project strict configuration) | Passed, 214 source files |
| `git diff --check` | Passed; Git emitted only existing LF/CRLF conversion notices |
| Operator `work qa --help` | Passed; no workspace created |

The 204-test regression command selected
`tests/integration/test_operational_deliverable_qa.py`,
`tests/integration/test_runtime_operator_cli.py`,
`tests/integration/test_worker_execution_runtime.py`,
`tests/integration/test_runtime_foundation.py`,
`tests/integration/test_operator_interface.py`,
`tests/integration/test_operator_approval_sqlite.py`,
`tests/unit/application/test_deliverable_qa.py` and `tests/unit/test_architecture.py`,
with `-q --tb=short -p no:cacheprovider`.

## Remaining limitations and verdict

**PASS_WITH_LIMITATIONS** for this local QA checkpoint. This is not a
production-readiness or whole-F02 claim.

- Old specifications without acceptance criteria remain readable but blocked for
  operational QA. They are not retroactively approved or re-executed automatically.
- Human-review-required criteria remain pending. A human QA resolution mechanism
  is not fabricated using submission approval; no force-PASS command is provided.
- Stale bound revisions require deliberate operator investigation/reconciliation;
  this checkpoint does not add a generic rebase/release/recovery framework.
- Source/profile/economic assertions remain trusted inputs; source changes after
  refresh cannot be locked. Completion of already-retained QA evidence is not
  renewed marketplace permission. Existing approval checks still apply.
- Local host/store writers are trusted; checksums are integrity checks, not an
  authentication mechanism. No cloud adapter/deployment or general backup/billing
  remediation is included.
- No paid AI, automatic submission, payment verification, wallet action, F05 revision
  execution or F02-B4 budget resume/policy workflow was added.

Offline tests require no operator credentials or action. A real walkthrough needs
truthful preapproved criteria and an authorized source refresh, then an explicit
operator review decision after PASS. Stop for operator review; do not start F02-B4.

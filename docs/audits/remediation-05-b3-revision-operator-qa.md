# F05-B3: Operator revision CLI and version-aware QA

Date: 2026-10-28 (Asia/Bangkok). Base commit:
`03ba4d8706f7566e3ebddfc8adcf31f5b8f9b1ce`.

## Scope and composition

Makes the existing deterministic Data rework Application workflow available through
the local operator CLI. Read AGENTS.md, Product Constitution, F05-A, B1/B2 reports,
ADR 0028, F02-B5 and current composition/runtime/QA/review/export code. The worktree
was clean before this checkpoint. No commit or push; F05-B4 is not started.

The composition root wires PrepareDataRevision, GetDataRevision,
ApproveDataRevision, ExecuteDataRevision and RecoverDataRevision to real SQLite
repositories/journals and the same BudgetManager, operator, ledger, source and clock
as first-version execution. DataWorker still executes with llm=None. DeliverableQA
still has no paid provider or QA budget. No worker/QA algorithm or Domain lifecycle
rule was changed.

Production source defaults to DisabledOpportunitySource. Existing explicit
`--live-superteam-refresh` opt-in and environment credential configuration are
required for fresh real source checks. Prepare/approve/execute/recover support that
opt-in; show/history reads do not need a source. No FakeSource, MockLLM or production
fallback was introduced. No external send/payment service is composed.

## Changed files

| File | Purpose |
| --- | --- |
| `application/use_cases/data_history.py` (new) | Read-only v1/revision history and actor/ledger-bound parent/revision lookups |
| `application/contracts/runtime.py` | Derived completed deliverable and expected active QA/revision metadata; v1 defaults unchanged |
| `application/ports/runtime.py` | Read-only WorkerRunReader contract; existing write port retains its first-run operations |
| `application/ports/data_revision.py` | Immutable execution/specification lookup for revision history |
| `application/ports/local_runtime.py` | Optional exact deliverable metadata for local artifact export |
| `application/use_cases/local_runtime.py` | Shared read-only status/specification/export; export requires a completed bound deliverable |
| `application/use_cases/operational_qa.py` | Resolve exact persisted deliverable version, reuse existing inspection and conditional completion |
| `bootstrap/local_runtime.py` | Shared authoritative local composition and revision services |
| `bootstrap/operator.py` | Trusted mutation actor, selected input root and explicit live-source handling for revision actions |
| `infrastructure/sqlite/runtime.py` | Return existing completion marker as read metadata |
| `infrastructure/sqlite/data_revision.py` | Read-only revision execution/specification lookup; write ownership/transactions unchanged |
| `infrastructure/local_artifact_export.py` | Bind manifest to exact execution, lineage, version and content digest; retain no-clobber publication |
| `presentation/revision_cli.py` (new) | Explicit revision parser, Application invocation and review views |
| `presentation/runtime_views.py` (new) | Existing escaped encode/specification views shared without circular imports |
| `presentation/runtime_cli.py` | Revision command routing, historical/current status and version-aware QA display |
| `presentation/runtime_inputs.py` | Existing bounded/duplicate-safe JSON parser also rejects non-JSON numeric constants |
| `tests/integration/test_revision_operator_qa.py` (new) | Offline real CLI/SQLite/DataWorker/DeliverableQA acceptance |
| This report (new) | Commands, evidence and limitations |

Paths above are relative to `src/agentmine/` except tests and this report. No
dependency was added or installed. Application/Domain import no concrete
infrastructure. No new ADR is needed: read projections, composition and export
metadata implement the already approved B3 design without changing consent,
ownership, transaction boundaries or lifecycle policy.

## CLI workflow

New commands:

```text
work revision prepare
work revision show
work revision approve
work revision execute
work revision recover
```

Preparation uses the existing strict bounded Data/facts/economics/scoring JSON
contracts. Each runtime JSON file is limited to 64,000 bytes; duplicate/unknown
fields, non-JSON numeric constants and unsupported scope are rejected. Inputs
remain approved-root CSV/JSON snapshots with expected SHA-256. No JSON field or
CLI flag selects a version, QA outcome, Budget snapshot, authorization or state.

Prepare/show display parent execution/deliverable/QA/trigger, reason, frozen input
digests/provenance, non-relaxing scope/criteria changes, bounds/constraints/formats,
subjective forecast components and estimated incremental costs. Preparation does
not grant consent or dispatch. Approval requires both --approve-inputs and
--confirm; it binds the exact retained B2 request. Execute/recover accept the
revision ID and --confirm, using only its original allocation IDs.

Example for an existing legitimate local workspace and completed parent (uppercase
IDs are placeholders to replace, not PowerShell angle-bracket syntax):

```powershell
$python = '.\.venv\Scripts\python.exe'
$env:AGENTMINE_OPERATOR_ID = 'local-operator'
$base = @('-m', 'agentmine.bootstrap.operator', '--db', '.tmp/agentmine.sqlite3', '--ledger', 'local')
$live = @('--live-superteam-refresh', '--archive', '.tmp/agentmine-raw.sqlite3')

& $python @base @live work revision prepare --revision-id revision-002 --parent-execution PARENT_EXECUTION --trigger qa --trigger-id PARENT_INSPECTION --spec-id data-spec-002 --evaluation evaluation-002 --inputs .tmp/data-v2.json --input-root .tmp/approved-inputs --facts .tmp/facts.json --minimum-time-seconds 3600 --economics .tmp/economics-v2.json --scoring .tmp/scoring-v2.json --forecast-evidence operator:forecast-v2 --reason "Repair the reviewed data requirements"
& $python @base work revision show --revision-id revision-002
# After reviewing exact retained input digests, scope and criteria:
& $python @base @live work revision approve --revision-id revision-002 --execution-id execution-002 --operation-id operation-002 --approve-inputs --confirm
& $python @base @live work revision execute --revision-id revision-002 --confirm
& $python @base work status --execution-id execution-002
& $python @base @live work qa --execution-id execution-002 --inspection-id inspection-002 --confirm
& $python @base work export --execution-id execution-002 --directory .tmp/export-v2
# Only after QA PASS, separate submission-scope review:
& $python @base review --opportunity OPPORTUNITY_ID --review-id review-002 --destination SUPPORTED_DESTINATION
& $python @base show-review --review-id review-002
```

Use `--trigger operator --trigger-id REVIEW_ID` for an applied REQUEST_REVISION.
The source must actually be configured/authorized; the example does not supply or
validate a credential. Never put a credential in a task manifest or paste it into
chat. Do not use fixture IDs/data to populate a production workspace.

After an uncertain acknowledgement, inspect/recover the same revision:

```powershell
& $python @base work revision show --revision-id revision-002
& $python @base @live work revision recover --revision-id revision-002 --confirm
```

There is no automatic next-version creation, supersession or claim release. New
spending, budget-policy consent, eligibility resolution and submission approval
remain separate permissions. `decide` remains an explicit separate action; even
submission approval does not send anything through this CLI.

## Version-aware QA, status and export

Read-only LocalDataHistory resolves existing first-run history or a revision's
immutable allocation/run. It cannot start work and does not replace first-run
ownership. Ambiguous specification/execution namespaces fail closed. QA obtains
the completed deliverable from the persisted finish marker/allocation, then checks
the exact versioned ExecutionRepository record, plan, result, content digest,
criteria and Opportunity snapshot. No caller-selected version is accepted.

The existing DeliverableQA/SQLiteQAJournal/conditional completion path is reused:

- PASS → READY_FOR_HUMAN_REVIEW; no automatic consent or submission.
- FAIL/NEEDS_REVISION → IN_PROGRESS and an explicitly prepared/approved next revision.
- REQUIRES_HUMAN_REVIEW → QA_PENDING; no force-PASS or automatic rework.
- Each version owns a distinct inspection. Old/conflicting IDs cannot inspect new
  content, even if artifact hashes are identical.
- Applied historical report readback performs no later-state mutation. Unapplied
  stale reports conflict rather than being rebased.

Existing review/show-review/decide bind the full current Deliverable, including
execution and version. A new version needs a new review ID; identical content
digests cannot transfer old QA or approval. No approval algorithm was weakened.

Status separates requested execution history from current execution/deliverable,
and labels historical QA/action explicitly. Revision consent/allocation is shown
through Application reads. RuntimeStatus's default active QA remains None for v1;
revision projections supply the exact retained parent QA and expected start
revision. This fixes a v1-only status assumption without changing dispatch guards.
Missing result, pending finish and changed active revision therefore display as
distinct recovery states.

Local export binds manifest `deliverable.lineage`, `deliverable.version`, execution
and content digest to the completed stored version. Historical export is read-only.
No-clobber hard-link publication and manifest-last recovery remain unchanged.
Different versions cannot reuse an export directory's manifest, even for identical
artifact bytes. Identical exports of the same version are idempotent. Choose a new
directory if an older binary's manifest lacks the new identity metadata; no upgrade
rewrite, deletion or overwrite is attempted. Unfinished results without a completed
deliverable are not exported as a versioned deliverable.

## Transaction, recovery and evidence boundaries

B1/B2 allocation, authorization, start, result, cost settlement and finish remain
the write authorities. All services share the configured SQLite workspace and
ledger. No transaction holds a lock over source I/O, worker processing or export.
Same-ID recovery reuses allocation, execution, operation, deliverable/version and
cost evidence; no new version or duplicate actual cost is inferred from retries.
QA retains its original claim/report/conditional completion crash boundaries.

Tests use the real operator parser/run_cli, production composition, SQLite,
DataWorker, DeliverableQA and review/decision commands. FakeSource/FakeClock are
explicitly injected only by test composition. Entrypoint tests separately verify
trusted actor/ledger errors, default-disabled source and missing live credentials.
They do not establish a live API contract or genuine eligible bounty.

QA FAIL fixtures deliberately corrupt retained result/artifact evidence coherently
after real worker execution, then invoke the real QA engine. This exercises actual
unsupported-value detection; no QA outcome is fabricated as a command input. V2
FAIL → v3 PASS follows the real revision CLI. The NEEDS_REVISION case repairs a
missing required output column by explicitly approving an added deterministic
column; it does not weaken acceptance criteria or change QA algorithms.

No production workspace was seeded, no live marketplace was contacted, no paid
provider was configured, and no external submission/payment or fabricated verified
revenue was created. Potential/expected values remain forecasts.

## Test-first and executed verification

Before production changes, the initial five acceptance cases failed in 8.83s with
the missing `work revision` argparse command. Later cases cover v3, consent,
freshness, recovery, history and strict input. An interim run had 17 passes and one
incorrect test expectation that a wrong ledger must exit 2; the existing entrypoint
correctly exited 1 with a structured missing-ledger error. The test now checks safe
nonzero failure. Production behavior was not weakened.

A separate status regression was reproduced before its fix: retained-result v2
status incorrectly reported STATE_CHANGED because parent QA was non-None. The
targeted test failed, then read metadata was corrected. A further test verifies
stale active Opportunity revisions remain BLOCKED. First-run start/finish guards,
Domain transitions and B2 exact-snapshot dispatch checks are unchanged.

| Check | Executed result |
| --- | --- |
| Final focused CLI/QA suite after status projection correction | 23 passed in 82.51s |
| v1 CLI/QA, B1/B2, review, budget and architecture selection below | 200 passed in 134.46s |
| Interim full suite before final status projection correction | 1309 passed in 216.34s |
| Final full suite, `python -m pytest -q -ra --tb=short -p no:cacheprovider` | 1310 passed in 241.32s |
| `python -m pytest tests/unit/test_architecture.py -q --tb=short -p no:cacheprovider` | 29 passed in 1.51s |
| `python -m ruff check .` | All checks passed |
| `python -m ruff format --check .` | 312 files already formatted |
| `python -m mypy` with strict project configuration | Success, 234 source/test files |
| Real module CLI `work revision --help`, `work revision approve --help`, `work qa --help` | Exit 0; help requires no source/workspace creation |

Commands use `.\.venv\Scripts\python.exe`. Focused command:
`-m pytest tests/integration/test_revision_operator_qa.py -q --tb=short -p no:cacheprovider`.
The 200-test selection used `tests/integration/test_runtime_operator_cli.py`,
`test_operational_deliverable_qa.py`, `test_data_revision_foundation.py`,
`test_data_revision_execution.py`, `test_operator_approval_sqlite.py`,
`test_budget_control.py`, `test_budget_control_persistence.py` (under
`tests/integration/`) and `tests/unit/test_architecture.py` with the same pytest flags.
The full suite also includes F01/F04 and all other existing regressions.

Final report whitespace and code-fence checks passed. `git diff --check` exited 0;
Git emitted only working-copy LF/CRLF notices. The working tree contains the
listed F05-B3 files and no commit was created.

## Remaining limitations and verdict

- Local deterministic first-version/revision Data only. No Research, semantic Data,
  paid AI, Bedrock, paid resume, AWS, external settlement or workflow framework.
- MANUAL/human eligibility and human-QA resolution remain blocked as documented in
  B2. No generic supersession, stale-claim rebase/release or F08 reconciliation.
- Source terms must remain unchanged; facts/profile/provenance assertions and
  subjective forecasts are not independently authenticated (F07). Remote terms
  cannot be locked while work runs. Production source compatibility was not tested.
- Local host/store/DI remain trusted; snapshots/hashes are consistency evidence,
  not a sandbox against an authorized writer. Filesystem export requires supported
  local no-clobber hard links. Full unmeasured operating costs remain UNKNOWN.
- Readable history, QA PASS and operator approval do not establish submission,
  acceptance, payment, production readiness or verified earnings.

**PASS_WITH_LIMITATIONS** for the offline local deterministic Data revision and
version-aware QA scope, based on the executed tests above. This is not a live
provider, production, or earnings readiness verdict. No commit or push. Do not
start F05-B4; stop for operator review after this B3 report.

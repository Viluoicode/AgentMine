# F03-B2: Atomic Manual Submission Handoff and Receipt Recovery

Date: 2026-11-01 (Asia/Bangkok)
Base commit: `543d54403fae8982bd22d4e3f00efb58d3e6cdbf`
Scope: uncommitted F03-B2 changes only. No commit or push.
Verdict: **PASS_WITH_LIMITATIONS ? F03-B2 offline scope only**.

## Scope and existing behavior

B1 retained an exact immutable SubmissionEnvelope, account/channel/outbound scope,
separate operator review and provisional evidence. Applied consent required both
saved decision and the exact approved Opportunity revision. B1 deliberately blocked
its reserved scope from legacy SubmitTask/manual receipt action paths. F01 already
provided an API-only atomic dispatch claim. None of these granted a manual handoff.

B2 adds only offline durable operator intent and provisional receipt coordination.
No production adapter can authorize an actual marketplace action. Default permission
is UNVERIFIED; explicit OFFLINE_TEST_ONLY test fixtures exercise the design. All
CLI views disclaim external authorization, verified send and payment. No production
workspace was populated with synthetic opportunities or payment data.

## Changes and architecture

New files:

- `src/agentmine/application/contracts/manual_handoff.py`: immutable permission,
  draft, claim, receipt, view and typed recovery/error contracts.
- `src/agentmine/application/ports/manual_handoff.py`: scoped permission inspection
  and narrow transactional handoff repository port.
- `src/agentmine/application/use_cases/manual_handoff.py`: readiness, prepare,
  confirm, readback and provisional receipt coordination.
- `src/agentmine/infrastructure/manual_permission.py`: default-denied permission.
- `src/agentmine/infrastructure/sqlite/manual_handoff.py`: atomic ownership and
  conditional receipt completion with BEGIN IMMEDIATE and CAS.
- `src/agentmine/presentation/manual_handoff_cli.py`: bounded strict JSON commands.
- `src/agentmine/bootstrap/manual_handoff.py`: shared SQLite/runtime composition.
- `tests/integration/test_manual_handoff.py`: explicit test-only source, clock and
  permission fixtures; real CLI, worker, QA, approval, Domain and file-backed SQLite.
- `docs/adr/0030-atomic-manual-submission-handoff.md`: transaction/identity decision.
- This report.

Updated files:

- `bootstrap/operator.py`: real composition and trusted actor gate for mutations.
- `presentation/submission_context_cli.py`: nested handoff commands; existing B1
  commands and optional service compatibility preserved.
- `infrastructure/snapshots.py`: allowlisted typed snapshot contracts.
- `docs/adr/README.md`: ADR index.

Paths above are relative to the repository; the first three updated source paths
are under `src/agentmine/`. No dependencies, schema migration, Domain rules, API
dispatch guards, existing legacy B1 guards, AWS or provider implementation changed.
Presentation invokes Application; infrastructure implements inner ports. Existing
WorkerPreflight performs source/eligibility/economics validation. The SQLite adapter
rechecks retained context and exact approved revision within the ownership transaction.

## Consent and preflight

Preparation and first confirmation require the exact applied B1 approval, original
Task/execution/lineage/deliverable/QA PASS/content, actor, sole authoritative ledger,
manual mode and immutable account/channel/outbound scope. Unknown/known mutations
are unsupported. The offline permission must match the full scope and be observed
within the current check. The default permission fails before source refresh.

With an explicit offline fixture, existing source refresh checks open status,
deadline, unchanged terms and requirements and deterministic eligibility. Unknown,
ineligible, expired or changed contexts fail closed. The existing narrow F04 manual
resolution is reusable only with its original matching evidence; there is no new
manual eligibility override. Applied consent is checked again after preflight;
the transaction independently compares the exact approved snapshot and ledger revision.

## Transactions, recovery and financial safety

See ADR 0030 for the write-by-write matrix. Draft preparation does not move lifecycle.
Confirmation atomically retains original submission intent, immutable external
provider/account/listing owner and manual claim, then invokes Domain.begin_submission
through CAS. Existing unowned legacy requests cannot be adopted. There is no lease,
claim release, renewal, replacement ID, send or automatic reconciliation.

A claim winning first makes cancellation/rework invalid; cancellation or another
revision winning first prevents a claim. Same-ID confirmation after commit is
historical readback, even after the deadline or loss of source availability. It
never renews permission or implies a human action occurred.

B1 evidence/capture persists before receipt attachment and conditional lifecycle
completion. Receipt metadata is fixed to OPERATOR_REPORTED / UNVERIFIED, original
account/provider/envelope/submission/actor and bounded capture digest. Reported time
must be at/after original confirmation and no later than observed time; B1 checks
observation/capture chronology. Invalid completion leaves provisional evidence for
inspection, without authoritative state. Conflicting receipt content/identity
cannot replace the attached receipt. A conflicting unattached B1 report may remain
as provisional evidence; it does not authorize completion.

Completion atomically persists the legacy manual receipt attempt, Submission,
SUBMITTED CAS and completion marker. A crash rolls all completion writes back while
retaining the receipt. Lost acknowledgement returns the original receipt. Changed
Opportunity revision blocks completion and retains evidence. Historical receipt
recording after deadline does not refresh source or authorize another send. Ledger
policy changes after a claim do not invalidate historical evidence recording.

No code path here calls SubmissionGateway, PaymentVerifier or a paid provider. Budget
snapshots, costs, commitments and released operation identities are untouched.
SUBMITTED and the legacy CONFIRMED receipt label are operator-reported facts only:
no authoritative Outcome, ACCEPTED, PAID or verified revenue is manufactured.

## Operator workflow

Safe module-entrypoint discovery executed:

```powershell
.\.venv\Scripts\python.exe -m agentmine.bootstrap.operator submission handoff --help
```

Observed subcommands: `readiness`, `prepare`, `confirm`, `show`, `receipt-record`,
`receipt-show`. Common prefix (use an existing authoritative workspace):

```powershell
$env:AGENTMINE_OPERATOR_ID = "local-operator"
.\.venv\Scripts\python.exe -m agentmine.bootstrap.operator --db .tmp/agentmine.sqlite3 --ledger local submission handoff readiness --context-id context-1 --review-id review-1
```

This example is syntax, not a successful live run. Production defaults return a
blocked readiness; there is no CLI flag that enables offline fixture permission.
For isolated tests with injected permission only, the sequence is:

```text
prepare --context-id context-1 --review-id review-1 --handoff-id handoff-1 --submission-id submission-1
show --handoff-id handoff-1
confirm --handoff-id handoff-1 --confirm
show --handoff-id handoff-1
receipt-record --handoff-id handoff-1 --evidence-id receipt-1 --inputs receipt.json
receipt-show --handoff-id handoff-1
```

Receipt JSON allows only `reported_at`, `observed_at`, `provenance`, `text`, optional
`external_id` and HTTPS `external_url`. It cannot select actor, trust, account,
version, acceptance or payment. URLs are validated data and never fetched. Input
uses existing 64,000-byte strict JSON parsing; duplicate/unknown fields fail closed.

## Bounded backup/restore and no-resend procedure

1. Stop all operator processes touching the workspace. Preserve its exact path,
   ledger, operator identity and original handoff/submission/evidence IDs. Do not
   send or create replacement IDs while investigating.
2. Make a consistent SQLite backup with Python's standard `sqlite3.Connection.backup`
   to a new destination. Do not copy a live database file alone or discard WAL/journal
   files. Retained typed snapshots, evidence captures and content are in this database.
   Preserve any separately maintained approved inputs/raw archives alongside it.
3. Keep the original unchanged. Verify the backup using `PRAGMA integrity_check`,
   open an isolated copy and inspect the original handoff ID. Verify exact claim,
   evidence and lifecycle history before treating it as a usable recovery artifact.
4. Never run two restored copies as authorities. A backup older than a possible
   human action does not prove that action never happened. Treat uncertainty as
   sticky: inspect only, never confirm a new identity or send again.
5. If current authoritative state is available, reopen it and use original-ID show
   and identical receipt recording. Receipt completion may recover local writes
   only; it cannot prove or repeat a marketplace operation.
6. If ownership/evidence is missing, contradictory or unrecoverable, stop and retain
   all copies. Generic reconciliation and manual release are excluded from B2.

An isolated test uses SQLite backup and verifies that the original in-flight claim,
unknown status and zero verified revenue survive readback. This is not a complete
F08 disaster-recovery certification or protection from out-of-band human actions.

## Test-first and verification evidence

Before production changes, the initial new CLI/SQLite acceptance test failed during
collection with `ModuleNotFoundError: agentmine.application.contracts.manual_handoff`
(1 error, 1.58s). This proves the missing capability; it does not claim every later
edge case was independently red before implementation. Subsequent test development
also corrected a missing pytest import and typed helper annotations.

Initial focused run: 1 passed. Expanded focused run: 18 passed in 79.61s.
Later focused run: 30 passed in 68.49s, including transaction fault injection,
concurrency, lost acknowledgements, source changes, strict receipt CLI, immutable
owner/context and stale-state evidence retention.

Final executed verification results are recorded below.

## Limitations and exclusions

- Offline only. No independently selected/permitted real account/channel exists.
- Operator-reported receipts are not independent proof of send, outcome or reward.
- Software cannot prevent an operator acting outside AgentMine or using stale copies.
- Unknown effects remain locked indefinitely; no general reconciliation/release.
- No F03-B3 outcome/payment work, F08 framework, provider POST, browser, wallet,
  AWS, paid AI or automatic sending/retrying was implemented.
- Tests use explicit synthetic opportunity/source/permission fixtures in isolated
  temporary SQLite databases, never a production workspace or paid API.

## Executed verification (final focused/static results)

Commands used `.venv/Scripts/python.exe`:

```text
-m pytest tests/integration/test_manual_handoff.py -q --tb=short -p no:cacheprovider
-m pytest tests/integration/test_manual_handoff.py tests/unit/test_architecture.py -q --tb=short -p no:cacheprovider
-m pytest -q --tb=short -p no:cacheprovider
-m ruff check .
-m ruff format --check .
-m mypy --strict
git diff --check
```

- Final handoff + architecture run: **62 passed in 87.97s**. This includes 33
  handoff cases and 29 architecture cases; original-ID recovery uses reopened
  file-backed SQLite and the backup test reads an isolated SQLite backup.
- Ruff: **All checks passed**.
- Ruff format check: **333 files already formatted**.
- Strict mypy: **Success: no issues found in 248 source files**.
- `git diff --check`: exit 0; only Git's existing LF/CRLF conversion warnings.
- Real module `submission handoff --help`: exit 0 and the six intended subcommands.

The earlier full-suite invocation was rejected before execution because automatic
approval review had exhausted its usage quota; this was an approval-service failure,
not a safety finding. After the operator continued, the same authorized offline
verification was retried through the normal approval mechanism. No bypass was used.
The completed full-suite result is recorded below. Local logs are under
`.tmp/f03-b2-focused-final.log` and `.tmp/f03-b2-full-20261101.log` (not committed).


## Full-suite result and acceptance verdict

**Full pytest: 1397 passed in 450.10s (7m30s), exit 0.** The run includes existing
F01 cancellation, F04 eligibility, F05 revision, B1 context, runtime, QA, budget and
architecture regressions. It collected before three additional B2 acceptance cases
were added; no production code changed after that full run began. Those three cases
(cancellation during refresh, changed ledger revision and isolated backup readback)
all passed in the final 62-case focused/architecture run. A subsequent independent
collection recorded **1400 current tests**. Thus the 1397-case full run plus the
three separately executed additions cover the current test inventory; this report
does not claim a single 1400-case full invocation was executed.

| Acceptance area | Result / evidence |
| --- | --- |
| Exact applied consent/version/account/channel/mode/actor/ledger | PASS: B1 regressions and B2 immutable-context rejection cases |
| Source freshness, terms, expiry, unknown/ineligible, outage | PASS: deterministic preflight and changed-source tests |
| Unknown account effects / unverified permission | PASS: default denied before source refresh; explicit fixture only |
| Cancellation versus ownership | PASS: cancellation before/during refresh blocks; claimed Domain disallows cancellation |
| Stable IDs / duplicate and legacy intents | PASS: same-ID concurrent readback; different IDs and unowned legacy intent rejected |
| Claim rollback / lost acknowledgement | PASS: injected failure after each claim write and post-commit acknowledgement loss |
| Provisional receipt conflicts and idempotency | PASS: immutable receipt identity, concurrent retries and original evidence readback |
| Receipt-before-lifecycle recovery | PASS: retained receipt survives each completion-write rollback and stale-revision block |
| Historical receipt / lost completion acknowledgement | PASS: expired closed-source readback and same-ID completion |
| Budget preservation / no financial action | PASS: ledger revision conflict without cost mutation; zero verified revenue |
| Default production composition / CLI compatibility | PASS: unavailable real channel; existing full CLI regressions; real module help |
| Backup ownership preservation | PASS: isolated SQLite backup readback; not a general F08 recovery certification |
| Live submission, independent outcome/payment verification | EXCLUDED / NOT ENABLED |

The verdict is **PASS_WITH_LIMITATIONS** for offline durable handoff and provisional
receipt semantics. It is not production readiness, permission to submit, proof of
marketplace acceptance or verified earnings. No new dependency or Clean Architecture
deviation was introduced. F03-B3 was not started. No commit or push was performed.
Stop here for operator review.

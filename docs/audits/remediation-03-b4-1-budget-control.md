# F02-B4-1: Audited budget inspection and policy control

Completed: 2026-10-27 (Asia/Bangkok), following implementation on 2026-10-26.
Scope: the approved B4-1 subset of the
[B4-A plan](remediation-03-b4-budget-recovery-plan.md).
Verdict: **PASS_WITH_LIMITATIONS** for this local checkpoint only.

## Implementation and architecture

Added real local budget inspection and explicitly approved immutable policy/mode
changes through the existing operator CLI and authoritative SQLite workspace.
No paid wait/resume, provider, Research, submission/payment, reservation release,
ledger reset, B4-2 or B5 work. No commit or push.

The repository already supplied history-preserving Budget methods, exact money,
BudgetManager, ledger CAS/audit and deterministic Data recovery. This change adds
operator consent and the consistency boundary those controls lacked. Domain,
BudgetManager, DataWorker, worker runtime, QA algorithms and existing approval
contracts are unchanged. No dependency was introduced or installed.

See [ADR 0027](../adr/0027-audited-local-budget-control.md). Presentation parses and
renders; Application loads authority and derives policy changes with Domain methods;
SQLite implements the inner port. No database/vendor dependency enters Application.
There is no second accounting ledger or business lifecycle.

## Changed files

| File | Purpose |
| --- | --- |
| `src/agentmine/application/contracts/budget_control.py` | Typed proposal, approved decision, receipt, internal application command, inspection/view and conflict/recovery enums |
| `src/agentmine/application/ports/budget_control.py` | Focused consistent read, immutable prepare and atomic apply contract |
| `src/agentmine/application/use_cases/budget_control.py` | InspectBudgetRecovery, PrepareBudgetPolicyChange, GetBudgetPolicyChange, ApplyBudgetPolicyChange |
| `src/agentmine/infrastructure/sqlite/budget_control.py` | Same-file inspection, ledger/audit integrity checks, immutable proposal/receipt reads and four-write transaction |
| `src/agentmine/infrastructure/snapshots.py` | Explicit allowlist for new application records; existing schema/codec version retained |
| `src/agentmine/presentation/budget_cli.py` | Four budget commands, bounded strict JSON input and escaped JSON output |
| `src/agentmine/presentation/operator_cli.py` | Parser/command registration and optional BudgetServices compatibility field |
| `src/agentmine/bootstrap/operator.py` | Explicit same-workspace DI and trusted actor guard; budget commands validate sole ledger |
| `tests/integration/test_budget_control.py` | CLI, input, confirmation, modes, immutable file and real Data compatibility tests |
| `tests/integration/test_budget_control_persistence.py` | Accounting preservation, race/fault/reopen/reconciliation and non-progression tests |
| `docs/adr/0027-audited-local-budget-control.md`, `docs/adr/README.md` | Focused decision and index |
| `docs/operator-interface.md` | Operator guide link and budget boundaries |
| This report | Commands, invariants, test evidence and limitations |

The untracked B4-A design report existed at task start and was preserved. It is not
a newly implemented feature or a modified design decision in this checkpoint.

## Transaction and consent invariants

- Prepare retains original change ID, ledger, exact before/proposed policy/mode,
  actor, timestamp, reason and expected revision. No authorization or financial
  snapshot is accepted from operator JSON. Same-ID identical prepare preserves its
  original timestamp; changed fields conflict.
- Apply uses the original retained change, same trusted actor and explicit
  confirmation. Its BudgetPolicyApplication is an internal consistency command,
  not a CLI deserialization contract. Updated Budget is derived, not supplied.
- Currency and calendar timezone are frozen. Direct Application calls are checked
  as well as CLI input. Numeric limits/ratios use Domain validation. Inputs are at
  most 16,000 bytes, require the exact seven keys and bounded plain decimal strings,
  and reject duplicate keys, numeric JSON values, exponent notation and extra fields.
- Apply compares the retained change and authoritative full budget snapshot/revision.
  It atomically writes budget, existing budget audit, approved policy decision and
  receipt. Any write failure rolls back all four; preparation remains retained.
- `Budget.with_policy` and `with_requested_mode` preserve every authorization,
  actual record and released operation identity. No policy command calls authorize,
  record, release, resume, worker, QA, submission or verifier.
- Current budget/audit identity/revision/content must agree. Receipt readback also
  verifies proposal, approved decision and historical before/after audit evidence.
  Missing or corrupt authority is an error, not an empty/free budget.
- Same applied ID returns the original receipt after acknowledgement loss or later
  policy changes. It does not reapply the old policy. A competing different change
  on the same revision loses CAS; the operator must inspect and prepare a new delta.
- A financially unchanged policy confirmation records one audit revision/decision/
  receipt. A retry adds no revision. Audit revisions are not counts of charges.
- Policy consent is separate from input, eligibility, spending and submission
  approval. The actor is the existing trusted single local operator; no new role
  or approval action is added to Domain.

```mermaid
sequenceDiagram
    participant O as Operator
    participant A as Application
    participant S as SQLite authority
    O->>A: prepare ID / exact values / reason / expected revision
    A->>S: immutable proposal (ledger unchanged)
    A-->>O: before / proposed / current liabilities / projection
    O->>A: apply original ID + confirm
    A->>S: CAS + budget audit + approval decision + receipt
    S-->>A: atomic commit or typed conflict
    A-->>O: original receipt; no work/resume
```

## Inspection and recovery semantics

`budget show` displays ledger revision, requested/derived mode, policy, daily/monthly
AI actuals, outstanding AI estimate subtotal, remaining amounts, all recorded cost
rows and released IDs. Each outstanding request retains its scope and estimate;
absence of an actual is JSON null. `unmeasured_costs` is explicitly UNKNOWN. A real
deterministic result's recorded zero AI cost remains a numeric zero.

Classifications are descriptive, never permissions:

| Classification | Meaning / operator boundary |
| --- | --- |
| deterministic_run | Matching zero-cost retained runtime authorization; use existing work status/recover and their checks |
| unlinked_operation | No matching retained runtime for that unresolved operation; do not invent a run or zero cost |
| reconciliation_required | Outstanding positive estimate or retained paid/legacy evidence; no retry/release through B4-1 |
| unsupported_wait | Existing WAITING_FOR_BUDGET record, including MANUAL-context cases; inspect-only, no resume |

Inspection reads the ledger, local opportunities, runtime state and selected local
paid claims/responses consistently. It reuses the existing same-connection SQLite
runtime inspector rather than creating new worker semantics. Any retained paid
evidence remains conservatively classified even when a known actual exists; this
is not a new provider outcome verifier. The separate Bedrock journal/billing is not
read or reconciled; its absence cannot be interpreted as no external effect.

Policy show includes the immutable before/proposed policy, receipt if applied,
current ledger summary, pending proposal staleness and fresh projection for a
still-current pending proposal. Negative projected/current remaining emits an
overcommit warning. After a receipt exists, `current` describes the latest ledger;
the receipt always describes the original approved revision, not a new application.

| Failure/retry | Behavior |
| --- | --- |
| Prepare persisted, apply not confirmed | Ledger unchanged; inspect original proposal |
| Failure after any of four apply writes | Entire financial transaction rolls back; same proposal may retry |
| Apply committed, acknowledgement lost | Read original receipt; no second policy write or approval |
| Receipt initially absent, another identical apply commits before snapshot read | Reload original receipt and return it |
| Competing different proposals | One revision wins; stale proposal remains stored and cannot overwrite |
| Later policy/accounting activity | Historical receipt readback preserves newer ledger state |
| Inspection races with another ledger write | A composite display may return stale/conflict; retry same IDs, never reset |
| Ambiguous paid claim / unknown actual | Evidence and commitment remain; F08 reconciliation required |
| Exhausted AI budget | Zero-AI Data remains operational with unchanged source/eligibility/economic checks |

## CLI commands

Use an existing initialized workspace and its actual ledger ID. No marketplace
credentials or live source flag are needed for budget commands. Mutation requires
`AGENTMINE_OPERATOR_ID`; use the same configured operator that prepared the proposal.

```powershell
$python = ".\.venv\Scripts\python.exe"
$base = @("-m", "agentmine.bootstrap.operator", "--db", ".tmp/agentmine.sqlite3", "--ledger", "local")
$env:AGENTMINE_OPERATOR_ID = "local-operator"
& $python @base budget show
```

Create a UTF-8 JSON file without BOM containing the complete proposed numeric
policy/mode. Example values are illustrative; choose and review actual limits:

```json
{
  "monthly_ai_budget": "20",
  "daily_ai_budget": "5",
  "max_cost_per_task": "3",
  "human_approval_cost_threshold": "1",
  "saver_remaining_ratio": "0.2",
  "saver_ai_cost_factor": "0.5",
  "requested_mode": "full"
}
```

Allowed modes are `full`, `saver`, `scout_only`. Do not include currency, timezone,
budget snapshots, authorizations or cost records. Currency/timezone come from the
ledger. Requested FULL cannot override a derived constrained mode.

```powershell
$state = & $python @base budget show | ConvertFrom-Json
& $python @base budget policy prepare --change-id budget-001 --inputs .tmp/budget-policy.json --expected-revision $state.revision --reason "Reviewed local monthly and daily limits"
& $python @base budget policy show --change-id budget-001
# Only after reviewing the retained delta and commitments:
& $python @base budget policy apply --change-id budget-001 --confirm
& $python @base budget show
```

Retry the same apply ID after an uncertain acknowledgement. For a stale *unapplied*
proposal, inspect the latest state and explicitly prepare a new reviewed change ID.
Never change execution/operation identities or clear reservations to free budget.
Changing policy does not resume a task. Existing `work recover --execution-id ID
--confirm` remains the separate deterministic recovery command, with its original
preflight/retained-evidence rules. Unsupported paid/legacy waits stay inspect-only.

## Test-first evidence and verification

Before production changes, 13 new CLI acceptance cases failed because `budget` was
not a recognized command. An earlier attempt exposed a test fixture accessor typo;
it was corrected and the missing-command failures were rerun before implementation.
This is missing-capability evidence, not a claim that all later fault-injection
scenarios reproduced an old bug.

Tests use real SQLite, Domain Budget, BudgetManager, DataWorker and operator CLI.
Only source/clock fixtures and deliberate fault/corruption injections are test-only.
The legacy paid wait and ambiguous semantic claim are explicit synthetic persisted
test evidence; no fake positive-cost provider enters production composition.

Coverage: prepare/apply/reopen and actor/reason/time/revision durability; strict
input and frozen currency/timezone; preservation of costs/commitments/releases;
budget increases/lowered-limit warnings; missing confirm; stale/conflicting IDs;
concurrent same/different applies; transaction failure at every write; lost-ack and
interleaved receipt recovery; no-op audit; current-calendar rollover; zero-cost
SCOUT_ONLY Data; immutable input-file proposal; legacy waits/unknown claims; missing/
corrupt authority; no source/provider/work/submission/payment progression.

| Command/check | Executed result |
| --- | --- |
| Initial `pytest tests/integration/test_budget_control.py -q --tb=short -p no:cacheprovider` | 13 expected missing-command failures before production changes |
| Final focused budget-control pair | 48 passed in 16.04s |
| Budget/runtime/QA/domain-budget/architecture group | 220 passed in 59.43s; before three final mode/race cases and test typing cleanup |
| `python -m pytest -q -ra --tb=short -p no:cacheprovider` | 1219 passed in 108.61s after final production/test changes; no skips |
| `python -m ruff check .` | Passed |
| `python -m ruff format --check .` | 291 files already formatted |
| `python -m mypy` with strict project configuration | Passed, 221 source/test files |
| `git diff --check` | Passed; only Windows LF/CRLF conversion notices |
| Operator `budget policy apply --help` | Passed, including --change-id and --confirm |
| Report/ADR local links, whitespace and code fences | Passed |

Commands above use `.\.venv\Scripts\python.exe`. The focused pair is
`tests/integration/test_budget_control.py` and
`tests/integration/test_budget_control_persistence.py`; use
`-q --tb=short -p no:cacheprovider`. The 220-test group additionally selected
`test_runtime_operator_cli.py`, `test_worker_execution_runtime.py`,
`test_operational_deliverable_qa.py` under `tests/integration/`, and
`tests/unit/domain/test_budget.py`, `tests/unit/domain/test_budget_resume.py`,
`tests/unit/test_architecture.py`. The final full suite includes all new cases and
the final test typing cleanup. All execution was offline with the repository's
network guard; no live marketplace, provider billing, submission or payment used.

## Limitations and verdict

**PASS_WITH_LIMITATIONS.** All executed final checks above passed. This checkpoint
does not close F02-A paid wait/resume or establish production readiness.

- Trusted local actor/host/store boundary is unchanged; hashes detect corruption,
  not a malicious authorized writer. There is no multi-user IAM.
- No paid capability, automatic budget increase/resume, claim release, billing
  reconciliation, policy currency/calendar migration, submission or revenue action.
- Unknown external usage remains unresolved. Local retained evidence is not proof
  of real provider billing, no external effect or complete system cost.
- Policy changes cannot cancel in-flight expenses. Existing paid-reservation policy
  semantics remain a future paid-resume gate; B4-1 does not enable that runtime.
- Inspection scans the local workspace and validates retained runtime evidence;
  corrupt/missing authority blocks control rather than providing a repair bypass.
  Full budget snapshot audits continue to grow; compaction/backup is separate F08 work.
- New snapshot types need the updated binary. No schema reset, migration framework,
  cloud adapter or downgrade support was added.

Offline verification requires no operator credentials/action. Operator action is
needed only when actually reviewing and confirming a chosen local policy change.
No commit/push. B4-2 and B5 are not started. Stop for operator review.

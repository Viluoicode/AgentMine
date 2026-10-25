# Milestone 7A: Local operator interface

Human eligibility review now has separate `eligibility prepare`, `eligibility show`
and `eligibility decide` commands. See the
[F04 remediation guide](audits/remediation-02-eligibility-review.md#9-operator-use-and-limitations)
for evidence inputs, source refresh and limitations. Eligibility approval never
grants submission approval.

The minimum interface is a standard-library CLI. It initializes or opens a SQLite
workspace and invokes application use cases. No web server, frontend framework,
AWS resource, paid model, submission gateway or payment verifier is instantiated.
There is one trusted local operator, identified by explicitly exported
`AGENTMINE_OPERATOR_ID` for decisions. This is audit attribution, not remote
authentication: protect access to the local account/database/environment.

## Commands

From the repository root with the existing development environment:

```powershell
.\.venv\Scripts\python.exe -m agentmine.bootstrap.operator --help
.\.venv\Scripts\python.exe -m agentmine.bootstrap.operator --db .tmp/agentmine.sqlite3 --ledger local workspace init --currency USD --monthly-ai-budget 20 --daily-ai-budget 5 --max-cost-per-task 4 --human-approval-cost-threshold 1
.\.venv\Scripts\python.exe -m agentmine.bootstrap.operator --db .tmp/agentmine.sqlite3 --ledger local dashboard
```

These commands use a concrete local path and ledger ID and can be copied into
PowerShell. The four amounts are example policy choices, not required defaults:
choose your limits before initializing. Budget periods use the existing UTC default.
Do not type angle-bracket placeholders such as `<ledger-id>` into PowerShell.

`workspace init` creates missing parent directories and initializes the ledger via
`InitializeWorkspace` and the existing conditional/audited repository commit. It
creates no opportunities, costs, submission, acceptance or payment evidence. An
empty dashboard is expected initially. Same-policy initialization is idempotent and
preserves existing reservations, actual costs and audit history. A different policy
or requested mode conflicts rather than resetting activity. This is initialization,
not a budget-edit command. Optional `--mode` accepts `full`, `saver`, `scout_only`.

The single-operator workspace supports one ledger. A different ledger ID in an
already initialized workspace fails. Run initialization serially; there is no
cross-process lock for simultaneous initialization under different ledger IDs.
Existing database files and unknown schema versions are never silently replaced.
The `dashboard` command still requires an initialized file/ledger and fails if missing.

## Load real opportunities

Set an authorized Superteam agent key in `AGENTMINE_SUPERTEAM_API_KEY` through your
process environment/secret manager. Do not paste the key into chat or commit it.
Then explicitly invoke the existing read adapter:

```powershell
.\.venv\Scripts\python.exe -m agentmine.bootstrap.operator --db .tmp/agentmine.sqlite3 --ledger local workspace discover --source superteam --live --limit 1
.\.venv\Scripts\python.exe -m agentmine.bootstrap.operator --db .tmp/agentmine.sqlite3 --ledger local dashboard
```

No network call occurs without `--live` and valid configured credentials. The default
raw archive is `.tmp/agentmine.sqlite3.raw.sqlite3` for this workspace; override it
with `--raw-archive .tmp/superteam.sqlite3` after `workspace discover`. Successful
raw source responses are retained by the existing adapter before interpretation.
This command calls `LoadWorkspaceOpportunities`, which first checks the initialized
workspace, then invokes existing `DiscoverOpportunities` and `NormalizeOpportunity`.
Repeated ingestion reuses stable source IDs and preserves later lifecycle states.

Only listings representable by the verified Superteam adapter are ingested. USDC,
prize pools, missing facts and other quarantined offers remain subject to the
[existing contract limitations](superteam-source.md). The command reports accepted
observations, normalized count, current IDs/states and whether pagination remains
unverified. It does not report complete marketplace coverage or quarantine counts.
An empty batch can be legitimate. A window is limited to 1–50 raw listings, default
10, requiring at most one list GET and one detail GET per distinct listing. There
is no invented cursor, automatic pagination or retry.

Loaded opportunities stop at NORMALIZED. Eligibility is not assumed; forecasts and
recommendations remain UNKNOWN until explicit eligibility facts, participant context,
economic predictions and policy are supplied through their application use cases.
The inventory shows stored potential rewards; discovery creates no verified revenue.
No model work, QA, approval, submission or payment is automatically performed.
Actual marketplace HTTP/provider compatibility is not verified by offline tests.

If you do not yet have a Superteam agent key, initialization and the empty dashboard
still work. Tests use injected fixture transports; they do not leave synthetic
earnings in your persistent workspace.

## Review commands

Prepare an immutable submission review for an opportunity in READY_FOR_HUMAN_REVIEW:

```powershell
.\.venv\Scripts\python.exe -m agentmine.bootstrap.operator --db .tmp/agentmine.sqlite3 --ledger local review --opportunity opportunity --review-id review-001 --destination destination
.\.venv\Scripts\python.exe -m agentmine.bootstrap.operator --db .tmp/agentmine.sqlite3 --ledger local show-review --review-id review-001
$env:AGENTMINE_OPERATOR_ID = "local-operator"
.\.venv\Scripts\python.exe -m agentmine.bootstrap.operator --db .tmp/agentmine.sqlite3 --ledger local decide --review-id review-001 --decision REQUEST_REVISION --reason "Add missing source evidence"
```

Use actual IDs/destination. Choices are APPROVE, REJECT and REQUEST_REVISION; the
parser requires an explicit choice. Reason is optional. `show-review` includes the
persisted decision/actor/time, if present. Existing spending reviews can also be
shown/decided by their review ID; creation of spending requests remains with the
application workflow. The CLI creates submission reviews only.

For submission APPROVE, existing 5A requires a fresh matching source status before
persisting approval. Default offline composition refuses refresh rather than
pretending an opportunity remains open. REJECT and REQUEST_REVISION work offline.
Tests explicitly inject a fake source and exercise all three choices at zero cost.

If operating an authorized, previously ingested Superteam opportunity, the existing
read adapter can be selected explicitly:

```powershell
# Set AGENTMINE_OPERATOR_ID and AGENTMINE_SUPERTEAM_API_KEY securely beforehand.
# Use the existing local raw-capture archive and an already inspected review.
.\.venv\Scripts\python.exe -m agentmine.bootstrap.operator --db .tmp/agentmine.sqlite3 --ledger local --live-superteam-refresh --archive .tmp/agentmine.sqlite3.raw.sqlite3 decide --review-id review-001 --decision APPROVE --reason "Reviewed deliverable and risks"
```

This performs live read-only refresh when required by the approval use case. It
does not submit, call Bedrock or verify payment. No live command was run during 7A.
Other source types require an explicitly injected supported OpportunitySource;
unknown/unavailable/closed/expired sources do not become approved automatically.
An already recorded identical decision may return idempotently without another
refresh; submission still has its separate current-state checks.

## Dashboard semantics

| Display | Definition |
| --- | --- |
| Operating Mode | Domain-derived FULL/SAVER/SCOUT_ONLY at the injected clock instant, including daily limits and requested restrictions. Display never changes mode or authorizes work. |
| Monthly limit / spent | Monthly AI policy limit and actual AI costs in the configured calendar month/timezone. |
| Reserved | Outstanding estimated AI commitments, including those carried from prior periods; never reported as actual spending. |
| Remaining | Monthly limit minus actual monthly AI spend minus outstanding AI commitments. Negative values expose overrun. Daily remaining is also shown; monthly headroom is not spending authorization. |
| Discovered / eligible | Current DISCOVERED / ELIGIBLE lifecycle queues. Separate total retained count covers all discovered records across states. |
| Recommended | Current SCORED queue with stored RECOMMEND or ATTEMPT. Later/terminal states do not inflate the queue; missing assessments do not imply a recommendation. |
| Waiting / execution / review | Current WAITING_FOR_BUDGET, IN_PROGRESS, QA_PENDING and READY_FOR_HUMAN_REVIEW counts. Inventory lists IDs, states, stored recommendations and titles. |
| Potential Reward Discovered | Sum of retained potential rewards per currency, including historical/closed opportunities. Forecast inventory, never earnings or current available offers. |
| Expected Value | Stored expected NET forecast subtotal per currency, with known/total coverage. No known forecasts means UNKNOWN. Subjective estimates may be stale and are not revenue. |
| Verified Revenue | Sum of Domain `verified_revenue`: independently evidenced PAID only. ACCEPTED and potential rewards contribute zero. |
| AI / Tool / Infrastructure / Transaction Cost | Actual recorded lifetime costs in the workspace's sole ledger, including costs without an opportunity ID. Estimates do not enter these totals. |
| Net Verified Value | Verified revenue minus the four recorded cost categories per currency. No currency conversion or cross-currency total. It is a recorded-cost measure, not a guarantee that all real costs were captured. |

Forecasts and verified/recorded economics occupy separate labeled terminal blocks.
Every money amount has a currency. Outstanding operations and the incompleteness of
unmeasured costs are displayed. A recorded zero does not claim that work was free.
Budget period totals and lifetime economic totals are explicitly labeled differently.
The snapshot is complete for stored local data, not for undiscovered source listings.

## Review and safety boundary

Review rendering includes opportunity, potential reward, eligibility reason codes,
score, expected net value, estimated/recorded costs, outstanding estimates, exact
deliverable version/content, QA evidence, risks and destination. Stored content is
untrusted and JSON-escaped so terminal escape sequences, forged newlines and bidi
controls cannot overwrite trusted labels. It is displayed as data, never executed.

Decisions use `DecideOperatorReview` unchanged: actor/time/reason are persisted;
stale opportunity/ledger/content and conflicting decisions fail. Identical retries
preserve original actor/time and can repair the existing transition failure window.
APPROVE grants scoped consent only. REJECT skips a submission opportunity;
REQUEST_REVISION returns it to work and requires new deliverable/QA/approval.
No CLI command submits externally or changes financial evidence.

## Architecture and limits

Presentation owns parsing/rendering. Application owns `GetOperatorDashboard`, typed
read models and `OperatorReadRepository`. SQLite implements a complete, consistent
read of opportunities and the sole ledger within one transaction. Bootstrap owns
path, clock, configured actor and optional source construction. Domain and existing
workflow/repository contracts are unchanged. No dependency was added.

The new dashboard read port currently has a SQLite adapter only; a DynamoDB
dashboard would need an explicit complete-report consistency/access-pattern design,
not summing eventually consistent GSI queues. Existing DynamoDB workflows are unaffected.
The full local inventory is intended for bounded V1 datasets: no pagination, browser
UI, daemon, deployment, automatic refresh, budget editing or notification system.
Business journals remain the audit source. There is no new public authentication API.

## Validation

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/application/test_dashboard.py tests/integration/test_operator_interface.py tests/unit/test_architecture.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests/integration/test_workspace_bootstrap.py tests/integration/test_operator_interface.py tests/unit/test_architecture.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
git diff --check
```

Tests use fake sources/clocks and real temporary SQLite files. They cover all modes,
actual/estimated spending, overrun, month rollover, currencies, missing forecasts,
terminal control escaping, accepted-versus-paid accounting, four cost categories,
review rendering, three decisions, durable retries/conflicts, stale budget/closed
source/offline refresh, missing/multiple ledgers, and required operator attribution.
No credentials or manual user action are needed for offline tests.

Validation on 2026-10-21: focused interface/architecture checks **28 passed**;
full regression suite **905 passed in 24.99 seconds**; Ruff lint passed; formatting
passed for 227 files; mypy passed for 178 source files; `git diff --check` passed.
The CLI `--help` entrypoint was also exercised. External API spend: **$0**.

Workspace follow-up validation on 2026-10-21: focused bootstrap/operator/architecture
checks **30 passed**; full regression suite **914 passed in 39.48 seconds**. Ruff
lint/format passed (230 files), mypy passed (180 source files), and `git diff --check`
passed. Root, workspace-init and workspace-discovery help commands were exercised.
Tests include real SQLite initialization, repeated init retaining actual costs,
different policy/ledger conflicts, invalid budgets rejected before file creation,
fixture Superteam ingestion through the CLI, exact raw retention, deduplication and
uninitialized-workspace/missing-key guards before source I/O. No dependency was
installed and no production read or paid model call was made.

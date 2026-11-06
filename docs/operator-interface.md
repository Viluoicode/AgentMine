# Milestone 7A: Local operator interface

F02-B3-A adds explicit local `opportunity` and `work` commands for deterministic
Data execution and artifact export. See the
[deterministic Data commands](#deterministic-data-commands).
Execution stops at QA_PENDING. F02-B3-B adds explicit `work qa` with retained
approved acceptance criteria; see the
[operational QA guide](#operational-qa).
External submission remains absent.

Human eligibility review now has separate `eligibility prepare`, `eligibility show`
and `eligibility decide` commands. See the
[eligibility review guide](#eligibility-review)
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

## Audited local budget policy control (F02-B4-1)

`budget show` displays the current ledger, commitments, recorded actuals and unknown
cost/recovery classifications. `budget policy prepare/show/apply` retains an exact
operator-reviewed proposal and applies it only with the same actor and `--confirm`.
Currency/timezone remain fixed. Policy changes preserve financial history and never
resume tasks or grant spending/submission approval. Existing paid/legacy waits and
ambiguous effects remain inspect-only.

See [policy consent and command examples](#budget-policy-control)
and [ADR 0027](adr/0027-audited-local-budget-control.md) for transactions, safe retries,
input schema and limitations. `workspace init` remains initialization, not policy reset.

## Deterministic Data commands

Use one initialized SQLite workspace, its actual ledger and the configured
`AGENTMINE_OPERATOR_ID`. These commands are separate operator actions, not an
automatic run-all script. Inspect `opportunity --help` and `work --help` first.
Select an actual retained opportunity from `dashboard`, then use:

```text
opportunity show --opportunity ID
opportunity eligibility --opportunity ID --facts FILE --minimum-time-seconds N
opportunity evaluate --opportunity ID --inputs FILE
opportunity score --opportunity ID --evaluation EVALUATION_ID --inputs FILE
opportunity plan --opportunity ID --task TASK_ID --description DESCRIPTION
work prepare --opportunity ID --spec-id SPEC_ID --inputs FILE --input-root DIRECTORY --facts FILE --minimum-time-seconds N --evaluation EVALUATION_ID --approve-inputs
work show --spec-id SPEC_ID
work execute --spec-id SPEC_ID --execution-id EXECUTION_ID --operation-id OPERATION_ID --deliverable-id DELIVERABLE_ID --expected-revision N --confirm
work status --execution-id EXECUTION_ID
work recover --execution-id EXECUTION_ID --confirm
work export --execution-id EXECUTION_ID --directory DIRECTORY
```

The lines above are argument shapes appended to
`python -m agentmine.bootstrap.operator --db DATABASE --ledger LEDGER`; replace
uppercase labels with actual IDs/paths, not literal placeholders. The global
`--live-superteam-refresh --archive RAW_ARCHIVE` opt-in and authorized environment
key are needed when an action requires a supported fresh source observation.
Default offline source access fails closed. Merely reading this guide does not
authorize live calls; do not seed fake marketplace facts to bypass prerequisites.

The facts/profile schema is described under [eligibility review](#eligibility-review).
Economics JSON uses `currency`, `predicted_success_probability`, `estimated_cost`
and `cost_rationale`, with optional `cost_evidence`. The probability object contains
`value`, `rationale` and optional evidence; estimated_cost contains the four decimal
strings `ai`, `tool`, `infrastructure`, `transaction`. Probability and costs are
explicit operator forecasts, not facts
or actual charges. Deterministic execution requires zero estimated AI cost.
Scoring JSON has `policy` (version/net_value_target/currency/rationale) and `signals`
(risk/competition/deadline/ai_suitability/historical_performance), each with value,
rationale and optional evidence. Unknown signal values remain null. Check the
[current parser](../src/agentmine/presentation/runtime_inputs.py) before preparing
inputs; no currency conversion or automatic favorable evidence is supplied.

Choose a protected local input root. The Data manifest binds each source id,
relative path, exact lowercase SHA-256, format (`csv`/`json`), locator and real
collected_at timestamp. It also declares columns (name/path/kind and applicable
constraints), unique_by, min_records/max_records, constraints and approved acceptance.
Digest the reviewed UTF-8 file without BOM before approval; do not rewrite inputs
to repair a mismatch. Each input is bounded to1,000,000 bytes, at most10 files;
metadata manifests are bounded to64,000 bytes. Linked/reparse paths, traversal,
duplicate/unknown JSON keys and unsupported semantic fields fail closed.

`work prepare --approve-inputs` freezes snapshots/scope and consent; it does not
execute. Add `--eligibility-review ACTUAL_REVIEW_ID` for a resolved MANUAL case;
do not relabel it AUTOMATIC or reapply eligibility to discard the reviewed decision.
Execute requires explicit confirmation and the current opportunity revision from
`opportunity show`. Recovery retains original IDs: retained results repair
cost/finish without recomputation; missing results require fresh preflight before
deterministic replay. Unknown AI claims remain blocked. Never change IDs or clear
commitments to force progress. See [runtime identity rationale](adr/0023-local-worker-runtime-foundation.md)
and [v2 contract](design/data-partitioned-deliverables.md).

`command_status` COMPLETED is execution history, not QA PASS or earnings. Inspect
opportunity_state, recovery_reason, retained artifacts and QA separately. Export
uses existing artifacts only, requires an existing local parent directory and
no-clobber publication support. Identical retry is idempotent; conflicting files
fail without overwrite. A crash may leave files without final manifest.json;
inspect and retry the original operation. Local export never opens a URL or submits.

## Operational QA

Set acceptance in the input manifest **before** prepare/execution: nonempty bounded
formats (artifact name/media type) and requirements (id/artifact/kind/criterion).
Legacy kinds include column/section/literal/semantic; v2 adds field_present and
requires explicit partition_acceptance matching output_policy. Choose criteria
from actual requirements, not the output that happened to be produced. See
[frozen v2 acceptance](design/data-partitioned-deliverables.md#artifacts-và-frozen-acceptance).

Use the original execution and a stable inspection ID:

```text
work qa --execution-id EXECUTION_ID --inspection-id INSPECTION_ID --confirm
work status --execution-id EXECUTION_ID
```

New QA loads retained plan/result/deliverable/digest and approved criteria, with
fresh source/authority checks. The operator does not supply a QA outcome or an
arbitrary filesystem/URL inspection. Same-ID retry reads the original persisted
report and completes it without recomputing or changing a later lifecycle state;
stale/conflicting evidence fails closed. Completed readback does not grant fresh
external permission. Deterministic zero-AI composition does not enable semantic QA;
unsupported semantic requirements remain human-review pending.

PASS transitions to READY_FOR_HUMAN_REVIEW, then reuse existing `review`,
`show-review` and `decide` commands. Eligibility, spending and submission consent
are distinct. FAIL/NEEDS_REVISION requires the authorized revision workflow;
first-version replay cannot stand in for rework. Human-pending QA is not approval.
See [QA tests/evidence](testing/partitioned-deliverables.md).

## Eligibility review

`eligibility prepare --opportunity ID --review-id ID --facts FILE --minimum-time-seconds N`
retains reviewed source/facts/policy evidence. `eligibility show --review-id ID`
reads it back. `eligibility decide --review-id ID --decision APPROVE|REJECT --reason TEXT`
requires the trusted actor. APPROVE additionally requires `--manual-destination`,
`--instructions-evidence`, `--access-evidence`, `--requirements-evidence` and
`--manual-requirements-met`. Inspect CLI help for complete argument usage.

Facts JSON contains `facts` and `profile` objects. Facts may specify ai_policy,
geography (allowed/excluded), account, identity, physical_presence, task_type,
required_skills, submission, payment (upfront_fee/secret_credentials), and
prohibited_actions. Profile may specify country/skills, account_requirement_met,
identity_requirement_met and will_disclose_ai. Check
[facts parser](../src/agentmine/presentation/eligibility_inputs.py) for typed values.
Missing facts remain UNKNOWN; source refresh supplies open/deadline facts and cannot
be overridden by input JSON. Do not copy permissive test facts into a real review.

Prepare/decide require authoritative refresh; the disabled default blocks them.
Evidence must describe current terms and actual account access without credentials.
Only supported reviewable reasons can be resolved. A material source/facts/policy
change invalidates old authority; approval is not permanent permission and never
substitutes for deliverable, spending or submission approval. Rationale remains in
[ADR0022](adr/0022-human-eligibility-resolution.md).

## Budget policy control

Budget commands use the authoritative ledger without a marketplace call:

```text
budget show
budget policy prepare --change-id CHANGE_ID --inputs FILE --expected-revision N --reason TEXT
budget policy show --change-id CHANGE_ID
budget policy apply --change-id CHANGE_ID --confirm
```

Policy JSON requires exactly seven string values: monthly_ai_budget,
daily_ai_budget, max_cost_per_task, human_approval_cost_threshold,
saver_remaining_ratio, saver_ai_cost_factor, requested_mode. Numeric strings use
bounded plain decimals; modes are full/saver/scout_only. Currency/timezone remain
from the ledger. No replacement Budget snapshot, cost record, authorization or
currency/timezone override is accepted. See [policy parser](../src/agentmine/presentation/budget_cli.py#L66).

Read current revision from budget show; prepare retains the immutable proposed
delta/actor/reason without changing policy. Inspect before apply. Apply requires
the same trusted actor, original ID and explicit confirmation. Ledger/audit/decision/
receipt commit atomically; same-ID retry returns the original receipt even after
later policy changes. For a stale unapplied proposal, inspect state and prepare a
new reviewed change, never alter its payload. Requested FULL cannot override a
derived constrained mode. Lower limits can expose negative remaining/overcommit;
existing commitments, actual costs and released identities remain preserved.

Policy consent grants neither spending approval nor automatic resume. Paid/legacy
waits and ambiguous outcomes stay inspect-only; unknown cost is not zero. Do not
use workspace init as policy reset. See [transaction rationale](adr/0027-audited-local-budget-control.md).

## Sao lưu, phục hồi cô lập và nguyên tắc không gửi lại

Sao lưu trước bảo trì, chuyển máy hoặc điều tra một thao tác có kết quả chưa rõ.
Dừng các process/operator đang truy cập workspace; giữ nguyên database gốc, ledger,
actor và các ID execution/operation/handoff/submission/evidence. Không gửi lại hoặc
tạo ID thay thế trong khi điều tra. Lưu backup trong thư mục riêng được bảo vệ,
ngoài repository và nơi xuất bản; bảo toàn approved inputs/raw archives riêng nếu có.

AgentMine chưa có backup/restore CLI. Đoạn PowerShell dưới dùng **SQLite backup API
của Python standard library**, không copy riêng file SQLite đang hoạt động. Đây là
thao tác operator chủ động, không phải lệnh tự chạy trong workflow. Thay các giá trị
UPPERCASE bằng đường dẫn thực; thư mục đích phải tồn tại và file đích chưa tồn tại.

```powershell
$python = '.\.venv\Scripts\python.exe'
function Copy-VerifiedSqliteSnapshot {
    param([string]$Source, [string]$Destination)
    @'
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

source = Path(sys.argv[1]).resolve(strict=True)
target = Path(sys.argv[2])
if not source.is_file() or not target.parent.is_dir():
    raise ValueError("Existing source file and destination parent required")
if target.resolve() == source or target.exists():
    raise ValueError("Use a new, separate destination; never overwrite")
with target.open("xb"):
    pass
with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
    with closing(sqlite3.connect(target.resolve().as_uri() + "?mode=rw", uri=True)) as dst:
        src.backup(dst)
with closing(sqlite3.connect(target.resolve().as_uri() + "?mode=ro", uri=True)) as check:
    if check.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise RuntimeError("Backup integrity check failed; stop")
print("SQLITE_SNAPSHOT_INTEGRITY_OK")
'@ | & $python -B - $Source $Destination
    if ($LASTEXITCODE -ne 0) { throw 'Backup/readback failed; stop and inspect.' }
}

$sourceDb = 'EXISTING_WORKSPACE_DATABASE'
$backupDb = 'NEW_PRIVATE_BACKUP_FILE'
Copy-VerifiedSqliteSnapshot -Source $sourceDb -Destination $backupDb

# Phục hồi để kiểm tra: tạo thêm một snapshot cô lập, không ghi đè database gốc.
$isolatedDb = 'NEW_ISOLATED_INSPECTION_DATABASE'
Copy-VerifiedSqliteSnapshot -Source $backupDb -Destination $isolatedDb
```

Nếu lỗi, giữ các file để điều tra; script không tự xóa partial output và không ghi
đè khi retry. Không bỏ WAL/journal hoặc copy một live database file đơn lẻ để tuyên
bố backup nhất quán. `integrity_check=ok` chỉ kiểm cấu trúc SQLite, không chứng minh
đủ business evidence hay external outcome. Dùng bản cô lập để kiểm đúng ledger/actor,
claims, history và original IDs trước khi coi backup là dùng được. Ví dụ readback
của một handoff đã tồn tại, không thêm live-refresh flag hoặc lệnh confirm:

```powershell
& $python -B -m agentmine.bootstrap.operator --db $isolatedDb --ledger ACTUAL_LEDGER submission handoff show --handoff-id ORIGINAL_HANDOFF_ID
& $python -B -m agentmine.bootstrap.operator --db $isolatedDb --ledger ACTUAL_LEDGER submission handoff receipt-show --handoff-id ORIGINAL_HANDOFF_ID
```

Không chạy hai restored copies như hai authority độc lập. Backup cũ hơn một lần
gửi/chuyển tiền có thể không ghi nhận việc đó; **không có record không chứng minh
external action chưa xảy ra**. Bản cô lập chỉ để inspection, không dispatch/confirm.
Chỉ chọn lại một authoritative workspace qua quyết định operator, giữ các bản khác
không hoạt động. Không đổi IDs, xóa claims hoặc release commitments để mở khóa.

Nếu submission/payment outcome chưa rõ: dừng mọi resend/retry có external effect,
giữ nguyên bằng chứng và nhờ operator đối chiếu qua kênh độc lập được phép. Không
tự gửi lại, ký/chuyển tiền hoặc đánh dấu PAID. Khi authoritative state còn nguyên,
chỉ dùng original-ID show và quy trình receipt giống hệt đã được kiểm tra để hoàn
tất local writes; receipt không chứng minh platform đã nhận hoặc đã trả tiền.
Thiếu/conflicting ownership hoặc evidence thì dừng và giữ mọi bản sao. Không có
automatic external reconciliation hay disaster-recovery certification được hứa hẹn.
Xem [backup/readback regression](../tests/integration/test_manual_handoff.py#L572),
[handoff parser/view](../src/agentmine/presentation/manual_handoff_cli.py#L42) và
[payment trust boundaries](production-readiness.md#submission-outcome-and-payment-boundaries).

## Quy trình CLI cho revision đã được duyệt

Revision tạo version mới của cùng Task/lineage; không phải replay v1, không tạo
Task mới để né ownership. Các ví dụ dưới là thao tác riêng biệt để operator review,
không phải script run-all. Giữ nguyên operating mode/budget và actor của workspace.
Không dùng fixture IDs/facts trong workspace thật.

### 1. Xác định parent và trigger thực tế

```powershell
$python = '.\.venv\Scripts\python.exe'
$base = @('-m', 'agentmine.bootstrap.operator', '--db', 'AUTHORITATIVE_DATABASE', '--ledger', 'ACTUAL_LEDGER')
& $python @base opportunity show --opportunity OPPORTUNITY_ID
& $python @base work status --execution-id PARENT_EXECUTION_ID
```

Dùng execution ID đã lưu từ lần chạy gốc, không đoán ID từ task/version. Nếu không
giữ được ID, dừng để đối chiếu hồ sơ authoritative; hướng dẫn này không có lệnh
lookup-all hay SQL sửa ownership. `opportunity show` cho task và opportunity_revision
(optimistic concurrency revision, không phải deliverable version). `work status`
cho binding, current_execution/current_deliverable, deliverable.version,
requested_execution_is_current và qa.inspection/qa.report/qa.applied. Chọn đúng
completed parent hiện hành, không dùng historical readback để cấp quyền mới.

- QA FAIL/NEEDS_REVISION đã applied: dùng `--trigger qa --trigger-id PARENT_INSPECTION_ID`
  từ qa.inspection, không thay bằng một report/ID tự đặt.
- QA PASS rồi operator yêu cầu sửa: dùng review thực tế và áp dụng quyết định riêng:

```text
review --opportunity OPPORTUNITY_ID --review-id PARENT_REVIEW_ID --destination SUPPORTED_DESTINATION
show-review --review-id PARENT_REVIEW_ID
decide --review-id PARENT_REVIEW_ID --decision REQUEST_REVISION --reason "Lý do sửa đã review"
```

Các argument shapes trên nối sau `$python @base`; giữ đúng destination/scope/version
đã xem xét. Sau decision đã applied, prepare dùng `--trigger operator --trigger-id PARENT_REVIEW_ID`.
QA REQUIRES_HUMAN_REVIEW chưa phải revision permission; không ép thành FAIL/PASS.

### 2. Prepare, inspect và approve scope mới

Chỉ cấu hình `$live` khi đã có quyền read-only source và key được cung cấp an toàn;
không chứa key trong command/manifest. Thiếu authoritative refresh thì dừng, không
fallback mock. Các JSON dùng schema hiện hữu ở phần [Data commands](#deterministic-data-commands).
Evidence/forecasts phải thật, thresholds không được nới để output mới đạt PASS.

```powershell
$live = @('--live-superteam-refresh', '--archive', 'AUTHORIZED_RAW_ARCHIVE')
& $python @base @live work revision prepare --revision-id REVISION_ID --parent-execution PARENT_EXECUTION_ID --trigger qa --trigger-id PARENT_INSPECTION_ID --spec-id NEW_SPEC_ID --evaluation NEW_EVALUATION_ID --inputs REVISED_MANIFEST --input-root APPROVED_INPUT_DIRECTORY --facts CURRENT_FACTS --minimum-time-seconds 3600 --economics CURRENT_ECONOMICS --scoring CURRENT_SCORING --forecast-evidence ACTUAL_FORECAST_EVIDENCE --reason 'Sửa theo yêu cầu đã review'
& $python @base work revision show --revision-id REVISION_ID
# Chỉ sau khi kiểm đúng input digests, criteria, forecasts và scope:
& $python @base @live work revision approve --revision-id REVISION_ID --execution-id NEW_EXECUTION_ID --operation-id NEW_OPERATION_ID --approve-inputs --confirm
& $python @base work revision show --revision-id REVISION_ID
```

Thay 3600 bằng policy thời gian thực tế, không mặc định đó là đủ cho mọi task.
Prepare giữ proposal, không consent/dispatch. Show cho parent execution/deliverable/QA,
trigger, scope/differences, status/recovery_reason, forecasts, consent và allocation.
Approve duyệt exact retained request, allocator chọn sequential version; không có
flag chọn version hay thay deliverable ID. Kiểm allocation.version và
allocation.binding trước execute. Revision/spending/eligibility/submission consent
vẫn riêng biệt; giữ cùng output policy và non-relaxing acceptance.

### 3. Execute, QA và kiểm lịch sử

```powershell
& $python @base @live work revision execute --revision-id REVISION_ID --confirm
& $python @base work revision show --revision-id REVISION_ID
& $python @base work status --execution-id NEW_EXECUTION_ID
& $python @base @live work qa --execution-id NEW_EXECUTION_ID --inspection-id NEW_INSPECTION_ID --confirm
& $python @base work status --execution-id NEW_EXECUTION_ID
& $python @base opportunity show --opportunity OPPORTUNITY_ID
```

Dùng execution ID đúng allocation, inspection ID mới cho exact new version; không
chuyển QA/approval từ parent dù output bytes giống nhau. Xem qa.report.findings,
artifact content reference, retained_results.artifacts và deliverable.version.
Export nếu cần bằng `work export --execution-id NEW_EXECUTION_ID --directory NEW_EXPORT_DIRECTORY`;
parent export directory phải tồn tại và no-clobber rules vẫn áp dụng. PASS chỉ
READY_FOR_HUMAN_REVIEW; review/approval version mới là bước riêng, không auto-submit.

Mất acknowledgement thì inspect original revision rồi chỉ recover cùng ID:

```powershell
& $python @base work revision show --revision-id REVISION_ID
& $python @base @live work revision recover --revision-id REVISION_ID --confirm
```

Same-ID retry không được đổi payload/inputs/operation. Stale source, changed terms,
parent/ledger conflict hoặc unknown paid claim phải giữ blocked; không chọn ID mới
để lách allocation. QA FAIL/NEEDS_REVISION version mới cần một revision request mới
từ completed parent mới và trigger đã applied, không execute lại first version.
Không có supersession hoặc claim-release command để tự cứu stale allocation.

Revision views báo external_submission=false, payment_simulated=false và
revision_consent_grants_submission_approval=false; work status cũng báo
external_submission=false. Kiểm đúng version/state và opportunity show có
verified_revenue; workflow này không được tự tạo approval/submission/revenue.
Các flags là cam kết local code path, không chứng minh con người hoặc hệ thống khác
chưa hành động bên ngoài. Nếu có nghi ngờ external effect, áp dụng no-resend ở trên.

Nguồn hành vi hiện tại: [revision parser/view](../src/agentmine/presentation/revision_cli.py#L49),
[runtime status](../src/agentmine/presentation/runtime_cli.py#L121),
[QA và separate-review tests](../tests/integration/test_revision_operator_qa.py#L132),
[stale-snapshot test](../tests/integration/test_revision_operator_qa.py#L754) và
[v2 partition revision test](../tests/integration/test_partition_runtime_e2e.py#L539).

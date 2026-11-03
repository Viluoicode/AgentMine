# AgentMine — Phase B.3: Offline Discovery Diagnostics Implementation

## 1. Scope và verdict

Ngày: **02/11/2026**, Asia/Bangkok. Base commit:
`fa1928b78f9ea43509501c6a1cb905af0cba426e`.

**Verification status: PASS - approved offline diagnostics scope only.**
Focused tests, full suite and static checks completed successfully. This does not
claim production readiness or live marketplace compatibility.

Đã thực hiện đúng approved offline diagnostic scope: selected raw capture readback,
normalization projection, per-listing issues, incomplete/invalid/conflicting evidence,
coverage limits và CLI riêng. Không đổi Domain lifecycle, eligibility, reward/currency,
budget authorization, live Superteam discovery, submission/handoff/payment hoặc AWS.
Không thêm third-party dependency, run journal/table hay provider.

Ba báo cáo B.1/B.2/B.3-design đã untracked trước implementation; không chỉnh nội dung.
Không commit/push. Không sử dụng kết quả live smoke do operator báo cáo như verification
được assistant chạy lại. Không tìm kiếm archive vận hành hoặc đọc secret files.

## 2. Architecture changes

```text
bootstrap.discovery_diagnostics
    → presentation.discovery_diagnostics_cli
        → InspectDiscoveryDiagnostics
            → DiscoveryDiagnosticsReader (Application port)
                ← ArchiveDiscoveryDiagnostics (Infrastructure)
                    → RawArchive.reading/read_capture
                    → existing pure normalize_detail
```

Application contracts là immutable diagnostic DTOs/enums, không lifecycle state mới.
Use case revalidates selected request/report identity và report invariants. Infrastructure
giữ SQLite/source schema, reuse normalizer hiện tại; không gọi OpportunitySource.inspect
hoặc tạo persisted Opportunity. NORMALIZED chỉ là normalization compatibility.

Bootstrap không import/compose operator workspace hoặc HTTP/LLM clients, không cần API key,
ledger, operating mode hoặc provider config. Stdlib argparse có thể đọc locale/terminal
preferences; test chặn riêng API-key access, không tuyên bố cấm mọi stdlib environment read.

Không thay discovery contracts để buộc pipeline ingestion nhận quarantine. Không dùng
timestamp làm join, không chọn detail mới nhất và không assert selected captures cùng run.

## 3. Exact files changed

### New production files

- `src/agentmine/application/contracts/discovery_diagnostics.py`: typed request, report,
  capture/listing evidence, reasons, classifications và safe typed error.
- `src/agentmine/application/ports/discovery_diagnostics.py`: read-only inspection port.
- `src/agentmine/application/use_cases/discovery_diagnostics.py`: selection/report checks.
- `src/agentmine/infrastructure/marketplaces/discovery_diagnostics.py`: selected archive
  projection, identity/route checks và normalizer reuse.
- `src/agentmine/presentation/discovery_diagnostics_cli.py`: bounded safe JSON output.
- `src/agentmine/bootstrap/discovery_diagnostics.py`: offline module entrypoint.

### Modified existing files

- `src/agentmine/infrastructure/marketplaces/raw_archive.py`: genuinely read-only
  snapshot/read helpers, bounded row/body validation và envelope digest check; get()
  uses read-only path. save() body unchanged.
- `docs/superteam-source.md`: command usage, output semantics, exit codes và limitations.

### New tests

- `tests/contract/test_discovery_diagnostics.py`
- `tests/unit/application/test_discovery_diagnostic_contracts.py`
- `tests/integration/test_discovery_diagnostics_cli.py`

Unit filename khác design để tránh trùng basename với contract test trong pytest layout
hiện có; không đổi architecture hoặc thêm package markers/framework.

### Implementation report

- `docs/audits/phase-b3-discovery-diagnostics-implementation.md` (file này).

## 4. Diagnostic semantics và invariants

| Classification | Meaning |
|---|---|
| EMPTY_FEED | Exact validated list body is []; không marketplace-wide conclusion |
| NORMALIZED | Existing normalizer có observation; không inventory/eligibility/permission |
| QUARANTINED | Existing normalizer issues, giữ nguyên codes; không Domain INELIGIBLE |
| INCOMPLETE_EVIDENCE | Detail không được chọn hoặc selected capture thiếu |
| INVALID_CAPTURE | Body/schema/digest/metadata không hợp lệ |
| IDENTITY_CONFLICT | List ID/slug hoặc selected detail route/identity conflict; không chọn owner |
| PARTIAL_FAILURE | Valid list inspected, selected detail evidence có known invalid/conflict; không API timeout inference |
| UNKNOWN_COVERAGE | Always present; không independent completeness proof |

Counts: raw rows, unique listings, duplicate rows, normalized, quarantined, unresolved.
Với list có unambiguous identity: raw = unique + duplicates; unique = normalized +
quarantined + unresolved. Invalid/conflicting list fail bằng unknown counts (null), không
fake empty feed. Verified list reference/time còn giữ khi body/identity validation lỗi.

List/detail timestamps giữ riêng, source ID/slug không rewrite. Corrupt digest không
được dùng làm trusted timestamp/association. Mọi supplied detail phải được account bằng
evidence hoặc typed problem. Nhiều selected captures cho cùng slug conflict, kể cả cùng
bytes. Chỉ capture operator chọn mới được đọc; không scan archive.

Output có `association_basis=EXPLICIT_SELECTED_CAPTURES_NOT_A_DISCOVERY_RUN`,
`api_run_outcome=UNKNOWN`, `recomputed_with_current_normalizer=true` và
`diagnostic_version=offline-discovery-v1`. Không có persisted diagnostic history.

## 5. Read-only safety

- SQLite URI `mode=ro`, một BEGIN/read snapshot; không immutable mode.
- Missing archive/schema không tạo file/table; archive views không được chấp nhận làm
  marketplace_captures table.
- Existing writer save() không đổi; không auto checkpoint/repair/migrate.
- WAL headers hoặc journal sidecars bị từ chối trước SQLite connect để tránh read-created
  sidecars. Báo ARCHIVE_REQUIRES_RECONCILIATION / INCOMPLETE_EVIDENCE.
- Reuse existing local filesystem link/network-path rejection helper.
- Body cap 2,000,000 bytes/capture, aggregate selected bodies 8,000,000 bytes, tối đa
  50 distinct detail refs; list take 1–50, bounded safe identities ≤256 chars.
- Digest gồm route + aware timestamp + exact body được kiểm tra.
- Không dump title/description/raw body, không log low-level exception/secret values.
- No workspace/ledger initialization, API-key access, network, provider construction,
  submission, wallet, budget/mode changes hoặc financial records.

Read-only mode không chứng minh archive authentic. Trusted local filesystem/SQLite và
không có adversarial concurrent file replacement/journal-mode switching vẫn là assumptions.

## 6. New CLI usage

```powershell
.\.venv\Scripts\python.exe -B -m agentmine.bootstrap.discovery_diagnostics --archive "C:\path\raw.sqlite3" --list-capture "raw:sha256:REPLACE_WITH_64_LOWERCASE_HEX"
```

Thêm bounded repeated `--detail-capture REF` khi có exact retained detail refs.
Không có --live/--db/--ledger. Không auto-discover capture refs.

Exit 0: selected evidence resolved, kể cả honest quarantine/empty feed.
Exit 1: incomplete/invalid/conflicting/unavailable evidence.
Exit 2: argparse usage error. UNKNOWN_COVERAGE một mình không cause failure.

## 7. Test-first evidence và intermediate failures

Trước production implementation, ba acceptance files đã được tạo. Lệnh:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -m pytest tests/contract/test_discovery_diagnostics.py tests/unit/application/test_discovery_diagnostic_contracts.py tests/integration/test_discovery_diagnostics_cli.py -q --tb=short -p no:cacheprovider
```

**RED:** 3 collection errors in 0.59s, missing new contracts/bootstrap modules.
Đây là suite-level RED; không claim mỗi case bổ sung sau đều được chạy RED riêng.

Sau initial implementation: 29 passed in 1.71s. Bổ sung bounds/corruption/read-only
SQL/WAL/application-binding tests, tổng hiện tại 44 new cases.

Intermediate failures đã xử lý, không bỏ qua:
- Ruff import ordering/format/E501 trong new files; sửa imports/format/long string.
- Mypy với --cache-dir NUL gây internal error; traceback WinError 3 tại NUL/3.12.
  Đây là lựa chọn cache path sai trên Windows; đổi sang real temporary directory,
  không đổi mypy version/dependencies.
- Mypy phát hiện **dict[str, object] truyền vào helper có identity:str; sửa helper call
  bằng explicit dictionary merge.
- Environment spy quá rộng chặn gettext locale rồi shutil COLUMNS lookup; sửa spy chặn
  exact API-key lookups/getenv, cho phép standard-library preference fallback. Không
  nới requirement API-key/no-provider/no-network.
- Final combined run trước spy correction: 1 failed, 207 passed in 15.81s. Final rerun
  cùng group đạt 208 passed; không claim lượt lỗi là PASS.

## 8. Executed verification

### Focused và regressions

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -m pytest tests/contract/test_discovery_diagnostics.py tests/unit/application/test_discovery_diagnostic_contracts.py tests/integration/test_discovery_diagnostics_cli.py tests/contract/test_superteam_normalization.py tests/contract/test_superteam_source.py tests/unit/test_superteam_smoke.py tests/integration/test_workspace_bootstrap.py tests/integration/test_operator_interface.py tests/integration/test_runtime_operator_cli.py tests/unit/test_architecture.py -q --tb=short -p no:cacheprovider
```

**208 passed in 15.52s**, exit 0: 44 new diagnostics + 164 existing regressions.
Includes architecture tests, real SQLite, existing Superteam source/smoke and operator
compatibility. Existing regression-only group earlier: 164 passed in 14.08s.

### Full suite

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q -ra --tb=short -p no:cacheprovider
```

**1520 passed in 660.48s (0:11:00), exit 0; 0 failed/errors/skipped.**
Final verbose run completed; no warnings reported in pytest summary.

First quiet full-suite attempt lost its execution session before completion; its log
ended near 33%, no final summary/exit result and no Python process remained when checked.
Cause of process/session termination is unknown. That attempt is NOT counted as PASS.
A new full run uses PTY, periodic polling and the exact command below, with verbose log
in .tmp/phase-b3-final-full-pytest.log:

```powershell
.\.venv\Scripts\python.exe -B -m pytest -vv -ra --tb=short -p no:cacheprovider
```

Full process output redirected to ignored `.tmp/phase-b3-full-pytest.log` for exact
completion review. No paid APIs/live sources: root tests/conftest.py blocks sockets.
Some older suites use explicit test-only marketplace/LLM/payment fakes; no synthetic
reward is treated as real revenue in this implementation.

### Static checks

```powershell
.\.venv\Scripts\python.exe -B -m ruff check . --no-cache --output-format concise
.\.venv\Scripts\python.exe -B -m ruff format --check . --no-cache
$diagnosticMypyCache = Join-Path ([System.IO.Path]::GetTempPath()) 'agentmine-b3-mypy-20261102'
.\.venv\Scripts\python.exe -B -m mypy --strict --cache-dir $diagnosticMypyCache
git diff --check
```

Executed final results so far: Ruff all checks passed; format 365 files already
formatted; strict mypy success in 272 source files (repository config includes tests).
git diff --check passed, including finalization. New report whitespace/code fences
were checked directly because git diff does not inspect untracked files.

## 9. Local acceptance demonstration

Không giả định archive vận hành tồn tại. Tạo **synthetic archive riêng trong OS temp**,
bằng existing RawArchive.save() chỉ trong setup demo. Không dùng live fixture hoặc key.
Timestamps/IDs/amounts là synthetic; không tạo Opportunity/approval/payment authority.

Archive: `C:\Users\tranv\AppData\Local\Temp\agentmine-b3-demo-3r954tbk\synthetic-raw.sqlite3`.

Actual module commands đã chạy:

```powershell
$archive = 'C:\Users\tranv\AppData\Local\Temp\agentmine-b3-demo-3r954tbk\synthetic-raw.sqlite3'
.\.venv\Scripts\python.exe -B -m agentmine.bootstrap.discovery_diagnostics --archive $archive --list-capture 'raw:sha256:9b22d3573aa9306895a4f67e73fadb87568f022185c280a8550764f21ab0014d'
.\.venv\Scripts\python.exe -B -m agentmine.bootstrap.discovery_diagnostics --archive $archive --list-capture 'raw:sha256:46a3401b4ec1e778bca6be392b7e6ff13957f51d3fd694a0e14fa0dfb48b901e' --detail-capture 'raw:sha256:28c58b7976fbfc8b5e6d6c2c49c4f32d0e44b7bbaa0dbdf726be828585fc6e31' --detail-capture 'raw:sha256:cea42ed1602d4bc040b1d67e801f3956056bef198918228696ae2c401f068405'
```

### Exact empty-feed JSON output

```json
{
  "status": "diagnostic_complete",
  "classifications": [
    "EMPTY_FEED",
    "UNKNOWN_COVERAGE"
  ],
  "coverage": "UNKNOWN_COVERAGE",
  "api_run_outcome": "UNKNOWN",
  "association_basis": "EXPLICIT_SELECTED_CAPTURES_NOT_A_DISCOVERY_RUN",
  "recomputed_with_current_normalizer": true,
  "diagnostic_version": "offline-discovery-v1",
  "normalized_meaning": "Normalization compatibility only; not inventory or eligibility",
  "partial_failure_scope": "Selected evidence inspection only; not historical network failure",
  "opportunities_ingested": false,
  "external_actions": false,
  "list_capture": {
    "reference": "raw:sha256:9b22d3573aa9306895a4f67e73fadb87568f022185c280a8550764f21ab0014d",
    "observed_at": "2026-11-02T12:00:00+00:00",
    "requested_limit": 2
  },
  "counts": {
    "raw_row_count": 0,
    "unique_listing_count": 0,
    "duplicate_row_count": 0,
    "normalized_count": 0,
    "quarantined_count": 0,
    "unresolved_count": 0
  },
  "items": [],
  "capture_problems": []
}
```

### Exact mixed JSON output

```json
{
  "status": "diagnostic_complete",
  "classifications": [
    "NORMALIZED",
    "QUARANTINED",
    "UNKNOWN_COVERAGE"
  ],
  "coverage": "UNKNOWN_COVERAGE",
  "api_run_outcome": "UNKNOWN",
  "association_basis": "EXPLICIT_SELECTED_CAPTURES_NOT_A_DISCOVERY_RUN",
  "recomputed_with_current_normalizer": true,
  "diagnostic_version": "offline-discovery-v1",
  "normalized_meaning": "Normalization compatibility only; not inventory or eligibility",
  "partial_failure_scope": "Selected evidence inspection only; not historical network failure",
  "opportunities_ingested": false,
  "external_actions": false,
  "list_capture": {
    "reference": "raw:sha256:46a3401b4ec1e778bca6be392b7e6ff13957f51d3fd694a0e14fa0dfb48b901e",
    "observed_at": "2026-11-02T12:00:00+00:00",
    "requested_limit": 2
  },
  "counts": {
    "raw_row_count": 2,
    "unique_listing_count": 2,
    "duplicate_row_count": 0,
    "normalized_count": 1,
    "quarantined_count": 1,
    "unresolved_count": 0
  },
  "items": [
    {
      "listing_id": "synthetic-data",
      "slug": "synthetic-data",
      "classification": "NORMALIZED",
      "detail_captures": [
        {
          "reference": "raw:sha256:28c58b7976fbfc8b5e6d6c2c49c4f32d0e44b7bbaa0dbdf726be828585fc6e31",
          "observed_at": "2026-11-02T12:00:00+00:00"
        }
      ],
      "issue_codes": [],
      "reasons": []
    },
    {
      "listing_id": "synthetic-bounty",
      "slug": "synthetic-bounty",
      "classification": "QUARANTINED",
      "detail_captures": [
        {
          "reference": "raw:sha256:cea42ed1602d4bc040b1d67e801f3956056bef198918228696ae2c401f068405",
          "observed_at": "2026-11-02T12:00:00+00:00"
        }
      ],
      "issue_codes": [
        "REWARD_MODEL_UNSUPPORTED",
        "REWARD_ASSET_UNSUPPORTED"
      ],
      "reasons": []
    }
  ],
  "capture_problems": []
}
```

### Filesystem evidence

```json
{
  "empty_exit": 0,
  "mixed_exit": 0,
  "before_sha256": "A79C5E1D5EE59AC3DA4335D16427E0EB17A98655F05E3CD3A72D0C8FC860A828",
  "after_sha256": "A79C5E1D5EE59AC3DA4335D16427E0EB17A98655F05E3CD3A72D0C8FC860A828",
  "files_unchanged": true
}
```

Cả hai commands exit 0. Raw archive bytes/hash và file inventory không đổi, không
sidecar/workspace mới. Output external_actions=false là descriptive flag, không thay
network telemetry: evidence cho no-external-call gồm architecture/composition inspection,
network-blocked tests và spies chặn key/HTTP/LLM/workspace construction. Không claim live
marketplace verification hoặc verified earnings.

Supplementary offline demo: the same module ran via runpy under a Python audit hook
that raises on socket.connect/socket.getaddrinfo. It exited 0 with EMPTY_FEED and
UNKNOWN_COVERAGE. A prior PowerShell -c attempt failed with shell-quoting SyntaxError
before module execution; stdin wrapper corrected it without any product change.
RawArchive.save() AST matched HEAD exactly.

## 10. Known limitations và remaining risks

- No discovery-run manifest: không reconstruct run, historical failure hoặc completeness.
- HTTP errors/oversized original responses không phải successful raw captures; tool
  không phục hồi evidence chưa được retained.
- Captures từ nhiều thời điểm chỉ là explicit evidence set, không fresh source authority.
- Recompute với current normalizer có thể khác historical normalization; version label
  phải được duy trì khi semantics thay đổi.
- No real bounty/USDC economic enablement, asset/network/FX hoặc settlement selection.
- WAL/hot-journal archives fail closed, không tự repair; cần operator xử lý writer
  activity ngoài diagnostic. No generic reconciliation feature được thêm.
- Bounded archive/body/output và local filesystem assumptions; không nhận remote paths
  hoặc linked paths. Concurrent malicious replacement/mode switching ngoài guarantee.
- Không tự tìm detail refs; operator phải cung cấp exact selected refs.
- Không production-readiness, real eligibility, acceptance hoặc reward earning claim.

## 11. Final status và next phase

**PASS - approved offline diagnostics scope, with the evidence/read-only limits above.**

Final summary: focused 208 passed (44 new + 164 regressions); full pytest 1520 passed;
Ruff lint passed; format 365 files already formatted; strict mypy passed in 272 files;
local empty/mixed demos exit 0, unchanged archive hash and file inventory.
No dependency introduced. No architecture deviation outside approved adapter/read-path scope.

Recommended next phase: operator review implementation/report và sử dụng diagnostic
trên exact retained captures được phép. Nếu feed vẫn rỗng, giữ honest EMPTY_FEED và
UNKNOWN_COVERAGE; không tạo opportunity giả. Candidate/reward/asset decision cần separate
checkpoint sau evidence thật. Không triển khai live discovery change/handoff/payment.

**Final Git status:**

```text
 M docs/superteam-source.md
 M src/agentmine/infrastructure/marketplaces/raw_archive.py
?? docs/audits/phase-b1-worker-superteam-readiness-audit.md
?? docs/audits/phase-b2-superteam-discovery-audit.md
?? docs/audits/phase-b3-discovery-diagnostics-design.md
?? docs/audits/phase-b3-discovery-diagnostics-implementation.md
?? src/agentmine/application/contracts/discovery_diagnostics.py
?? src/agentmine/application/ports/discovery_diagnostics.py
?? src/agentmine/application/use_cases/discovery_diagnostics.py
?? src/agentmine/bootstrap/discovery_diagnostics.py
?? src/agentmine/infrastructure/marketplaces/discovery_diagnostics.py
?? src/agentmine/presentation/discovery_diagnostics_cli.py
?? tests/contract/test_discovery_diagnostics.py
?? tests/integration/test_discovery_diagnostics_cli.py
?? tests/unit/application/test_discovery_diagnostic_contracts.py
```

Tracked changes: raw archive reader and operator documentation. New B.3 source/tests/report
are untracked. Three earlier audit/design reports remain pre-existing untracked files.
RawArchive.save() AST is unchanged relative to HEAD. No unrelated implementation file changed.

Không commit hoặc push.

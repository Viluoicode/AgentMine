> **Latest verdict — 2026-11-04: COMMIT_PLAN_READY.** Fixture byte-preservation prerequisite đã được operator duyệt, tạo và kiểm tra bằng lệnh chỉ đọc. Xem mục10. Các mục1–9 bên dưới giữ nguyên bằng chứng/plan lịch sử, gồm verdict BLOCKED trước khi có .gitattributes. READY không cấp approval staging/commit; staged-byte và checkout verification còn PENDING.

# B.4.3 Commit Preparation Gate — Safe Local Commit Plan

## 1. Verdict, HEAD và branch

**COMMIT_PLAN_BLOCKED** — cần giải quyết bảo toàn byte của golden fixtures trước khi staging/commit.

- HEAD: `7c660a8adfac07e408c3e3939988c9697770c204`.
- Branch: `main`.
- Workspace thực tế: `D:\DNTU\Tuhoc\AgentMine`.
- Đầu gate: **19 tracked modifications, 151 untracked files = 170 files**, chưa staged.
- Tracked diff: **19 files, 701 insertions, 21 deletions**. Ba source mới chưa nằm trong tracked diff.
- Final Acceptance: **ACCEPTANCE_PASS**, 0 BLOCKER/0 MAJOR/1 MINOR/2 INFORMATIONAL cho workflow local trên worktree. Gate này phát hiện rủi ro Git conversion riêng, không phủ nhận kết quả chạy trên worktree.
- Chỉ tạo report được yêu cầu này. Không sửa file hiện có, không stage/commit/push/reset/clean, không thay Git config, không tạo .gitattributes.

Đã đọc AGENTS.md, Product Constitution, Final Acceptance và đối chiếu approved B.4.2 design. Tất cả **169/169 baseline files** của acceptance audit giữ nguyên hash; acceptance report là file thứ170 được kiểm kê. Không chạy lại pytest trong gate chuẩn bị commit; các số **1801 full / 585 focused / 29 architecture** là bằng chứng của Final Acceptance, không phải kết quả chạy mới ở gate này.

## 2. Exact proposed file inventory

Danh sách dưới đây là allowlist chính xác, không phải glob hoặc directory staging. Các block chỉ khai báo mảng để operator dùng ở mục7, chưa được thực thi.

| Nhóm | Số file hiện tại đề xuất |
|---|---:|
| Production source | 22 |
| Tests và test-only helpers | 11 |
| Golden fixtures, manifests và fixture README | 129 |
| B.4.3 checkpoint/acceptance/commit-plan documentation | 7 |
| Context documentation có trước C1, đề xuất kèm rõ ràng | 2 |
| Tổng sau khi tạo report này | **171** |

Điều kiện bắt buộc chưa có trong worktree: **.gitattributes**, thêm riêng sau operator approval và review. Nếu giải pháp này được duyệt, inventory cuối sẽ là **172 files** (171 file liệt kê + một prerequisite). Không coi file chưa tồn tại là đã inspected hoặc đã được phép tạo. Kế hoạch phải được cập nhật/review khi prerequisite hoàn tất.

### 2.1. Production source — 22 files

Application contracts/use cases/pure workers/QA; Infrastructure chỉ codec/export; Presentation chỉ parser/view. Không Domain, AWS, marketplace adapter, budget policy, dependencies hay SQL transaction changes.

```powershell
$b43Source = @(
    'src/agentmine/application/contracts/data.py'
    'src/agentmine/application/contracts/data_revision.py'
    'src/agentmine/application/contracts/local_runtime.py'
    'src/agentmine/application/contracts/qa.py'
    'src/agentmine/application/contracts/runtime.py'
    'src/agentmine/application/contracts/worker_execution.py'
    'src/agentmine/application/ports/local_runtime.py'
    'src/agentmine/application/qa/checks.py'
    'src/agentmine/application/qa/partition_checks.py'
    'src/agentmine/application/use_cases/data_revision.py'
    'src/agentmine/application/use_cases/deliverable_qa.py'
    'src/agentmine/application/use_cases/local_runtime.py'
    'src/agentmine/application/use_cases/operational_qa.py'
    'src/agentmine/application/use_cases/worker_preflight.py'
    'src/agentmine/application/workers/data.py'
    'src/agentmine/application/workers/data_partition.py'
    'src/agentmine/application/workers/data_partition_artifacts.py'
    'src/agentmine/application/workers/data_transform.py'
    'src/agentmine/infrastructure/local_artifact_export.py'
    'src/agentmine/infrastructure/snapshots.py'
    'src/agentmine/presentation/runtime_inputs.py'
    'src/agentmine/presentation/runtime_views.py'
)
```

### 2.2. Tests và test-only helpers — 11 files

```powershell
$b43Tests = @(
    'tests/integration/test_partition_artifact_runtime.py'
    'tests/integration/test_partition_core_persistence.py'
    'tests/integration/test_partition_operational_qa.py'
    'tests/integration/test_partition_runtime_e2e.py'
    'tests/integration/test_partition_snapshot_compatibility.py'
    'tests/integration/test_partition_worker_artifacts.py'
    'tests/unit/application/partition_artifact_fakes.py'
    'tests/unit/application/partition_e2e_fakes.py'
    'tests/unit/application/partition_qa_fakes.py'
    'tests/unit/application/test_data_partition.py'
    'tests/unit/application/test_partition_contracts.py'
)
```

### 2.3. Golden fixtures — 129 files

Bao gồm inputs, literal expected outputs, historical snapshot fixtures, hash manifests và README provenance. Đây là fixtures có chủ đích; không phải generated runtime outputs từ workspace vận hành.

```powershell
$b43Fixtures = @(
    'tests/contract/fixtures/data_partition/README.md'
    'tests/contract/fixtures/data_partition/data_cell-v1.json'
    'tests/contract/fixtures/data_partition/data_plan-v1.json'
    'tests/contract/fixtures/data_partition/data_result-v1.json'
    'tests/contract/fixtures/data_partition/independent-oracles.json'
    'tests/contract/fixtures/data_partition/optional-null-inspection-v1.json'
    'tests/contract/fixtures/data_partition/qa_inspection-v1.json'
    'tests/contract/fixtures/data_partition/sha256.json'
    'tests/contract/fixtures/data_partition/work_specification-v1.json'
    'tests/contract/fixtures/data_partition_c2/README.md'
    'tests/contract/fixtures/data_partition_c2/oracles.json'
    'tests/contract/fixtures/data_partition_c3/README.md'
    'tests/contract/fixtures/data_partition_c3/all_invalid/clean.csv'
    'tests/contract/fixtures/data_partition_c3/all_invalid/clean.json'
    'tests/contract/fixtures/data_partition_c3/all_invalid/rejected.json'
    'tests/contract/fixtures/data_partition_c3/all_invalid/validation.json'
    'tests/contract/fixtures/data_partition_c3/all_valid/clean.csv'
    'tests/contract/fixtures/data_partition_c3/all_valid/clean.json'
    'tests/contract/fixtures/data_partition_c3/all_valid/rejected.json'
    'tests/contract/fixtures/data_partition_c3/all_valid/validation.json'
    'tests/contract/fixtures/data_partition_c3/batch_count/clean.csv'
    'tests/contract/fixtures/data_partition_c3/batch_count/clean.json'
    'tests/contract/fixtures/data_partition_c3/batch_count/rejected.json'
    'tests/contract/fixtures/data_partition_c3/batch_count/validation.json'
    'tests/contract/fixtures/data_partition_c3/cases.json'
    'tests/contract/fixtures/data_partition_c3/cross_source/clean.csv'
    'tests/contract/fixtures/data_partition_c3/cross_source/clean.json'
    'tests/contract/fixtures/data_partition_c3/cross_source/rejected.json'
    'tests/contract/fixtures/data_partition_c3/cross_source/validation.json'
    'tests/contract/fixtures/data_partition_c3/csv_duplicates/clean.csv'
    'tests/contract/fixtures/data_partition_c3/csv_duplicates/clean.json'
    'tests/contract/fixtures/data_partition_c3/csv_duplicates/rejected.json'
    'tests/contract/fixtures/data_partition_c3/csv_duplicates/validation.json'
    'tests/contract/fixtures/data_partition_c3/csv_missing_header/clean.csv'
    'tests/contract/fixtures/data_partition_c3/csv_missing_header/clean.json'
    'tests/contract/fixtures/data_partition_c3/csv_missing_header/rejected.json'
    'tests/contract/fixtures/data_partition_c3/csv_missing_header/validation.json'
    'tests/contract/fixtures/data_partition_c3/duplicate_and_error/clean.csv'
    'tests/contract/fixtures/data_partition_c3/duplicate_and_error/clean.json'
    'tests/contract/fixtures/data_partition_c3/duplicate_and_error/rejected.json'
    'tests/contract/fixtures/data_partition_c3/duplicate_and_error/validation.json'
    'tests/contract/fixtures/data_partition_c3/empty/clean.csv'
    'tests/contract/fixtures/data_partition_c3/empty/clean.json'
    'tests/contract/fixtures/data_partition_c3/empty/rejected.json'
    'tests/contract/fixtures/data_partition_c3/empty/validation.json'
    'tests/contract/fixtures/data_partition_c3/formula_and_quoting/clean.csv'
    'tests/contract/fixtures/data_partition_c3/formula_and_quoting/clean.json'
    'tests/contract/fixtures/data_partition_c3/formula_and_quoting/rejected.json'
    'tests/contract/fixtures/data_partition_c3/formula_and_quoting/validation.json'
    'tests/contract/fixtures/data_partition_c3/invalid_ids_not_grouped/clean.csv'
    'tests/contract/fixtures/data_partition_c3/invalid_ids_not_grouped/clean.json'
    'tests/contract/fixtures/data_partition_c3/invalid_ids_not_grouped/rejected.json'
    'tests/contract/fixtures/data_partition_c3/invalid_ids_not_grouped/validation.json'
    'tests/contract/fixtures/data_partition_c3/lookup_provenance/clean.csv'
    'tests/contract/fixtures/data_partition_c3/lookup_provenance/clean.json'
    'tests/contract/fixtures/data_partition_c3/lookup_provenance/rejected.json'
    'tests/contract/fixtures/data_partition_c3/lookup_provenance/validation.json'
    'tests/contract/fixtures/data_partition_c3/malformed_csv/validation.json'
    'tests/contract/fixtures/data_partition_c3/malformed_non_object/validation.json'
    'tests/contract/fixtures/data_partition_c3/missing_null_blank_ids/clean.csv'
    'tests/contract/fixtures/data_partition_c3/missing_null_blank_ids/clean.json'
    'tests/contract/fixtures/data_partition_c3/missing_null_blank_ids/rejected.json'
    'tests/contract/fixtures/data_partition_c3/missing_null_blank_ids/validation.json'
    'tests/contract/fixtures/data_partition_c3/mixed/clean.csv'
    'tests/contract/fixtures/data_partition_c3/mixed/clean.json'
    'tests/contract/fixtures/data_partition_c3/mixed/rejected.json'
    'tests/contract/fixtures/data_partition_c3/mixed/validation.json'
    'tests/contract/fixtures/data_partition_c3/negative_numeric_allowed/clean.csv'
    'tests/contract/fixtures/data_partition_c3/negative_numeric_allowed/clean.json'
    'tests/contract/fixtures/data_partition_c3/negative_numeric_allowed/rejected.json'
    'tests/contract/fixtures/data_partition_c3/negative_numeric_allowed/validation.json'
    'tests/contract/fixtures/data_partition_c3/nested_presence/clean.csv'
    'tests/contract/fixtures/data_partition_c3/nested_presence/clean.json'
    'tests/contract/fixtures/data_partition_c3/nested_presence/rejected.json'
    'tests/contract/fixtures/data_partition_c3/nested_presence/validation.json'
    'tests/contract/fixtures/data_partition_c3/optional_invalid/clean.csv'
    'tests/contract/fixtures/data_partition_c3/optional_invalid/clean.json'
    'tests/contract/fixtures/data_partition_c3/optional_invalid/rejected.json'
    'tests/contract/fixtures/data_partition_c3/optional_invalid/validation.json'
    'tests/contract/fixtures/data_partition_c3/optional_null_and_blank/clean.csv'
    'tests/contract/fixtures/data_partition_c3/optional_null_and_blank/clean.json'
    'tests/contract/fixtures/data_partition_c3/optional_null_and_blank/rejected.json'
    'tests/contract/fixtures/data_partition_c3/optional_null_and_blank/validation.json'
    'tests/contract/fixtures/data_partition_c3/partial_malformed/validation.json'
    'tests/contract/fixtures/data_partition_c3/sha256.json'
    'tests/contract/fixtures/data_partition_c3/three_duplicates/clean.csv'
    'tests/contract/fixtures/data_partition_c3/three_duplicates/clean.json'
    'tests/contract/fixtures/data_partition_c3/three_duplicates/rejected.json'
    'tests/contract/fixtures/data_partition_c3/three_duplicates/validation.json'
    'tests/contract/fixtures/data_partition_c3/two_duplicates/clean.csv'
    'tests/contract/fixtures/data_partition_c3/two_duplicates/clean.json'
    'tests/contract/fixtures/data_partition_c3/two_duplicates/rejected.json'
    'tests/contract/fixtures/data_partition_c3/two_duplicates/validation.json'
    'tests/contract/fixtures/data_partition_c3/two_groups_order/clean.csv'
    'tests/contract/fixtures/data_partition_c3/two_groups_order/clean.json'
    'tests/contract/fixtures/data_partition_c3/two_groups_order/rejected.json'
    'tests/contract/fixtures/data_partition_c3/two_groups_order/validation.json'
    'tests/contract/fixtures/data_partition_c3/unicode_group/clean.csv'
    'tests/contract/fixtures/data_partition_c3/unicode_group/clean.json'
    'tests/contract/fixtures/data_partition_c3/unicode_group/rejected.json'
    'tests/contract/fixtures/data_partition_c3/unicode_group/validation.json'
    'tests/contract/fixtures/data_partition_c4/README.md'
    'tests/contract/fixtures/data_partition_c4/qa-expectations.json'
    'tests/contract/fixtures/data_partition_c4/sha256.json'
    'tests/contract/fixtures/data_partition_c5/README.md'
    'tests/contract/fixtures/data_partition_c5/catalog-schema.json'
    'tests/contract/fixtures/data_partition_c5/complete-input.json'
    'tests/contract/fixtures/data_partition_c5/complete/clean.csv'
    'tests/contract/fixtures/data_partition_c5/complete/clean.json'
    'tests/contract/fixtures/data_partition_c5/complete/rejected.json'
    'tests/contract/fixtures/data_partition_c5/complete/validation.json'
    'tests/contract/fixtures/data_partition_c5/control-input.json'
    'tests/contract/fixtures/data_partition_c5/control/clean.csv'
    'tests/contract/fixtures/data_partition_c5/control/clean.json'
    'tests/contract/fixtures/data_partition_c5/control/rejected.json'
    'tests/contract/fixtures/data_partition_c5/control/validation.json'
    'tests/contract/fixtures/data_partition_c5/dirty-input.json'
    'tests/contract/fixtures/data_partition_c5/dirty/clean.csv'
    'tests/contract/fixtures/data_partition_c5/dirty/clean.json'
    'tests/contract/fixtures/data_partition_c5/dirty/rejected.json'
    'tests/contract/fixtures/data_partition_c5/dirty/validation.json'
    'tests/contract/fixtures/data_partition_c5/facts.json'
    'tests/contract/fixtures/data_partition_c5/legacy-complete/data.csv'
    'tests/contract/fixtures/data_partition_c5/legacy-complete/data.json'
    'tests/contract/fixtures/data_partition_c5/legacy-complete/validation.json'
    'tests/contract/fixtures/data_partition_c5/malformed-input.json'
    'tests/contract/fixtures/data_partition_c5/malformed/validation.json'
    'tests/contract/fixtures/data_partition_c5/scenarios.json'
    'tests/contract/fixtures/data_partition_c5/sha256.json'
)
```

### 2.4. B.4.3 audit documentation — 7 files

```powershell
$b43AuditDocs = @(
    'docs/audits/phase-b4-3-c1-contracts-snapshots.md'
    'docs/audits/phase-b4-3-c2-partition-core.md'
    'docs/audits/phase-b4-3-c3-worker-artifacts-persistence.md'
    'docs/audits/phase-b4-3-c4-operational-qa-acceptance.md'
    'docs/audits/phase-b4-3-c5-runtime-e2e.md'
    'docs/audits/phase-b4-3-commit-plan.md'
    'docs/audits/phase-b4-3-final-acceptance.md'
)
```

### 2.5. Pre-C1 context documentation — 2 files, inclusion có chủ đích

Hai file này **đã tồn tại trước C1**, không phải implementation B.4.3 mới:

- B.4.1 ghi baseline mô phỏng và client failure ban đầu.
- B.4.2 ghi approved design mà source và acceptance report dẫn chiếu.

Đề xuất kèm cả hai để commit tự chứa baseline/design cần review. Đây là lựa chọn tài liệu minh bạch cần operator duyệt cùng plan; không gán chúng cho C1–C5. Hash không đổi so với baseline acceptance/C5. Nếu operator muốn commit riêng hai file này, cần cập nhật allowlist và kiểm tra lại staged scope; không tự ý thêm/bớt.

```powershell
$b43ContextDocs = @(
    'docs/audits/phase-b4-realistic-bounty-simulation.md'
    'docs/audits/phase-b4-2-deliverable-contract-qa-design.md'
)
```

## 3. Exclusions và sensitive-file inspection

Không đưa các nhóm sau vào allowlist:

- Secrets/credentials: .env, .env.*, .aws/, credential stores, private keys, token/key files; .env.example hiện không thay đổi và không nằm trong scope.
- Local databases và sidecars: *.db, *.sqlite, *.sqlite3, *-wal, *-shm, raw archives hoặc workspace databases.
- Toàn bộ .tmp/, gồm final-acceptance probes/SQLite/transcripts/logs, C5 evidence và newline before/after hash record.
- .venv/, __pycache__/, *.pyc, .pytest_cache/, .mypy_cache/, .ruff_cache/, coverage/build/dist và runtime exports.
- File ngoài exact allowlist, dependency lock/config changes, source không liên quan và Git internals.

Đã inspect tên/type/size của mọi candidate trước khi đọc nội dung. Không candidate có tên nhạy cảm hoặc nonregular/reparse/binary; không mở secret files, environment secrets hay credential stores. .env/.aws không có ở workspace theo metadata; điều đó không khẳng định mọi nơi trên máy đều không có secret.

Toàn bộ170 candidates được decode UTF-8 và đọc để kiểm tra; Python AST parse, CSV strict parse và JSON parse được kiểm tra theo loại. **malformed-input.json** là ngoại lệ JSON có chủ đích theo negative fixture, không phải file lỗi ngoài scope. Scanner kiểm private-key headers, AWS access-key shape, GitHub token shape và long literal secret assignments; chỉ xuất nhãn/path nếu gặp, không in matching values. Kết quả **0 alerts**, không đồng nghĩa chứng nhận nhận diện mọi định dạng credential.

Ignored metadata inventory thấy ít nhất **12772 entries**; Git cảnh báo permission denied với .pytest_cache và một số .tmp test directories. Không mở nội dung hay tìm cách vượt quyền các thư mục đó. Việc exclusions dùng allowlist và không dùng -f vẫn áp dụng toàn bộ, dù không enumerate được mọi ignored entry.

Fresh filename/type/size check:

- 170 files trước report: **847745 bytes** tổng, không có file >1000000 bytes.
- File lớn nhất: Final Acceptance report **43517 bytes**; cases.json C3 **38527 bytes**; B.4.2 **38495 bytes**; B.4.1 **30694 bytes**; C2 oracle **30527 bytes**.
- Chỉ .py/.md/.json/.csv; không unexpected binaries, links, archives hoặc runtime DBs trong candidates.
- Manifests C1/C3/C4/C5: **7/88/1/23 entries**, đều khớp hiện tại; whole C2 oracle SHA khớp documented hash.
- Không có tracked changes trong Domain hoặc pyproject.toml.

## 4. Blocker: Git line-ending conversion phá golden bytes

Read-only metadata:

- core.autocrlf = **true**; core.eol và core.safecrlf không có explicit value ở scope đã query.
- Không có .gitattributes tracked hoặc untracked.
- text/eol/filter/working-tree-encoding của representative fixtures đều **unspecified**.

Reproduction không ghi object/index (không dùng hash-object -w):

```powershell
git config --get core.autocrlf
git check-attr text eol filter working-tree-encoding -- tests/contract/fixtures/data_partition_c5/control-input.json
git hash-object --no-filters tests/contract/fixtures/data_partition_c5/control-input.json
git hash-object --path=tests/contract/fixtures/data_partition_c5/control-input.json tests/contract/fixtures/data_partition_c5/control-input.json
```

Observed:

- Raw Git blob ID: **c9b3489a47d4e1c8a467fdba197e07e1f3e197e0**.
- Git clean-filtered blob ID: **1c4cdc66dc0d022c50b8b7ae63ec1eaf0501015e**.
- Raw input có17 CRLF; raw SHA-256 khớp approved manifest; CRLF→LF SHA-256 không khớp.

**9 manifest-protected files** bị clean conversion thay byte:

```text
tests/contract/fixtures/data_partition/data_cell-v1.json
tests/contract/fixtures/data_partition/independent-oracles.json
tests/contract/fixtures/data_partition_c3/cases.json
tests/contract/fixtures/data_partition_c4/qa-expectations.json
tests/contract/fixtures/data_partition_c5/catalog-schema.json
tests/contract/fixtures/data_partition_c5/complete-input.json
tests/contract/fixtures/data_partition_c5/control-input.json
tests/contract/fixtures/data_partition_c5/dirty-input.json
tests/contract/fixtures/data_partition_c5/scenarios.json
```

C2 oracle toàn file cũng có CRLF và documented byte hash cần giữ. Ngược lại, nhiều artifact golden v2 đang LF và có thể bị checkout autocrlf chuyển thành CRLF. Do đó chỉ bỏ qua warning hoặc chỉ chạy git -c core.autocrlf=false add một lần không tạo repository-level protection cho các checkout sau.

### Minimum required remediation — chỉ là đề xuất cần approval

Operator duyệt một thay đổi riêng, hẹp cho .gitattributes để **giữ nguyên exact bytes**, ví dụ:

```gitattributes
tests/contract/fixtures/data_partition/** -text
tests/contract/fixtures/data_partition_c2/** -text
tests/contract/fixtures/data_partition_c3/** -text
tests/contract/fixtures/data_partition_c4/** -text
tests/contract/fixtures/data_partition_c5/** -text
```

Không dùng text eol=lf cho toàn fixtures, không rewrite old CRLF, không đổi expected hashes/goldens để khớp Git conversion. -text tắt EOL conversion, không tự áp đặt binary diff; text review vẫn thực hiện được. Verify attrs cho toàn129 fixture paths, verify no clean filter/encoding transform, giữ raw hashes/manifest, kiểm staged blob bytes và checkout/readback trong môi trường cô lập sau khi được duyệt.

Sau khi prerequisite được implement/review đúng scope, revalidate allowlist và cập nhật verdict trước staging. Gate hiện tại không tạo file này và không chỉnh local/global Git settings.

## 5. Scope alignment và remaining risks

| Approved B.4.2 / Acceptance | Proposed scope |
|---|---|
| Explicit v2; None vẫn v1; frozen thresholds/ID policy | contracts, strict CLI parser và immutable binding |
| Full-group REJECT_ALL, provenance/presence/conservation | partition core + literal oracles |
| Complete4 / incomplete validation-only | versioned renderer, WorkerResult, persistence/recovery tests |
| QA replay từ frozen sources, zero-clean/global gates | operational QA/checkers + hostile fixtures |
| Local execution, SCOUT_ONLY/zero AI, safe export | existing use cases, port metadata và adapter |
| Legacy behavior/history không migrate | snapshots, old golden fixtures và revision guards |
| No paid/live/submission/payment/AWS expansion | Không file hoặc provider tương ứng trong proposal |
| Audited limitation M01 | Giữ nonblocking thiếu summary work status; không tự sửa feature |

Thiết kế đề xuất sửa legacy renderer nhưng implementation tách renderer v2 mới để giữ v1; Acceptance đã review. Một temporary reason enum vẫn tồn tại và các guard probes đã được cập nhật theo C5; không có refactor ngoài scope được thêm ở gate này.

Risks cần operator biết: line endings là **blocking** cho commit preparation; M01 là **nonblocking** runtime diagnostic; fixtures/manifests chưa có external provenance attestation; golden digests là input integrity, không authenticated marketplace facts. Local commit không chứng minh bounty eligibility, client acceptance, revenue hay production readiness.

## 6. Proposed conventional commit message

```text
feat(data): add opt-in partitioned deliverables and offline QA workflow
```

Một commit logic cho C1–C5 tích lũy cùng tests/goldens và evidence docs. Nếu .gitattributes prerequisite được duyệt kèm, mục đích là giữ immutable fixture bytes của chính feature này, không đổi policy cho repository còn lại.

## 7. Exact PowerShell commands — REQUIRE OPERATOR APPROVAL, NOT EXECUTED

**Không chạy ở verdict hiện tại.** Các lệnh staging/commit dưới đây chỉ dùng sau explicit approval, prerequisite EOL protection được review và plan chuyển READY. Không dùng git add ., git add -A, directory staging, wildcard staging, -f, reset hoặc clean.

Chạy các mảng exact inventory ở mục2 trong cùng PowerShell session. Mỗi mảng là danh sách file đầy đủ; chúng không tự stage.

### 7.1. Preflight và selective staging có guard

```powershell
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath 'D:\DNTU\Tuhoc\AgentMine'

# Current plan is BLOCKED. Change these only after a reviewed READY plan + approval.
$b43PlanVerdict = 'COMMIT_PLAN_BLOCKED'
$b43OperatorApproved = $false
if ($b43PlanVerdict -ne 'COMMIT_PLAN_READY' -or -not $b43OperatorApproved) {
    throw 'STOP: commit preparation blocker or operator approval unresolved.'
}

$b43ExpectedHead = '7c660a8adfac07e408c3e3939988c9697770c204'
$b43ActualHead = git rev-parse HEAD
if ($LASTEXITCODE -ne 0 -or $b43ActualHead -ne $b43ExpectedHead) {
    throw 'HEAD changed; review plan again.'
}
$b43Branch = git branch --show-current
if ($LASTEXITCODE -ne 0 -or $b43Branch -ne 'main') {
    throw 'Branch changed; review plan again.'
}
$b43AlreadyStaged = @(git diff --cached --name-only)
if ($LASTEXITCODE -ne 0 -or $b43AlreadyStaged.Count -ne 0) {
    throw 'Existing staged changes; stop without modifying the index.'
}

# Define b43Source/Tests/Fixtures/AuditDocs/ContextDocs exactly as section 2.
$b43ReviewedFiles = @($b43Source + $b43Tests + $b43Fixtures + $b43AuditDocs + $b43ContextDocs)
if ($b43Source.Count -ne 22 -or $b43Tests.Count -ne 11 -or
    $b43Fixtures.Count -ne 129 -or $b43AuditDocs.Count -ne 7 -or
    $b43ContextDocs.Count -ne 2 -or $b43ReviewedFiles.Count -ne 171) {
    throw 'Missing or changed allowlist.'
}

# Conditional prerequisite: not created or approved by the current plan.
if (-not (Test-Path -LiteralPath '.gitattributes' -PathType Leaf)) {
    throw 'Approved fixture-byte protection is missing.'
}
$b43Files = @($b43ReviewedFiles + '.gitattributes')
if (@($b43Files | Sort-Object -Unique).Count -ne 172) {
    throw 'Duplicate or changed inventory.'
}
foreach ($b43Path in $b43Files) {
    if (-not (Test-Path -LiteralPath $b43Path -PathType Leaf)) {
        throw "Missing reviewed file: $b43Path"
    }
}

$b43TextAttrs = @(git check-attr text -- $b43Fixtures)
if ($LASTEXITCODE -ne 0 -or $b43TextAttrs.Count -ne 129 -or
    @($b43TextAttrs | Where-Object { -not $_.EndsWith(': text: unset') }).Count -ne 0) {
    throw 'Fixture EOL conversion is not disabled for every reviewed path.'
}
$b43OtherAttrs = @(git check-attr filter working-tree-encoding -- $b43Fixtures)
if ($LASTEXITCODE -ne 0 -or $b43OtherAttrs.Count -ne 258 -or
    @($b43OtherAttrs | Where-Object { -not $_.EndsWith(': unspecified') }).Count -ne 0) {
    throw 'Unexpected fixture filter or encoding transform.'
}

git status --short --untracked-files=all
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect worktree.' }
git diff --stat
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect tracked diff.' }
git diff --check
if ($LASTEXITCODE -ne 0) { throw 'Tracked diff check failed.' }

# This is the first mutation; it requires the approvals above.
git --literal-pathspecs add -- $b43Files
if ($LASTEXITCODE -ne 0) {
    throw 'Staging failed. Inspect the index; do not auto-reset or retry blindly.'
}
```

### 7.2. Staged-diff inspection và exact byte verification

```powershell
$b43Staged = @(git -c core.quotepath=false diff --cached --name-only)
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect staged inventory.' }
$b43ScopeMismatch = @(Compare-Object ($b43Files | Sort-Object) ($b43Staged | Sort-Object))
if ($b43ScopeMismatch.Count -ne 0) {
    $b43ScopeMismatch
    throw 'Staged scope differs from approved exact allowlist.'
}

git diff --cached --stat
if ($LASTEXITCODE -ne 0) { throw 'Staged stat failed.' }
git diff --cached --name-status
if ($LASTEXITCODE -ne 0) { throw 'Staged name/status failed.' }
git diff --cached --numstat
if ($LASTEXITCODE -ne 0) { throw 'Staged numstat failed.' }
git diff --cached --check
if ($LASTEXITCODE -ne 0) {
    throw 'Staged whitespace/EOL check failed; stop for review, do not normalize golden files.'
}
git --no-pager diff --cached --no-ext-diff --no-textconv
if ($LASTEXITCODE -ne 0) { throw 'Staged diff review failed.' }

# No -w: hash-object is read-only. Check all fixture bytes including manifests.
foreach ($b43Fixture in $b43Fixtures) {
    $b43RawBlob = git hash-object --no-filters -- $b43Fixture
    if ($LASTEXITCODE -ne 0) { throw "Raw hash failed: $b43Fixture" }
    $b43IndexBlob = git rev-parse ":$b43Fixture"
    if ($LASTEXITCODE -ne 0 -or $b43RawBlob -ne $b43IndexBlob) {
        throw "Fixture bytes changed during staging: $b43Fixture"
    }
}
git status --short --untracked-files=all
if ($LASTEXITCODE -ne 0) { throw 'Final status failed.' }
```

Operator review actual staged diff, all fixtures/manifests, prerequisite .gitattributes và exclusions. Nếu staged diff check nêu CR-at-EOL trên intentional frozen CRLF, dừng để review cấu hình whitespace phù hợp; không đổi bytes/hash hoặc bỏ check để ép commit. Gate này chưa kiểm được staged data vì không được phép tạo index changes.

### 7.3. Local commit — separate approval after staged review

```powershell
# Run only after all prior checks and explicit staged-diff approval.
$b43CommitApproval = Read-Host 'Type COMMIT only after reviewing and approving the exact staged diff'
if ($b43CommitApproval -cne 'COMMIT') {
    throw 'Local commit not approved.'
}
git commit -m 'feat(data): add opt-in partitioned deliverables and offline QA workflow'
if ($LASTEXITCODE -ne 0) {
    throw 'Commit failed. Inspect the reported reason; do not bypass hooks or auto-reset.'
}
git status --short
git log -1 --oneline
```

Không có push command. Các lệnh trên là đề xuất có điều kiện, không được execute trong checkpoint này.

## 8. Commands đã thực hiện và limitations

Read-only: git rev-parse HEAD, branch --show-current, status --short --untracked-files=all, diff --stat/--numstat/--name-status/full tracked diff, diff --cached --name-only (rỗng), diff --check (exit0), config --get core.autocrlf/eol/safecrlf, check-attr, hash-object không -w, check-ignore và ls-files metadata. Query config chưa set có thể exit1 theo Git semantics, không phải test failure.

Python stdin read-only kiểm kê toàn170 candidates, hash/type/size/UTF-8/AST/JSON/CSV/secret-pattern checks; bước đầu JSON validation gặp expected malformed fixture, sau đó phân loại rõ negative fixture và rerun inventory thành công. Không sửa fixture để parser pass.

Không stage nên chưa có staged blob, local commit, checkout verification hoặc new pytest execution. Permission-denied warnings khi liệt kê ignored metadata đã được công khai ở mục3, không ảnh hưởng exact candidate enumeration. Không viết probe/log/cache mới; file duy nhất tạo là report này.

## 9. Operator decision required

**COMMIT_PLAN_BLOCKED** vì conversion risk có reproduction trực tiếp, dù workflow Final Acceptance là ACCEPTANCE_PASS.

Đề nghị operator duyệt scope .gitattributes preservation riêng, sau đó revalidate hashes/attributes/staged-byte/checkout semantics và cập nhật plan sang READY. Đồng thời review việc kèm hai pre-C1 context reports và nonblocking M01. Không cần thay đổi business behavior hay regenerate oracle.

Dừng tại đây, chờ operator approval. Không stage, commit, push, reset hoặc clean.

## 10. Fixture Byte Preservation Verification — latest authoritative status

### 10.1. Operator-approved scope và resolution

**Latest verdict: COMMIT_PLAN_READY.** Operator chỉ duyệt tạo đúng5 fixture-only .gitattributes rules, verification, cập nhật plan và tạo report. Chưa có staging/commit/push approval.

HEAD `7c660a8adfac07e408c3e3939988c9697770c204`, branch main và original171 allowlist khớp reviewed plan. **169/169** acceptance baseline files nguyên hash trước/sau gate. Không conflict. Git config giữ nguyên: core.autocrlf=true, core.eol/core.safecrlf unset.

File .gitattributes được tạo UTF-8 no-BOM, LF, đúng nội dung:

```gitattributes
tests/contract/fixtures/data_partition/** -text
tests/contract/fixtures/data_partition_c2/** -text
tests/contract/fixtures/data_partition_c3/** -text
tests/contract/fixtures/data_partition_c4/** -text
tests/contract/fixtures/data_partition_c5/** -text
```

Không normalization, rewrite hoặc regeneration fixture. Rủi ro clean conversion ở mục4 đã được giải quyết bằng thuộc tính -text, không bằng đổi hashes/expected bytes. Original blocker evidence và commands tại mục1–9 được giữ nguyên để audit.

### 10.2. Read-only verification đã chạy

- Exact raw .gitattributes bytes bằng literal5-rule content, không BOM/global rules.
- `git check-attr -z text filter working-tree-encoding -- <each-fixture>` cho toàn129 reviewed paths: text unset; filter và encoding unspecified; mọi call exit0.
- `git hash-object --no-filters -- <each-fixture>` so với `git hash-object --path=<each-fixture> -- <each-fixture>`: **129/129 equal**, mọi call exit0; không -w.
- `git check-attr --all -z --stdin` trước/sau trên534 repo paths: đúng129 fixture text attributes mới; **405 unrelated paths không đổi**. Control paths outside approved dirs cũng không đổi attributes.
- SHA-256 manifests C1/C3/C4/C5: **7/88/1/23 entries PASS**. Whole C2 oracle hash giữ `6deaf129e37db2375622cc247b9abae686da96c140db9f784d90fc11885dda5a`.
- **169/169 Final Acceptance baseline files unchanged**; trước update docs **171/171** pre-gate files giữ nguyên. Sau update, commit-plan.md là existing file duy nhất thay đổi, đúng user yêu cầu;170 file khác giữ hash.
- core.autocrlf/eol/safecrlf chỉ query, không set. HEAD/branch không đổi, index rỗng.

Detailed per-file129 raw/clean hashes, phương pháp và limitations: `docs/audits/phase-b4-3-fixture-byte-preservation.md`.

Probe summary đầu có lỗi biến config/configs trong stdin serialization; đã sửa câu probe read-only và rerun toàn bộ129 checks. Không sửa fixtures/tests/production để PASS.

### 10.3. Fresh regression/static evidence

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -m pytest tests/unit/application/test_partition_contracts.py tests/integration/test_partition_snapshot_compatibility.py tests/unit/application/test_data_partition.py tests/integration/test_partition_core_persistence.py tests/integration/test_partition_worker_artifacts.py tests/integration/test_partition_artifact_runtime.py tests/integration/test_partition_operational_qa.py tests/integration/test_partition_runtime_e2e.py -q --tb=short -p no:cacheprovider
.\.venv\Scripts\python.exe -B -m ruff check . --no-cache
.\.venv\Scripts\python.exe -B -m ruff format --check . --no-cache
$b43PreservationCache = Join-Path ([IO.Path]::GetTempPath()) 'agentmine-fixture-preservation-mypy'
.\.venv\Scripts\python.exe -B -m mypy --strict --cache-dir $b43PreservationCache
git diff --check
git diff --cached --name-only
git status --short --untracked-files=all
```

Results: **281 passed in 97.18s**, exit0; Ruff exit0 PASS; format exit0 **394 files already formatted**; strict mypy exit0 **286 source files**, no issues; diff check exit0; cached names rỗng; status exit0. Không full pytest rerun trong prerequisite-only gate; không gán historical1801 thành fresh result. Các test groups overlap, không cộng tổng.

### 10.4. Exact172 scope reconciliation

Original arrays tại mục2 giữ nguyên **171 unique paths**. Scope đề xuất chính xác:

```powershell
# Proposal only: not executed, staging approval remains outstanding.
$b43Files = @($b43Source + $b43Tests + $b43Fixtures + $b43AuditDocs + $b43ContextDocs + '.gitattributes')
# Expected: 172 distinct paths; validate with section 7 guards after approval.
```

22 production +11 tests/helpers +129 fixtures +7 B.4.3 docs +2 pre-C1 context reports +1 .gitattributes = **172**. Hai reports B.4.1/B.4.2 có trước C1 được kèm có chủ đích. Không secrets/credentials, DBs/sidecars, .tmp evidence, caches hoặc generated runtime exports.

Report mới `docs/audits/phase-b4-3-fixture-byte-preservation.md` là required deliverable **ngoài allowlist172**, chưa đề xuất staging nó. Do đó worktree có173 changed/untracked paths sau gate, với đúng1 known authorized extra. Nếu operator muốn kèm report này, cần duyệt inventory173 riêng; không tự mở scope.

M01 thiếu status partition summary giữ nguyên nonblocking finding. Không thêm unrelated source changes hoặc sửa production/test behavior.

### 10.5. Safe staging plan và outstanding approval gates

Plan mục7 vẫn là exact selective staging plan. Historical `$b43PlanVerdict = 'COMMIT_PLAN_BLOCKED'` và `$b43OperatorApproved = $false` trong example được giữ nguyên, nên copy chạy sẽ dừng an toàn. Chỉ sau **explicit staging approval** và review latest READY evidence, operator mới điều chỉnh verdict guard thành COMMIT_PLAN_READY và xác nhận approval cho lần chạy đó. Gate này chưa thay approval flag hoặc execute bất kỳ lệnh staging/commit nào.

**PENDING, không báo PASS**:

1. Actual staged scope172 và staged .gitattributes content.
2. Actual staged blob hash bằng raw bytes cho toàn129 fixtures.
3. Staged whitespace/full diff review; nếu intentional CRLF gây check, dừng review, không normalize fixture hay nới oracle.
4. Authorized isolated checkout/readback byte/hash verification.
5. Separate local commit approval sau staged-diff review. Không có push authorization.

Read-only prerequisite đã PASS đủ để plan READY theo gate được duyệt, không đồng nghĩa index/checkout đã kiểm. Config/HEAD/branch/worktree khác sau review phải revalidate.

### 10.6. Final recommendation

**COMMIT_PLAN_READY** cho operator consideration của exact172-file local commit scope. Dừng chờ operator review; chưa stage/commit/push/reset/clean.

Files tạo/sửa trong prerequisite checkpoint: `.gitattributes` mới; commit-plan.md này cập nhật; fixture-byte-preservation.md mới ngoài proposal172. Không sửa các169 baseline files, fixture manifests/goldens hay Git config. Không new dependencies, business behavior hoặc live external action.

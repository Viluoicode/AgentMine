# Phase B.4.3-C2 — Deterministic Partition Core & Duplicate Policy A

## 1. Executive Summary

C2 triển khai **pure deterministic partition core**, dùng production transform/validate và typed assessment C1. Policy A loại mọi thành viên có cùng ID hợp lệ sau chuẩn hóa, bao gồm occurrence đầu. Không triển khai C3/C4/C5: chưa có v2 artifacts, operational QA, CLI opt-in hoặc production workflow v2.

Base commit: `7c660a8adfac07e408c3e3939988c9697770c204`. C1 đang là worktree chưa commit khi bắt đầu. Đã ghi checksum và xác nhận giữ nguyên 25 file C1/source/report/fixture có sẵn; không revert/clean/stage/commit/push.

Fresh checks đã hoàn tất: **34 C2 tests passed**, **198 tests passed** trong regression selection; Ruff/format/strict mypy PASS. Full-suite mới: **1608 passed in 714.11s**, exit 0. C1 historical numbers không dùng làm fresh C2 verification.

## 2. Approved Scope

- Opt-in v2; output_policy=None vẫn legacy v1.
- REJECT_ALL trên valid canonical IDs qua toàn approved batch; không first/last wins hoặc nhóm null giả.
- Mọi parsed record, original value sau normalization, actual issue và provenance được giữ; không impute/repair invalid values.
- Capture MISSING/NULL/VALUE trước normalize; blank vẫn VALUE.
- Pure computation và isolated persistence tests; không gỡ runtime guard hoặc enable v2 QA.
- Không đổi budget/authorization, journal transactions, Domain lifecycle, eligibility/reward, marketplace/provider; không thêm dependencies/migration.

## 3. Test-First RED Evidence

Trước production changes, tạo `tests/contract/fixtures/data_partition_c2/oracles.json`: 20 bộ input/expected literal. Không import AgentMine, gọi DataWorker, transform hay partition để sinh expected normalized values/memberships/issues. Golden JSON/hash được chuẩn bị độc lập bằng stdlib json/hashlib theo serialization spec được ghi ở mục 5.

Oracle SHA-256 trước và sau implementation:

```text
6deaf129e37db2375622cc247b9abae686da96c140db9f784d90fc11885dda5a
```

Chạy hai file test mới trước khi tạo module:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -m pytest tests/unit/application/test_data_partition.py tests/integration/test_partition_core_persistence.py -q --tb=short -p no:cacheprovider
```

**RED: exit 1, 2 collection errors in 0.80s**, `ModuleNotFoundError: agentmine.application.workers.data_partition`. Không gọi đó là hai assertion failures.

Sau core GREEN đầu tiên, viết thêm regression bảo vệ direct worker path trước khi thêm guard:

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/unit/application/test_data_partition.py -k direct_worker -q --tb=short -p no:cacheprovider
```

**RED: 1 failed, 32 deselected in 0.52s**, `DID NOT RAISE PortError`: direct DataWorker(v2plan) có thể chạy transform/validate v2 rồi renderer v1. Đã sửa bằng typed UNSUPPORTED guard trước journal/ledger, không wire execution v2. Oracle không bị sửa để lấy PASS.

## 4. Partition Algorithm

Source mới: `src/agentmine/application/workers/data_partition.py:56`.

API:

```python
partition(plan: DataPlan) -> tuple[
    tuple[DataRecord, ...], tuple[DataIssue, ...], DataPartitionAssessment
]
```

Các bước:

1. Revalidate frozen DataPlan bằng dataclass replace; reject legacy plan tại pure v2 API. Matching policy/threshold/schema C1 vẫn được enforce.
2. Gọi production transform và validate; giữ toàn bộ parsed records cùng field/source/batch issues.
3. Đánh dấu ID invalid khi có actual missing_column/missing_value/invalid_value cho ID column. ID None không tham gia group. Lỗi field khác không loại valid ID khỏi duplicate scan.
4. Group valid canonical IDs theo insertion order của parsed records, xuyên mọi approved source. Group ≥2 tạo một SHA-256 reference và duplicate issue cho **mọi** member, column=id.
5. Sort/deduplicate exact identical issues theo thứ tự rõ ràng: global batch issue trước; rồi approved source order; source-level row=None trước rows; row tăng; column theo approved schema; code theo string enum. Các issue khác source/row/column/code vẫn giữ riêng.
6. Duyệt lại records theo original order: row có issue → rejected với mọi row reasons và group ref nếu có; không issue → clean reference.
7. Tạo ordered source outcomes và typed DataPartitionAssessment. C1 contract checks conservation, membership/source/count/group consistency. Return records nguyên thứ tự, full issues và assessment; không tạo deliverable/QA/acceptance decision.

Dictionary dùng cho lookup/insertion order, **không dùng Python hash() để tạo identity**. Group order theo first member encounter; clean/rejected là stable subsequences. Không sort nguồn theo tên, không sort nhóm theo canonical ID.

`data_transform.py:224` giữ seen-set duplicate cũ chỉ cho v1. V2 duplicate ownership thuộc partition core, tránh sót occurrence đầu và tránh duplicate-null giả. Core không bỏ actual field validation để làm record sạch.

## 5. Duplicate Policy A

| Case | Hành vi thực tế được test |
|---|---|
| ` a1 ` / `A1` | Approved trim+UPPER → A1; reject cả hai |
| Ba A1 | Reject cả ba, một group ba distinct refs |
| Cross-source | Group xuyên batch; original source refs/digests giữ riêng |
| Valid ID, field khác invalid | Vẫn vào group; giữ duplicate + actual field error |
| Missing/null/blank ID | Actual missing reasons; không group dưới None |
| Quá max_length hoặc ID dạng array | Actual invalid_value; array thành canonical None nhưng vẫn origin VALUE; không group invalid IDs |
| Optional-null đi cùng duplicate | Null hợp lệ không thêm lỗi; duplicate vẫn reject |
| Unicode case | Normalize theo production TextCase; golden JSON escaping/hash kiểm chứng |

### Canonical serialization chính xác

Group payload là JSON array theo đúng thứ tự:

```text
[
  "agentmine-data-duplicate-v2",
  {"contract_version": 2, "duplicate_policy": "REJECT_ALL", "id_column": "id"},
  canonical_id,
  [{"reference": source_reference, "sha256": lowercase_raw_source_sha256}, ...]
]
```

Settings: `ensure_ascii=True`, `sort_keys=True`, `separators=(",", ":")`, `allow_nan=False`, sau đó `.encode("utf-8")`. Không BOM/newline. Object keys sorted; arrays giữ approved order. Source digest tính trên exact UTF-8 input bytes, không trên normalized/pretty JSON. Group reference = `sha256:` + lowercase SHA-256 hex của payload bytes.

Golden vector từ fixture `two_duplicates`:

```json
["agentmine-data-duplicate-v2",{"contract_version":2,"duplicate_policy":"REJECT_ALL","id_column":"id"},"A1",[{"reference":"s1","sha256":"140f6b01e3a21ffde56772e7fdd1ead956566ec834034a3d7328f77ecdfada2e"}]]
```

```text
sha256:b38f10624b37589e4abe2208685bb58fc2b897b3daca247f7e6d90528a616fc2
```

Golden fixtures không gọi production duplicate_group_payload/hash function để sinh expected. Tests so exact payload bytes và actual group reference với literal stored values. Source-order reversal có group identity khác. Same frozen inputs/policy/canonical ID cho identity ổn định; không random UUID, timestamp hoặc execution ID.

Group ID là evidence identity, không spending/submission authority. Nó không bao gồm acceptance thresholds; C1 spec/plan/operation bindings vẫn ngăn thay thresholds dưới same identity/authorization. Approved normalization nằm trong frozen DataColumn, không có transformation override trong partition core.

## 6. Input Presence Semantics

`data_transform.py:118` xác định ngay sau extract, trước normalize:

- Path thiếu → MISSING.
- Key hiện diện, JSON null → NULL.
- Mọi value còn lại, gồm blank string, invalid list/number-text → VALUE.

DataCell giữ normalized value và origin riêng; blank có thể canonical null nhưng không biến origin thành NULL/MISSING. V1 giữ input_presence=None. Optional null không tự sinh missing_value; optional invalid non-null vẫn giữ invalid_value và bị reject. Negative numbers vẫn giữ canonical negative string cùng actual issue, không clamp 0.

Không đổi existing normalization capabilities hoặc tạo regex ID mới. Fixture ID rule là required TEXT, trim/UPPER, max_length=4 được approved trong test plan; không suy rộng một format ID bắt buộc cho mọi client.

## 7. Independent Oracle Results

Mỗi fixture so exact normalized values, origins, ordered issues, clean/rejected row IDs, group canonical ID/reference/member IDs; thêm assertions source provenance, source parsed counts, repeat determinism và conservation.

| Fixture | Parsed | Clean | Reject | Issues | Groups | Evidence complete |
|---|---:|---:|---:|---:|---:|---|
| all_valid | 2 | 2 | 0 | 0 | 0 | true |
| mixed | 2 | 1 | 1 | 1 | 0 | true |
| all_invalid | 2 | 0 | 2 | 3 | 0 | true |
| two_duplicates | 3 | 1 | 2 | 2 | 1 | true |
| three_duplicates | 3 | 0 | 3 | 3 | 1 | true |
| cross_source | 3 | 1 | 2 | 2 | 1 | true |
| duplicate_and_error | 2 | 0 | 2 | 3 | 1 | true |
| missing_null_blank_ids | 3 | 0 | 3 | 4 | 0 | true |
| invalid_ids_not_grouped | 3 | 0 | 3 | 4 | 0 | true |
| optional_null_and_blank | 2 | 2 | 0 | 0 | 0 | true |
| optional_invalid | 2 | 0 | 2 | 2 | 0 | true |
| two_groups_order | 4 | 0 | 4 | 4 | 2 | true |
| unicode_group | 2 | 0 | 2 | 2 | 1 | true |
| csv_duplicates | 2 | 0 | 2 | 2 | 1 | true |
| csv_missing_header | 1 | 0 | 1 | 3 | 0 | true |
| partial_malformed | 1 | 1* | 0 | 1 | 0 | false |
| malformed_csv | 0 | 0 | 0 | 1 | 0 | false |
| malformed_non_object | 0 | 0 | 0 | 1 | 0 | false |
| empty | 0 | 0 | 0 | 0 | 0 | true |
| batch_count | 1 | 1 | 0 | 1 | 0 | true |

**Tất cả 20 fixture khớp oracle.** *partial_malformed clean ref chỉ là candidate trong dữ liệu nguồn đã parse, không biết nguồn hỏng có ID trùng hay không; evidence_complete=false cấm hiểu thành complete deliverable/client acceptance. Không xuất clean files ở C2. Batch_count vẫn giữ global record_count issue dù row schema-valid. Empty/all-rejected cũng không phải acceptance PASS; core không áp threshold để tự duyệt.

## 8. Provenance and Conservation

- Parsed count = clean refs + rejected refs, membership unique; source-reference/digest/source-row/row_id giữ exact identity.
- Rejected.reasons là full ordered row issue subset; group members đều rejected và có duplicate reason. Source/batch issues ở full issue tuple, không gán sai vào một row.
- Raw content giữ nguyên trong immutable plan/DataSource; source digest không bị thay bằng cleaned-data hash. Locator/timestamp/column source paths được so với approved input.
- Malformed source parsed_count=None, không fabricated 0. Strict parser không salvage một vài object từ source chứa non-object hoặc CSV malformed; raw source vẫn trace được. Những records nguồn khác parse thành công vẫn retain.
- Bound 1.000 rows của C1 không cho assessment lớn hơn. V2 overflow raise structured DomainError field `partition_record_limit` trước khi trả empty/truncated assessment. Raw approved source vẫn có đủ 1.001 rows; test xác nhận không đổi raw input. V1 overflow behavior giữ nguyên.

SQLite integration test chỉ persist **core-only DataResult** với artifacts=(), actual cost=None và warning partition_artifacts_unavailable. Đây không phải DataWorker execution/completed runtime/deliverable/QA. Sau reopen/retry có đúng một data_plan và một data_result, không budget/cost/submission/revenue rows; same-ID changed source bytes bị conflict. Không fabricate actual cost=0 chỉ vì core không gọi AI.

## 9. Compatibility and Safety

- V1 DataWorker regression, duplicate-later-only và null-key behavior giữ nguyên.
- Actual production transform/validate/artifact output so exact records/issues/artifact bytes với pre-C1 v1 snapshot fixture.
- Legacy COLUMN optional-null semantics vẫn được C1 test bảo vệ; QA execution/check logic không sửa.
- C1 contracts/snapshots/immutable binding tests chạy lại; 25 baseline C1 file hashes giữ nguyên. Không historical rewrite hoặc migration.
- Runtime CAPABILITY_UNAVAILABLE và v2 operational QA UNSUPPORTED giữ nguyên. Production CLI không được thêm v2 parser.
- Thêm **direct DataWorker v2 UNSUPPORTED guard** tại `workers/data.py:99`, trước save_plan/cost để không rơi vào legacy renderer. V1 code path không đổi. Đây là safety guard, không v2 worker integration.
- Pure tests dùng v2 plan dựa retained zero-estimate SCOUT_ONLY test snapshot; không chạy source freshness/eligibility/budget dispatch hoặc quảng bá production readiness. Direct-worker guard test dùng existing isolated fake ledger/clock, llm=None và xác nhận ledger/journal không đổi.
- Không mở production workspace/secret files hoặc gọi source/provider/submission/wallet/payment; pytest có global network block. Không revenue claim, không thay operating mode/AI budget vận hành. Không đo infrastructure cost hoặc suy ra total execution cost bằng 0.

## 10. Test-First GREEN Evidence

Command giống RED cuối: **34 passed in 3.94s**. Green đầu tiên: 33 passed in 0.80s, sau đó test guard mới RED như mục 3 rồi sửa guard để GREEN.

34 tests gồm 20 exact oracle cases, 7 golden-payload cases, 6 compatibility/safety/bound/order cases và 1 core-persistence integration test. Không gọi số cases là số real bounty được hoàn thành.

## 11. Regression Results

Fresh C2 selection:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -m pytest tests/unit/application/test_data_partition.py tests/integration/test_partition_core_persistence.py tests/unit/application/test_partition_contracts.py tests/integration/test_partition_snapshot_compatibility.py tests/unit/application/test_data_worker.py tests/integration/test_data_recovery.py tests/integration/test_operational_deliverable_qa.py tests/unit/test_architecture.py -q --tb=short -p no:cacheprovider
```

**198 passed in 30.03s.** Bao gồm C2/C1, existing worker/recovery/QA và architecture, không lấy 1.571 C1 tests cũ làm evidence mới. Không cộng overlapping focused/regression counts thành unique tests.

Static commands:

```powershell
.\.venv\Scripts\python.exe -B -m ruff check . --no-cache
.\.venv\Scripts\python.exe -B -m ruff format --check .
$c2MypyCache = Join-Path ([IO.Path]::GetTempPath()) 'agentmine-c2-mypy'
.\.venv\Scripts\python.exe -B -m mypy --strict --cache-dir $c2MypyCache
git diff --check
```

Ruff PASS; format **376 files already formatted**; strict mypy **277 source files**, no issues; diff check exit 0. Initial formatting pass có import/line-length/one-line statement errors trong code mới, đã sửa rồi check lại, không nới rules/config.

Full-suite command thực thi trên source/tests cuối (không thêm test sau collection):

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -m pytest -q --tb=short -p no:cacheprovider
```

**Exit 0: 1608 passed in 714.11s (0:11:54)**; không failed/skipped/warning summary. Đây là fresh C2 execution, không copy kết quả C1.

## 12. Files Changed

Chỉ C2:

- **New** src/agentmine/application/workers/data_partition.py — pure core và canonical group payload.
- **Modified** src/agentmine/application/workers/data_transform.py — v2 input origin, duplicate delegation, explicit bound failure; v1 preserved.
- **Modified** src/agentmine/application/workers/data.py — direct v2 UNSUPPORTED safety guard; không integration.
- **New** tests/unit/application/test_data_partition.py.
- **New** tests/integration/test_partition_core_persistence.py.
- **New** tests/contract/fixtures/data_partition_c2/oracles.json và README.md.
- **New** docs/audits/phase-b4-3-c2-partition-core.md.

Scratch `.tmp/c2-preserved-baseline.json` chỉ ghi checksum đầu phiên, ignored/uncommitted, không phải database vận hành. Các C1 modified/untracked files trong git status đã có sẵn và không phải C2 edits. Không dependency/config/ADR/Domain/port/schema changes.

## 13. Risks / Deferred Work

- Chưa wire core vào DataWorker v2 và result-before-cost execution/recovery v2; hiện direct caller bị block an toàn. Core-only snapshot test không thay production runtime E2E.
- Chưa render/export v2, chưa client-acceptance QA, chưa FIELD_PRESENT execution, chưa CLI opt-in. Không gỡ guards ở checkpoint này.
- `evidence_complete` chỉ parse coverage, không schema/batch/client acceptance. Incomplete candidates không được publish; C3/C4 phải enforce boundary đó.
- Group hash là evidence content scope, không thay exact approval/spec/execution/deliverable identities.
- Resource overflow fail closed; không có >1.000-record feature hoặc tự phân trang/chia batch để né approved scope.
- No live bounty readiness, provider compatibility, rewards hoặc financial verification claim.

Sai lệch triển khai nhỏ có chủ đích: thay vì wire v2 worker vào renderer chưa tồn tại, thêm fail-closed guard sau RED test chứng minh legacy-fallback path. Không đổi approved Duplicate Policy A hoặc semantics C1; pure function integration dùng production transforms đủ để chứng minh C2.

## 14. Git Status

Final `git status --short`:

```text
 M src/agentmine/application/contracts/data.py
 M src/agentmine/application/contracts/data_revision.py
 M src/agentmine/application/contracts/local_runtime.py
 M src/agentmine/application/contracts/qa.py
 M src/agentmine/application/contracts/runtime.py
 M src/agentmine/application/contracts/worker_execution.py
 M src/agentmine/application/use_cases/data_revision.py
 M src/agentmine/application/use_cases/local_runtime.py
 M src/agentmine/application/use_cases/operational_qa.py
 M src/agentmine/application/use_cases/worker_preflight.py
 M src/agentmine/application/workers/data.py
 M src/agentmine/application/workers/data_transform.py
 M src/agentmine/infrastructure/snapshots.py
?? docs/audits/phase-b4-2-deliverable-contract-qa-design.md
?? docs/audits/phase-b4-3-c1-contracts-snapshots.md
?? docs/audits/phase-b4-3-c2-partition-core.md
?? docs/audits/phase-b4-realistic-bounty-simulation.md
?? src/agentmine/application/workers/data_partition.py
?? tests/contract/fixtures/data_partition/
?? tests/contract/fixtures/data_partition_c2/
?? tests/integration/test_partition_core_persistence.py
?? tests/integration/test_partition_snapshot_compatibility.py
?? tests/unit/application/test_data_partition.py
?? tests/unit/application/test_partition_contracts.py
```

Không stage/commit/push; C1 worktree giữ nguyên theo checksum.

## 15. Final Verdict

**C2_PASS.** Full-group rejection, independent oracle agreement, conservation, deterministic identity/order và legacy compatibility đã được kiểm chứng. Artifacts/QA/runtime v2 vẫn chưa operational.

Exact report path: `D:\DNTU\Tuhoc\AgentMine\docs\audits\phase-b4-3-c2-partition-core.md`.

Executed results: C2 focused **34 passed in 3.94s**; regression selection
**198 passed in 30.03s**; full pytest **1608 passed in 714.11s**; Ruff check PASS;
format **376 files already formatted**; strict mypy **277 source files**, PASS;
`git diff --check` exit 0. Overlapping counts are not additive.

Changed C2 files are listed in section 12; all 25 prior C1 file checksums and the
independent oracle checksum were reverified unchanged. The report has 15 required
sections, no Unicode replacement characters and no trailing-whitespace lines.
Git diff check does not include untracked Markdown, so this validation was separate.

Readiness: **READY_FOR_C3_OPERATOR_REVIEW**. Recommended next action: operator
reviews this bounded core and approves C3 separately. Stop after C2; do not remove
runtime/QA/direct-worker guards until the relevant integration is explicitly
implemented and tested. No commit/push or external/financial actions.

# Phase B.4.3-C1 — Contracts, Independent Oracles & Snapshot Compatibility

## 1. Executive Summary

C1 triển khai nền contract v2 opt-in và snapshot compatibility; **chưa có partition worker v2 hoạt động**. Không triển khai C2–C5, transformation, artifact rendering hoặc QA field-presence semantics. Không gọi provider/network/submission/wallet; không thay production workspace hay budget/mode.

Base commit: `7c660a8adfac07e408c3e3939988c9697770c204`. Worktree đầu checkpoint chỉ có hai report untracked từ B.4.1/B.4.2; giữ nguyên. C1 không commit/push.

Contracts/snapshots focused cuối: **54 passed in 1.51s**. Strict mypy toàn cấu hình: **274 source files, no issues**; Ruff check PASS; format **371 files already formatted**. Full-suite invocation mới đạt **1571 passed in 771.23s**; xem mục 14 về ba supplemental tests thêm sau collection. Không lấy baseline cũ làm fresh verification.

## 2. Approved Scope

- V2 chỉ khi có output_policy rõ ràng và matching acceptance; None là legacy.
- Duplicate enum duy nhất REJECT_ALL; semantics reject mọi member đã được operator duyệt nhưng phép tính grouping thuộc C2, chưa chạy ở C1.
- Thresholds bắt buộc, không default: min_clean 1..1000, max_rejected 0..1000 và không vượt approved max_records.
- Giữ DataResult.valid = not issues, legacy COLUMN, artifact bytes/names và execution/QA/replay v1.
- Contract/binding/codec và offline tests; không database schema/index migration hoặc dependency mới.

## 3. Source Findings

Source đối chiếu trước edit: data.py chưa có policy/partition/presence; qa.py chỉ có legacy criteria, COLUMN non-null; runtime.py có frozen WorkSpecification và immutable WorkerRun; snapshots.py dùng exact field-set với migration allowlist. Existing coverage tại `tests/integration/test_local_persistence.py:428`, `test_data_recovery.py`, `test_operational_deliverable_qa.py`, `test_data_revision_foundation.py` và `tests/unit/application/test_data_worker.py`.

**Sai lệch tài liệu:** file `docs/audits/phase-b4-realistic-bounty-simulation.md` hiện bắt đầu bằng yêu cầu B.4.2, sau đó mới có report B.4.1 (Executive Summary bắt đầu khoảng dòng 331). Không phải chỉ một report B.4.1 thuần như tên file. C1 không sửa/khôi phục file này. Approved design riêng `phase-b4-2-deliverable-contract-qa-design.md` và phần report mô phỏng cùng source vẫn đủ để đối chiếu. Một lần tra tên `test_sqlite_persistence.py` không tồn tại; đã tìm lại owner thực tế là `test_local_persistence.py`, không tạo test giả theo tên sai.

Thiết kế nói acceptance được freeze nhưng không đặt nó trong DataPlan do vòng import QA↔Data. C1 giải quyết bằng canonical PartitionAcceptance ở module Data, QA re-export cùng class; thêm DataPlan.partition_acceptance để replay plan bind cả policy và thresholds. Đây là cụ thể hóa binding, không thay business semantics đã duyệt.

## 4. Test-First RED Evidence

Trước production edits:

1. Trích nguyên raw snapshot payloads từ SQLite **mô phỏng B.4.1 riêng** bằng read-only connection, không chạy DataWorker/encoder để tạo expected.
2. Viết literal `independent-oracles.json` và reconstructed DataCell tagged fixture.
3. Viết hai file test mới rồi chạy focused command:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -m pytest tests/unit/application/test_partition_contracts.py tests/integration/test_partition_snapshot_compatibility.py -q --tb=short -p no:cacheprovider
```

**RED: exit 1, 2 collection errors in 0.63s**, vì import DataPartitionPolicy chưa tồn tại. Không gọi đó là hai assertion failures.

Vòng test-first bổ sung trước siết cấu trúc assessment/result:

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/integration/test_partition_snapshot_compatibility.py -q --tb=short -p no:cacheprovider
```

**RED: 2 failed, 18 passed in 2.96s**: contract chưa reject missing input origin/membership và duplicate/unknown-source membership. Sau đó chỉ bổ sung validation của evidence được cung cấp; không tính partitions từ raw values.

Không sửa literal expected policy/threshold/group examples để code pass. Checksum manifest chỉ bổ sung entry khi thêm payload optional-null được trích từ mô phỏng cũ. Các lỗi formatting/mypy ban đầu được sửa ở source/test typing, không bằng nới checker hoặc expected values.

## 5. Contracts Implemented

`src/agentmine/application/contracts/data.py`:

- Frozen DataPartitionPolicy(version, id_column, DuplicatePolicy.REJECT_ALL), strict int version 2, enum typed; unknown kwargs bị TypeError, snapshot unknown fields bị PortError.
- Frozen PartitionAcceptance với thresholds explicit; bool/float/string không được giả làm int.
- InputPresence MISSING/NULL/VALUE; DataCell.input_presence optional, default None legacy. C1 không populate origin trong transformer.
- DataRowReference giữ source/digest/source-row/row_id; DataSourceOutcome có PARSED/MALFORMED và parsed_count None khi malformed, không fabricated zero.
- PartitionRejection giữ actual DataIssue reasons + optional duplicate group reference; DuplicateIDGroup giữ canonical ID và ≥2 distinct member refs.
- DataPartitionAssessment chứa typed ordered clean/rejected/source/group tuples, completeness; validates bounded evidence, membership uniqueness, source/count/group-reference consistency. Không canonicalize, group hoặc lựa record cho operator.
- DataPlan.output_policy/partition_acceptance optional; DataResult.partition optional. V2 result cần typed origin trên retained cells và membership đúng records. `valid` giữ nguyên zero-issues predicate.

Binding validator kiểm tra policy/acceptance phải đi cặp, ID column tồn tại/required TEXT, unique_by đúng một ID, không semantic columns, thresholds trong approved dataset bounds. Approved normalization nằm trong DataColumn của immutable schema, không có normalization override độc lập trong policy.

`contracts/qa.py`: FIELD_PRESENT enum và additive PartitionAcceptance fields ở DataAcceptanceCriteria/QAInspection. V2 criteria biết exact inventory clean.csv/clean.json/rejected.json/validation.json và media types; đây là **contract validation**, không renderer. FIELD_PRESENT không bật cho legacy criteria hoặc Research inspection. Existing COLUMN execution/check logic không sửa.

## 6. Snapshot Compatibility

Fixture directory: `tests/contract/fixtures/data_partition/`.

- data_plan-v1.json, data_result-v1.json, work_specification-v1.json, qa_inspection-v1.json: nguyên payload trước C1 từ complete-control B.4.1.
- optional-null-inspection-v1.json: nguyên payload trước C1 từ optional-null control.
- data_cell-v1.json: reconstructed tagged fixture viết tay, ghi rõ không phải authentic history.
- independent-oracles.json: policy/threshold và example memberships viết literal độc lập; examples dành cho C2, không khẳng định algorithm đã chạy.
- sha256.json và README.md: integrity/provenance. Đây là genuine pre-C1 **test** payloads, không production history, real listing hoặc earnings.

Codec thêm narrow None defaults đúng các model/field đã duyệt: WorkSpecification.output_policy; DataPlan.output_policy/partition_acceptance; DataCell.input_presence; DataResult.partition; DataAcceptanceCriteria/QAInspection.partition_acceptance. Giữ migrations cũ execution_evidence/acceptance. Không global missing-field fallback, không ignore unknown fields, không đổi envelope version.

Missing policy/acceptance một phía, thiếu required v2 assessment fields, wrong typed value, unknown fields hoặc unsupported version vẫn reject. Model decode là structure check; không phải authentication cho arbitrary caller-supplied snapshot. Existing SQLite payload checksum/immutable identity và contextual model binding vẫn bắt buộc.

Nested legacy QAInspection và reconstructed WorkerRun wrapper được đọc đúng mà không kích hoạt v2. Genuine historical revision payload độc lập chưa có; F05 existing regression/full suite kiểm tra revision paths, không tuyên bố wrapper tự dựng là production revision history.

Test SQLite trực tiếp insert raw old payload vào database test rồi read qua repository, xác nhận payload/digest/revision không bị rewrite. Không migration SQL/table/index. Re-encode một decoded old model có thể thêm None fields; không hứa byte-equality cho reserialized snapshot, chỉ original persisted payload/artifact/content authority không tự thay.

## 7. Frozen Policy and Acceptance Binding

- PrepareDataRequest → WorkSpecification → DataPlan copy exact approved output policy và thresholds.
- Policy/threshold/schema-normalization thay đổi cùng spec ID bị immutable persistence conflict; cùng execution ID thay thresholds bị journal plan conflict. Không coi chúng equivalent.
- QAInspection yêu cầu exact plan thresholds và matching result assessment policy; thiếu assessment hoặc mismatch bị structured error. Acceptance v2 không tự authorize work hoặc QA.
- Revision contract giữ same output_policy; partition thresholds không được relax. Copy paths không bỏ policy. Legacy→v2 không được dùng để lách lineage/acceptance guards.
- **C1 fail-closed:** WorkerPreflight trả CAPABILITY_UNAVAILABLE cho v2 trước authorization/start/dispatch. Operational Data QA trả PortError.UNSUPPORTED cho v2; không nhờ checker legacy xử lý FIELD_PRESENT. Chỉ thêm guard/binding, không triển khai QA engine logic.
- Production CLI parser vẫn chưa nhận output_policy manifest v2; unknown fields tiếp tục reject. Không có mock/provider fallback, không auto bật capability mới.

DataWorker.execute(v2plan) trực tiếp không phải operational capability được C1 hỗ trợ. Code worker chưa đổi và không được quảng bá là biết Policy A; C2 phải làm integration riêng. C1 chỉ chứng minh production application runtime từ chối v2, không chứng minh partition worker chạy được.

## 8. Test-First GREEN Evidence

Focused command giống RED, final **54 passed in 1.51s**. Green đầu tiên trước mở rộng tests: 44 passed in 0.95s; sau structural validation 51 passed in 2.75s. Final focused gồm thêm chứng minh raw SQLite non-rewrite, explicit identifier-policy conflict và standalone legacy acceptance decode.

Coverage: valid/invalid versions/policies, ID column schema, composite uniqueness, threshold omission/bounds/types, policy/acceptance pairing, immutable identity/replay, nested old payloads, v2 round-trip, unknown/missing fields, old valid predicate, old optional-null COLUMN và no-dispatch before budget mutation. Fixtures/group examples không được dùng làm claim algorithm C2 PASS.

V2 round-trip dùng encode/decode **actual model under test**, expected model viết explicit. Không dùng encoder để sinh historical expected fixture; không dùng transform/partition để sinh expected records.

## 9. Legacy Regression Results

Fresh regression command đã chạy:

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/unit/application/test_partition_contracts.py tests/integration/test_partition_snapshot_compatibility.py tests/unit/application/test_data_worker.py tests/integration/test_data_recovery.py tests/integration/test_operational_deliverable_qa.py tests/integration/test_local_persistence.py tests/unit/test_architecture.py -q --tb=short -p no:cacheprovider
```

**190 passed in 26.57s** ở test selection lúc đó (trước khi bổ sung vòng structural tests cuối). Không cộng số overlapping runs thành unique coverage. Tests mới final đã chạy lại riêng và full-suite evidence được ghi cuối report.

Static final commands:

```powershell
.\.venv\Scripts\python.exe -B -m ruff check . --no-cache
.\.venv\Scripts\python.exe -B -m ruff format --check .
$c1MypyCache = Join-Path ([IO.Path]::GetTempPath()) 'agentmine-c1-mypy'
.\.venv\Scripts\python.exe -B -m mypy --strict --cache-dir $c1MypyCache
git diff --check
```

Ruff PASS; format 371 files; mypy 274 files PASS; diff check exit 0. Trước final run, mypy đã bắt non-overlapping enum comparison trong test và variable inference DuplicateIDGroup|None; sửa assertions/variable name đúng type, không disable strictness. Ruff ban đầu có import/format/line-length errors, đã format đúng các file thay đổi rồi chạy check lại.

## 10. Deferred C2–C5 Work

- Tính full normalized duplicate groups/partition memberships, deterministic group hash/origin population — C2.
- Render/export usable clean/rejected artifacts, version-aware runtime artifact allowlists — checkpoints sau.
- QA FIELD_PRESENT/schema/threshold semantics thật và exact recomputation — checkpoint QA sau.
- Production CLI opt-in parser/inspection/export integration; remove temporary capability guards chỉ sau acceptance gates.
- Real bounty/source eligibility/readiness, paid providers/AI QA, submission/payment/wallet/AWS nằm ngoài toàn bộ C1.

Không tạo data_partition.py, không sửa data_transform.py/data_artifacts.py/QA checks, BudgetManager, SQLite journal transactions hoặc providers.

## 11. Risks and Open Questions

- C1 model validates evidence structure, không xác minh semantic correctness của supplied canonical values hoặc group hash; C2/QA tests phải làm đúng independent oracle.
- Giữ guard trong runtime cho tới pipeline v2 đầy đủ; không chỉ gỡ guard vì contract round-trip PASS.
- FIELD_PRESENT chỉ là typed token ở C1, không có QA execution support.
- Snapshot fixtures là test history; không có authentic production revision migration evidence. Không cần migration production để hoàn thành checkpoint này.
- Không thay threshold values hoặc duplicate decisions đã approved. Không có quyết định business mới cần hỏi để đóng C1; operator review vẫn cần trước bắt đầu C2.

## 12. Files Changed

Production (11 files):

1. src/agentmine/application/contracts/data.py
2. src/agentmine/application/contracts/qa.py
3. src/agentmine/application/contracts/runtime.py
4. src/agentmine/application/contracts/local_runtime.py
5. src/agentmine/application/contracts/data_revision.py
6. src/agentmine/application/contracts/worker_execution.py
7. src/agentmine/application/use_cases/local_runtime.py
8. src/agentmine/application/use_cases/data_revision.py
9. src/agentmine/application/use_cases/worker_preflight.py
10. src/agentmine/application/use_cases/operational_qa.py
11. src/agentmine/infrastructure/snapshots.py

New tests: tests/unit/application/test_partition_contracts.py; tests/integration/test_partition_snapshot_compatibility.py. New fixtures: README.md, independent-oracles.json, sha256.json, data_cell-v1.json, data_plan-v1.json, data_result-v1.json, work_specification-v1.json, qa_inspection-v1.json, optional-null-inspection-v1.json. New report: docs/audits/phase-b4-3-c1-contracts-snapshots.md.

Không thêm dependencies. Không Domain changes hoặc architecture dependency deviation. Canonical PartitionAcceptance ở Data (QA re-export), DataPlan threshold binding và guards là các cụ thể hóa nhỏ cần thiết cho scope contract-only; không triển khai trước C2.

## 13. Git Status

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
 M src/agentmine/infrastructure/snapshots.py
?? docs/audits/phase-b4-2-deliverable-contract-qa-design.md
?? docs/audits/phase-b4-3-c1-contracts-snapshots.md
?? docs/audits/phase-b4-realistic-bounty-simulation.md
?? tests/contract/fixtures/data_partition/
?? tests/integration/test_partition_snapshot_compatibility.py
?? tests/unit/application/test_partition_contracts.py
```
 Hai reports B.4.1/B.4.2 untracked đã tồn tại trước C1, không phải C1 edits. Không stage/commit/push, không thay existing production database.

## 14. Final Verdict

**C1_PASS.** Contracts/compatibility foundation đã implement và kiểm chứng trong scope C1. Không có nghĩa pipeline v2 operational hoặc real bounty ready.

Full-suite command executed:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -m pytest -q --tb=short -p no:cacheprovider
```

**Exit 0: 1571 passed in 771.23s (0:12:51).** No failures/skips/warning summary.
This run collected the 51-test C1 selection available when it started. Three
additional compatibility tests were added after collection; all are included in
the final focused **54 passed in 1.51s** run. Do not describe this as a full-suite
1574-test execution or add overlapping test counts. The only production edit
after full-suite start renamed a local variable for strict mypy, without behavior
change; the final focused run and final static checks used that source.

Final checks: Ruff check PASS; format 371 files; strict mypy 274 files PASS;
`git diff --check` exit 0. The two pre-existing report checksums were also verified
unchanged. Untracked Markdown reports were inspected separately for Unicode and
trailing whitespace.

Report: `D:\DNTU\Tuhoc\AgentMine\docs\audits\phase-b4-3-c1-contracts-snapshots.md`.

Decision: **C1_PASS / READY_FOR_C2_OPERATOR_REVIEW**. Stop here; no C2 code has
been created. Recommended next action: operator reviews C1 and authorizes C2
separately. No commit/push, no new dependencies, no financial/external actions.

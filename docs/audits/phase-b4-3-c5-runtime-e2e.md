# Phase B.4.3-C5 — Runtime Integration, CLI Opt-In & Independent E2E Simulation

Ngày kiểm tra: 2026-11-04. Phạm vi: local, offline, deterministic Data. HEAD: `7c660a8adfac07e408c3e3939988c9697770c204`; kiểm tra trên worktree chưa commit, gồm cả C1–C4.

## 1. Executive Summary

C5 nối opt-in partition v2 vào CLI/composition hiện có, DataWorker, SQLite runtime, operational QA và export. Không tạo runtime hay QA engine thứ hai. Legacy v1 vẫn là mặc định. Bằng chứng xác nhận trước full suite: 66 test C5 và 585 test hồi quy đạt; Ruff, format và strict mypy đạt. Full suite chạy độc lập lần cuối: **1801 passed / 742.48s**, exit 0. Verdict: **C5_PASS** cho phạm vi local offline.

Đây là bằng chứng năng lực local với fixture tổng hợp, không phải live bounty, quyền tham gia marketplace, khách hàng chấp nhận hay doanh thu. Catalog bẩn vẫn cần sửa dữ liệu có thẩm quyền trước khi có thể được chấp nhận.

## 2. Approved Scope

Giữ nguyên các quyết định C1–C4: opt-in v2 rõ ràng; `output_policy=None` là v1; Duplicate Policy A `REJECT_ALL`; acceptance đóng băng; `min_clean_records >= 1`; `max_rejected_records` bắt buộc; không nới ngưỡng tự động. Không đổi `DataResult.valid`, semantics legacy `COLUMN`, thuật toán partition, renderer hay QA integrity checks.

Không thêm dependency, provider, schema migration, Domain lifecycle, marketplace fulfillment, paid AI, submission, payment hoặc AWS. Không stage, commit hay push.

## 3. Test-First RED Evidence

Trước production changes, tạo các scenario literal và oracle độc lập rồi chạy `tests/integration/test_partition_runtime_e2e.py`.

- Lần đầu: **37 failed, 15 passed, 14.65s**. Một lỗi nằm ở setup legacy test vẫn dùng tên artifact v2.
- Sửa riêng setup legacy về ba artifact v1; chạy RED lại: **36 failed, 16 passed, 12.93s**, exit 1. Các đường v2 hợp lệ bị parser/runtime/export hiện hữu chặn.

Oracle không lấy từ kết quả DataWorker. Dữ liệu đầu vào lấy nguyên byte từ mô phỏng B.4.1; expected membership, reason codes, threshold và QA được xác định riêng. Canonical encoding dựa trên contract C3.

Có một lỗi vận chuyển oracle cần công khai: `Path.write_text` trên Windows chuyển JSON LF thành CRLF. GREEN đầu ghi nhận **5 failed, 47 passed**. Chỉ chuẩn hóa newline của bảy expected JSON về LF đã quy định trước; không thay đổi giá trị, membership, input, ngưỡng hoặc lấy actual output làm expected. Hash trước/sau nằm tại `.tmp/c5-oracle-newline-fix.json`; fixture README giải thích thay đổi.

## 4. Runtime Dispatch and Authorization

`WorkerPreflight.check()` bỏ đúng blanket guard CAPABILITY_UNAVAILABLE cho v2. WorkSpecification được kiểm tra lại bằng typed contracts; source freshness, deadline, terms, eligibility, ownership, economics/scoring và zero-AI restrictions vẫn được giữ.

`ExecuteWorkerTask` không bị thay thế: dùng actor/ledger và identity gốc, authorize trước dispatch, persist start trước DataWorker, persist result trước accounting, finish bằng repository transaction hiện hữu. Không có semantic/paid fallback. Unknown AI claim vẫn chặn trước dispatch.

Ba test/helper trước đây dựa vào blanket guard được đổi thành probe actor chưa được duyệt và phải nhận APPROVAL_DENIED. Các positive C5 tests chứng minh dispatch được duyệt qua composition thật, không gọi tắt repository start để tạo thành công giả.

## 5. CLI Opt-In Contract

Dùng các command `work prepare`, `show`, `execute`, `recover`, `qa`, `status`, `export` hiện có. Không thêm live execution command.

Phần opt-in trong JSON specification:

```json
{
  "output_policy": {
    "contract_version": 2,
    "id_column": "id",
    "duplicate_policy": "REJECT_ALL"
  },
  "acceptance": {
    "partition_acceptance": {
      "contract_version": 2,
      "min_clean_records": 1,
      "max_rejected_records": 2
    }
  }
}
```

Đây là trích đoạn, chưa phải specification đầy đủ: vẫn cần approved columns, normalization, sources/digests và các acceptance fields hiện hữu. Contract version nằm trong typed policy/acceptance; top-level version tự đặt không được chấp nhận. Không kích hoạt v2 từ tên file. Thiếu policy/threshold, unknown fields, bool thay integer, unsupported policy/version hoặc semantic columns đều fail closed.

`work prepare --approve-inputs` thể hiện consent chuẩn bị; execute/recover/qa dùng confirmation hiện hữu. Prepare không dispatch. Specification view hiển thị policy/version v2; v1 giữ nguyên hình dạng output cũ.

## 6. Artifact Export and Integrity

Application kiểm tra finished run, execution/specification identity, original deliverable content reference, typed retained result và original frozen plan. Kết quả partition được tái tạo bằng pure C2 core, artifacts bằng C3 renderer để so exact records/issues/assessment/bytes. Đây là integrity check trước publication, không phải QA engine mới.

Exporter nhận metadata version/completeness rõ ràng qua optional keyword contracts; không đoán từ filenames. Complete v2 chỉ nhận đúng thứ tự/inventory `clean.csv`, `clean.json`, `rejected.json`, `validation.json`. Incomplete chỉ nhận `validation.json`.

Missing/extra/tampered artifact, sai reference, path traversal hoặc destination conflict bị từ chối. Giữ no-clobber, manifest-last publication, hardlink/path protections hiện hữu. Manifest v2 thêm contract/policy/completeness; manifest và allowlist v1 không thay đổi. Export chỉ ghi local, không phải submission.

## 7. End-to-End Data Flow

Continuous integration scenarios dùng parser/run_cli, production composition, file-backed SQLite, DataWorker và DeliverableQA thật:

```text
approved inputs → prepare/show frozen specification
→ execute: preflight + authorization + durable start
→ DataWorker → retained result → cost record → atomic finish
→ restart/readback → work qa → retained QA evidence
→ READY_FOR_HUMAN_REVIEW hoặc existing non-PASS state
→ local export → byte-for-byte oracle comparison → same-ID retry
```

FakeSource và FakeClock chỉ được inject rõ ràng trong test harness. Không có provider mock được thêm vào production configuration. Helper opportunity vẫn là brief tổng hợp của test factory, không chứng minh marketplace đã duyệt catalog scope.

## 8. B.4.1 Before/After Simulation

Walkthrough độc lập đã chạy bằng `.tmp/run_c5_simulation.py`, exit 0. Đây là các lần gọi CLI in-process thật qua production composition, không phải live module-entrypoint fulfillment.

| Scenario | Parsed / clean / rejected | QA | Lifecycle sau QA |
|---|---|---|---|
| Dirty | 4 / 0 / 4 | NEEDS_REVISION | IN_PROGRESS |
| Optional-null + FIELD_PRESENT | 2 / 2 / 0 | PASS | READY_FOR_HUMAN_REVIEW |
| Optional-null + COLUMN non-null | 2 / 2 / 0 | NEEDS_REVISION | IN_PROGRESS |
| Complete | 2 / 2 / 0 | PASS | READY_FOR_HUMAN_REVIEW |
| Malformed | 0 / 0 / 0 parsed; total UNKNOWN | NEEDS_REVISION | IN_PROGRESS |

Dirty v1 từng ghi 11 issues và chưa có partition contract chính thức. V2 ghi **12 issues**, reject cả hai thành viên duplicate A001, và cả các dòng thiếu/invalid còn lại; clean rỗng nhưng vẫn có bốn artifact vì evidence đầy đủ. Không được hiểu đây là client acceptance PASS. Không tự tạo ID, stock hay category để sửa fixture.

Evidence root: `.tmp/phase-b4-c5-e2e-20261104-df32a515/`. Mỗi scenario có SQLite riêng, frozen spec/facts/inputs, `cli-transcript.json`, export; root có `results.json` và nhãn OFFLINE_FIXTURES_ONLY. Raw inputs và expected outputs được giữ tại `tests/contract/fixtures/data_partition_c5/`.

So sánh trực tiếp với kết quả B.4.1 đã lưu:

| Input | B.4.1 v1 | C5 v2 |
|---|---|---|
| Dirty | 11 issues; validation-only; NEEDS_REVISION | 12 issues; 0 clean/4 rejected; bốn artifact; NEEDS_REVISION |
| Optional-null | Ba artifact; COLUMN coverage → NEEDS_REVISION | Bốn artifact; FIELD_PRESENT → PASS; COLUMN vẫn NEEDS_REVISION |
| Complete | Ba artifact; PASS | Bốn artifact; PASS |
| Malformed | Validation-only; 2 issues; NEEDS_REVISION | Validation-only; 2 issues; count UNKNOWN; NEEDS_REVISION |

Thay đổi FIELD_PRESENT là tiêu chí được duyệt cho specification mới, không phải nới criteria của run cũ. Việc xuất clean dataset rỗng không tạo client acceptance.
## 9. Duplicate Policy A and Optional-Null

Mọi thành viên duplicate group sau normalization đều bị reject, kể cả cross-source; không giữ arbitrary first winner. Dirty issues: row 1 duplicate; row 2 missing name, invalid/missing category, invalid/missing price, invalid stock; row 3 duplicate; row 4 missing column/value cho ID và stock — tổng 12.

Optional brand thiếu trong raw input được biểu diễn thành canonical null. FIELD_PRESENT được duyệt cho task v2 mới có thể PASS; COLUMN non-null vẫn yêu cầu giá trị không null và dẫn tới NEEDS_REVISION. Không sửa historical criteria để ép PASS.

## 10. Frozen Acceptance and QA Outcomes

C4 QA dùng retained evidence, exact plan/result/artifact bindings và frozen inspection. Zero-clean, all-rejected, vượt ngưỡng, record-count issue và incomplete evidence không PASS. Malformed source giữ source/total count UNKNOWN, không biến parsed=0 thành tuyên bố đã kiểm tra tổng số 0.

PASS chỉ tới READY_FOR_HUMAN_REVIEW. Separate operator submission approval không được tạo tự động. QA retry đọc evidence gốc; altered inspection bị chặn và không rewind lifecycle về bản cũ.

## 11. Persistence, Replay and Recovery

Test crash trước/sau result, trước/sau cost, trước/sau finish acknowledgment, và sau từng write của atomic finish. Rollback giữ transaction nhất quán; retry dùng execution/operation/deliverable identities gốc, không ghi cost hai lần. Retained result cho phép finish recovery không dispatch lại worker.

Mismatched frozen spec, source digest, operation/content identity và unknown AI claims fail closed. QA crash sau report persistence được recover bằng inspection ID gốc. Fault injection chứng minh các cửa sổ application/SQLite đã chọn, không phải chứng nhận filesystem power-loss.

Có thêm integration test revision thật: v1 mixed vượt ngưỡng → approved repaired input cùng policy → v2 execute → fresh QA PASS → export version 2. Thiếu approval không dispatch; history/cost v1 giữ nguyên; QA cũ không đổi current version.

Lưu ý source mạnh hơn mô tả lịch sử: RevisionPreflight là luồng riêng, không có blanket v2 guard như WorkerPreflight. C5 không bỏ một guard không tồn tại ở đó; các authorization/revision controls riêng được giữ và có test mới.

## 12. Legacy Compatibility

Không policy vẫn là v1, với exact ba artifact legacy và manifest không có version metadata mới. Legacy COLUMN, DataResult.valid, execute/recovery và existing CLI giữ nguyên. Không migration historical plans/results/acceptance. C1–C4 algorithms, golden oracles và reports được giữ nguyên; ba temporary runtime guard probes được cập nhật có giới hạn như mục 4.

## 13. Safety and Cost

Mọi scenario dùng workspace test riêng, SCOUT_ONLY và AI budget 0 USD; measured AI cost 0. Infrastructure cost chưa đo là UNKNOWN, không tuyên bố tổng chi phí thực tế bằng 0. Mỗi run ghi cost identity đúng một lần.

Pytest có network-deny fixture; standalone walkthrough cũng chặn socket connect. Không live Superteam, Bedrock, wallet, signing, submission hay payment. Verified revenue vẫn 0; không ghi synthetic reward thành earnings. Production source mặc định disabled vẫn giữ nguyên.

## 14. Test-First GREEN Evidence

Command chính, với `PYTHONDONTWRITEBYTECODE=1`:

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/integration/test_partition_runtime_e2e.py -q --tb=short -p no:cacheprovider
```

GREEN sau sửa newline: 52 passed / 32.44s; sau bổ sung recovery: 65 passed / 40.07s; bản cuối: **66 passed / 40.87s**, exit 0. Không cộng các lần chạy chồng lặp thành số test độc lập.

## 15. Regression Results

Selection C5 + C4 QA + C3 worker/persistence + C2 core + C1 contracts/snapshots + DataWorker/recovery + runtime/QA/revision/CLI + architecture: **585 passed / 320.51s**, exit 0.

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/integration/test_partition_runtime_e2e.py tests/integration/test_partition_operational_qa.py tests/integration/test_partition_worker_artifacts.py tests/integration/test_partition_artifact_runtime.py tests/unit/application/test_data_partition.py tests/integration/test_partition_core_persistence.py tests/unit/application/test_partition_contracts.py tests/integration/test_partition_snapshot_compatibility.py tests/unit/application/test_data_worker.py tests/integration/test_data_recovery.py tests/integration/test_worker_execution_runtime.py tests/integration/test_operational_deliverable_qa.py tests/integration/test_deliverable_qa_sqlite.py tests/unit/application/test_deliverable_qa.py tests/integration/test_data_revision_foundation.py tests/integration/test_data_revision_execution.py tests/integration/test_revision_operator_qa.py tests/integration/test_runtime_operator_cli.py tests/unit/test_architecture.py -q --tb=short -p no:cacheprovider
.\.venv\Scripts\python.exe -B -m mypy --strict --cache-dir $c5MypyCache
.\.venv\Scripts\python.exe -B -m ruff check . --no-cache
.\.venv\Scripts\python.exe -B -m ruff format --check . --no-cache
git diff --check
```

`$c5MypyCache` là OS temporary directory `agentmine-c5-mypy`. Strict mypy: **286 source files, PASS**. Ruff check: PASS. Format ở lần xác nhận trước: **390 files already formatted**; chạy lại khi hoàn tất harness: **392 files already formatted**, PASS. Diff check: exit 0. Không tắt rule, thêm ignore hay giảm type strictness.

Full pytest rerun: **1801 passed in 742.48s (0:12:22)**, exit 0; không có failed/skipped được pytest báo trong summary. Command: `.\.venv\Scripts\python.exe -B -m pytest -q --tb=short -p no:cacheprovider`, với `PYTHONDONTWRITEBYTECODE=1`; log tại `.tmp/c5-full-pytest.log`. Lần chạy cũ không truy xuất được completion nên không tính là PASS. Các con số 66, 585 và 1801 chồng lặp, không cộng lại.

Các safe module-entrypoint commands đã chạy exit 0:

```powershell
.\.venv\Scripts\python.exe -B -m agentmine.bootstrap.operator work prepare --help
.\.venv\Scripts\python.exe -B -m agentmine.bootstrap.operator work export --help
.\.venv\Scripts\python.exe -B .tmp/run_c5_simulation.py
```

## 16. Files Changed

Production C5:

- `src/agentmine/presentation/runtime_inputs.py`: strict explicit v2 parsing.
- `src/agentmine/presentation/runtime_views.py`: display approved v2 policy.
- `src/agentmine/application/use_cases/worker_preflight.py`: remove blanket guard, preserve all evidence checks.
- `src/agentmine/application/ports/local_runtime.py`: optional explicit export metadata.
- `src/agentmine/application/use_cases/local_runtime.py`: retained v2 export integrity.
- `src/agentmine/infrastructure/local_artifact_export.py`: exact v2 inventory/manifest, legacy compatibility.

New tests: `tests/integration/test_partition_runtime_e2e.py`, `tests/unit/application/partition_e2e_fakes.py`, `tests/contract/fixtures/data_partition_c5/`.

Focused compatibility edits: `tests/integration/test_partition_artifact_runtime.py`, `tests/integration/test_partition_snapshot_compatibility.py`, `tests/unit/application/partition_qa_fakes.py`.

Report: this file. Ignored execution evidence/scripts live only under `.tmp/`. No dependencies introduced. Architecture deviation: none; the port extension is backward-compatible explicit metadata, not an infrastructure dependency in Application.

## 17. Risks and Remaining Gaps

- No live eligibility/agentAccess or client acceptance verified; no real marketplace fulfillment readiness claim.
- Dirty catalog remains client-unacceptable without authoritative corrections and separate approved rework.
- Provenance records retained input origin; it cannot establish truth of operator-provided source facts.
- Local hardlink/export filesystem limitations remain; no remote publication added.
- Unknown infrastructure/tool costs must remain unknown until measured.
- Recovery tests use controlled faults; broader power-loss/platform behavior is not certified.
- Actual earning requires separately approved source/account/submission/outcome/payment work. C5 authorizes none of it.

## 18. Git Status

Baseline manifest `.tmp/c5-baseline.json` tracked 137 pre-existing dirty/untracked files. C5 intentionally changed five of those paths: local_runtime use case, worker_preflight and three compatibility test/helper files. The other 132 baseline files were preserved at last hash verification. Additional C5 files were new or previously clean. Whole-worktree diff includes C1–C4 and must not be attributed entirely to C5.

No files staged, committed or pushed. Snapshot `git status --short` nằm ngay bên dưới.

Snapshot cuối (bao gồm thay đổi C1–C4 đã có sẵn):

```text
 M src/agentmine/application/contracts/data.py
 M src/agentmine/application/contracts/data_revision.py
 M src/agentmine/application/contracts/local_runtime.py
 M src/agentmine/application/contracts/qa.py
 M src/agentmine/application/contracts/runtime.py
 M src/agentmine/application/contracts/worker_execution.py
 M src/agentmine/application/ports/local_runtime.py
 M src/agentmine/application/qa/checks.py
 M src/agentmine/application/use_cases/data_revision.py
 M src/agentmine/application/use_cases/deliverable_qa.py
 M src/agentmine/application/use_cases/local_runtime.py
 M src/agentmine/application/use_cases/operational_qa.py
 M src/agentmine/application/use_cases/worker_preflight.py
 M src/agentmine/application/workers/data.py
 M src/agentmine/application/workers/data_transform.py
 M src/agentmine/infrastructure/local_artifact_export.py
 M src/agentmine/infrastructure/snapshots.py
 M src/agentmine/presentation/runtime_inputs.py
 M src/agentmine/presentation/runtime_views.py
?? docs/audits/phase-b4-2-deliverable-contract-qa-design.md
?? docs/audits/phase-b4-3-c1-contracts-snapshots.md
?? docs/audits/phase-b4-3-c2-partition-core.md
?? docs/audits/phase-b4-3-c3-worker-artifacts-persistence.md
?? docs/audits/phase-b4-3-c4-operational-qa-acceptance.md
?? docs/audits/phase-b4-3-c5-runtime-e2e.md
?? docs/audits/phase-b4-realistic-bounty-simulation.md
?? src/agentmine/application/qa/partition_checks.py
?? src/agentmine/application/workers/data_partition.py
?? src/agentmine/application/workers/data_partition_artifacts.py
?? tests/contract/fixtures/data_partition/
?? tests/contract/fixtures/data_partition_c2/
?? tests/contract/fixtures/data_partition_c3/
?? tests/contract/fixtures/data_partition_c4/
?? tests/contract/fixtures/data_partition_c5/
?? tests/integration/test_partition_artifact_runtime.py
?? tests/integration/test_partition_core_persistence.py
?? tests/integration/test_partition_operational_qa.py
?? tests/integration/test_partition_runtime_e2e.py
?? tests/integration/test_partition_snapshot_compatibility.py
?? tests/integration/test_partition_worker_artifacts.py
?? tests/unit/application/partition_artifact_fakes.py
?? tests/unit/application/partition_e2e_fakes.py
?? tests/unit/application/partition_qa_fakes.py
?? tests/unit/application/test_data_partition.py
?? tests/unit/application/test_partition_contracts.py
```

## 19. Final Verdict

**C5_PASS**. Continuous local offline v2 workflow, independent oracle agreement, QA gates, safe export, replay/recovery và legacy compatibility được chứng minh bằng các kiểm tra đã chạy. Đây không phải production, live eligibility hay payment readiness. Dừng tại C5 để operator review; đề xuất bước tiếp theo là independent local acceptance audit C1–C5, chưa chạy live bounty.

Bàn giao cuối:

- Report: `docs/audits/phase-b4-3-c5-runtime-e2e.md`.
- Commands và kết quả chính xác: mục 14–15; full suite 1801 passed, focused 66 passed, regression selection 585 passed, strict mypy/Ruff/format/diff đạt.
- Files changed: mục 16; không thêm dependency, không đổi Domain hay transaction semantics.
- Deviations: không có thay đổi kiến trúc ngoài phạm vi; lỗi newline oracle và cập nhật temporary guard probes được công khai ở mục 3–4.
- Risks: mục 17; catalog bẩn vẫn không đạt client acceptance, nguồn/provenance chưa được xác minh live, chi phí chưa đo vẫn UNKNOWN.
- Post-B.4.3: chờ operator review và audit acceptance local độc lập; không tự khởi động checkpoint mới, không stage/commit/push.

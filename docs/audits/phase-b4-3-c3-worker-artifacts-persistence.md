# Phase B.4.3-C3 — Worker Artifacts & Persistence

Ngày kiểm chứng: 2026-11-03. Checkpoint chỉ bao gồm C3; không triển khai C4/C5.

## 1. Executive Summary

Đã nối partition core C2 vào DataWorker cho thực thi v2 cô lập, deterministic và không dùng LLM. Kết quả có đầy đủ bằng chứng parse tạo đúng bốn artifact: `clean.csv`, `clean.json`, `rejected.json`, `validation.json`. Bằng chứng không đầy đủ chỉ tạo `validation.json`; các record parse được vẫn giữ trong DataResult.

Oracle độc lập được ghi trước thay đổi production. Bộ hồi quy tập trung hiện đạt **291 passed**. Báo cáo phân biệt artifact kỹ thuật đúng với client acceptance: C3 không quyết định chấp nhận deliverable, không mở runtime CLI v2 hoặc operational QA v2.

Commit nền: `7c660a8adfac07e408c3e3939988c9697770c204`. Worktree đã có thay đổi C1/C2 chưa commit từ trước. Không commit, push hoặc stage trong C3.

## 2. Approved Scope

Đã đọc AGENTS.md, Product Constitution, thiết kế B4.2 và báo cáo C1/C2; đối chiếu source hiện tại trước thay đổi. Giữ nguyên các quyết định: v2 opt-in bằng output policy; None là v1; Duplicate Policy A là REJECT_ALL; thresholds được giữ bất biến trong plan; `DataResult.valid = not issues`.

Thay đổi production giới hạn ở DataWorker, renderer v2 mới và guard WorkerResult theo phiên bản. Không sửa Domain, port, BudgetManager, journal, database schema, transaction, eligibility, submission, reward, QA engine hoặc CLI. Không thêm dependency.

## 3. Test-First RED Evidence

Trước sửa production, đã tạo `tests/contract/fixtures/data_partition_c3/` gồm 24 case và 87 file artifact kỳ vọng literal. Script chuẩn bị chỉ dùng thư viện chuẩn, dữ kiện kỳ vọng C2 và các quy tắc serialization chỉ định trước; không import AgentMine, không gọi worker, partition core hoặc renderer production để sinh expected output. Manifest SHA-256 được ghi cùng oracle trước triển khai.

Lệnh RED thực tế:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -m pytest tests/integration/test_partition_worker_artifacts.py -q --tb=short -p no:cacheprovider
```

Kết quả: **35 failed, 2 passed in 5.03s**. Các case v2 chính thất bại vì direct-worker guard C2 trả UNSUPPORTED. Hai test không cần thực thi v2 vẫn đạt. Đây là RED của worker/artifact trước production; các test atomic finish, authorization và corruption được bổ sung sau vòng GREEN đầu, không trình bày chúng như cùng một vòng RED.

Các file expected không được tái sinh từ actual output. README của fixture giải thích nguồn gốc; test manifest kiểm tra byte/hash.

## 4. Worker Integration

`src/agentmine/application/workers/data.py` gọi duy nhất `partition(plan)` của C2 khi output_policy có giá trị. v1 giữ transform/validate và renderer cũ. Không chép lại duplicate grouping trong worker hoặc renderer.

Thứ tự: lưu immutable plan → đọc retained result → kiểm tra deadline/authorization theo protocol hiện hữu → partition → render → lưu DataResult → ghi actual cost. Replay đọc original result, kiểm tra cấu trúc/artifact v2 từ retained evidence rồi dùng cơ chế ghi cost idempotent hiện hữu. Không chạy lại partition khi đã có result.

Cached result thiếu partition/cost hoặc có artifact không khớp bị từ chối bằng INVALID_RESPONSE; không tự sửa artifact và không biến unknown cost thành zero. AI response bất ngờ trong nhánh v2 chưa có result bị chặn OUTCOME_UNKNOWN. Không có semantic execution v2 vì contract C1 đã cấm semantic columns.

Renderer nằm ở Application, dùng dữ liệu contract và thư viện chuẩn; không phụ thuộc SQLite hoặc adapter. Infrastructure hiện hữu chỉ giữ vai trò persistence. Dependency direction không thay đổi.

## 5. Artifact Schemas

| Artifact | Nội dung và thứ tự |
|---|---|
| clean.json | Array theo clean_rows C2; mọi cột được duyệt, giá trị string/null, `_provenance` đầy đủ |
| clean.csv | Header theo DataPlan.columns rồi `_provenance`; thứ tự row giống clean.json; UTF-8 không BOM, LF, quoting minimal |
| rejected.json | Array chứa row_id, normalized values, mọi reason và `_provenance`; duplicate reason có group_id |
| validation.json | contract_version, policy, evidence_complete, input_valid, counts, total_input_records, sources, issues, duplicate_groups, unresolved |

JSON dùng sorted keys, indent=2, ASCII escape, không newline cuối; provenance trong CSV là compact sorted JSON. Số canonical vẫn là string; không đổi sang floating point. CSV thêm apostrophe cho giá trị có ký tự đầu sau lstrip là `=`, `+`, `-`, `@`; JSON giữ nguyên giá trị. Test bao gồm newline, dấu phẩy, quote và số âm hợp lệ.

Provenance giữ source reference, digest, locator, source row, row_id, collected_at, source path, input_presence và lookup evidence. Nhãn source_verification luôn là `caller_supplied_unverified`; không tự nâng độ tin cậy của nguồn. Semantic evidence không được tạo.

CSV ô rỗng không tự phân biệt null/missing/blank; cần provenance hoặc JSON. Artifact không chứa `client_acceptance=PASS`. Threshold nằm trong frozen DataPlan, không bị renderer suy diễn.

## 6. Evidence Completeness

Với malformed source, source parsed_count giữ null; total_input_records cũng null. counts.parsed chỉ là số record thực sự parse được, không phải tổng input đã biết. Clean candidates của các source hợp lệ vẫn có thể có trong assessment nhưng không được xuất thành dataset khi evidence_complete=false.

Chỉ validation.json được phát hành trong trường hợp này. Full issues, source parse outcomes và lỗi source/batch vẫn tồn tại. Tất cả record parse được vẫn được giữ nội bộ và readback từ journal.

Batch hoàn toàn parse được nhưng có RECORD_COUNT vẫn xuất bộ bốn file để giữ biểu diễn, đồng thời input_valid=false và unresolved chứa issue. **C4 phải đánh giá và từ chối acceptance khi cần; số clean row không thể che batch-level error.** Empty batch hoặc all-rejected batch có CSV header và JSON array rỗng đúng oracle, không có ngầm định acceptance.

## 7. Duplicate Policy A Preservation

C2 partition core không thay đổi. Mọi thành viên của nhóm normalized duplicate-ID đều bị reject; không có first-wins/last-wins. Rejected record vẫn giữ các lỗi khác cùng duplicate reason. Group ID, canonical ID và members được chiếu từ assessment đã có; renderer không tự băm lại hoặc phân nhóm lại.

Oracle kiểm tra hai/ba bản trùng, nhiều nhóm, cross-source, Unicode, duplicate kèm lỗi khác, invalid/missing ID không được đưa nhầm vào nhóm. Nguồn và thứ tự record/issue theo C2 giữ nguyên.

## 8. Persistence and Recovery

Dùng SQLiteDataJournal, SQLiteCostLedgerRepository và SQLiteWorkerRuntimeRepository hiện hữu, file-backed trong tmp_path riêng từng test. Không sửa protocol giao dịch.

| Điểm lỗi được mô phỏng | Bằng chứng và phục hồi |
|---|---|
| Renderer hoặc trước save_result | Không có result/cost; replay cùng frozen plan/IDs chạy deterministic lại |
| Sau save_result, mất acknowledgement | Result còn nguyên; restart đọc lại, không recompute partition |
| Trước ghi cost | Result đã durable; original-ID retry ghi cost đúng một lần |
| Sau ghi cost, mất acknowledgement | Replay không nhân đôi actual cost hoặc ledger record |
| Trước/giữa atomic finish | Result/cost đã durable; rollback content/deliverable/opportunity/finish cùng transaction |
| Sau commit finish, mất acknowledgement | Retry original command đọc original finish, không cấp ID hoặc charge mới |
| Cùng ID đổi policy, thresholds hoặc source | Immutable plan conflict; không thay lịch sử hoặc chi phí |
| Cached artifact bị hỏng hoặc core-only result thiếu cost | Fail closed; không repair hoặc ghi zero cost |

Test atomic finish thử cả complete và incomplete evidence, lỗi sau từng loại write: content, deliverable, opportunity, runtime_finish. Kiểm tra bundle content reference/digest, original identities, QA_PENDING và không có approval/submission/revenue.

**Ranh giới bằng chứng:** production ExecuteWorkerTask vẫn trả CAPABILITY_UNAVAILABLE trước authorization/dispatch cho v2. Test atomic finish trước hết xác nhận guard đó, sau đó dùng lệnh repository nội bộ được tạo rõ ràng trong test-only composition để kiểm chứng contract lưu trữ. Đây không phải luồng CLI v2 liên tục, không phải production readiness. FakeSource/FakeClock chỉ thuộc test.

## 9. Independent Oracle Results

24 case bao gồm 20 case C2 với expected partition literal và bốn case artifact bổ sung: formula/quoting, negative numeric, lookup provenance, nested input presence. Tổng 87 artifact literal; mọi output so sánh exact UTF-8 bytes với fixture.

Kiểm tra riêng inventory/media type, schema và key order qua exact bytes, header/row order, canonical numeric, provenance, valid predicate, source outcomes và digest. Không lấy actual output làm expected. Independent here có nghĩa expected không chạy implementation; không phải chứng nhận của bên thứ ba.

## 10. Legacy Compatibility

Renderer `data_artifacts.py`, C2 core/transform và bộ C1 snapshot không bị sửa trong C3. None vẫn chạy v1. WorkerResult v1 tiếp tục từ chối partition evidence và artifact v2; allowlist legacy không được mở rộng chung.

Chỉ thay test tạm `test_direct_worker_cannot_render_v2_with_legacy_artifacts`: trước đây mong UNSUPPORTED của C2, giờ yêu cầu real v2 partition, đúng bộ bốn file và retained cost; tên test tiếp tục kiểm tra không dùng artifact legacy. Đây là thay thế guard được user cho phép trong C3.

Snapshot compatibility, contract, C2 oracle, DataWorker v1, recovery, execution và operational QA nằm trong bộ hồi quy 291 test. Không tuyên bố v1 tương thích chỉ dựa vào class name/comment.

## 11. Safety and Cost

Composition C3 mới dùng real DataWorker(llm=None), real BudgetManager, ledger với requested mode SCOUT_ONLY và monthly/daily/per-task/threshold đều 0 USD. Authorization phải tồn tại trong ledger trước computation. Test foreign authorization và expired task xác nhận không tạo result/cost.

Deterministic worker ghi actual AI cost 0 qua protocol hiện hữu, một lần cho original operation; đây là chi phí AI đo được của đường không gọi AI, không phải lời khẳng định tổng execution miễn phí. Warning infrastructure_cost_not_measured được giữ. Core-only result có cost=None không được tự biến thành record 0.

Không gọi live Superteam, LLM, submission hoặc wallet; không truy cập secret, không dùng database production, không ghi synthetic revenue. Test finish xác nhận verified_revenue=0 và không có submission/approval. Không thay global operating mode hoặc policy workspace người dùng.

## 12. Test-First GREEN Evidence

Sau triển khai renderer/worker ban đầu: cùng lệnh RED đạt **37 passed in 5.33s**.

Sau bổ sung persistence/authorization/corruption coverage và thay test guard C2:

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/integration/test_partition_worker_artifacts.py tests/integration/test_partition_artifact_runtime.py tests/unit/application/test_data_partition.py -q --tb=short -p no:cacheprovider
```

Kết quả: **85 passed in 15.89s**. Đây là một tập gộp; không cộng nó với các bộ hồi quy chồng lặp.

## 13. Regression Results

Lệnh tập trung/hồi quy đã chạy:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -m pytest tests/integration/test_partition_worker_artifacts.py tests/integration/test_partition_artifact_runtime.py tests/unit/application/test_data_partition.py tests/integration/test_partition_core_persistence.py tests/unit/application/test_partition_contracts.py tests/integration/test_partition_snapshot_compatibility.py tests/unit/application/test_data_worker.py tests/integration/test_data_recovery.py tests/integration/test_worker_execution_runtime.py tests/integration/test_operational_deliverable_qa.py tests/unit/test_architecture.py -q --tb=short -p no:cacheprovider
```

**291 passed in 50.80s.** Bao gồm C3, C2 oracles/persistence, C1 contracts/snapshots, DataWorker/recovery, worker execution, operational QA và architecture. Những con số này là các tập chồng lặp, không cộng thành tổng.

Static checks đã chạy:

```powershell
.\.venv\Scripts\python.exe -B -m ruff check . --no-cache
.\.venv\Scripts\python.exe -B -m ruff format --check . --no-cache
$c3MypyCache = Join-Path ([IO.Path]::GetTempPath()) 'agentmine-c3-mypy'
.\.venv\Scripts\python.exe -B -m mypy --strict --cache-dir $c3MypyCache
git diff --check
```

Kết quả: Ruff All checks passed; format 381 files already formatted; strict mypy Success, 281 source files; diff check exit 0. Lần mypy đầu phát hiện hai lỗi inference type của patch context trong test mới; đã sửa annotation AbstractContextManager rồi chạy lại đạt. Không che giấu lỗi verification ban đầu.

Full suite:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -m pytest -q --tb=short -p no:cacheprovider
```

**1660 passed in 897.27s (0:14:57), exit 0.** Summary không báo failed, skipped hoặc warning. Đây là kết quả chạy mới trong C3, không tái sử dụng kết quả C1/C2.

## 14. Files Changed

Production C3:

- `src/agentmine/application/workers/data.py`: direct isolated v2 path, retained-result integrity guard; v1 giữ nhánh cũ.
- `src/agentmine/application/workers/data_partition_artifacts.py`: renderer pure v2 mới.
- `src/agentmine/application/contracts/runtime.py`: WorkerResult inventory theo version/evidence completeness, giữ guard v1.

Tests/docs C3:

- `tests/integration/test_partition_worker_artifacts.py`: literal oracle, auth, replay, crash và corruption.
- `tests/integration/test_partition_artifact_runtime.py`: internal atomic finish/recovery, allowlist và guard runtime.
- `tests/unit/application/partition_artifact_fakes.py`: composition offline cho test.
- `tests/unit/application/test_data_partition.py`: thay duy nhất kỳ vọng guard direct-worker C2.
- `tests/contract/fixtures/data_partition_c3/`: cases.json, sha256.json, README.md và 87 expected artifact files.
- `docs/audits/phase-b4-3-c3-worker-artifacts-persistence.md`: báo cáo này.

Scratch phục vụ kiểm chứng nằm dưới `.tmp/` đã bị ignore: baseline hash và script chuẩn bị oracle. Không được dùng trong runtime; không stage. Không xóa phần công việc trước.

## 15. Risks / Deferred C4-C5 Work

1. **C4:** operational acceptance QA v2 chưa triển khai. Cần kiểm tra thresholds, evidence completeness, unresolved batch errors và partition correctness; không được chỉ dùng DataResult.valid hoặc clean count.
2. **C5:** runtime/CLI opt-in và export v2 chưa mở. Existing CLI export allowlist không được sửa ở C3; readback đã chứng minh ở journal/bundle, không khẳng định local CLI export v2.
3. Input provenance là caller-supplied/unverified. C3 không chứng minh dữ liệu là sự thật ngoài đời hoặc một listing cho phép AI.
4. CSV formula escaping là cơ chế hiện hữu, không phải bảo đảm cho mọi spreadsheet consumer. Null/missing phải đọc provenance/JSON.
5. Crash tests là fault injection tại protocol/write boundaries, không phải thử mất điện thực hoặc nghiệm thu môi trường production.
6. Cached result validation kiểm tra phép chiếu cấu trúc/artifact; không thay thế independent semantic/client QA C4.
7. Actual AI 0 không có nghĩa tool/infrastructure cost được đo đủ; không đưa ra kết luận profitability.

Không phát hiện yêu cầu thay transaction semantics hoặc thiết kế Domain để hoàn tất C3. Không có dependency mới, service mới hay policy nới lỏng.

## 16. Git Status

Repository thực tế trong môi trường này là `D:\DNTU\Tuhoc\AgentMine`; đường dẫn có dấu trong context cũ không tồn tại. Mọi kiểm thử và thay đổi diễn ra trong repo thực tế này.

Trước C3 đã có nhiều source/docs/tests C1/C2 dirty/untracked. Đã ghi checksum 33 path trước sửa. Sau C3 chỉ ba path trong baseline thay đổi: application/contracts/runtime.py, application/workers/data.py và tests/unit/application/test_data_partition.py. Ba thay đổi này được giải thích ở trên; 30 path còn lại giữ exact bytes. Các file mới C3 được liệt kê riêng, không gán nhầm toàn bộ git diff cho C3.

Output `git status --short` sau khi tao bao cao (bao gom ca C1/C2 da co):

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
?? docs/audits/phase-b4-3-c3-worker-artifacts-persistence.md
?? docs/audits/phase-b4-realistic-bounty-simulation.md
?? src/agentmine/application/workers/data_partition.py
?? src/agentmine/application/workers/data_partition_artifacts.py
?? tests/contract/fixtures/data_partition/
?? tests/contract/fixtures/data_partition_c2/
?? tests/contract/fixtures/data_partition_c3/
?? tests/integration/test_partition_artifact_runtime.py
?? tests/integration/test_partition_core_persistence.py
?? tests/integration/test_partition_snapshot_compatibility.py
?? tests/integration/test_partition_worker_artifacts.py
?? tests/unit/application/partition_artifact_fakes.py
?? tests/unit/application/test_data_partition.py
?? tests/unit/application/test_partition_contracts.py
```

Không commit, push, stage, reset hoặc destructive cleanup.

## 17. Final Verdict

**C3_PASS.** Artifact deterministic khớp oracle độc lập; partition/provenance được giữ; persistence/replay/cost idempotency đạt; full suite không báo regression. PASS chỉ áp dụng artifact/persistence C3, không phải client acceptance QA hoặc production v2 readiness.

C3 đủ cơ sở để operator xem xét chuyển sang thiết kế/triển khai C4 sau phê duyệt. Chưa được thực thi production CLI v2, chưa có client acceptance hoặc real bounty readiness. Dừng tại C3.

- Report path: `docs/audits/phase-b4-3-c3-worker-artifacts-persistence.md`.
- Exact commands/results: mục 3, 12 và 13; không cộng các tập test chồng lặp.
- Files changed: mục 14; phân biệt baseline C1/C2 ở mục 16.
- Deviations: không đổi approved semantics; chỉ thay guard tạm direct-worker theo quyền C3; runtime/QA guards giữ nguyên.
- Readiness for C4: artifact/persistence foundation sẵn sàng review, acceptance QA vẫn deferred.
- Recommended next action: operator review C3 và chỉ phê duyệt C4 như checkpoint riêng; không tự tiếp tục C4/C5.

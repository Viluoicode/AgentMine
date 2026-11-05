# Phase B.4.3-C4 — Operational QA & Frozen Acceptance Gates

Ngày kiểm chứng: 2026-11-04 (Asia/Bangkok). Phạm vi chỉ C4; không triển khai C5.

## 1. Executive Summary

C4 tích hợp kiểm tra deterministic v2 vào DeliverableQA và RunOperationalDataQA hiện hữu. QA tái dựng dữ liệu từ frozen source bytes, so sánh toàn bộ records/issues/assessment/artifacts, rồi áp dụng acceptance được duyệt trước execution. Không tin riêng validation.json, claimed counts hoặc bundle digest tự nhất quán.

Bộ C4 cuối đạt **75 passed in 37.23s**. Ruff, format, strict mypy và diff check đạt; kết quả full suite được ghi riêng ở mục 14. PASS trong báo cáo này chỉ là nghiệm thu kỹ thuật QA C4, không phải client acceptance, approval để submit, payment hoặc real bounty readiness.

Commit nền: `7c660a8adfac07e408c3e3939988c9697770c204`; worktree có C1–C3 chưa commit. Không stage, commit, push hoặc cleanup.

## 2. Approved Scope

Đối chiếu AGENTS.md, Product Constitution, thiết kế B4.2, báo cáo C1/C2/C3 và source hiện tại. Giữ v2 opt-in, output_policy=None là v1, Policy A REJECT_ALL, thresholds explicit/frozen, min_clean>=1, không ngầm cho phép reject records.

Chỉ thêm checker v2 trong pipeline QA hiện có và sửa hẹp các use case để bind evidence. Không tạo QA engine/approval system khác. Không thay Domain, C2 partition algorithm, C3 renderer, DataWorker, SQLite transaction/schema/journal, budget policy, provider hoặc CLI parser/export.

Files production dự kiến và thực tế: application/qa/checks.py; qa/partition_checks.py mới; use_cases/deliverable_qa.py; operational_qa.py; worker_preflight.py. Infrastructure vẫn thực thi các port có sẵn; Application không import adapter cụ thể.

## 3. Test-First RED Evidence

Trước production edits đã ghi literal `tests/contract/fixtures/data_partition_c4/qa-expectations.json`, manifest SHA-256 và 60 test acceptance/hostile evidence. 27 quyết định QA được viết trực tiếp từ quy tắc đã duyệt và expected facts C2/C3, không chạy production QA để sinh expected.

Lệnh RED:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -m pytest tests/integration/test_partition_operational_qa.py -q --tb=no -p no:cacheprovider
```

Kết quả RED trước production: **42 failed, 18 passed in 22.93s**, exit 1. Các failures chứng minh guard UNSUPPORTED chưa mở operational QA, thiếu phân loại FAIL cho forged evidence/inventory và thiếu replay verification. Những test binding/integrity cũ đã có hiệu lực có thể đạt ngay; không coi 18 test đó là lỗi test-first.

Lượt đầu với `--tb=short` đạt 42 failed/18 passed trong 28.76s nhưng có một lỗi setup: test coverage giữ nhầm source malformed ở vị trí đầu. Đã sửa để loại đúng source bị che giấu rồi chạy lại RED nêu trên, vẫn trước production edit. Không sửa expected outcome để lấy PASS.

15 test bổ sung sau GREEN đầu kiểm tra human-pending, paid/unbound rejection, altered inspection, historical approval, source freshness và revision contracts. Không trình bày các supplemental test này như cùng vòng RED ban đầu.

## 4. Frozen Acceptance Binding

RunOperationalDataQA đọc retained WorkerRun, original WorkSpecification, DataPlan, DataResult, deliverable và exact content từ cùng workspace. Với v2, get_specification phải trả đúng specification gốc; thiếu/thay đổi actor, ledger, schema/policy/requirements/threshold đều bị conflict.

QAInspection nhận nguyên PartitionAcceptance từ criteria đã freeze. Constructor C1 vẫn kiểm tra exact equality với plan và result policy. Retry so sánh cả thresholds, formats, requirements, plan, min_verified_sources mặc định và không có AI authorization. Candidate mới phải bằng retained inspection; Opportunity revision sau claim phải giữ nguyên.

Không cho caller thay Budget snapshot, authorization hoặc threshold để phù hợp output. Direct DeliverableQA v2 không có operational binding bị UNSUPPORTED; entrypoint có thẩm quyền cho retained execution là RunOperationalDataQA. Binding, ownership và lifecycle completion dùng port/SQLite repository hiện hữu.

Nguồn tham chiếu: `src/agentmine/application/use_cases/operational_qa.py:49`, `:84`, `:137`; `contracts/qa.py` giữ nguyên các binding C1, không migration.

## 5. Optional Field Semantics

| Trường hợp | V2 QA |
|---|---|
| Input thiếu optional field | Có output key null; provenance MISSING; có thể PASS nếu schema/criteria cho phép |
| Input explicit null | Có output key null; provenance NULL; FIELD_PRESENT cho phép |
| Input blank string | Giữ origin VALUE dù canonical null; FIELD_PRESENT có thể cho phép |
| Required null | Actual missing_value; record bị reject, không giả thành clean |
| Optional non-null không hợp lệ | Actual invalid_value vẫn tồn tại và record bị reject |
| Output thiếu key, kể cả optional | Exact evidence/artifact mismatch → FAIL |
| Explicit JSON COLUMN | Vẫn yêu cầu key và non-null như v1; null → NEEDS_REVISION |

FIELD_PRESENT chỉ thực thi structural coverage trên clean.json của v2. COLUMN checker cũ không bị đổi. Một optional field không tự vượt criterion non-null đã được freeze. Zero-clean không thể PASS do vacuous `all([])`, vì gate min_clean>=1 luôn áp dụng sau integrity.

Tham chiếu: `application/qa/checks.py:132`; tests optional null/missing/blank, required-null, optional-invalid và COLUMN đối chứng.

## 6. Partition and Evidence Verification

`application/qa/partition_checks.py:15` nằm trong deterministic stage của DeliverableQA. Từ approved DataPlan có retained source bytes, checker:

1. Revalidate typed inspection/plan, policy/version, thresholds, schema và source snapshots.
2. Gọi pure partition C2 để tái dựng records, canonical values, input presence, ordered full issues và assessment.
3. So exact equality với retained DataResult: clean/rejected membership, reasons, group IDs/members, source outcomes/counts/completeness và record order đều phải khớp.
4. Dùng renderer C3 cho expected projection của chính replay đó và so exact artifact inventory/media type/order/bytes.
5. Giữ kiểm tra bundle digest với stored content/deliverable reference của pipeline cũ.

Như vậy conservation parsed=clean+rejected, full-group rejection, không first-wins, không drop reason/row/source, canonical values và provenance được kiểm chứng từ frozen bytes, không từ claimed clean count hoặc validation report.

Không sửa/chép lại algorithm C2 hoặc renderer C3. Việc dùng chung deterministic primitives không được quảng bá là một implementation độc lập: tính đúng được đối chiếu thêm bằng oracle literal C1/C2/C3 và expected QA C4. Test forged value + renderer-generated matching artifact + matching forged digest vẫn phải FAIL khi replay khác source.

Missing replay bytes trả typed UNSUPPORTED. Retained contradiction/unknown version hoặc issue/evidence không khớp cho FAIL, không fallback sang v1. Không truy cập URL hoặc filesystem từ locator khi QA.

## 7. Evidence Completeness / Global Issues

Một validation-only result do source malformed là evidence hợp lệ về biểu diễn, nhưng không phải deliverable hoàn chỉnh. Integrity phải khớp diagnostic inventory; không tạo lỗi giả vì các dataset vốn bị cấm publish. Domain acceptance sau đó trả PARTITION_INCOMPLETE và giữ global malformed-source issue.

Unknown parsed_count và total_input_records vẫn null trong retained artifacts; QA không invent row/count. Nếu completeness false, không PASS dù có clean candidate. Nếu có unresolved source/batch issue với row=None, kể cả RECORD_COUNT, không PASS dù clean/rejected nằm trong threshold.

Zero-clean/all-rejected/empty batch bị PARTITION_CLEAN_MINIMUM. Rejected vượt ngưỡng bị PARTITION_REJECT_LIMIT. Global/source errors không bị biến thành ordinary row rejections để vượt qua gate.

## 8. QA Outcomes and Lifecycle

| Tình huống | Outcome / hành vi |
|---|---|
| Evidence đúng, complete, criteria và thresholds đạt | PASS → existing Domain path tới READY_FOR_HUMAN_REVIEW |
| Evidence đúng nhưng incomplete/global issue/zero-clean/vượt ngưỡng/criterion thiếu | NEEDS_REVISION → existing QA failed/rework behavior |
| Evidence/artifact/provenance bị sửa, reasons/membership không khớp | FAIL khi kiểm tra được evidence; không PASS |
| Authority/source freshness/replay bytes unavailable hoặc snapshot conflict | Typed blocking/UNSUPPORTED; không tự tạo report PASS |
| Criterion semantic cần diễn giải | REQUIRES_HUMAN_REVIEW; QA_PENDING, không gọi AI |

Không thêm lifecycle state. DeliverableQA vẫn lưu report trước conditional completion. SQLiteOperationalQARepository dùng Domain.review_qa qua existing QACompletion; Presentation không mutate lifecycle.

QA PASS không tạo submission approval. Test operator review/decide thực hiện explicit approval riêng trên fixture, không submit. QA retry sau APPROVED_FOR_SUBMISSION giữ nguyên state, không kéo lùi về human review. Không accepted/payment/verified revenue tự động.

## 9. Independent Oracle Results

27 literal normal decisions bao phủ mọi fixture C3, cộng đối chứng min-clean/max-rejected:

- all-valid/optional-null/lookup/nested/formula/numeric có thể PASS theo criteria.
- mixed clean1/reject1: maximum2 PASS, maximum0 NEEDS_REVISION.
- hai duplicates + một valid: clean1/reject2, maximum2 PASS; maximum0 NEEDS_REVISION.
- ba duplicates: zero-clean, không PASS dù maximum3.
- cross-source duplicates phải reject đủ group trước đánh giá acceptance.
- all-rejected, missing/invalid ID, optional-invalid, empty, malformed và batch issue không thể PASS trong các brief literal tương ứng.

Hostile tests có literal FAIL assertions cho altered normalized value, provenance, presence, missing column, unknown issue, missing reason, first duplicate bị đưa vào clean, che source, output key thiếu, extra/missing artifact và corrupted bytes. Có cả forged digest tự nhất quán và forged artifact được re-render; không chỉ so hai production functions với nhau.

Manifest expectation C4 giữ nguyên từ trước production. Toàn bộ C1/C2/C3 expected artifacts/reports/fixtures không đổi; kiểm tra hash ghi ở mục 17. Không có evidence live client hoặc Superteam.

## 10. Persistence and Replay

Dùng SQLite file-backed trong tmp_path và real DataWorker/DeliverableQA/production bootstrap composition. Test-only FakeSource/FakeClock cung cấp source observations và thời gian; không phải source thật.

Setup retained v2 dùng internal WorkerRunStart/finish như C3, sau khi test xác nhận ExecuteWorkerTask vẫn CAPABILITY_UNAVAILABLE và chưa có run. Đây là setup contract test riêng, không phải production CLI v2 được mở.

| Điểm recovery | Bằng chứng |
|---|---|
| Sau report persistence, trước lifecycle, mất ack | Original inspection/report retained; retry cùng ID hoàn tất, không tính QA lại hoặc ghi cost mới |
| Opportunity thay revision sau report | Conflict; không rebase original decision lên state mới |
| Inspection bị đổi thresholds/result/requirements | Conflict; original report không được tái sử dụng cho evidence khác |
| Retry/reopen sau PASS | Readback original report, không worker replay hoặc source revalidation cho quyết định đã apply |
| Retry sau NEEDS_REVISION hoặc human-pending | Giữ exact original history/state/cost, không apply lần hai |
| Concurrent inspection IDs | Chỉ một owner; attempt còn lại blocked; không overwrite lịch sử |
| Sau operator approval riêng | Historical readback không kéo lùi approval hoặc gửi submission |

Không thay transaction semantics. Các regression hiện hữu kiểm tra rollback trong claim/completion và version-aware QA. Fault injection là mô phỏng protocol failure; không tuyên bố đã thử power loss thực.

## 11. Legacy Compatibility

output_policy=None tiếp tục checker Data v1 và renderer/worker cũ. COLUMN giữ nguyên body kiểm tra non-null. Không alias artifact clean.json thành data.json hoặc auto-activate policy. Không thay DataResult.valid, snapshot codec, C1 contracts hoặc F05 revision business rules.

Test C4 về DataRevisionRequest dùng parent v2 thật đã QA trong fixture, rồi kiểm tra contract cho proposal tương lai: có thể siết min/max; giảm min-clean, tăng max-rejected hoặc đổi COLUMN thành FIELD_PRESENT bị reject. Không approve/execute một v2 revision, không mở C5 revision workflow.

C1 snapshot, C2 oracle, C3 artifact/persistence, legacy QA, worker/recovery và F05 runtime/CLI regressions được chạy trong selection mục 14. Source DataWorker/C2/C3 renderer và fixture hashes giữ nguyên.

## 12. Safety and Cost

Test composition C4 giữ SCOUT_ONLY, monthly/daily/per-task/threshold AI budget 0 USD. Real DataWorker(llm=None) đã ghi actual AI 0 trước QA theo protocol C3; QA không tạo cost mới hoặc mutate ledger. Không suy ra toàn bộ infrastructure/tool cost đã được đo là zero.

Operational QA và direct v2 DeliverableQA từ chối paid provider/budget/AI authorization. Semantic criterion chỉ nhận human-pending qua cơ chế hiện hữu, không gọi provider. QAProvider trong test cấu hình lỗi có calls=[]; production không có mock fallback mới.

Không live Superteam, paid LLM, wallet/payment transaction, submission, API key/secret access hoặc production workspace mutation. verified revenue luôn 0 trong fixtures operational. Operator approval test là approval synthetic đã ghi nhãn test-only, không đại diện quyền trên một bounty thật.

## 13. Test-First GREEN Evidence

Lệnh focused cuối:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -m pytest tests/integration/test_partition_operational_qa.py -q --tb=short -p no:cacheprovider
```

**75 passed in 37.23s.** GREEN đầu 60 passed in 38.51s; sau supplemental safety/replay cases có 69 và 71 test đạt. Chỉ dùng 75 làm focused final, không cộng các lần chạy chồng lặp.

Static errors ban đầu: mypy bắt dynamic **dict trong dataclass replace của test; Ruff bắt import/line length. Đã dùng named typed arguments, format các file C4 và chia explanation strings; không nới cấu hình hoặc thêm ignore để che lỗi.

## 14. Regression Results

Lệnh regression selection đã thực thi:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -m pytest tests/integration/test_partition_operational_qa.py tests/integration/test_partition_worker_artifacts.py tests/integration/test_partition_artifact_runtime.py tests/unit/application/test_data_partition.py tests/integration/test_partition_core_persistence.py tests/unit/application/test_partition_contracts.py tests/integration/test_partition_snapshot_compatibility.py tests/unit/application/test_data_worker.py tests/integration/test_data_recovery.py tests/integration/test_worker_execution_runtime.py tests/integration/test_operational_deliverable_qa.py tests/integration/test_deliverable_qa_sqlite.py tests/unit/application/test_deliverable_qa.py tests/integration/test_data_revision_foundation.py tests/integration/test_data_revision_execution.py tests/integration/test_revision_operator_qa.py tests/integration/test_runtime_operator_cli.py tests/unit/test_architecture.py -q --tb=short -p no:cacheprovider
```

**513 passed in 225.44s (0:03:45), exit 0.**

Selection này collect 69 test C4 tại thời điểm start; sáu supplemental C4 cases còn lại đã nằm trong final focused 75 và full-suite collection sau đó. Không mô tả selection cũ như đã collect đủ 75. Không cộng các số test chồng lặp.

Static checks:

```powershell
.\.venv\Scripts\python.exe -B -m ruff check . --no-cache
.\.venv\Scripts\python.exe -B -m ruff format --check . --no-cache
$c4MypyCache = Join-Path ([IO.Path]::GetTempPath()) 'agentmine-c4-mypy'
.\.venv\Scripts\python.exe -B -m mypy --strict --cache-dir $c4MypyCache
git diff --check
```

Ruff: All checks passed. Format: **386 files already formatted**. Strict mypy: **Success, 284 source files**. git diff --check: exit 0. Đây là kết quả chạy C4 mới, không dùng lại kết quả C3.

Full suite, sau khi chốt source và đủ 75 test C4:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -m pytest -q --tb=short -p no:cacheprovider
```

**1735 passed in 809.03s (0:13:29), exit 0.** Summary không báo failed, skipped hoặc warning. Full suite đã collect đủ 75 test C4 cuối; không có sửa source/test sau khi bắt đầu lượt này.

## 15. Files Changed

Production C4:

- `src/agentmine/application/qa/partition_checks.py` — mới; replay integrity và frozen acceptance checks trong DeliverableQA pipeline.
- `src/agentmine/application/qa/checks.py` — v2 evidence stage, FIELD_PRESENT và domain acceptance branch; legacy COLUMN body giữ nguyên.
- `src/agentmine/application/use_cases/deliverable_qa.py` — yêu cầu operational binding và zero-AI cho v2.
- `src/agentmine/application/use_cases/operational_qa.py` — original specification/acceptance/history binding; gỡ riêng QA UNSUPPORTED guard; gọi QA-only evidence preflight.
- `src/agentmine/application/use_cases/worker_preflight.py` — tách common evidence checks; check() vẫn chặn v2 dispatch, check_qa() chỉ phục vụ retained QA.

Tests/docs C4:

- `tests/integration/test_partition_operational_qa.py` — 75 cases.
- `tests/unit/application/partition_qa_fakes.py` — isolated retained evidence setup, real SQLite/worker/bootstrap, test-only source/clock.
- `tests/contract/fixtures/data_partition_c4/qa-expectations.json`, `sha256.json`, `README.md` — literal oracle và provenance.
- `docs/audits/phase-b4-3-c4-operational-qa-acceptance.md` — báo cáo này.

Không dependency, ADR, Domain, port, infrastructure schema hoặc transaction change. `.tmp/c4-baseline.json` là checksum scratch ignored, không runtime data. Không sửa expected C1/C2/C3 để làm test pass.

## 16. Risks / Deferred C5 Work

1. Production ExecuteWorkerTask và revision execution vẫn dùng WorkerPreflight.check, giữ CAPABILITY_UNAVAILABLE cho v2. Chỉ guard operational QA được mở vì retained evidence verification đã có; dispatch không được mở theo guard đó.
2. C5 vẫn cần CLI opt-in parser/approval representation, runtime dispatch và export v2 đầy đủ. C4 không thêm command/flag hoặc nới exporter allowlist.
3. QA replay kiểm tra đúng phép biến đổi theo frozen inputs, không xác thực source truth, licensing hoặc client acceptance. Provenance vẫn caller_supplied_unverified.
4. Shared C2 primitives và C3 renderer không là hai implementation độc lập. Literal oracles và hostile evidence tests là đối chứng; chưa có nghiệm thu dữ liệu thật/bounty thật.
5. V2 revision acceptance contract được kiểm tra nhưng revision execution chưa được mở. Không tự chạy rework hoặc dùng first-run replay thay revision.
6. Unknown tool/infrastructure cost vẫn unknown; không tính profitability hoặc real revenue.
7. Không có continuous production CLI v2 E2E hay live source/provider verification. Dữ liệu operational trong test là fixture và internal setup được ghi rõ.

Không có design ambiguity buộc đổi approved semantics; QA-only preflight factoring là thay đổi hẹp cần thiết để giữ freshness mà không mở dispatch. Không thêm framework hoặc approval model.

## 17. Git Status

Repo thực tế: `D:\DNTU\Tuhoc\AgentMine`; đường dẫn có dấu trong context cũ không tồn tại. Không truy cập hoặc tạo production workspace database.

Trước sửa đã ghi checksum **128 file C1–C3 dirty/untracked**. Trong nhóm này chỉ hai file thay đổi có chủ đích ở C4: use_cases/operational_qa.py và worker_preflight.py; **126 file còn lại giữ exact bytes**. qa/checks.py và deliverable_qa.py trước đó clean; thay đổi C4 của chúng được liệt kê riêng. Không gán toàn bộ git diff nền cho C4.

Manifest C1/C3 và literal C2 oracle đều đã đối chiếu nguyên vẹn; C4 manifest cũng khớp bytes trước production. Các báo cáo trước giữ nguyên. Git diff --check không bao gồm untracked Markdown, nên báo cáo mới được kiểm tra UTF-8/Unicode và trailing whitespace riêng.

Output `git status --short` (gom ca C1-C3 da co):

```text
 M src/agentmine/application/contracts/data.py
 M src/agentmine/application/contracts/data_revision.py
 M src/agentmine/application/contracts/local_runtime.py
 M src/agentmine/application/contracts/qa.py
 M src/agentmine/application/contracts/runtime.py
 M src/agentmine/application/contracts/worker_execution.py
 M src/agentmine/application/qa/checks.py
 M src/agentmine/application/use_cases/data_revision.py
 M src/agentmine/application/use_cases/deliverable_qa.py
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
?? docs/audits/phase-b4-3-c4-operational-qa-acceptance.md
?? docs/audits/phase-b4-realistic-bounty-simulation.md
?? src/agentmine/application/qa/partition_checks.py
?? src/agentmine/application/workers/data_partition.py
?? src/agentmine/application/workers/data_partition_artifacts.py
?? tests/contract/fixtures/data_partition/
?? tests/contract/fixtures/data_partition_c2/
?? tests/contract/fixtures/data_partition_c3/
?? tests/contract/fixtures/data_partition_c4/
?? tests/integration/test_partition_artifact_runtime.py
?? tests/integration/test_partition_core_persistence.py
?? tests/integration/test_partition_operational_qa.py
?? tests/integration/test_partition_snapshot_compatibility.py
?? tests/integration/test_partition_worker_artifacts.py
?? tests/unit/application/partition_artifact_fakes.py
?? tests/unit/application/partition_qa_fakes.py
?? tests/unit/application/test_data_partition.py
?? tests/unit/application/test_partition_contracts.py
```

Không stage, commit, push, reset hoặc destructive cleanup.

## 18. Final Verdict

**C4_PASS.** Frozen thresholds và optional-null semantics đúng; full-group duplicate verification, conservation, source/global evidence và exact artifacts được kiểm chứng; không false PASS trong các case unsafe đã thử. Binding, restart, concurrency, lifecycle và legacy regressions đạt. PASS chỉ trong phạm vi QA C4, không phải client acceptance hoặc production CLI v2 readiness.

- Exact report path: `docs/audits/phase-b4-3-c4-operational-qa-acceptance.md`.
- Exact executed commands/results: mục 3, 13 và 14; các tập test chồng lặp không cộng dồn.
- Files changed: mục 15; baseline worktree được phân biệt tại mục 17.
- Deviations: không thay approved semantics; chỉ mở QA guard và tách QA-only preflight; giữ guard dispatch tới C5.
- Readiness for C5: QA foundation sẵn sàng operator review, chưa mở production v2 CLI hoặc chứng minh real bounty readiness.
- Recommended next action: operator review C4 và phê duyệt C5 như checkpoint riêng. Dừng C4, không tự triển khai C5.

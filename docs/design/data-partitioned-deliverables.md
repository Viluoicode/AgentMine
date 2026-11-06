# Deliverable dữ liệu phân vùng

Phạm vi: deterministic Data local/offline tại commit
`da0461fcb13f47022d34989e17dcbc251b04fa21`. Đây là hành vi đã triển khai,
không phải xác nhận production readiness hoặc khả năng hoàn thành bounty thật.
Xem [chiến lược kiểm chứng](../testing/partitioned-deliverables.md).

## Bài toán và luồng vận hành

Một catalog có thể chứa cả dòng hợp lệ lẫn dòng thiếu thuộc tính, sai giá trị hoặc
trùng ID. Bàn giao tất cả như dữ liệu sạch sẽ che giấu lỗi; loại dòng không giữ lý
do sẽ mất khả năng kiểm tra. V2 phân vùng clean/rejected, bảo toàn bằng chứng và
đánh giá chất lượng theo tiêu chuẩn được duyệt trước khi chạy.

Luồng hiện hữu: source/eligibility/economics/scoring được kiểm tra → chuẩn bị và
duyệt WorkSpecification/inputs → authorize budget → persist start → DataWorker →
retain result/cost → atomic finish, QA_PENDING → QA → human review. Prepare không
tự execute. Source refresh không khả dụng hoặc authority thiếu thì runtime chặn,
không tạo eligibility giả để chạy.

[ExecuteWorkerTask](../../src/agentmine/application/use_cases/worker_execution.py)
và [WorkerPreflight](../../src/agentmine/application/use_cases/worker_preflight.py)
orchestrate qua ports. Domain giữ lifecycle/approval; Infrastructure sở hữu SQLite
và export. Pure partition core không sở hữu authorization, QA hoặc external I/O.

## V1 mặc định, v2 phải opt-in

`output_policy=None` giữ transform/validate, renderer và QA legacy. Không bật v2
theo tên artifact hoặc vì input có duplicate: điều đó sẽ đổi ngầm scope và approval
cũ. Historical snapshots được decode bằng migration hẹp, không tự kích hoạt policy.

Ví dụ **trích đoạn** JSON specification, chưa phải request đầy đủ:

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

Vẫn cần sources, digests, columns và acceptance fields khác. Policy/thresholds phải
đi cùng nhau; unsupported version/policy, unknown fields hoặc bool thay integer bị
từ chối. ID phải là required TEXT; `unique_by` gồm đúng một cột ID đó. V2 hiện không
hỗ trợ semantic columns. Xem [contracts:211](../../src/agentmine/application/contracts/data.py#L211)
và [parser](../../src/agentmine/presentation/runtime_inputs.py#L182).

## Contracts và input presence

| Contract | Trách nhiệm |
|---|---|
| DataPlan | Execution đã authorize, frozen sources/columns/constraints, policy và acceptance |
| DataRecord | Dòng đã parse, canonical cells, source reference/digest, locator, timestamp và source row |
| DataResult | Toàn bộ parsed records/issues, artifacts, cost/warnings và optional partition assessment |

Định nghĩa trong [data.py](../../src/agentmine/application/contracts/data.py#L243).
`DataResult.valid` vẫn là `not issues` ([dòng575](../../src/agentmine/application/contracts/data.py#L575)),
không phải client acceptance. Mixed dataset có thể `valid=False` nhưng QA PASS nếu
rejected rows được giữ đúng và nằm trong ngưỡng đã duyệt. Không xóa issues để lấy PASS.

V2 ghi input origin trước normalize: MISSING là không có path, NULL là explicit
null, VALUE là mọi giá trị khác, kể cả blank hoặc invalid value. Chúng có thể cùng
thành canonical null nhưng vẫn phải phân biệt nguồn gốc. Optional null không tự
thành lỗi; optional non-null sai kiểu vẫn bị reject. Không đoán thuộc tính thiếu,
sinh ID hoặc clamp giá trị sai. Xem [transform](../../src/agentmine/application/workers/data_transform.py#L116).

## Duplicate Policy A và partition

[Partition core](../../src/agentmine/application/workers/data_partition.py#L56)
dùng transform/validate hiện hữu rồi group canonical ID hợp lệ trên toàn batch,
kể cả nhiều sources. Group có ít nhất hai thành viên phải **REJECT_ALL**, gồm cả
occurrence đầu. Không first/last-wins hoặc merge vì chưa có authority chọn bản đúng.
ID missing/invalid không bị gom dưới null; valid ID với field khác sai vẫn tham
gia group và giữ đầy đủ duplicate reason cùng lỗi field.

Mọi parsed row thuộc đúng một partition: **parsed = clean + rejected**. Clean không
có row issue; rejected giữ mọi row reason. Source/batch issues vẫn nằm trong full
issues, không gán tùy tiện cho một dòng. Source/row order được bảo toàn. Group ID
là SHA-256 của canonical payload, không dùng Python `hash()`; cách này cho replay
ổn định với cùng frozen inputs và policy.

`evidence_complete` chỉ là parse coverage, không tự chứng minh schema, batch
constraints hoặc client acceptance. Khi source hỏng, clean references từ nguồn
khác chỉ là candidates: nguồn chưa parse có thể chứa duplicate chưa quan sát.

## Artifacts và frozen acceptance

| Coverage | Artifact inventory | Ý nghĩa |
|---|---|---|
| Parse đầy đủ | clean.csv, clean.json, rejected.json, validation.json | Đúng inventory/thứ tự; chưa tự QA PASS |
| Parse không đầy đủ | Chỉ validation.json | Không phát hành clean dataset; unknown total không thành zero |
| Đầy đủ nhưng tất cả rejected | Clean JSON rỗng/CSV header và full rejects/report | Không thể vượt minimum-clean gate |

Renderer giữ canonical numeric values dạng string; CSV escape giá trị có nguy cơ
formula và biểu diễn null thành blank. JSON/provenance giữ thông tin chi tiết hơn
CSV đơn thuần. Validation giữ counts, source parse status, input validity, issues,
duplicate groups và unresolved source/batch issues; không tự ghi client PASS.
Xem [renderer:145](../../src/agentmine/application/workers/data_partition_artifacts.py#L145).

`PartitionAcceptance` bắt buộc explicit: min_clean_records từ1 đến1000,
max_rejected_records từ0 đến1000 và không vượt approved max_records. Đóng băng các
ngưỡng trước execution tránh việc chỉnh tiêu chuẩn theo output để lấy PASS.
Xem [contract](../../src/agentmine/application/contracts/data.py#L77).

QA replay frozen sources, so records/issues/assessment và exact artifact bytes,
rồi mới kiểm complete coverage, global issues, minimum clean và reject limit.
Không tin riêng count/report/hash tự khai. Evidence mismatch dẫn đến FAIL; chưa
đạt acceptance có thể NEEDS_REVISION. FIELD_PRESENT kiểm structural coverage trên
clean JSON; legacy COLUMN giữ semantics non-null. Xem
[QA evidence/acceptance](../../src/agentmine/application/qa/partition_checks.py#L15)
và [coverage checker](../../src/agentmine/application/qa/checks.py#L132).

## Provenance, revision và replay

Provenance giữ source/digest/source row, field paths và lookup evidence nếu có.
Artifact ghi `caller_supplied_unverified`: digest chỉ chứng minh integrity/binding
bytes, không chứng minh source truth, licensing hoặc marketplace acceptance.
Xem [provenance renderer](../../src/agentmine/application/workers/data_partition_artifacts.py#L37).

Scope/input digests/acceptance và execution/operation/deliverable identity không
được thay dưới cùng một ID. Recovery dùng original identity và retained result;
không tạo execution mới để né commitment. DataWorker persist result trước cost
accounting; cached retry kiểm artifact rồi ghi chi phí qua existing idempotent path.
Unknown cost không biến thành zero; unknown paid outcome không được retry.
Xem [worker](../../src/agentmine/application/workers/data.py#L102),
[recovery tests](../../tests/integration/test_partition_worker_artifacts.py#L84)
và [atomic finish](../../tests/integration/test_partition_artifact_runtime.py#L105).

Revision là version mới được duyệt, khác replay cùng version. Revision giữ cùng
output policy; minimum clean không giảm, reject limit không tăng. Không chuyển
ngầm v1→v2 trong lineage. QA/review bind exact version/digest; bytes giống nhau
không chuyển approval từ version trước. Xem
[revision binding](../../src/agentmine/application/contracts/data_revision.py#L120)
và [ADR0028](../adr/0028-versioned-data-rework-foundation.md).

**QA PASS nghĩa READY_FOR_HUMAN_REVIEW**, không phải submit. Domain sở hữu transition
([opportunity.py:464](../../src/agentmine/domain/opportunity.py#L464)); submission
approval vẫn riêng biệt. Local export không tạo acceptance, payment hoặc revenue.

## Giới hạn hiện tại

- Runtime v2 chỉ deterministic Data với approved inputs; không paid/semantic AI.
  Zero AI cost không chứng minh infrastructure hoặc công sức operator miễn phí.
- Batch v2 tối đa1000 records; không tự chia batch để né approved scope.
- Partition không bổ sung XLSX, OCR, fuzzy matching hoặc transformation mới.
- **M01 còn mở:** work status thiếu partition summary v2. Xem specification và
  validation artifacts để kiểm policy/counts. Đây là giới hạn hiển thị chưa sửa.
- Offline tests chưa xác minh live listing eligibility, source permissions,
  client acceptance, authenticated settlement hoặc doanh thu thật. Không được bỏ
  qua source freshness, eligibility, budget và human approval để chạy simulation.

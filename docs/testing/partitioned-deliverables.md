# Kiểm chứng deliverable dữ liệu phân vùng

Implementation đối chiếu: commit `da0461fcb13f47022d34989e17dcbc251b04fa21`.
Xem [thiết kế](../design/data-partitioned-deliverables.md). Kết quả acceptance bên
dưới là **bằng chứng lịch sử có ngày**, không phải rerun khi viết tài liệu2026-11-05.

## Chiến lược và oracle độc lập

Expected outputs được xác định từ client brief giả lập, schema và transformation
rules trước implementation, không gọi DataWorker để sinh expected. Literal oracles
bao gồm canonical values, input presence, ordered issues, partition membership,
duplicate groups và artifact bytes. Hash chứng minh fixture nguyên vẹn, không chứng
minh expected đúng nghiệp vụ: vẫn cần review oracle và semantic assertions.

Production QA replay cùng core để phát hiện retained evidence sai. Replay không
phải oracle độc lập; lỗi chung trong implementation cần literal tests phát hiện.
Giữ hai lớp này riêng giúp tránh tự xác nhận một output sai nhưng nhất quán.

| Lớp | Test references |
|---|---|
| Contracts/legacy snapshots | [Typed contracts](../../tests/unit/application/test_partition_contracts.py#L67), [legacy decode/non-rewrite](../../tests/integration/test_partition_snapshot_compatibility.py#L37) |
| Pure core | [Literal cases/hash vectors](../../tests/unit/application/test_data_partition.py), [core SQLite persistence](../../tests/integration/test_partition_core_persistence.py) |
| Worker/artifacts | [Exact artifact oracles](../../tests/integration/test_partition_worker_artifacts.py#L31), result-before-cost, restart và unknown cost |
| Transactions | [Atomic finish/lost acknowledgement](../../tests/integration/test_partition_artifact_runtime.py#L105) |
| Operational QA | [Replay, thresholds, tampering, retries/concurrency](../../tests/integration/test_partition_operational_qa.py) |
| CLI/E2E | [Continuous oracle/export](../../tests/integration/test_partition_runtime_e2e.py#L29), [v1 bytes](../../tests/integration/test_partition_runtime_e2e.py#L97), [original-ID recovery](../../tests/integration/test_partition_runtime_e2e.py#L233), [explicit revision](../../tests/integration/test_partition_runtime_e2e.py#L539) |

## Golden fixtures và manifests

| Directory | Mục đích | Integrity record |
|---|---|---|
| [data_partition](../../tests/contract/fixtures/data_partition/README.md) | Pre-C1 v1 snapshots, contract expectations | [sha256.json](../../tests/contract/fixtures/data_partition/sha256.json), 7 entries |
| [data_partition_c2](../../tests/contract/fixtures/data_partition_c2/README.md) | Literal values/issues/membership và canonical vectors | [oracles.json](../../tests/contract/fixtures/data_partition_c2/oracles.json), whole-file hash bên dưới |
| [data_partition_c3](../../tests/contract/fixtures/data_partition_c3/README.md) | Worker artifact golden outputs và edge cases | [sha256.json](../../tests/contract/fixtures/data_partition_c3/sha256.json), 88 entries |
| [data_partition_c4](../../tests/contract/fixtures/data_partition_c4/README.md) | QA integrity/acceptance expectations | [sha256.json](../../tests/contract/fixtures/data_partition_c4/sha256.json), 1 entry |
| [data_partition_c5](../../tests/contract/fixtures/data_partition_c5/README.md) | Schema/scenarios và E2E artifacts | [sha256.json](../../tests/contract/fixtures/data_partition_c5/sha256.json), 23 entries |

C2 oracle whole-file SHA-256:

```text
6deaf129e37db2375622cc247b9abae686da96c140db9f784d90fc11885dda5a
```

Duplicate group payload là JSON array gồm `agentmine-data-duplicate-v2`, policy
object, canonical ID và ordered source references/digests. Serialization dùng
ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False, UTF-8
không BOM/newline. Arrays giữ approved order; group reference là sha256: + lowercase
digest. So exact vectors, không chỉ so độ dài digest. Xem
[duplicate_group_payload](../../src/agentmine/application/workers/data_partition.py#L25).

## Bảo toàn exact bytes

[.gitattributes](../../.gitattributes) có năm fixture-only rules -text tương ứng
năm directories trên. Một số files dùng CRLF hoặc mixed LF/CRLF có chủ đích. Không
format/regenerate/đổi newline để lấy PASS. Hash trên raw bytes, không trên JSON
đã parse hoặc pretty-print. Manifests không bao phủ mọi README hoặc chính manifest;
Git blob/raw-byte comparisons bổ sung cho coverage đó.

Read-only checks có thể dùng:

```sh
git check-attr text filter working-tree-encoding -- tests/contract/fixtures/data_partition_c2/oracles.json
git hash-object --no-filters tests/contract/fixtures/data_partition_c2/oracles.json
git hash-object --path=tests/contract/fixtures/data_partition_c2/oracles.json tests/contract/fixtures/data_partition_c2/oracles.json
git -c core.whitespace=cr-at-eol diff --check
```

Hai blob hashes phải bằng nhau khi không có clean-filter conversion. Không dùng
hash-object -w; -c chỉ áp dụng cho command, không ghi Git config. Whitespace check
không thay hash verification; clean diff không kiểm lại mọi fixture trong HEAD.

## Lệnh kiểm chứng

Từ repository root sau [development setup](../../README.md), PowerShell:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
.\.venv\Scripts\python.exe -B -m pytest tests/unit/application/test_partition_contracts.py tests/integration/test_partition_snapshot_compatibility.py tests/unit/application/test_data_partition.py tests/integration/test_partition_core_persistence.py tests/integration/test_partition_worker_artifacts.py tests/integration/test_partition_artifact_runtime.py tests/integration/test_partition_operational_qa.py tests/integration/test_partition_runtime_e2e.py -q --tb=short -p no:cacheprovider
.\.venv\Scripts\python.exe -B -m pytest tests/unit/test_architecture.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -B -m pytest -q --tb=short -p no:cacheprovider
.\.venv\Scripts\python.exe -B -m ruff check . --no-cache
.\.venv\Scripts\python.exe -B -m ruff format --check .
.\.venv\Scripts\python.exe -B -m mypy --strict
```

Commands để tái lập, không phải bản ghi rerun trong draft gate. Tools có thể tạo
temporary/cache files, không được commit. Default tests chặn network qua
[conftest.py](../../tests/conftest.py); partition suite không cần live credentials
hoặc paid provider.

## Bằng chứng acceptance C1–C5

Nguồn lịch sử là các báo cáo C1–C5 và Final Acceptance tại tree commit B.4.3;
originals đã được archive riêng. Chúng kiểm worktree trước khi gom vào
commit, không phải fresh run trên clean checkout của commit sau này. Bảng giữ
evidence cần thiết khi audit reports được rút khỏi latest tree.

| Checkpoint / ngày | Phạm vi | Kết quả lịch sử |
|---|---|---|
| C1 / 2026-11-03 | Opt-in contracts, literal expectations, strict legacy snapshots | Focused54 PASS; full1571 PASS. Ba supplemental tests sau full-suite collection được chạy trong focused cuối; không nói full này bao phủ mọi final C1 test |
| C2 / 2026-11-03 | Pure partition, full-group duplicate policy, canonical hashes | Focused34, regression198, full1608 PASS |
| C3 / 2026-11-03 | Real worker/artifacts, result/accounting/restart | Regression291, full1660 PASS |
| C4 / 2026-11-04 | Operational replay QA, frozen gates, legacy semantics | Focused75, regression513, full1735 PASS |
| C5 / 2026-11-04 | Explicit CLI opt-in, local composition, export/recovery/revision | Focused66, regression585, full1801 PASS; full742.48s |
| Independent Final Acceptance / 2026-11-04 | C1–C5 flow và adversarial checks | Focused585/350.41s; architecture29/1.50s; full1801/918.35s PASS; Ruff/format/strict mypy PASS, mypy286 source files |
| Isolated staged-tree readback / 2026-11-04 | Actual staged materialization và fixture bytes | 535/535 file checks, 129/129 fixture byte comparisons; focused281/210.85s PASS |

Các selections chồng lặp, không cộng thành tổng test độc lập. Duration không phải
performance benchmark. Các guard “chưa hỗ trợ v2” trong báo cáo C1–C4 là trạng thái
checkpoint, không phải trạng thái cuối C5.

## Ranh giới offline và giới hạn

E2E dùng real CLI/application composition, file-backed SQLite, DataWorker và
DeliverableQA. [Test-only helpers](../../tests/unit/application/partition_e2e_fakes.py)
inject source/clock giả lập để tái lập freshness và thời gian; đây không phải live
Superteam observation. Tests kiểm explicit consent, stale authority, original-ID
recovery, zero-AI accounting, no-clobber export và separate approval. Không chứng
minh production CLI có quyền bỏ source freshness hoặc fallback sang mocks.

Simulation B.4.1 ngày2026-11-03 ghi TECHNICAL_PASS_CLIENT_FAIL: transform/validation
đúng nhưng catalog bẩn v1 chỉ có diagnostic, chưa có dataset khách hàng ingest.
V2 giải quyết contract bằng reject partition và frozen gates; không biến simulation
thành real client acceptance.

**M01 còn mở:** work status thiếu partition summary v2. Operator xem specification
và validation artifacts để kiểm policy/counts. Acceptance audit coi đây là MINOR,
không phải QA/approval bypass; không mô tả đã sửa.

Chưa được xác minh: live agentAccess=AGENT_ALLOWED/AGENT_ONLY, eligibility listing
thật, source permission/licensing, yêu cầu ngoài schema đã duyệt, live submission,
client acceptance, independently authenticated settlement hoặc verified revenue.
Xem [provenance/replay](../design/data-partitioned-deliverables.md#provenance-revision-và-replay).
QA PASS chỉ là READY_FOR_HUMAN_REVIEW, không phải tự submit hoặc ghi nhận thu nhập.

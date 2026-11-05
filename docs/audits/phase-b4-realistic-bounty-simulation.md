# AgentMine — Phase B.4.2: Deliverable Contract & QA Semantics Design

## Context

Repository: AgentMine

Previous checkpoint:
`docs/audits/phase-b4-realistic-bounty-simulation.md`

Phase B.4.1 verdict:
**TECHNICAL_PASS_CLIENT_FAIL**

Verified findings from the previous simulation:

- DataWorker correctly transformed records and detected validation issues.
- Dirty catalog: 4 retained records, 11 validation issues.
- Dirty catalog produced only `validation.json`, not an ingestible dataset.
- A valid catalog with an optional null field produced CSV/JSON, but operational QA returned NEEDS_REVISION.
- A complete catalog with no missing optional values passed QA.
- Existing execution preserved SCOUT_ONLY, $0 AI budget, and no external actions.
- Simulation used production composition and CLI parser with injected test-only dependencies, not a complete live production CLI workflow.

Treat the B.4.1 report and current repository implementation as the primary sources of truth. Revalidate relevant findings against source code.

## Objective

Design the smallest safe improvement that allows AgentMine to produce auditable data-cleaning deliverables when some source records are invalid.

The design must preserve:
- Data integrity
- Source provenance
- Validation evidence
- Deterministic behavior
- Budget controls
- Human review
- Clean/Hexagonal Architecture

Do not implement changes in this phase.

## Confirmed Business Decision — Duplicate ID Policy

The operator has explicitly selected:

**POLICY A: REJECT ALL DUPLICATE IDs**

Requirements:

1. Normalize identifiers using the approved transformation rules before checking uniqueness.
2. If two or more records share the same normalized ID, reject every record in that duplicate group.
3. Never silently retain the first or last duplicate.
4. Preserve every rejected record and its original source reference.
5. Include a machine-readable duplicate reason and group identifier.
6. Never invent or replace IDs.
7. Records with missing or invalid IDs must also be rejected, with their actual validation reasons.
8. Do not assume this policy applies universally to future clients. Define it as an explicit, approved execution policy for the relevant task.

Example:

Input IDs:
- ` a001 `
- `A001`
- `B002`

After normalization:
- `A001`
- `A001`
- `B002`

Expected:
- Both `A001` records → rejected
- `B002` → clean, provided all other validations pass

## Phase 1 — Current Architecture Investigation

Inspect:

- DataWorker
- DataPlan / DataResult / DataRecord / DataCell contracts
- Data transformations and validation
- Artifact generation
- Data journal and recovery
- Operational QA and DeliverableQA
- Work specification and frozen acceptance criteria
- Worker execution and CLI export
- Existing data-worker and QA tests

Trace:

Source → DataPlan → Transform → Validate → DataResult → Artifacts → QA → Export → Human Review

For each relevant component, document:
- Current responsibility
- Actual source file and line reference
- Relevant invariants
- Existing test coverage
- Potential compatibility concerns

## Phase 2 — Clean / Rejected Dataset Contract

Design a deterministic partitioning contract with:

1. `clean` records
2. `rejected` records
3. Validation report
4. Source provenance
5. Partition-level and batch-level counts
6. Explicit classification reasons

Core invariants:

- Every successfully parsed source record belongs to exactly one partition.
- No record is silently dropped or duplicated.
- Clean records must satisfy the approved validation requirements.
- Rejected records must retain normalized values, validation reasons and source identity.
- Raw input must remain traceable through retained source references and digests.
- Duplicate groups must be rejected in full under Policy A.
- A malformed source must be reported as a source-level failure; do not fabricate parsed records.
- Never invent missing attributes.
- Preserve deterministic output ordering.
- Preserve current fail-closed behavior for unsafe or incomplete evidence.

Investigate whether partitioning should occur:
- Inside DataWorker
- In a dedicated application service
- During artifact generation
- Or through another minimal architecture-compatible mechanism

Recommend one approach with justification.

Specify the exact output artifacts and schemas. Consider names such as:
- `clean.json`
- `clean.csv`
- `rejected.json`
- `validation.json`

Do not assume these filenames are mandatory if backward compatibility requires another design.

Explain how existing `data.json`, `data.csv` and `validation.json` consumers remain compatible or are safely migrated.

## Phase 3 — Duplicate Policy Semantics

Design exact behavior for:

- Two records with identical normalized IDs
- Three or more records in the same group
- Case and whitespace normalization
- Duplicate IDs across multiple sources
- Missing ID
- Invalid ID
- Duplicate ID plus other validation issues
- Duplicate ID with optional-null fields
- Repeated execution and replay

Specify:
- Whether duplicate policy belongs in DataPlan or an approved work specification
- How policy authorization is frozen
- How duplicate group identity is represented
- How duplicate reasons map to existing issue codes
- How policy changes affect plan identity, replay and idempotency

Do not introduce an unnecessary policy framework.

## Phase 4 — Optional Field QA Semantics

Investigate the mismatch between:

`DataColumn(required=False)`

and operational JSON COLUMN coverage that currently treats null as uncovered.

Design distinct checks for:

1. Field presence
2. Field non-null requirement
3. Field value validity
4. Dataset-level acceptance
5. Partition-level acceptance

Required semantics:

- Optional fields may be null when explicitly permitted by the approved schema.
- Required fields must satisfy their actual validation requirements.
- Missing field and explicit null must not be treated as equivalent without a documented contract.
- A schema-valid optional null must not automatically fail QA.
- A present but invalid value must not pass merely because the field is optional.
- QA must not silently weaken existing approved acceptance requirements.

Specify how these semantics connect to frozen WorkSpecification acceptance criteria.

## Phase 5 — Failure and Recovery Design

Analyze:

- Zero clean records
- All records rejected
- Mixed valid/invalid records
- Duplicate groups spanning sources
- Malformed JSON or CSV
- Invalid schema
- Missing source evidence
- Corrupted source digest
- Failed artifact persistence
- Restart after worker execution
- Repeated QA
- Replay and idempotent cost accounting
- Deadline expiry
- SCOUT_ONLY and $0 budget enforcement

For each case, specify expected worker, artifact, QA and lifecycle behavior.

Do not claim client acceptance PASS merely because artifacts exist.

## Phase 6 — Test-First Acceptance Plan

Design tests with independent expected outputs.

At minimum include:

1. All-valid dataset
2. Mixed valid/invalid dataset
3. All-invalid dataset
4. Two normalized duplicate IDs
5. Three duplicate IDs
6. Cross-source duplicates
7. Duplicate plus other field errors
8. Missing and invalid IDs
9. Optional-null accepted
10. Required-null rejected
11. Optional field with invalid non-null value
12. Malformed source
13. Missing/corrupted evidence
14. Deterministic ordering
15. No record loss or duplication
16. Source provenance retained
17. Backward compatibility
18. Restart and replay consistency
19. QA cannot pass unsafe output
20. No external actions and no paid AI calls

For every test, define:
- Input
- Expected output
- Expected issue codes
- Expected QA outcome
- Contract or component under test

Expected outputs must not be derived from DataWorker's own implementation.

## Phase 7 — Minimal Implementation Plan

Provide:

- Exact source files to modify
- Exact tests to add or update
- Whether new contracts are necessary
- Database/schema migration requirements, if any
- Compatibility risks
- Estimated implementation complexity
- Recommended implementation sequence
- Explicit non-goals

Prefer modifying existing components over adding new abstractions unless required for correctness.

Do not introduce:
- New paid providers
- AWS infrastructure
- New marketplace integrations
- Wallet functionality
- Automatic submission
- Unrelated AI capabilities
- Unnecessary third-party dependencies

## Strict Safety Constraints

This is DESIGN ONLY.

- Do not modify production source code.
- Do not modify existing tests.
- Do not modify configuration or dependencies.
- Do not execute live Superteam requests.
- Do not access API keys or secret files.
- Do not call paid LLM services.
- Do not submit bounty applications.
- Do not perform wallet or payment transactions.
- Do not change eligibility or reward semantics.
- Do not change the operating mode from SCOUT_ONLY.
- Keep AI budget at $0.
- Do not commit or push.
- Do not mark simulated value as verified revenue.

Read-only inspection and safe offline checks are allowed.

## Deliverable

Write a detailed Vietnamese Markdown design report:

`docs/audits/phase-b4-2-deliverable-contract-qa-design.md`

Required sections:

1. Executive Summary
2. B.4.1 Findings and Root Causes
3. Current Architecture and Evidence
4. Proposed Clean / Rejected Contract
5. Duplicate ID Policy A
6. Optional Field QA Semantics
7. Failure and Recovery Matrix
8. Backward Compatibility
9. Independent Test Plan
10. Exact Files to Change
11. P0 / P1 / P2 Risks
12. Implementation Sequence
13. Final GO / NO-GO Recommendation

The report must clearly distinguish:
- Verified repository behavior
- Operator-approved business policy
- Proposed design decisions
- Unverified assumptions

End with:
- Exact report path
- Read-only checks performed
- Git status
- Files changed
- Implementation readiness decision
- Recommended next action

Create only the requested Markdown report. Do not implement the design.# Phase B.4.1 — Mô phỏng bounty làm sạch danh mục sản phẩm

## 1. Executive Summary

**Verdict: TECHNICAL_PASS_CLIENT_FAIL.** DataWorker thực thi được các phép chuẩn hóa hiện có, kết quả nội bộ khớp oracle độc lập, lưu SQLite và phục hồi/replay không ghi trùng chi phí. Tuy nhiên, bộ catalog bẩn chưa tạo được dataset CSV/JSON để khách hàng ingest: chỉ một lỗi cũng làm worker chỉ xuất `validation.json`. Đây là hành vi fail-closed, không phải hoàn thành yêu cầu bàn giao.

Audit ngày 2026-11-03 trên commit `7c660a8adfac07e408c3e3939988c9697770c204`; worktree sạch lúc bắt đầu. Không sửa production source, tests, configuration hay dependencies. Toàn bộ workspace, fixture, oracle và artifact mô phỏng nằm tại `.tmp/phase-b4-simulation/`, tách khỏi database vận hành. Chỉ báo cáo này là thay đổi tracked-scope dự kiến.

Không có bằng chứng bounty thật, agentAccess thật, source freshness thật hay doanh thu thật. Không gọi Superteam, LLM, submission, wallet hoặc payment provider.

## 2. Simulated Client Brief

Khách hàng hư cấu cung cấp catalog nhỏ có khoảng trắng/case không nhất quán, category alias, số dạng text, thiếu thuộc tính, ID trùng và JSON hỏng. Cần định danh nhất quán, chuẩn hóa có quy tắc, xử lý lỗi minh bạch, dataset máy đọc được và QA giải thích hạn chế. Không suy diễn thuộc tính bị thiếu.

Tiêu chí acceptance được xác định trước execution: dữ liệu có thể ingest phải phân biệt record hợp lệ với lỗi/reject, bảo toàn nguồn và không âm thầm sửa/loại record. Dataset chứa ID trùng, thiếu ID hoặc stock âm không đủ điều kiện ingest. Không ép worker làm thêm phép biến đổi ngoài capability hiện tại.

## 3. Capability Mapping

| Yêu cầu | Capability thực tế | Bằng chứng source | Kết quả mô phỏng |
|---|---|---|---|
| ID nhất quán | Trim, uppercase; ID vẫn là text, không sinh ID mới | `src/agentmine/application/workers/data_transform.py:74` | PASS cho ID có sẵn; thiếu ID bị báo lỗi |
| Tên chuẩn hóa | Trim và lowercase; không sửa chính tả, không collapse khoảng trắng bên trong | `data_transform.py:74` | PASS trong scope này |
| Category | Lookup đóng, có evidence reference; không đoán alias ngoài bảng | `src/agentmine/application/contracts/data.py:84`, `data_transform.py:74` | Alias hợp lệ đúng; `mystery` thành null và có issue |
| Số | Integer/Decimal canonical text, min/max; không locale/currency parsing | `data_transform.py:74`, `data_transform.py:172` | `003` → `3`, `12.500` → `12.5`; stock âm bị flag nhưng giá trị vẫn giữ |
| Missing/invalid | Null, mã lỗi machine-readable, không impute | `data_transform.py:116`, `data_transform.py:172` | Khớp oracle; một field có thể vừa invalid vừa missing |
| Trùng ID | Phát hiện bằng unique_by; không deduplicate | `data_transform.py:172` | Record trùng vẫn được retain |
| JSON hỏng | Từ chối source, không tự sửa cú pháp | `data_transform.py:26`, `data_transform.py:47` | 0 record, malformed_source + record_count |
| CSV/JSON output | Chỉ xuất dataset khi toàn bộ validation không có issue | `src/agentmine/application/workers/data_artifacts.py:10` | Bộ bẩn thiếu dataset |
| Provenance | Source digest, row, locator, timestamp, field path và lookup reference | `data_artifacts.py:39` | Có trên control; `caller_supplied_unverified` |
| LLM | Không cần cho mọi operation đã chạy | `src/agentmine/application/workers/data.py:48` | `llm=None`, $0 |

Giới hạn schema: CSV/JSON, tối đa 10 sources, 50 columns, 1.000 records/plan và 1 MB/source; không XLSX/Parquet, array traversal, fuzzy matching, unit conversion hay tự sinh missing ID (`src/agentmine/application/contracts/data.py:49`, `:165`; `data_transform.py:65`). Không triển khai bổ sung capability trong checkpoint này.

## 4. Input Fixture and Independent Expected Output

Fixture và oracle chính được viết thành literal JSON **trước lần gọi worker đầu tiên**. Script oracle không import hoặc gọi transform/normalize của AgentMine. SHA-256 oracle chính: `65e5485c4b150ca6b963f9b58995fcd7aa609e77bd2297470aa29d4deb5f0428`; harness kiểm tra bytes không đổi sau execution.

Quy tắc độc lập: ID trim/uppercase; name trim/lowercase; category trim/lowercase và map `elec`, `electronics` → `electronics`, `acc` → `accessories`; price Decimal ≥0, stock Integer ≥0; brand optional, thiếu → null. Không phát minh brand/name/ID/category. Các giá trị số chuẩn hóa là string theo hợp đồng worker, không giả định JSON number.

Input chính (`dirty-input.json`):

```json
[
  {"id":" a001 ","name":" USB Cable ","category":" ELEC ","price":"12.500","stock":"003"},
  {"id":"a002","name":"  ","category":"mystery","price":"oops","stock":"-1"},
  {"id":"A001","name":"USB Cable","category":"electronics","price":"12.5","stock":"3"},
  {"name":" Mouse ","category":"ACC","price":"8.00"}
]
```

Expected nội bộ được ghi trước execution:

```json
[
  {"id":"A001","name":"usb cable","category":"electronics","price":"12.5","stock":"3","brand":null},
  {"id":"A002","name":null,"category":null,"price":null,"stock":"-1","brand":null},
  {"id":"A001","name":"usb cable","category":"electronics","price":"12.5","stock":"3","brand":null},
  {"id":null,"name":"mouse","category":"accessories","price":"8","stock":null,"brand":null}
]
```

Expected issue positions: row 2 category/price invalid; row 2 name/category/price missing; row 2 stock invalid; row 3 duplicate; row 4 id/stock missing_column và missing_value — tổng 11 issue. Giá trị `-1` được giữ để audit, không được xem là hợp lệ.

Ca bổ sung: `control-input.json` có hai record hợp lệ nhưng brand optional ở record đầu là null. `malformed-input.json` chứa `[{"id":` và phải bị từ chối. Sau khi phát hiện QA optional-null, tạo **oracle bổ sung trước execution ca mới** tại `independent-complete-expected.json`, cùng `complete-input.json` có brand đầy đủ. Không đổi oracle gốc hoặc hạ tiêu chí QA để lấy PASS.

## 5. Actual AgentMine Execution

Đường thực thi thực tế:

```text
Test-only build_world/FakeSource/FakeClock (isolated SQLite)
  → production compose_operator
  → real CLI parser/run_cli work prepare --approve-inputs
  → immutable WorkSpecification + exact input digests + frozen acceptance
  → work execute --confirm
  → ExecuteWorkerTask → WorkerPreflight → BudgetManager
  → persist start → real DataWorker(llm=None)
  → SQLiteDataJournal result → actual cost → atomic runtime finish
  → work export / work status
  → work qa --confirm → RunOperationalDataQA → DeliverableQA
  → SQLiteQAJournal + existing Domain lifecycle
```

Dùng helper test hiện có `tests/integration/test_runtime_operator_cli.py:31` và `:84`, `tests/integration/test_worker_execution_runtime.py:131` để dựng **bằng chứng giả chỉ trong test workspace**. Các bước eligibility/economics/scoring/planning ban đầu chạy use case thật nhưng input/source/forecast là fixture, không phải xác nhận thị trường hay authorization ngoài đời. Opportunity nền của helper vẫn có tên/requirements mẫu “Normalize names”; specification/plan catalog và acceptance là artifact của mô phỏng. Vì vậy không tuyên bố đã chứng minh toàn bộ brief marketplace thật qua discovery/plan.

Mỗi workspace có ledger riêng. Trước worker authorization, fixture budget chưa có records/commitments được đặt monthly/daily/per-task/approval threshold = 0 USD, requested_mode SCOUT_ONLY. Đây là setup dữ liệu mô phỏng, không phải thay đổi policy database vận hành và không phải bằng chứng CLI policy control.

**Blocker production CLI live:** composition với `DisabledOpportunitySource` trả exit 1, `BLOCKED / SOURCE_UNAVAILABLE`, vẫn PLANNED và không tạo WorkerRun. Default module entrypoint không cung cấp fixture source; bật live refresh bị cấm trong bài này. Walkthrough dùng production composition/CLI parser với FakeSource/FakeClock inject minh bạch trong process, **không phải continuous real module-entrypoint/live readiness**. Module-entrypoint chỉ chạy `--help` an toàn.

Acceptance criteria được freeze trước execution: yêu cầu data.json, data.csv, validation.json; coverage sáu cột. Không caller-supplied QA outcome.

## 6. Artifact Inspection

| Ca | Retained records | Issues | Artifact worker | QA thực tế | Lifecycle sau QA |
|---|---:|---:|---|---|---|
| dirty — ca chính | 4 | 11 | validation.json | NEEDS_REVISION | IN_PROGRESS |
| control — brand optional null | 2 | 0 | data.csv, data.json, validation.json | NEEDS_REVISION | IN_PROGRESS |
| complete — brand đầy đủ | 2 | 0 | data.csv, data.json, validation.json | PASS | READY_FOR_HUMAN_REVIEW |
| malformed JSON | 0 | 2 | validation.json | NEEDS_REVISION | IN_PROGRESS |

CSV/JSON đã được parse độc lập. Bytes file export bằng artifact content thực tế. data.json được so field-by-field với literal oracle; CSV control/complete có đúng hai data rows; provenance SHA bằng input bytes. CSV có cột `_provenance`, numeric JSON là string và missing optional là null: downstream cần chấp nhận schema này. Không kiểm chứng tất cả spreadsheet consumers, mọi encoding hoặc công thức CSV trong simulation này.

`retained-records-inspection.json` là **inspection dump do harness tạo từ DataResult**, không phải artifact bàn giao do worker sinh. Không dùng file này để giả vờ worker đã xuất dataset sạch. `manifest.json` là export metadata, không phải dữ liệu khách hàng.

## 7. Independent Acceptance Results

| Gate | Kết quả | Giới hạn |
|---|---|---|
| Record completeness | PASS | Bốn object của input chính đều còn trong DataResult; malformed source không salvage |
| Field correctness | PASS | Toàn bộ value và null khớp literal expected; không dùng transform implementation làm oracle |
| Issue classifications | PASS | Exact code/row/column của cả 11 dirty issues và hai malformed issues khớp oracle |
| Không impute | PASS | Không tạo missing ID/name/category/brand/stock |
| Dataset ingestible cho catalog bẩn | **FAIL** | Chỉ validation.json; không clean dataset/reject dataset |
| Duplicate resolution | **FAIL cho brief** | Detect được nhưng không có approved resolution/quarantine partition |
| Artifact readability | PASS trong scope | Artifact thực tế parse được; không khẳng định artifact bị thiếu |
| Determinism | PASS | Same-ID restart replay và fresh computation trên journal/ledger riêng cho kết quả bằng nhau ở cả bốn ca |
| Missing optional + QA | **FAIL end-to-end** | Worker valid nhưng JSON COLUMN coverage yêu cầu mọi giá trị non-null |
| QA complete control | PASS | Chỉ chuyển sang human review; không approval/submission |

Technical PASS có nghĩa engine thực thi và từ chối lỗi đúng hợp đồng hiện tại; không có nghĩa đã tạo deliverable đạt brief. Ca complete không thay thế thất bại của ca chính.

## 8. QA and Safety Results

- Cả bốn case dùng real SQLite/DataWorker/DeliverableQA và không cấu hình LLM. Mỗi case có đúng một actual AI cost record 0 USD; retry QA, restart replay và recompute không tăng record count ở ledger gốc. AI budget vẫn 0 và mode vẫn SCOUT_ONLY.
- Không suy ra infrastructure/tool/transaction cost bằng 0. Warnings gồm `source_provenance_unverified`, `infrastructure_cost_not_measured`. Chỉ AI cost zero có measurement record trong scope này.
- Socket connect và DNS getaddrinfo được chặn bằng guard; không có attempt nào trong harness. Không tích hợp provider, wallet, signing hoặc submission gateway vào đường work/QA. Không kiểm chứng bảo mật sandbox OS toàn diện.
- Sau QA, mọi opportunity đều không có submission hoặc approval; verified revenue = 0 USD. QA PASS chỉ READY_FOR_HUMAN_REVIEW. Không chạy lệnh quyết định approval hay handoff.
- Exact bundle/digest và evidence QA được retain. Với dirty/malformed, thiếu artifact được QA bắt. Với control optional-null, `REQUIREMENT_NOT_COVERED` cho brand là lý do cần revision.
- QA COLUMN của JSON hiện yêu cầu field hiện diện **và non-null**, trong khi DataColumn(required=False) cho phép null (`src/agentmine/application/qa/checks.py:121`). Không hạ tiêu chí hoặc sửa source trong audit này.
- QA domain-specific có thể kiểm tra lại bằng chính validation primitives (`checks.py:268`), nên không thay thế independent oracle.

Hai lần harness chưa hoàn tất cũng được giữ lại: lần đầu cố recompute với authorization đã settle và bị `Persisted sufficient authorization required`; chỉnh harness dùng ledger riêng và authorization riêng. Lần hai giả định control optional-null sẽ QA PASS và assertion thất bại; giữ nguyên criteria, ghi nhận NEEDS_REVISION, thêm complete control riêng. Đây là lỗi giả định của harness được sửa, không phải thay đổi behavior production. Thư mục `dirty/`, `dirty-attempt2/`, `control-attempt2/` là evidence chưa hoàn tất; chỉ các thư mục `*-final/` và results.json là kết quả hoàn chỉnh.

Không kiểm tra crash injection mới trong mô phỏng; regression suite hiện có cung cấp coverage phục hồi được nêu ở phần commands. Không tuyên bố mọi crash/race đã được chứng minh bằng walkthrough này.

## 9. P0/P1/P2 Gaps

| Priority | Gap | Tác động và remediation nhỏ nhất được đề xuất |
|---|---|---|
| P0 cho acceptance brief | Không xuất dataset khi có bất kỳ issue | Cần thiết kế rõ clean/rejected partition và audit-safe export; không tự drop/sửa record. Chưa implement |
| P1 | Optional-null không tương thích JSON COLUMN QA coverage | Tách tiêu chí “có cột” với “không-null”, bind requiredness của approved schema; bổ sung regression trước sửa |
| P1 | Không có policy xử lý trùng ID | Khách hàng/operator phải quyết định giữ/reject/version; không chọn đại record thắng |
| P1 | Source refresh thật unavailable trong offline composition | Chỉ làm được simulation có fake source; cần opportunity agent-eligible thật và read-only authorization riêng trước real trial |
| P1 | Brief/economics mẫu không đặc thù catalog | Cần planning/evidence thật của brief và acceptance được operator duyệt, không dùng fixture forecasts làm readiness evidence |
| P2 | Case-only name normalization, không fuzzy/unit/locale parsing | Chọn brief đơn giản phù hợp hoặc design capability sau, không mở scope trong simulation |
| P2 | Numeric JSON string và CSV provenance lớn | Document downstream schema, xác nhận consumer; không tự đổi kiểu money/number |
| P2 | Provenance chỉ caller-supplied | Có integrity/digest, không chứng minh tính đúng hoặc quyền sử dụng source |
| P2 | Validation report không có narrative/giải pháp | Operator vẫn cần đọc issue codes và bổ sung diễn giải/hướng xử lý được duyệt |
| P2 | Cost infrastructure chưa đo | Không quảng bá total cost/profit bằng zero |

P0 ở đây là blocker bàn giao của **brief mô phỏng**, không phải phát hiện vulnerability CRITICAL hoặc lý do nới validation.

## 10. Final Verdict

**TECHNICAL_PASS_CLIENT_FAIL.** Có bằng chứng trực tiếp DataWorker chuẩn hóa đúng phạm vi, giữ record/issue, bảo toàn $0 AI SCOUT_ONLY và không phát sinh external action. Bộ catalog bẩn chưa trở thành deliverable ingestible. Bộ complete mới QA PASS, vẫn cần human review riêng. Không có real bounty readiness hay revenue claim.

Next phase đề xuất: một design-only checkpoint cho clean/rejected dataset contract và optional-field QA semantics, kèm yêu cầu operator chọn duplicate policy. Sau phê duyệt mới làm sửa nhỏ, test-first; không thêm provider, paid AI hay live submission để bù thiếu capability.

### Exact commands, artifacts và git status

Working directory: `D:\DNTU\Tuhoc\AgentMine`.

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B .tmp/phase-b4-simulation/run_simulation.py > .tmp/phase-b4-simulation/execution.log
.\.venv\Scripts\python.exe -B -m agentmine.bootstrap.operator --help
.\.venv\Scripts\python.exe -B -m pytest tests/unit/application/test_data_worker.py tests/integration/test_data_recovery.py tests/integration/test_worker_execution_runtime.py tests/integration/test_runtime_operator_cli.py tests/integration/test_operational_deliverable_qa.py tests/integration/test_deliverable_qa_sqlite.py -q --tb=short -p no:cacheprovider
```

CLI argv đầy đủ từng ca được ghi bổ sung tại `commands.txt`; `cli-transcript.json` chứa response thực tế, helpers prepare/execute dùng đúng argv được liệt kê trong commands.txt. Các argv này đã chạy in-process qua parser/composition, không phải bằng chứng module entrypoint hỗ trợ fake source.

Artifacts gốc: `.tmp/phase-b4-simulation/{dirty,control,complete,malformed}-input.json`; `independent-expected.json`; `independent-complete-expected.json`; `run_simulation.py`; `results.json`; `execution.log`. Mỗi `*-final/` có `execution.sqlite3`, `spec.json`, inputs, `cli-transcript.json`, `retained-records-inspection.json`, `export/`, và `independent-worker-journal.sqlite3`. Fixture nằm trong .tmp có thể bị dọn; muốn tái lập cần giữ thư mục này. Harness giữ evidence nên chạy lại nguyên lệnh trên cùng thư mục sẽ từ chối tạo thư mục đã tồn tại; chọn thư mục mới thay vì overwrite lịch sử.
Kết quả đã thực thi:

| Command/check | Kết quả | Điều chứng minh |
|---|---|---|
| Final simulation harness | exit 0; 4/4 ca, assertions đều qua | Independent cells/issues, artifact parse/bytes, restart, fresh recompute, QA, costs và no submission/revenue trong isolated setup |
| Focused pytest command ở trên | **150 passed in 61.21s**; không failed/skipped được báo | Existing DataWorker, SQLite recovery, execution preflight, CLI, operational QA và QA journal regressions; test-only providers chỉ ở test |
| Architecture pytest dưới đây | **29 passed in 4.33s** | Existing dependency-boundary checks |
| Module operator --help | exit 0 | Entrypoint/parser khả dụng, không chứng minh live execution |
| git diff --check | exit 0, không output | Tracked diff không có whitespace errors; report mới chưa tracked không được Git kiểm tra bởi lệnh này |

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/unit/test_architecture.py -q --tb=short -p no:cacheprovider
git diff --check
git status --short
```

Không có warning summary ở hai pytest run. Không chạy full pytest/Ruff/mypy trong checkpoint chỉ tạo báo cáo và scratch simulation này; không dùng kết quả cũ làm fresh verification. Tổng fresh existing tests: **179 passed**. Các assertion trong harness không được tính thêm thành pytest test count.

`commands.txt` ghi `--expected-revision 6`, đối chiếu bằng một reference-only isolated fixture dựng bởi đúng helper (không dispatch worker). FakeClock là 2026-10-25, deadline fixture là 2026-10-27; không tuyên bố deadline đó còn hiệu lực ở thời gian thật ngày audit 2026-11-03. Reference workspace phụ nằm tại `revision-reference-only/`; không phải bounty thật hoặc workspace vận hành.

Git status cuối checkpoint:

```text
?? docs/audits/phase-b4-realistic-bounty-simulation.md
```

Không commit/push. Không sửa production source/tests/dependencies; `.tmp/` artifacts bị Git ignore và không nằm trong commit. Recommended next phase: **design-only clean/rejected export và QA optional-null contract**, chờ operator duyệt trước implementation.
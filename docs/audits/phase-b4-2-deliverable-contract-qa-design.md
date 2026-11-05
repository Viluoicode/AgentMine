# Phase B.4.2 — Deliverable Contract & QA Semantics Design

## 1. Executive Summary

**GO cho implementation opt-in sau operator review; NO-GO cho real bounty readiness.** DESIGN ONLY: chỉ tạo báo cáo này. Commit đối chiếu `7c660a8adfac07e408c3e3939988c9697770c204`, ngày 2026-11-03.

Đề xuất: contract partition v2 được đóng băng trong WorkSpecification; DataWorker gọi hàm partition thuần sau transform/validate; retain toàn bộ records/issues; render `clean.json`, `clean.csv`, `rejected.json`, `validation.json`. QA kiểm tra completeness, schema, partitions và ngưỡng acceptance đã duyệt. Không đổi ngầm nghĩa `DataResult.valid`, legacy COLUMN, artifact hoặc QA lịch sử.

Nhãn bằng chứng: **[V]** đọc trực tiếp source/check mới; **[O]** operator đã duyệt Policy A; **[P]** đề xuất cần duyệt; **[U]** chưa chứng minh. Policy A đã approved, không cần hỏi lại; tên artifact/version/migration/acceptance dưới đây vẫn là đề xuất. Không có live marketplace hoặc client acceptance evidence.

## 2. B.4.1 Findings and Root Causes

[V] B.4.1 report ghi dirty catalog: 4 retained rows, 11 issues, chỉ validation.json; optional-null control: CSV/JSON nhưng QA NEEDS_REVISION; complete control QA PASS. Đây là evidence lịch sử, không phải rerun trong B.4.2.

[V] Source xác nhận:

- `application/workers/data_artifacts.py:26`: có issue thì return validation artifact duy nhất; chưa partition.
- `application/workers/data_transform.py:172`: seen-set chỉ flag occurrence thứ hai trở đi; không đáp ứng Policy A reject cả bản đầu.
- `application/qa/checks.py:121`: JSON COLUMN yêu cầu key và non-null; khác optional-null schema.
- `application/qa/checks.py:268`: input issues đều thành NEEDS_REVISION cả batch; chỉ sửa exporter không đủ.
- `application/contracts/data.py:283`: valid = not issues. Đây là input validity, không phải client acceptance.
- `infrastructure/snapshots.py:249` và exact field-set guard sau đó: dataclass default mới không tự bảo đảm đọc snapshot cũ.

Không cần LLM để sửa mismatch này. Không nới eligibility, budget hoặc QA cho output không an toàn.

## 3. Current Architecture and Evidence

Source paths rút gọn dưới đây tính từ `src/agentmine/`.

| Thành phần [V] | File:line | Responsibility/invariants | Test source / compatibility |
|---|---|---|---|
| Input/column/plan | `application/contracts/data.py:49`, `:84`, `:165` | Bounded UTF-8 source/digest, typed columns/counts, estimate 0 cho deterministic | `tests/unit/application/test_data_worker.py:258`; chưa output policy |
| Transform | `application/workers/data_transform.py:47`, `:65`, `:74`, `:116` | Strict parse, extract, canonicalize, giữ source/row | Worker tests `:32`, `:59`, `:286`, `:308`; missing/null cùng có thể thành normalized null |
| Validate | `application/workers/data_transform.py:172` | Required, bounds, allowed values, duplicates, counts/constraints | Worker tests `:106`, `:182`, `:319`, `:328`; duplicate chỉ flag từ bản sau |
| Worker | `application/workers/data.py:99` | Save plan, replay, deadline/auth, result trước actual-cost record | Worker tests `:53`, `:206`, `:226`, `:236`; không retry paid unknown |
| Artifacts | `application/workers/data_artifacts.py:10` | Validation always; dataset khi zero issue; CSV formula escape/provenance | Worker test `:339`; không đổi legacy bytes |
| Journal | `infrastructure/sqlite/data.py:16`, `:40`, `:44` | Immutable plan/result theo execution ID | `tests/integration/test_data_recovery.py`; không replace history |
| Specification | `application/contracts/runtime.py:59`, `:158` | Frozen actor/ledger/source/digests/columns/acceptance → DataPlan | `test_runtime_operator_cli.py:132`, `:192`; policy phải freeze ở đây |
| Prepare/execute | `application/use_cases/local_runtime.py:41`; `application/use_cases/worker_execution.py:84`, `:181` | Approval/evidence preflight, authorization/start trước worker(llm=None), retained finish | `test_worker_execution_runtime.py`, `test_runtime_operator_cli.py`; không bypass freshness |
| Result guard | `application/contracts/runtime.py:293`, `:325` | Provenance, zero-cost binding và artifact whitelist | Runtime integrations; v2 cần allowlist tại boundary này |
| QA contracts | `application/contracts/qa.py:62`, `:116`, `:144` | Frozen formats/requirements, exact bundle, typed inspection | `test_operational_deliverable_qa.py:339`, `:349`; whitelist ba tên hiện tại |
| Operational QA | `application/use_cases/operational_qa.py:39` | Load retained result/criteria, same actor/ledger, no paid dependencies | QA tests `:133`, `:147`, `:212`, `:251`; phải bind cả acceptance mới |
| QA engine | `application/use_cases/deliverable_qa.py:56`; `application/qa/checks.py:36`, `:268` | Deterministic→domain-specific→AI khi cần; report trước lifecycle application | `test_deliverable_qa_sqlite.py:20`; v2 branch không nới v1 |
| Export | `application/use_cases/local_runtime.py:151`; `infrastructure/local_artifact_export.py:22` | Retained artifacts, no-clobber, manifest cuối, local-only | Runtime CLI tests `:423`, `:548`; whitelist cần update |
| Snapshot codec | `infrastructure/snapshots.py:60`, `:123`, `:227` | Allowlisted models, strict version/fields, narrow migrations | Cần golden historical fixtures mới; không generic fallback |
| Revision | `application/contracts/data_revision.py:112`; `application/use_cases/data_revision.py:85` | Acceptance không relax, version/identity allocation riêng | `test_data_revision_foundation.py`, `test_data_revision_execution.py`, `test_revision_operator_qa.py`; không contract-switch ngầm |

Test references không có prefix đầy đủ trong bảng là các file trong `tests/integration/`, trừ worker tests trong `tests/unit/application/`. Đây là source coverage inventory, không tuyên bố toàn bộ integration tests được rerun.

[V] Flow: retained Source → WorkSpecification → authorized DataPlan → transform → validate → DataResult/artifacts → journal/cost → atomic finish/QA_PENDING → QA → human review/rework. Export có thể trước QA, không chứng minh QA PASS hoặc submission. Presentation không sở hữu lifecycle/partition rules.

## 4. Proposed Clean / Rejected Contract

### Vị trí xử lý [P]

Một hàm thuần mới trong `application/workers/data_partition.py`, được DataWorker gọi sau transform/validate và trước renderer. Worker vẫn orchestration owner; partition quyết định membership, renderer chỉ serialize; Infrastructure persist/export. Không thêm service class/framework/repository. Contract ở Application vì gắn capability Data; chưa cần Domain aggregate mới.

### Typed contracts tối thiểu [P]

- `DataPartitionPolicy`: frozen `contract_version=2`, `id_column`, `duplicate_policy=REJECT_ALL`. First version chỉ deterministic; id column required TEXT, có trong columns, `unique_by == (id_column,)`; không composite IDs.
- `WorkSpecification.output_policy`, `DataPlan.output_policy`: optional, None = legacy; exact copy từ approved request, equality bao gồm policy.
- `DataCell.input_presence`: optional enum MISSING/NULL/VALUE, None chỉ legacy. Ghi trước normalize; blank input là VALUE dù normalized null.
- `DataPartitionAssessment`: policy/version, ordered clean row refs, rejected row refs + reasons, duplicate groups, source parse outcomes, counts, evidence_complete.
- `DataResult.partition`: optional assessment; `records` vẫn toàn bộ parsed rows, `issues` vẫn đầy đủ. Membership dùng `(source, digest, source_row)`/row_id references, không nhân đôi authority DataRecord.
- `PartitionAcceptance`: frozen trong DataAcceptanceCriteria, version2, explicit `min_clean_records>=1`, `0<=max_rejected_records<=1000`. Không default cho phép mọi reject.
- `QAInspection.partition_acceptance`: exact copy từ frozen acceptance, immutable và compare trên retry.
- `CoverageKind.FIELD_PRESENT`: kind mới; legacy COLUMN giữ semantics cũ.

Giữ `DataResult.valid = not issues`; có rejected rows thì false nhưng QA v2 có thể PASS nếu deliverable đúng contract và thresholds. CLI tách input_valid/partition counts/qa_outcome. Không gọi input-invalid là worker crash hoặc client rejection tự động.

`min_records/max_records` cũ vẫn là bounds toàn parsed batch; `min_clean_records` riêng. Không đổi ngầm nghĩa record limit.

### Invariants [P]

1. Mọi parsed record thuộc đúng một partition; `parsed = clean + rejected`, không membership thiếu/trùng. Mỗi source-row identity duy nhất.
2. Clean không có row/field issue, ID valid và không duplicate. Batch/source errors không gán đại vào một row.
3. Rejected retain canonical values, mọi issue và group membership. Không clamp số âm, sinh ID hoặc đoán missing attributes.
4. Full-group duplicate dùng code hiện có `duplicate` trên mọi member; group ID nằm trong structured partition reason. Không rewrite issue lịch sử.
5. Source metadata gồm ref/locator/digest/time, parse status, parsed_count hoặc null nếu không biết. Raw content vẫn retain trong DataSource; không copy raw secret-bearing bytes vào rejected artifact.
6. Digest chỉ integrity/binding; giữ `caller_supplied_unverified`, không hứa source truth/licensing.
7. Source order = approved tuple; row order = source order rồi source row; partitions stable subsequences. Group order = first member encounter; members theo global order. Issues sort cố định theo source/row/column-plan-index/code; source-level trước row-level. Không set iteration/hash ngẫu nhiên.
8. Malformed source/missing/corrupt evidence → incomplete, không phát hành clean dataset. Không fabricate parsed records hoặc record_count=0 cho source chưa parse được.
9. Unknown issue scope/version hoặc assessment không khớp source → fail closed; không fallback clean.

### Exact artifact schemas [P]

V2 evidence đầy đủ xuất theo thứ tự `clean.csv`, `clean.json`, `rejected.json`, `validation.json`; không data.csv/json aliases.

- **clean.json**: array flat approved columns + `_provenance`. Mọi key hiện diện; required non-null, optional được null theo schema. Numeric values vẫn canonical strings. Provenance giữ source/locator/time/digest/source-row/field-path/lookup evidence, thêm input_presence từng field.
- **clean.csv**: columns theo plan + `_provenance`; cùng clean records/order. Null thành blank như hiện tại; provenance phân biệt MISSING/NULL/VALUE. Giữ formula escape; JSON là representation chính xác giá trị, không hứa CSV thiếu provenance round-trip null.
- **rejected.json**: array `{row_id, values, reasons, _provenance}`; values = normalized columns; reasons = `{code, column, group_id?}`; provenance đầy đủ như clean. Có nhiều lỗi giữ đủ, không ưu tiên làm mất evidence.
- **validation.json**: object `{contract_version:2, policy, evidence_complete, input_valid, counts, sources, issues, duplicate_groups, unresolved}`. counts gồm parsed/clean/rejected/duplicate_groups; sources có ref/digest/status/parsed_count; groups có group_id/canonical_id/member row refs; issues có code/source/row/column/optional group_id. unresolved chỉ actual codes/scope, không AI narrative. Không worker-generated client_acceptance=PASS.

Ví dụ rejected item rút gọn schema (không phải canonical fixture):

```json
{"row_id":"row-1","values":{"id":"A001","brand":null},"reasons":[{"code":"duplicate","column":"id","group_id":"sha256:..."}],"_provenance":{"source":"source-1","sha256":"...","source_row":1,"fields":{"brand":{"path":["brand"],"input_presence":"MISSING"}},"source_verification":"caller_supplied_unverified"}}
```

QAReport vẫn do DeliverableQA/journal tạo; validation không tự duyệt QA. Input issues không bị xóa để input_valid=true.

All-rejected với evidence complete vẫn có clean.json=[], CSV header, full rejected/report; QA không PASS vì min_clean>=1. Malformed source thì chỉ validation diagnostic, retain các parsed records khác nội bộ. Report `total_input_records:null`, parsed_count của source lỗi null, coverage incomplete; biết số parsed ở source khác không đồng nghĩa biết tổng input. Missing/corrupt retained evidence là integrity failure, không được giả làm source parse lỗi bình thường.

## 5. Duplicate ID Policy A

[O] Normalize rồi group toàn batch. Group size≥2 reject mọi member, kể cả occurrence đầu, qua nhiều sources. Không first/last wins, không merge, không replace ID.

[P] Hai pass bounded 1.000 rows: transform/collect issues → xác định valid canonical IDs → group → thêm duplicate reason mọi member → partition. Member có lỗi field khác vẫn tham gia group nếu ID hợp lệ. Missing/invalid ID không bị gom dưới null; reject bằng actual ID issues. ID invalid dựa required/type/allowed/max_length thật, không tự thêm regex ngoài schema.

Group ID đề xuất: SHA256 của canonical JSON tuple gồm domain separator `agentmine-data-duplicate-v2`, ordered source refs+digests, canonical policy và canonical ID. Chốt UTF-8/ensure_ascii/sort_keys/separators và golden bytes khi implementation. Không Python hash hoặc concatenation mơ hồ. Stable cùng frozen inputs/policy/replay; khác batch/policy khác scope. Không có monetary ownership gắn group ID.

| Case | Kết quả |
|---|---|
| ` a001 ` + `A001`, approved trim+upper | Cả hai reject, một group A001 |
| Ba A001 | Reject cả ba, ba member refs |
| Cross-source A001 | Một group batch, provenance riêng mỗi source |
| Missing ID | missing_column + missing_value; không invent |
| Null/blank ID | missing_value; origin NULL/VALUE; không group null |
| Invalid ID | invalid_value theo schema; không dùng invalid key như valid ID |
| Duplicate + invalid stock | duplicate và invalid_value cùng giữ |
| Duplicate + optional null | Duplicate reject; optional-null không tự sinh lỗi |
| Repeated execution | Same policy/input → same membership/artifact, same-ID replay không cost trùng |

Freeze policy qua PrepareDataRequest→WorkSpecification→DataPlan; approve-inputs duyệt policy/schema/acceptance hiển thị rõ. Không env/worker default bật Policy A. Task legacy giữ behavior cũ, client tương lai cần approval explicit.

Đổi input/policy/threshold cùng ID → conflict. Trước start cần spec mới + consent mới; sau start/completed không overwrite hoặc fresh execution ID né commitment. V2 revision chỉ cho cùng output policy/version; v1→v2 migration trong lineage bị typed unsupported, cần checkpoint riêng. Acceptance revision chỉ non-relax: min_clean không giảm, max_rejected không tăng. Không nới F05.

## 6. Optional Field QA Semantics

[P] Legacy COLUMN vẫn giữ nguyên (JSON key và non-null; CSV header như cũ). V2 dùng FIELD_PRESENT cho structural coverage trên clean.json, cộng schema checks từ frozen DataColumn. Explicit non-null criterion tiếp tục enforce; không đổi criteria sau output để lấy PASS.

| Check | Semantics đề xuất |
|---|---|
| Presence | Mọi output clean row có mọi approved key; thiếu key artifact → integrity/QA FAIL |
| Non-null | DataColumn.required=True hoặc explicit JSON COLUMN criterion cấm null; optional không tự vượt criterion chặt hơn |
| Validity | Type/bounds/allowed/max_length/constraints áp dụng mọi non-null value dù optional |
| Input origin | MISSING khác NULL khác VALUE; có thể cùng canonical null nhưng provenance khác; blank là VALUE |
| Dataset acceptance | Complete evidence, parsed bounds, conservation, min_clean/max_rejected frozen |
| Partition acceptance | Clean schema-valid; rejected có actual reasons đúng/đủ, không bắt rejected schema-valid |

Optional DECIMAL='oops' → invalid_value dù normalized null, reject. Missing optional/explicit null/blank có thể clean theo schema nhưng retain origin khác. Missing required path có missing_column + missing_value; explicit required null chỉ missing_value. Không gộp source missing với missing output key.

Output v2 thiếu PartitionAcceptance hoặc version mâu thuẫn → block. Operational QA phải copy toàn acceptance mới vào inspection và compare full equality trên retry; hiện chỉ formats/requirements là chưa đủ. Exact retained plan/spec/policy/digest vẫn authoritative.

Mixed clean1/reject2 có thể QA PASS nếu min_clean=1,max_rejected=2 được approved trước chạy; max_rejected=0 thì NEEDS_REVISION. Không default partial acceptance. QA recompute origin, canonical values, group membership, issues, counts, sources và rendered bytes; fake clean/dropped issue/provenance mismatch → FAIL. Recompute cùng primitives không thay independent literal test oracle.

PASS → READY_FOR_HUMAN_REVIEW, submission approval riêng exact version/digest. FAIL/NEEDS_REVISION giữ Domain behavior hiện tại và F05 rework; human-pending giữ QA_PENDING. Historical applied inspection readback không mutate later lifecycle. Semantic QA vẫn human review khi zero-AI runtime không support.
## 7. Failure and Recovery Matrix

Các outcome sau là [P], giữ transaction/auth/journal protocol hiện có.

| Case | Worker/evidence và artifacts | QA/lifecycle/recovery |
|---|---|---|
| All valid | All clean, bốn artifacts, rejected=[] | PASS nếu criteria đủ → human review |
| Mixed valid/invalid | Tất cả parsed rows retain, clean/reject đúng lý do | PASS chỉ theo ngưỡng approved; không thì NEEDS_REVISION |
| Zero clean/all rejected | Complete evidence; empty clean/header + full rejects/report | NEEDS_REVISION; cấm vacuous PASS |
| Cross-source duplicates | Full-group reject toàn batch, giữ source identities | Outcome theo clean/reject thresholds |
| Malformed JSON/CSV | Không fabricate rows source lỗi; retain source khác; validation-only | NEEDS_REVISION, incomplete coverage, không clean publish |
| Invalid schema/policy/version | Typed invalid/unsupported trước start/auth khi có thể; không fabricated result | BLOCKED, không worker dispatch |
| Parsed count ngoài min/max | Retain parsed/partition và batch record_count issue | NEEDS_REVISION dù min_clean đạt |
| Missing evidence/digest corrupt | Preflight block hoặc integrity guard; không clean publish | BLOCKED trước work, QA FAIL nếu retained corruption |
| Artifact render/result persist lỗi | Start/auth vẫn retain; không công bố incomplete result | Same-ID deterministic retry; không release commitment |
| Result durable/cost write lỗi | Read retained result, record đúng actual operation | Same-ID settlement retry, không duplicate/fabricated zero |
| Cost durable/finish lỗi | Giữ result và ledger; retry atomic finish | Không worker/provider resend |
| Crash sau compute/trước result | Preserve start/commitment; không complete export | Recompute chỉ deterministic frozen inputs, original IDs, preconditions còn hợp lệ |
| Export crash giữa files | No-clobber, manifest cuối; thiếu manifest chưa complete | Retry exact bytes; conflicting bytes không overwrite |
| Restart | Decode exact contract version; original result/history | Không auto-upgrade policy/evidence |
| Repeated QA | Original binding/report và exact content | Idempotent readback, không kéo lùi lifecycle/cost |
| Deadline hết trước dispatch/recompute | Existing deadline guard block | Không start/recompute; retained history vẫn đọc được |
| Source/terms đổi trước new QA | Preflight fail closed | Không new QA authority; applied historical report vẫn readback |
| SCOUT_ONLY/AI budget $0 | Authorization vẫn bắt buộc, deterministic estimate/actual AI zero | Không LLM/AI-QA fallback; other unknown cost vẫn unknown |
| Unknown paid claim | Inspect-only, ngoài capability v2 | Không paid retry hoặc release claim |

Worker completion chỉ có nghĩa execution evidence đã lưu, không client acceptance. Nếu incomplete source được lưu thành diagnostic result và lifecycle tới QA_PENDING thì QA phải NEEDS_REVISION; không phát hành clean data để che source failure. Missing/corrupt retained evidence không được classify như input malformed để tiếp tục.

## 8. Backward Compatibility

[P] Hai chế độ explicit:

- **Legacy output_policy=None:** giữ data.csv/data.json/validation shape, duplicate behavior, COLUMN semantics và old replay/QA outcomes. Missing new fields decode thành None, không bật v2.
- **V2:** filenames/version/partition acceptance mới; consumer không hỗ trợ phải báo unsupported, không fallback gọi clean subset là full original dataset.

Không alias clean.json thành data.json. Không nâng history khi read. Giữ input valid khác QA outcome. Export manifest giữ execution/content/deliverable binding; có thể thêm contract_version cho v2 nhưng không rewrite manifest cũ. Exact bundle bytes bind artifact content và provenance, nên không reuse approvals khi bytes/contract đổi.

**Không SQL table/index migration dự kiến** vì snapshots lưu typed objects; **snapshot model migrations là bắt buộc**. Narrow defaults None cho WorkSpecification, DataPlan, DataCell, DataResult, DataAcceptanceCriteria, QAInspection và PrepareDataRequest nếu có persisted instances. Xác nhận từng nested type bằng golden snapshots; strict unknown field/version rejection vẫn giữ. Không generic “default missing fields” hoặc bỏ unknown fields.

Các model mới nên nằm data/qa modules đang codec-register. V2 decode bắt buộc typed policy/partition/origin/acceptance đầy đủ, không None fallback. Legacy decode rồi encode có thể thêm explicit None fields nên không hứa snapshot serialization bytes identical; yêu cầu **original stored payload không rewrite**, original embedded artifacts/content digests không đổi và replay equality/idempotency giữ nguyên. Golden fixture phải kiểm tra nested plan/result/inspection/revision, không chỉ standalone DTO.

F05: bổ sung output policy equality và non-relax partition thresholds (min_clean không giảm/max_rejected không tăng). V1→v2 contract migration trong cùng lineage chưa support, không sửa subset checks để lách approved old criteria. V2→v2 rework giữ version/group policy và fresh economics/source/budget/consent như cũ.

## 9. Independent Test Plan

**Đây là plan chưa được implementation/thực thi.** Oracle literal viết trước production changes; không gọi DataWorker/transform/partition/render để sinh expected. Assert exact normalized values, row membership, source provenance, codes và counts; conservation/property checks bổ trợ, không thay oracle.

Baseline proposed fixture C: id required TEXT trim+upper; price DECIMAL ≥0; brand optional TEXT. Acceptance min_clean=1/max_rejected=2, complete sources; FIELD_PRESENT. Trừ khi ghi khác, thêm B002 hợp lệ để clean không rỗng. Expected duplicate group canonical IDs/members viết tay; hash golden được kiểm tra từ đặc tả encoding độc lập, không gọi production hash function để tính expected.

| # | Input | Expected output và issue codes | Expected QA | Contract/component |
|---:|---|---|---|---|
| 1 | A001/B002 valid | clean2/reject0; issues=[]; bốn artifacts | PASS | Worker/render/QA |
| 2 | B002 + A001 price=-1 | clean1/reject1; invalid_value(price) | PASS theo C; max_rejected=0 → NEEDS_REVISION | Partition/threshold |
| 3 | Chỉ A001 price=-1 | clean0/reject1; invalid_value | NEEDS_REVISION | Zero-clean gate |
| 4 | ` a001 `, `A001`, B002 | Reject cả A001; clean B002; duplicate trên hai rows, một group | PASS theo C | Policy A normalization |
| 5 | Ba A001 + B002 | clean1/reject3; duplicate trên cả ba, một group | NEEDS_REVISION theo C; approved max=3 mới PASS | Full group |
| 6 | X:A001; Y:A001,B002 | Reject X/Y A001, clean B002, source refs riêng | PASS theo C | Cross-source |
| 7 | Hai A001, một stock/price invalid, +B002 | Cả A001 reject; giữ duplicate và invalid_value trên member lỗi | PASS theo C | Reason union |
| 8 | B002 + missing ID + ID quá max_length | clean1/reject2; missing_column/missing_value và invalid_value; không null group | PASS theo C | Valid identifier rule |
| 9 | B002 optional brand:null | clean1; brand key null, origin NULL, không issue | PASS FIELD_PRESENT; explicit legacy COLUMN(brand) vẫn NEEDS_REVISION | Optional QA |
| 10 | B002 price:null hoặc thiếu price | reject; null→missing_value; absent→missing_column+missing_value; origin khác | NEEDS_REVISION nếu clean0 | Required/null |
| 11 | Optional DECIMAL field='oops' | invalid_value dù required=False; không silently-null clean | NEEDS_REVISION nếu clean0 | Optional validity |
| 12 | Malformed JSON/CSV + source valid | malformed_source; retain parsed source khác, source lỗi count UNKNOWN; validation-only | NEEDS_REVISION | Source completeness |
| 13 | Missing source ref/corrupted digest | No dispatch hoặc retained integrity error; không invented row | BLOCKED/FAIL theo thời điểm | Preflight/QA |
| 14 | Source order Y→X, IDs unordered | Partitions stable subsequences, group/member/issue order fixed, golden bytes | PASS nếu C | Determinism |
| 15 | Mixed four rows; cố thêm/xóa membership | Good output exact partition union; altered output thiếu/trùng row | FAIL khi corruption | Conservation |
| 16 | Nested path/lookup, hai sources | Exact digest/path/locator/timestamp/lookup ref theo oracle | PASS; sửa provenance → FAIL | Provenance |
| 17 | Legacy valid/invalid snapshots | Old bytes/invalid→validation-only/COLUMN giữ nguyên; no auto policy | Outcomes cũ | Compatibility/codec |
| 18 | Crash quanh result/cost/finish rồi reopen | Original IDs, same result, một actual cost record, không release | Same expected QA, no rewind | SQLite/runtime |
| 19 | Giả clean value hoặc bỏ first duplicate/reason | Recompute/membership/report/artifact mismatch | FAIL | Unsafe-output QA |
| 20 | SCOUT_ONLY $0, provider/network/submission fail-if-called | Deterministic output; một actual AI zero; revenue zero, no action | PASS output hợp lệ; side effect làm test fail | Budget/composition |
| 21 | Brand missing vs null vs blank | Canonical null nhưng MISSING/NULL/VALUE; mọi output key hiện diện | PASS nếu schema; xóa output key → FAIL | Presence semantics |
| 22 | Hai A001 có optional-null + B002 | Cả A001 duplicate reject; không thêm lỗi vì optional-null | PASS theo C | Duplicate+null |
| 23 | Hai missing/null IDs | Hai rejects với actual missing reasons; không duplicate_groups | NEEDS_REVISION nếu clean0 | No artificial null group |
| 24 | Parsed count ngoài min/max, clean đạt | Batch record_count issue vẫn còn; partition counts đúng | NEEDS_REVISION | Batch vs partition |
| 25 | Same-ID changed policy/threshold, stale inspection | Typed conflict; original result/report không đổi | BLOCKED/no new authority | Consent/immutability |
| 26 | Empty input, min_records=0 | parsed=clean=rejected=0, no fabricate | NEEDS_REVISION min_clean≥1 | No vacuous PASS |
| 27 | Result write fail/partial export/ack lost | Same-ID readback/retry; manifest chỉ complete khi đủ exact bytes | No PASS từ incomplete evidence | Recovery/export |
| 28 | Unknown policy version/optional ID/composite unique_by | Typed invalid/unsupported trước dispatch | BLOCKED | Parser/contract |
| 29 | V1→v2 revision hoặc v2 tăng max_rejected | Reject contract-switch/relaxation, history nguyên vẹn | BLOCKED | F05 guards |
| 30 | Valid source trước malformed source | Parsed rows nguồn đầu retain, coverage incomplete, không clean publication | NEEDS_REVISION | No false coverage |

Fixture B.4.1 dưới Policy A phải **clean0/reject4**: row1/row3 cùng A001 đều reject, row2 invalid, row4 thiếu ID/stock. Không lấy đó làm client PASS chỉ vì có partition files. Cần fixture hỗn hợp thêm B002 valid để chứng minh partial-clean acceptance, thresholds approved trước run.

## 10. Exact Files to Change

Danh sách sau là **implementation proposal**, không phải files đã sửa.

| Source file | Thay đổi cần thiết [P] |
|---|---|
| `src/agentmine/application/contracts/data.py` | Typed policy/assessment/origin; additive plan/cell/result fields; giữ valid |
| **New** `src/agentmine/application/workers/data_partition.py` | Pure grouping/partition/conservation; không generic framework |
| `src/agentmine/application/workers/data_transform.py` | V2 origin tracking và duplicate semantics opt-in; preserve legacy |
| `src/agentmine/application/workers/data.py` | Call partition; giữ result-before-cost |
| `src/agentmine/application/workers/data_artifacts.py` | V2 four-artifact rendering, legacy byte behavior |
| `src/agentmine/application/contracts/qa.py` | PartitionAcceptance, FIELD_PRESENT, inspection binding và version-aware inventory |
| `src/agentmine/application/qa/checks.py` | Presence/schema/partition/threshold/exact artifacts QA v2; legacy branch |
| `src/agentmine/application/contracts/runtime.py` | Policy spec→plan; WorkerResult assessment/filename/type guards |
| `src/agentmine/application/contracts/local_runtime.py` | PrepareDataRequest explicit policy |
| `src/agentmine/application/use_cases/local_runtime.py` | Prepare copy/equality, retained export projection |
| `src/agentmine/application/use_cases/operational_qa.py` | Copy/compare frozen PartitionAcceptance trong inspection/retry |
| `src/agentmine/presentation/runtime_inputs.py` | Strict v2 manifest parse, reject unknown/contradictory inputs |
| `src/agentmine/presentation/runtime_views.py` | `specification_view` (line 29) hiển thị approved policy; shared first-version/revision projection |
| `src/agentmine/presentation/runtime_cli.py` | Existing status/show output tách policy/counts/input-valid/QA; không new workflow |
| `src/agentmine/infrastructure/local_artifact_export.py` | V2 bounded filenames/version metadata, no-clobber/manifest-last |
| `src/agentmine/infrastructure/snapshots.py` | Narrow missing-field None migrations + strict v2 decode |
| `src/agentmine/application/contracts/data_revision.py` | Same-policy/version guard và non-relax acceptance |
| `src/agentmine/application/use_cases/data_revision.py` | Copy exact approved output policy cho same-contract revision |

[V] Đã xác nhận runtime_cli import specification_view từ runtime_views; runtime_cli.runtime_view (line 121) sở hữu status projection. Hai file trên là owner cần sửa, không tạo serializer trùng. Domain, BudgetManager, DataJournal port, SQLiteDataJournal và atomic execution transaction dự kiến không cần đổi. Nếu buộc đổi transaction semantics thì dừng để review scope riêng.

Tests mới dự kiến:

- `tests/unit/application/test_data_partition.py`: independent literals/full groups/conservation/order.
- `tests/unit/application/test_partition_qa.py`: optional/schema/threshold/unsafe artifacts.
- `tests/integration/test_partitioned_data_runtime.py`: real SQLite/DataWorker/DeliverableQA/CLI/export, no providers.
- `tests/integration/test_data_partition_snapshot_compatibility.py`: golden old snapshots, nested plan/result/inspection/revision, unknown versions.

Tests cập nhật: `tests/unit/application/test_data_worker.py`; `tests/integration/test_data_recovery.py`, `test_worker_execution_runtime.py`, `test_runtime_operator_cli.py`, `test_operational_deliverable_qa.py`, `test_deliverable_qa_sqlite.py`, `test_data_revision_foundation.py`, `test_data_revision_execution.py`, `test_revision_operator_qa.py`. Preserve legacy assertions; architecture tests chạy lại, không nới rules.

Không table/index/dependency mới. Có snapshot model compatibility work, không migrate trusted authority. ADR focused cho opt-in semantics có thể tạo ở implementation sau approval; không tạo ADR/checkpoint code trong B.4.2.

## 11. P0 / P1 / P2 Risks

| Priority | Risk | Gate |
|---|---|---|
| P0 | Giữ first duplicate, mất rows/reasons | Independent full-group oracle, exact partition conservation |
| P0 | Artifact tồn tại bị hiểu client PASS | Explicit thresholds, zero-clean gate, separate input_valid/qa_outcome |
| P0 | Silently đổi old consent/history/replay | Frozen opt-in, strict version/codec, no same-ID replacement/contract-switch revision |
| P1 | Optional invalid bị null hóa rồi clean | Retain transform issue và origin; schema validity dù optional |
| P1 | Malformed source trông như empty | Unknown count, incomplete coverage, no clean publication |
| P1 | Chỉ renderer update, guards/export/QA vẫn cũ | Real component end-to-end acceptance gates |
| P1 | Additive fields phá snapshots/approval bindings | Golden nested history, no blanket default, không rewrite artifacts |
| P1 | COLUMN bị nới hoặc inspection thiếu thresholds | Keep legacy semantics + exact frozen new acceptance binding |
| P1 | Revision bỏ policy/relax acceptance | Same-policy copy/guard + F05 regressions |
| P2 | CSV null/blank/numeric text consumer mismatch | JSON canonical, origin provenance, documented consumer contract |
| P2 | Digest bị hiểu verified fact | caller_supplied_unverified, no automatic URL access |
| P2 | Scope lan thành policy framework | Pure function/additive contracts, no provider/services/domain changes |

P0 là blocker tính đúng/acceptance trong implementation dự kiến, không kết luận vulnerability CRITICAL mới. Complexity **vừa đến cao** do consent/codec/QA/revision compatibility, không chỉ thêm renderer. Chưa đủ cơ sở ước lượng giờ chắc chắn.

## 12. Implementation Sequence

1. **Operator design gate:** duyệt opt-in v2, filenames, giữ COLUMN/valid legacy, malformed-source diagnostic-only, explicit min_clean/max_rejected và no lineage contract migration. Policy A đã approved.
2. **Test-first contract/codec:** failing literals + golden snapshots trước production edits; typed models/parser/bindings, strict migration. Same-ID altered payload phải conflict.
3. **Partition core:** origin/full-group/ordering/conservation, independent expected outputs; không infrastructure business rules.
4. **Worker/render/persistence:** v2 artifacts, result-before-cost, restart/ack loss; giữ actual-zero only measured AI.
5. **QA:** schema + FIELD_PRESENT + frozen thresholds + exact artifact/evidence checks; zero-clean/malformed fail closed; old QA unchanged.
6. **Runtime/export/revision:** status rõ nghĩa, bounded filenames, no-clobber, same-contract revision copy và non-relax guards. Không new workflow.
7. **Simulation độc lập lại:** B.4.1 phải clean0/client fail; thêm mixed fixture B002 với approved thresholds để chứng minh useful deliverable. Không dùng fixture forecast làm real-world readiness.
8. **Verification/review:** focused/new tests, F02/F05 regressions, architecture, full pytest, Ruff check/format, strict mypy, git diff --check; ghi exact results và limitations; stop operator review.

Non-goals: Research/semantic Data/Bedrock/AI QA, paid workers, auto budget resume, source eligibility/reward changes, Superteam/live submission/payment/wallet/FX, AWS, frontend/framework/service mới, generic policy engine và v1→v2 history/lineage migration.

## 13. Final GO / NO-GO Recommendation

**GO cho operator review thiết kế và bounded test-first implementation sau approval. NO-GO cho implementation chưa duyệt hoặc real bounty readiness.** Không cần chọn lại duplicate policy. Acceptance thresholds của từng task vẫn cần operator duyệt trước execution; không tự chọn số để giả định một client thật chấp nhận reject rate.

### Exact report path

`D:\DNTU\Tuhoc\AgentMine\docs\audits\phase-b4-2-deliverable-contract-qa-design.md`

### Read-only checks performed

Đọc attachment, AGENTS.md, Product Constitution, B.4.1 và source/tests được dẫn; dùng Get-Content/rg/git rev-parse HEAD/git status. Trace qua codec, runtime result guard, QA và revision acceptance. Không đọc keys/secret files, mở production workspace, gọi live source/provider/submission/wallet hoặc đổi budget/mode.

Fresh safe offline checks:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -m pytest tests/unit/application/test_data_worker.py tests/unit/test_architecture.py -q --tb=short -p no:cacheprovider
```

**79 passed in 2.36s**, không failed/skipped/warning summary. Chỉ baseline tests hiện có, không chứng minh v2 đã implement. Không chạy integration/full suite/Ruff/mypy trong design-only checkpoint; không dùng B.4.1 counts làm fresh verification.

### Git status / files changed

```text
?? docs/audits/phase-b4-2-deliverable-contract-qa-design.md
?? docs/audits/phase-b4-realistic-bounty-simulation.md
```

**File duy nhất tạo trong B.4.2:** report này. B.4.1 có sẵn trước checkpoint, giữ nguyên. Không source/test/config/dependency/ADR changes, không commit/push. Final `git diff --check` exit 0; kiểm tra riêng report: 13 required sections, 0 Unicode replacement characters, 0 trailing-whitespace lines. Git không đưa untracked report vào diff.

Implementation readiness: **GO_PENDING_OPERATOR_DESIGN_APPROVAL**. Recommended next action: operator review các lựa chọn [P] tại mục 12.1; sau approval mới test-first implementation. Tiếp tục SCOUT_ONLY, AI budget $0; không bắt đầu code ở checkpoint này.
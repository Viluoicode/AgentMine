# AgentMine — Phase B.3: Discovery Diagnostics Design

> Lưu lại đề xuất thiết kế cuối trong cuộc trò chuyện. DESIGN ONLY: không triển khai code/tests. Kết quả smoke test là bằng chứng do operator cung cấp, không phải live verification do assistant thực hiện trong checkpoint này.

## 1. Kết luận thiết kế

**GO cho chẩn đoán offline từ raw archive hiện có.** Không thay đổi discovery, normalization, eligibility, reward hoặc budget behavior.

Đề xuất nhỏ nhất là một lệnh đọc lại các capture được operator chỉ định, trả về:

- Feed có trả về dữ liệu hay không.
- Listing nào chuẩn hóa được.
- Listing nào bị quarantine và lý do.
- Bằng chứng nào thiếu, hỏng hoặc mâu thuẫn.
- Phạm vi quan sát còn UNKNOWN.

**Không tự quét archive rồi ghép list/detail theo timestamp.** Archive hiện chưa có discovery-run manifest để chứng minh những capture đó thuộc cùng một lần chạy.

Checkpoint này chỉ thiết kế. Không sửa source/tests, chạy live API, gọi provider hoặc commit/push. Việc lưu đề xuất chỉ thêm file tài liệu này.

## 2. Hiện trạng và nguyên nhân thiếu visibility

Đã kiểm tra repository tại commit:

`fa1928b78f9ea43509501c6a1cb905af0cba426e`

Luồng hiện tại:

```text
SuperteamOpportunitySource.inspect()
  → đọc list và detail
  → lưu raw trước khi parse
  → tạo NormalizationResult cho từng listing
  → tạo DiscoveryReport gồm items/issues và normalized batch

SuperteamOpportunitySource.discover()
  → chỉ trả DiscoveryReport.batch

Application ingestion
  → chỉ lưu OpportunityObservation đã chuẩn hóa được
```

Điểm mất visibility nằm tại [superteam.py:102](../../src/agentmine/infrastructure/marketplaces/superteam.py#L102): `discover()` chỉ trả `.batch`, nên per-listing normalization issues không tới application inventory.

Các trường hợp `bounty`, `USDC`, missing fields vẫn có raw evidence nhưng không có Opportunity để hiển thị. Đây là **quarantine**, không phải kết luận Domain `INELIGIBLE`.

Bằng chứng liên quan:

| Thành phần | Hiện trạng |
|---|---|
| [superteam.py:34](../../src/agentmine/infrastructure/marketplaces/superteam.py#L34) | Infrastructure DiscoveryReport có items và issues |
| [superteam_normalization.py:143](../../src/agentmine/infrastructure/marketplaces/superteam_normalization.py#L143) | Unsupported listing trả observation=None kèm issues |
| [raw_archive.py:15](../../src/agentmine/infrastructure/marketplaces/raw_archive.py#L15) | Capture giữ route, timestamp, body và digest reference |
| [operator_cli.py:435](../../src/agentmine/presentation/operator_cli.py#L435) | Discovery output chỉ đếm observations đã qua normalization |
| [superteam_smoke.py:22](../../src/agentmine/bootstrap/superteam_smoke.py#L22) | Smoke có summary quarantine nhưng không có offline per-listing readback |

**Giới hạn quan trọng:** raw archive giữ từng response, chưa giữ quan hệ durable giữa toàn bộ capture của một discovery run. HTTP failures cũng không được lưu như successful response captures.

## 3. Diễn giải smoke result mới

Kết quả operator cung cấp:

```text
read_succeeded
unique_listings=0
normalized=0
quarantined=0
duplicates=0
normalization_issues=[]
```

Theo implementation hiện tại, kết quả này phù hợp với **list response rỗng của lần đọc đó**, không phải lỗi normalization.

Tuy nhiên:

- Đây là bằng chứng do operator cung cấp, chưa được đọc lại từ archive trong checkpoint này.
- Chưa có list_capture, timestamp và request limit trong thông tin được cung cấp.
- Không chứng minh toàn marketplace không có bounty.
- Không xác minh detail contract vì không có listing để fetch detail.

Khi có exact list capture chứa `[]`, diagnostic có thể xác nhận **EMPTY_FEED cho response đó**, đồng thời giữ **UNKNOWN_COVERAGE**.

## 4. Interface tối thiểu

### CLI đề xuất

Một module riêng, không khởi tạo operator workspace:

```powershell
python -m agentmine.bootstrap.discovery_diagnostics `
  --archive ".tmp/superteam-smoke.sqlite3" `
  --list-capture "raw:sha256:..."
```

Khi cần inspect listing:

```powershell
python -m agentmine.bootstrap.discovery_diagnostics `
  --archive ".tmp/superteam-smoke.sqlite3" `
  --list-capture "raw:sha256:..." `
  --detail-capture "raw:sha256:..."
```

`--detail-capture` có thể lặp lại, với giới hạn số lượng rõ ràng.

Các ID trong ví dụ là placeholder. Lệnh chỉ được triển khai sau approval.

### Vì sao dùng module riêng?

Bootstrap operator hiện compose workspace repositories. Diagnostic chỉ cần archive nên không nên:

- Mở hoặc khởi tạo workspace database.
- Resolve budget ledger.
- Đọc API key.
- Construct HTTP/LLM client.
- Có tùy chọn --live.

Module này vẫn theo Clean Architecture:

```text
Presentation CLI
    → InspectDiscoveryDiagnostics
        → DiscoveryDiagnosticsReader port
            ← SQLite/raw-archive infrastructure adapter
```

Không cần Domain model mới, workflow framework hoặc database table mới.

### Application contracts đề xuất

| Contract | Trách nhiệm |
|---|---|
| DiscoveryDiagnosticRequest | Exact list capture reference và bounded detail references |
| DiscoveryDiagnosticReport | Tổng hợp bằng chứng, counts, coverage và diagnostic findings |
| ListingDiagnostic | Listing identity, capture references, timestamps, disposition và issues |
| Typed diagnostic enums | Phân biệt dữ liệu, incomplete evidence và errors |

Port duy nhất:

```text
DiscoveryDiagnosticsReader.inspect(request)
    → DiscoveryDiagnosticReport
```

Use case InspectDiscoveryDiagnostics kiểm tra invariants và trả report; không ingest Opportunity.

Infrastructure dùng lại pure normalization function hiện có, rồi chuyển kết quả sang application DTO. Không đưa Superteam NormalizationResult hoặc SQLite types vào Application.

## 5. Semantics của các trạng thái

Không dùng một enum duy nhất cho cả feed, listing và coverage: một response có thể đồng thời chứa NORMALIZED, QUARANTINED và UNKNOWN_COVERAGE.

| Nhãn | Điều kiện | Không được diễn giải thành |
|---|---|---|
| **EMPTY_FEED** | Exact list capture hợp lệ chứa array rỗng | Không có cơ hội trên toàn marketplace |
| **NORMALIZED** | Retained detail hợp lệ, identity khớp, normalizer hiện tại tạo observation | Đã lưu vào inventory, eligible hoặc được phép execute |
| **QUARANTINED** | Detail hợp lệ nhưng normalizer trả unsupported/unknown issue codes | Domain INELIGIBLE hoặc API failure |
| **PARTIAL_FAILURE** | Một phần evidence được inspect thành công, phần khác có lỗi xác định như malformed/corrupt capture | Chứng minh API run trước đó bị timeout |
| **UNKNOWN_COVERAGE** | Không có bằng chứng completeness của source traversal | Có next page hợp lệ hoặc feed chắc chắn chưa hết |

Bổ sung classification cho evidence:

- MISSING_CAPTURE
- INVALID_CAPTURE
- IDENTITY_CONFLICT
- DETAIL_NOT_PROVIDED

**Thiếu detail không tự chứng minh một network failure.** Báo INCOMPLETE_EVIDENCE, giữ API-run outcome UNKNOWN; không biến nó thành QUARANTINED.

Nếu list capture không đọc được, diagnostic fail bằng typed error. Tuyệt đối không trả EMPTY_FEED.

### Counts phải có scope

Nên hiển thị:

- raw_row_count
- unique_listing_count
- duplicate_row_count
- normalized_count
- quarantined_count
- unresolved_count

Chỉ tính số khi evidence đủ. Không biến unavailable count thành 0.

Với list hợp lệ, toàn bộ identities phân giải được:

```text
unique_listing_count
  = normalized_count + quarantined_count + unresolved_count
```

Identity conflict phải được báo riêng; không ép dữ liệu mâu thuẫn vào đẳng thức bằng cách đoán owner.

## 6. Evidence và read-only safeguards

Mỗi listing giữ, khi có bằng chứng:

| Field | Nguồn |
|---|---|
| External listing ID và slug | Exact list/detail payload |
| List observation timestamp | List RawCapture |
| Detail observation timestamp | Detail RawCapture |
| List/detail raw references | Verified archive references |
| Normalization issue codes | Existing normalizer |
| Diagnostic version | Phiên bản projection để phân biệt recomputation |

Không gộp hai timestamps thành một giá trị giả.

Các quy tắc bắt buộc:

1. Kiểm tra capture digest bằng cơ chế hiện có.
2. Detail route, ID và slug phải khớp listing.
3. Không dùng detail mới nhất hoặc proximity timestamp để ghép tự động.
4. Capture được operator chỉ định chỉ là **selected evidence set**, chưa chứng minh cùng discovery run.
5. Hiển thị rõ recomputed_with_current_normalizer; không khẳng định đó là kết quả normalization lịch sử.
6. Không dump raw description/body mặc định; chỉ bounded, escaped metadata và issue codes.
7. Không tạo Opportunity, evaluation, eligibility decision hoặc revenue.
8. Không gọi source.inspect() trong diagnostic vì phương thức đó thực hiện HTTP và archive writes.

### SQLite phải thực sự read-only

[RawArchive.get() hiện tại:54](../../src/agentmine/infrastructure/marketplaces/raw_archive.py#L54) dùng sqlite3.connect(path), có thể tạo file nếu path chưa tồn tại.

Đề xuất sửa read path sang SQLite mode=ro:

- Archive phải tồn tại.
- Không CREATE TABLE, migration hoặc initialization.
- Không tạo database khi sai đường dẫn.
- Không dùng immutable=1 để bỏ qua khả năng archive đang được ghi.
- Đọc evidence trong một read transaction nhất quán.
- Giới hạn số capture và bytes xử lý.

save() giữ nguyên behavior.

## 7. Exact files cho implementation tiếp theo

### Thêm mới

| File | Nội dung |
|---|---|
| src/agentmine/application/contracts/discovery_diagnostics.py | Immutable DTOs và typed classifications |
| src/agentmine/application/ports/discovery_diagnostics.py | Read-only reader port |
| src/agentmine/application/use_cases/discovery_diagnostics.py | Focused inspection use case |
| src/agentmine/infrastructure/marketplaces/discovery_diagnostics.py | Archive decoding, identity validation, normalization projection |
| src/agentmine/presentation/discovery_diagnostics_cli.py | Argument parsing và safe rendering |
| src/agentmine/bootstrap/discovery_diagnostics.py | Offline-only composition |
| tests/unit/application/test_discovery_diagnostics.py | Report invariants/use case |
| tests/contract/test_discovery_diagnostics.py | Synthetic payload projection |
| tests/integration/test_discovery_diagnostics_cli.py | File-backed archive, CLI và read-only guarantees |

### Sửa có giới hạn

| File | Thay đổi |
|---|---|
| src/agentmine/infrastructure/marketplaces/raw_archive.py | Read-only capture access |
| docs/superteam-source.md | Diagnostic command và evidence limitations |

**Không cần sửa** Domain, OpportunitySource, OpportunityBatch, discovery ingestion, normalizer rules, operator dashboard, budget hoặc submission.

## 8. Test plan

Viết acceptance tests thất bại trước production changes.

| Case | Expected |
|---|---|
| Synthetic valid fixed project | NORMALIZED; không persist Opportunity |
| Synthetic type=bounty | QUARANTINED + REWARD_MODEL_UNSUPPORTED |
| Synthetic token=USDC | QUARANTINED + REWARD_ASSET_UNSUPPORTED; không USD conversion |
| Bounty + USDC | Giữ cả hai issue codes |
| Exact empty list capture | EMPTY_FEED, zero observed counts, UNKNOWN_COVERAGE |
| Mixed normalized/quarantined | Counts và per-ID reasons chính xác |
| Duplicate ID/slug | Đếm raw duplicates; không duplicate listing |
| Conflicting ID/slug | Typed identity conflict; không chọn owner |
| Missing detail | INCOMPLETE_EVIDENCE; không giả API timeout |
| Một detail malformed, detail khác hợp lệ | PARTIAL_FAILURE trong diagnostic; giữ kết quả hợp lệ và lỗi |
| Corrupt digest hoặc invalid JSON | Typed error; không empty success |
| Detail unrelated/changed identity | Reject association |
| Capture khác thời điểm | Giữ timestamps riêng; không claim same run/freshness |
| Missing archive/table | Không tạo file/schema |
| Repeated inspection | Cùng kết quả cho cùng evidence và diagnostic version |
| Unknown fields | Giữ archive nguyên byte, không execute content |
| Malicious text/control characters | Safe output, không raw-body dump |
| Zero external effects | HTTP/LLM/submission factories không được gọi; không đọc key |
| Read-only persistence | Archive/workspace/ledger không đổi; không tạo workspace |

Regression cần chạy sau implementation:

- Existing Superteam normalization/source/smoke tests.
- Workspace discovery và operator CLI compatibility.
- Architecture tests.
- Full pytest, Ruff, format, strict mypy và git diff --check.

**Checkpoint thiết kế này không chạy lại tests**; các kết quả B.1/B.2 không được báo thành verification mới.

## 9. Acceptance criteria và risks

Implementation được chấp nhận khi:

- Operator đọc được exact empty response và quarantine reasons từ retained evidence.
- Listing ID, timestamps, raw references và issue codes không bị mất hoặc phát sinh giả.
- NORMALIZED được ghi rõ là normalization compatibility, không phải inventory/eligibility.
- Missing/corrupt evidence không thành EMPTY_FEED.
- Coverage luôn phản ánh giới hạn; không claim toàn marketplace.
- Inspection không thay đổi bất kỳ financial/lifecycle state nào.
- Không có dependency hoặc provider mới.

Risks còn lại:

| Risk | Cách giới hạn |
|---|---|
| Archive thiếu discovery-run correlation | Không tự reconstruct run; chỉ selected evidence set |
| Không có persisted HTTP error | Không suy đoán historical failure |
| Normalizer thay đổi theo thời gian | Ghi diagnostic version và recomputation semantics |
| Path sai tạo DB | SQLite read-only open |
| Nhiều detail cho cùng ID | Fail conflict, không chọn bản mới nhất |
| Raw chứa dữ liệu nhạy cảm/untrusted | Bounded metadata-only output mặc định |
| Operator hiểu UNKNOWN_COVERAGE là lỗi | Giải thích riêng coverage và response outcome |

## 10. GO / NO-GO

**GO** cho implementation offline diagnostic theo phạm vi trên.

**NO-GO** cho tự động ghép capture thành discovery-run history, durable run journal mới, live API calls, reward enablement hoặc thay đổi eligibility/budget.

Smoke result rỗng hiện tại không cần sửa để tạo cơ hội. Phần cần cải thiện là khả năng giải thích chính xác **đã quan sát gì, bị chặn vì sao và chưa biết điều gì**.

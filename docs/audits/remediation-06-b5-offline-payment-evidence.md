# F03-B5: Offline Payment Evidence Foundation

Date: 2026-11-01, Asia/Bangkok.
Base commit: `bc00cbb1a90d5cab34884298950e81a40cff5195`.
Starting worktree: clean.
Verdict: **PASS_WITH_LIMITATIONS - provisional offline evidence only**.

## Scope, inventory and decision

Read AGENTS.md, Product Constitution, F03-A through B4, ADRs 0029-0031, original
F03/F07/F08/F09 findings and current Domain payment, legacy settlement, capture,
handoff, outcome, SQLite and metrics implementation. Source remains authoritative.

B1 already stores OPERATOR_REPORTED/UNVERIFIED PAYMENT_REPORT captures; B2 retains
immutable exact submission scope and sticky handoff ownership; B3 retains Outcome
identity. Legacy VerifyPayment consumes PaymentVerificationResult histories and an
injected PaymentVerifier. It does not turn raw B1 reports into payment proof.
B4 selects no real provider, asset/network, recipient, amount or payout obligation.

B5 adds only provisional report identity, frozen binding, capture attachment and
read-only diagnostics. It introduces **no payment verifier or Domain PaymentEvidence,
no settlement expectation, no monetary credit ownership and no PAID path**. No
actual settlement values are inferred from listings, potential/accepted rewards,
fixtures or hints. No financial metric is rewritten. No dependency installed/added,
no AWS or network capability enabled, no commit or push.

## Changed files

New paths under `src/agentmine/`:

- `application/contracts/payment_evidence.py`: PaymentReportRequest input DTO,
  immutable PaymentReport/PaymentObservation, PaymentEvidenceView/Status and typed
  report conflict errors. No VERIFIED/PAID status exists.
- `application/ports/payment_evidence.py`: narrow prepare/attach/inspect repository
  port, explicitly no credit/verifier behavior.
- `application/use_cases/payment_evidence.py`: RecordPaymentEvidence and
  GetPaymentEvidence, with trusted actor/ledger and original context resolution.
- `infrastructure/sqlite/payment_evidence.py`: same-workspace immutable report,
  B1 capture attachment, snapshot/lineage checks and consistent read projection.
- `presentation/payment_evidence_cli.py`: bounded record/show/status commands and
  explicit unverified/unavailable result/error views.
- `bootstrap/payment_evidence.py`: real SQLite composition; no provider factory.

Updated: `bootstrap/operator.py`, `presentation/submission_context_cli.py`,
`infrastructure/snapshots.py`. Appended services/defaults preserve prior constructors
and command behavior. New contracts are explicitly allowlisted by SnapshotCodec.

Other files: `tests/integration/test_payment_evidence.py`,
`docs/adr/0032-provisional-payment-evidence-foundation.md`, `docs/adr/README.md`,
and this report. Domain, legacy VerifyPayment/PaymentVerifier, existing journals,
financial calculations and prior ADR contents are unchanged. No schema DDL migration.

## Contracts and trust boundary

PaymentReportRequest contains a stable report ID, original handoff ID, applicable
Outcome evidence ID or explicit None, bounded raw capture/digest/provenance, observed
time, optional reported event time and nullable transaction/URL/asset/network/
recipient/amount hints. The amount is an opaque reported string, not Money/Decimal
or an authorized obligation. Unknown settlement fields are not guessed; even supplied
hints leave actual asset/network/recipient/amount and payout obligation UNKNOWN.

PaymentReport is built by Application from the retained applied B2 receipt and the
authoritative Versioned Opportunity. It freezes handoff, envelope/scope, marketplace
account, channel/listing, actor/ledger, exact Submission/Deliverable version and
applicable Outcome. The caller supplies no replacement snapshot, account, version,
Outcome object, Budget or authority. Existing Outcome ID must match; None is not a
wildcard for a later Outcome. Reports may also bind a submitted context with no
Outcome, without fabricating acceptance.

PaymentObservation binds the original report ID to existing B1 metadata, fixed to
PAYMENT_REPORT / OPERATOR_REPORTED / UNVERIFIED. There is no authenticated observing
source or provider event identity; transaction hints are not promoted into either.
Server preparation/capture timestamps are retained. Unknown event time stays None.
Contracts are versioned; raw bytes/text and bounded digest are validated without
opening URLs or following task instructions.

No B5 object converts to authoritative Domain PaymentEvidence, constructs a verified
Reward, calls Domain.verify_payment or accesses a PaymentVerifier. Production and
tests exercise the same provisional-only B5 path. The test-only authority used to
prepare an accepted parent belongs to the existing B3 test fixture, not B5 or
production composition. There is no environment/CLI/config selector for it.

## Immutable identity and transaction design

New snapshot kinds are `provisional_payment_report` and
`provisional_payment_observation`, keyed only by report ID. Hints have no uniqueness
index or credit owner. The same transaction hint can be reported without creating
rights over money. Existing `payment_observation` remains a different typed journal.

All new write operations use BEGIN IMMEDIATE on the same authoritative SQLite file.

1. Prepare resolves and compares the original applied B2 receipt, stored Submission,
   exact account/scope, actor/sole ledger, existing Outcome and current snapshot.
   It persists the immutable report/body/digest before capture. Existing unowned or
   legacy capture IDs cannot be adopted. Concurrent equal preparation retains the
   first prepared timestamp; every other field must match.
2. Capture reuses B1's atomic metadata/body mechanism. Metadata fields and reported
   content are fixed; the first server capture timestamp wins on identical retries.
   No user-provided timestamp becomes the server capture time.
3. Attach validates the original report, exact B1 metadata/body/digest and retained
   lineage, then checks current snapshot again within the write transaction. Only
   the immutable provisional observation is inserted. No financial/lifecycle write.
4. Inspect uses one read transaction to check source snapshot, stored Submission,
   scope/account/Outcome links and metadata/body integrity. It never repairs state.

Freezing the report before capture prevents a crash retry from reinterpreting old
text under a newly applied Outcome. A stale pending report/capture remains blocked
and inspectable, not rebound. A completed same-ID retry is historical readback;
current context changes may produce CONFLICT while original rows remain unchanged.
Changed payloads fail rather than silently updating text, hints or context.

### Transaction and recovery matrix

| Failure/checkpoint | Durable state and allowed recovery |
| --- | --- |
| Prepare write interrupted | Whole report write rolls back; MISSING; original ID may retry |
| Prepared, capture not committed | CAPTURE_PENDING; original frozen context/body preserved; retry same ID |
| Failure at either B1 capture write | Metadata/body transaction rolls back together; prepared report remains |
| Capture committed, attachment interrupted | CAPTURE_RETAINED; original metadata/time/body retained; same-ID attach retry if snapshot still valid |
| Observation write interrupted | Observation transaction rolls back, capture retained; no financial state affected |
| Lost acknowledgement after attachment | Original observation/time returns; no duplicate capture or monetary record |
| Concurrent identical writes | Equal immutable data/first timestamps converge; no duplicate report observation |
| Same ID, changed capture/hints/binding | CONFLICT; old evidence preserved; no replacement ID to repair authority |
| Wrong actor/ledger/account/version/submission/Outcome | Rejected before new attachment; no state/budget/cost changes |
| Outcome/current revision changes during capture | Pending attachment blocked, capture retained; status CONFLICT; no guessed rebinding |
| Missing body/Outcome or conflicting digest/lineage | MISSING/CONFLICT projection or structured invalid-evidence failure; no automatic repair |
| Completed historical inspection/retry | Original evidence remains read-only; changed current snapshot is diagnostic, not permission |
| Existing legacy payment capture/proof | Not adopted, migrated or reclassified by B5 |

This is local application-exception/write-fault recovery, not a power-loss,
multi-authority restore or generic F08 reconciliation certification. Host/store and
existing protected local filesystem are trusted. Hashes detect consistency, not
provider origin or hostile authorized database rewriting.

## Inspection CLI and unknown facts

Executed real help:

```powershell
.\.venv\Scripts\python.exe -m agentmine.bootstrap.operator submission payment --help
```

Observed exit 0, exactly `record`, `show`, `status` (no verify/apply/PAID operation).
For an existing authoritative workspace/ledger/operator, command suffixes are:

```text
submission payment record --handoff-id handoff-1 --evidence-id payment-report-1 --inputs report.json
submission payment show --evidence-id payment-report-1
submission payment status --evidence-id payment-report-1
```

These are syntax examples, not real settlement evidence. Record requires the
existing trusted local actor. Report JSON allows only observed_at, provenance,
text, optional event_at/outcome_id and the six explicitly named *_hint fields.
For an applicable Outcome, outcome_id must be its exact evidence reference; no
Outcome means omission/null. Caller-supplied account, version, trust, verified,
asset selection, payment amount or Budget fields are rejected.

Existing strict JSON parser imposes a 64,000-byte input limit and rejects duplicate/
unknown fields and non-JSON constants. URL hints follow existing conservative HTTPS
validation and are never fetched. Capture/hint validation rejects recognizable
secret material; text is untrusted data, never instructions.

Every B5 evidence result and handled error explicitly displays:

- reported payment versus independently_verified_payment=false;
- OPERATOR_REPORTED / UNVERIFIED trust;
- settlement identity and actual asset/network/recipient/amount UNKNOWN;
- missing/conflicting state and capture/attachment checkpoint where available;
- current_paid_authority=UNAVAILABLE, verified_revenue_created=false.

On errors, reported_payment is UNKNOWN rather than inferring no commit from a failed
acknowledgement; messages contain no raw exception/capture/credential content.
Existing global startup/argparse help/errors remain their established CLI boundary,
not evidence or settlement results. Displayed source Outcome/marketplace account is
lineage context, not an authorized settlement recipient or payment amount.

## Legacy containment and architecture

Legacy VerifyPayment reads PaymentVerificationResult from `payment_observation`,
not `provisional_payment_observation` or raw `submission_evidence`/capture rows.
Tests run legacy VerifyPayment against the same SQLite workspace with an explicitly
unavailable test verifier: provisional B5 text/hashes cannot produce payment or
revenue. This does not certify arbitrary trusted caller-supplied legacy verifiers;
B4's real-verifier/proof/canonical-ownership enablement gaps remain open.

Protected-row comparisons verify no B5 changes outside its two journals and B1
capture kinds: Opportunity/lifecycle, budget, actual costs/audit, commitments, released
identities, B2 claims/owners, Outcome and existing financial histories remain unchanged.
Spies additionally prohibit both legacy VerifyPayment.execute and Domain.verify_payment
during B5 reporting. Network/socket guards prohibit external I/O in automated tests.
No signing, wallet, submission, AWS or paid provider object is composed.

Presentation invokes use cases and displays typed results. Application depends only
on ports/Domain; SQLite implements storage/capture consistency. No vendor/SDK or
schema semantics leak into Domain. No generic transaction framework, new payment
lifecycle or financial reporting rewrite. ADR 0032 records the bounded decision.

## Test-first and executed verification

Before production changes:

```text
python -m pytest tests/integration/test_payment_evidence.py -q --tb=short -p no:cacheprovider
```

Observed: expected ModuleNotFoundError for the new application contract (1 collection
error in 0.28s). This proves the missing capability, not that every later case was
red independently before implementation.

A later review identified missing safety labels on CLI error results. Test-first:

```text
python -m pytest tests/integration/test_payment_evidence.py -k cli_error_outputs -q --tb=short -p no:cacheprovider
```

Observed **2 failed, 35 deselected in 8.81s**, both KeyError on the missing
independently_verified_payment field. The focused presentation fix makes missing
input and wrong-Outcome errors carry the same unverified/unavailable labels. It
does not change Domain or grant authority.

Tests use a clearly isolated test template populated once by real DataWorker,
DeliverableQA, approval, B2 and B3, with explicit FakeSource/FakeClock and B3 test-only
authority. SQLite backup clones isolate each test; no synthetic data enters a
production workspace. All reported payment facts remain absent or explicit test
hints. Fixtures never select an actual payout asset/network/recipient/amount.

Interim runs: 23 B5 cases passed; broader selections passed 89 then 90 cases before
the final error-label correction. Final focused selection after that correction:

```text
python -m pytest tests/integration/test_payment_evidence.py tests/unit/test_architecture.py tests/unit/domain/test_payment_tracking.py tests/unit/application/test_outcome_payment.py tests/integration/test_outcome_payment_sqlite.py -q --tb=short -p no:cacheprovider
```

**92 passed in 43.16s**, exit 0: 37 B5 cases, 29 architecture cases and 26 existing
financial regressions. Cases include accepted/absent Outcome lineage, wrong identity,
unknown facts/no reward conversion, payload/ID conflicts, concurrent equal writes,
original-ID recovery, capture/attach crashes and lost acknowledgement, stale context,
missing body/Outcome, historical readback, legacy containment, strict CLI and no
payment/network authority.

One earlier full-suite process was deliberately interrupted before completion to
correct the reproduced CLI error-label issue. It is **not counted as passed**.
The completed final full-suite result is recorded below separately from focused
counts. It runs F01/B1/B2/B3/F04/F05/runtime/QA/budget/financial regressions unchanged.
No previous B3 run is represented as B5 verification. Logs are under ignored `.tmp/`:
`f03-b5-final-focused.log` and `f03-b5-final-full.log`.

Static checks executed after the correction: Ruff check passed; strict mypy found
no issues in 263 source files. Format/diff/report checks and final full-suite result
are recorded below. No unexecuted command is counted as passed.

## Limitations and operator boundary

- All reports remain OPERATOR_REPORTED / UNVERIFIED. B5 cannot authenticate a
  provider, statement, transaction hash or real settlement, even with complete hints.
- No authorized provider, asset/network/recipient/amount/payout obligation exists;
  B4 decisions remain open. Real PAID/verification is not implemented or enabled.
- No FX, partial/multiple-payment aggregation, credit ownership, conditional PAID,
  financial reporting rewrite, signing/transfer, account mutation, live submission
  or AWS. No change to F09 cost-completeness semantics.
- Stale/incomplete/corrupt evidence is inspectable or fails closed; no generic F08
  repair, rebinding, release, migration or authority upgrade.
- No operator credentials or action are needed for offline tests. This checkpoint
  neither asks for a real transaction nor certifies earnings/production readiness.

No commit or push. No real payment verifier or conditional PAID checkpoint started.
Stop for operator review after final verification.


## Final verification and verdict

Commands use `.venv/Scripts/python.exe`:

| Check | Executed result |
| --- | --- |
| Completed final full suite: `-m pytest -q -ra --tb=short -p no:cacheprovider` | **1476 passed in 724.55s (12m04s), exit 0**, no skips reported |
| Final focused selection above | **92 passed in 43.16s**, exit 0 (37 B5 + 29 architecture + 26 financial regressions) |
| `-m ruff check .` | All checks passed |
| `-m ruff format --check .` | 353 files already formatted |
| `-m mypy --strict` | Success: no issues in 263 source files |
| `git diff --check` | Exit 0; only existing Windows LF/CRLF conversion notice for ADR index |
| New report/ADR whitespace and fenced-block checks | Passed |
| Real `submission payment --help` | Exit 0; record/show/status only |

The full and focused results are separate runs, not summed. No production/test code
changed after the final full suite started. It includes F01 cancellation, F03-B1/B2/B3,
F04 eligibility, F05 rework, existing runtime/QA/budget and financial regressions.
The interrupted pre-correction full run is not represented as a passing invocation.

| Acceptance gate | Result |
| --- | --- |
| Exact retained submission/version/account and accepted or absent Outcome | PASS; original context frozen, wrong identity rejected |
| Missing asset/network/recipient/amount remains unknown | PASS; no conversion/selection from potential or accepted reward |
| Same-ID immutable retry, conflicts and concurrent equal writes | PASS; original report/capture/observation/time retained |
| Report/capture/attachment crashes and lost acknowledgement | PASS; original-ID recovery with no lifecycle or financial write |
| Stale/unrelated Outcome, missing capture/canonical Outcome | PASS containment; typed missing/conflict diagnostics and preserved evidence |
| Historical readback/retry | PASS; no row mutation or rebinding |
| Legacy verified-payment path cannot consume B5 records | PASS; separate typed journal, explicit unavailable verifier test |
| CLI unknown/unverified/unavailable labels including handled errors | PASS; no verify/authority flag or financial override input |
| No provider/network/signing/transfer/PAID/revenue or protected-row mutation | PASS within executed offline evidence and composition |
| Real payment verification / monetary credit | NOT IMPLEMENTED / UNAVAILABLE by approved scope |

**PASS_WITH_LIMITATIONS** for F03-B5's strictly provisional offline foundation.
No real payment, accepted payout amount, asset/network or beneficiary has been
selected or independently verified. Existing Domain/payment lifecycle and financial
reporting are unchanged. No new dependency or Clean Architecture deviation was
introduced. No credentials/operator action were required for offline verification.
No commit or push. No real verifier or conditional PAID implementation started.
Stop for operator review.

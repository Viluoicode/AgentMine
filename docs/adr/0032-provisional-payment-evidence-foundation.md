# ADR 0032: Provisional offline payment reports and immutable capture binding

Date: 2026-11-01
Status: Implemented for approved F03-B5 provisional scope only

## Context

F03-B4 leaves real provider, asset/network, recipient, amount and payout obligation
unselected. Domain PaymentEvidence, PaymentVerifier and PAID already exist, but a
payment report cannot authenticate them. B1 stores provisional PAYMENT_REPORT
captures; B2 owns exact handoff/submission scope; B3 retains Outcome identity.
B5 must preserve reported evidence without enabling any financial transition.

## Decision

Application owns PaymentReportRequest (untrusted input), PaymentReport (server-resolved
frozen context), PaymentObservation, PaymentEvidenceView and PaymentEvidenceStatus.
No Domain payment model, lifecycle, provider/verifier, settlement expectation,
monetary credit owner or financial reporting behavior is added.

A report binds the exact applied B2 handoff/envelope/scope, marketplace account,
channel/listing, Submission/Deliverable version, actor/sole workspace ledger and
Versioned Opportunity snapshot, including its applicable Outcome or explicit absence.
For an existing Outcome the caller supplies its evidence reference, never an Outcome
object; it must match the actual retained context. Absence is not a wildcard for a
later Outcome. New reports require current exact context; old observations remain
historical and do not overwrite later state.

PaymentReportRequest contains bounded text/digest, provenance, observed time,
optional reported event time and optional transaction/URL/asset/network/recipient/
amount hints. Hints are opaque reported strings: never decoded into a Money, asset,
recipient authorization, actual amount or payment ID. No fields default from a
potential/accepted reward or a fixture. URLs are metadata, never fetched.

All evidence remains OPERATOR_REPORTED / UNVERIFIED. Unknown settlement facts stay
UNKNOWN even when hints are provided. PAID authority is always UNAVAILABLE. There
is no verifier selection, provider configuration, environment override, verify/apply
command or test-only payment verifier in production composition.

## Transactions and recovery

Use the same authoritative SQLiteDatabase and explicit snapshot codec allowlist.
New kinds are `provisional_payment_report` and `provisional_payment_observation`,
not legacy `payment_observation`. No DDL migration or dependency is required.

1. Prepare: BEGIN IMMEDIATE validates original retained B2 receipt/submission,
   account/scope, actor/ledger and exact current Opportunity/Outcome, then stores
   the immutable report including original body and digest. Preparation grants no
   monetary ownership. Existing unowned/legacy capture IDs are not adopted.
2. Capture: reuse B1's atomic metadata/text persistence with fixed PAYMENT_REPORT,
   OPERATOR_REPORTED, UNVERIFIED and no authenticated event/source. Server capture
   time is retained on identical retries. Missing event time remains None.
3. Attach: BEGIN IMMEDIATE compares original report, exact metadata/capture, current
   context and retained lineage; inserts the immutable provisional observation.
   No Opportunity, budget, cost, payment, revenue or existing claim is written.
4. Inspect: one read transaction checks capture/body/digest, current snapshot and
   retained submission/account/Outcome/scope links. View status is MISSING,
   CAPTURE_PENDING, CAPTURE_RETAINED, UNVERIFIED or CONFLICT. Settlement identity
   remains UNKNOWN. Reads never repair or dispatch.

A failed capture leaves the original prepared report. A successful capture followed
by failed attachment remains CAPTURE_RETAINED and can retry the original ID/context.
Stale context blocks pending attachment and remains inspectable; it is never rebound.
A completed identical retry returns original historical evidence with current
conflict diagnostics where appropriate, without rewriting rows. Same-ID changed
payloads conflict. Concurrent equal writes return first retained timestamps.
No hint index reserves a transaction or recipient; canonical monetary ownership
remains a separately approved future checkpoint.

## Presentation, containment and limits

CLI adds only `submission payment record/show/status`. B5 evidence results and
handled errors explicitly distinguish reported evidence, independent verification,
unknown actual identity/amount, missing/conflicting evidence and unavailable PAID
authority. Error output does not infer that a failed acknowledgement means no report
exists. Existing global startup/argparse boundaries remain unchanged.

RecordPaymentEvidence depends on evidence ports, original handoff read, existing
capture use case and Clock. GetPaymentEvidence enforces actor/ledger binding.
Bootstrap composes real SQLite only; no PaymentVerifier dependency or factory exists.
Domain remains vendor-neutral and unchanged; Presentation parses/delegates/projects.

Legacy VerifyPayment reads PaymentVerificationResult from `payment_observation`,
not these new records or B1 raw captures. B5 creates no authoritative PaymentEvidence
and never calls Domain.verify_payment. Legacy behavior is not redesigned or certified
as a live payment lane by this checkpoint. Reconciliation, corrupted-store repair,
provider contracts, real asset/network, FX, aggregation, conditional PAID and complete
financial accounting remain excluded. Trusted local host/store and existing capture
access/retention controls remain necessary; hashes are consistency, not origin proof.

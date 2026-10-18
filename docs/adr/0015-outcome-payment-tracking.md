# ADR 0015: Independent settlement evidence and derived economic metrics

Status: Implemented for the requested Milestone 5C scope.

## Context

Existing domain separates acceptance and payment, but a Reward stage/evidence reference is
not a structured settlement record. Pending payment checks are not retained, rejection
reasons and payment timestamps are missing, and verified receipts lack retry journals.

## Decision

Require explicit PaymentEvidence for verified-payment domain transitions and application
results. Bind reward, external payment ID/time, independent source/method and verification
record; keep actual verification behind PaymentVerifier. Add rejection reasons and retain
all outcome/payment observations through the existing SubmissionRepository. SQLite atomically
rejects conflicting final evidence and duplicate source/payment IDs across submissions.

Persist resolved evidence before aggregate updates and reuse it on retries. Calculate current
EconomicMetrics from outcome/payment and actual attributed ledger costs on read, rather than
maintaining a separate cache. Preserve forecasts and avoid guessed performance calibration.

## Consequences

Acceptance alone contributes zero revenue. Actual costs remain visible before payment and
can produce negative net value. Unknown payment remains pending/unverifiable. New proof fields
require additive codec handling; pre-5C PAID snapshots without proof fail closed and require
explicit future migration/re-verification. Existing data is never silently reset or assigned
fabricated proof. VerifyPayment gains an explicit submission-repository dependency.

Evidence authenticity is the trusted independent adapter's responsibility. No live verifier,
SDK, AWS resource, wallet action or new dependency is introduced. One payment/outcome,
single-currency metrics and separate repository snapshots remain V1 limitations.

## Alternatives

Treating acceptance or an operator claim as payment corrupts verified revenue. Using polling
time as settlement time invents a financial event. Caching metrics adds write-recovery paths
and can hide late costs. Keeping legacy PAID revenue without independent proof defeats the
new rule. Creating a payment adapter from uncertain source APIs violates project policy.

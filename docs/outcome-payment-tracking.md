# Outcome and Payment Tracking (Milestone 5C)

TrackOutcome observes SUBMITTED work and retains pending/final marketplace observations.
Resolved outcomes become ACCEPTED or REJECTED. Acceptance and settlement are independent:
ACCEPTED has zero verified revenue until VerifyPayment obtains independent evidence and
moves the aggregate to PAID. Forecasts and score remain the original estimates.

## Recorded fields and trust boundary

Opportunity exposes accepted_reward, verified_reward, payment_reference, payment_timestamp
and currency. Accepted reward is optional if the source does not specify it; potential
reward is never substituted. Verified reward can differ from the accepted/potential amount.

PaymentEvidence binds the exact VERIFIED_PAYMENT reward/submission/amount/currency to an
external payment reference, actual settlement timestamp, stable verification source,
verification record and method (independent ledger or payment-provider settlement).
Verification record must match the reward evidence reference. Payment time must not
predate submission or exceed verification observation time; observation time cannot be
in the future. The payment timestamp is not replaced by the polling timestamp.

The injected PaymentVerifier is responsible for actually reading an independent source,
checking the authorized recipient, amount/currency, settlement status and correlation.
Structured evidence records its assertion; an enum/reference cannot independently prove
money moved. There is no production verifier, live financial API or wallet integration in
this milestone. A marketplace acceptance/winner flag, operator claim, LLM assertion or
unverifiable receipt must return PENDING/UNVERIFIABLE with no reward/evidence. Returning
VERIFIED without matching independent evidence fails the contract. Direct domain payment
transitions now require this evidence too; a reward stage label alone is insufficient.

Read-only payment verification does not initiate a transfer or financial account action.
Potential Reward != Expected Value != Accepted Reward != Verified Revenue remains enforced.
Only a PAID aggregate with matching payment evidence contributes to verified revenue.

## Histories, rejection and recovery

SubmissionRepository now retains outcome_history and payment_history, including pending and
unverifiable observations with explanations. Rejection reasons are retained on Outcome,
through SQLite and the aggregate. Missing reasons stay None rather than being guessed;
a rejection reason cannot be attached to an accepted outcome.

Final observations persist before final outcome/payment state changes. A retry reuses retained
resolved evidence after a failed receipt/outcome/aggregate write without re-polling the
provider. Pending/unverifiable checks may be polled again. Identical observation writes
are idempotent; conflicting final outcomes/verified payments fail atomically. A stable
(verification_source, payment_reference) cannot credit two submissions. SQLite protects
this across local connections; trusted adapters must use stable source/payment identities.

VerifyPayment now requires SubmissionRepository explicitly in addition to its previous
opportunity/verifier/clock dependencies. Inject the same repository used for submission and
outcome tracking. Neither Domain nor Application constructs infrastructure implementations.

## Economic metrics

GetEconomicMetrics(opportunities, ledger).execute(opportunity_id, ledger_id) reads current
outcome/payment and attributed actual cost records, returning EconomicMetrics. It derives:

- verified_revenue from independently verified payment only;
- actual AI, tool, infrastructure and transaction costs separately;
- total_actual_cost and net_verified_value = verified_revenue - total_actual_cost;
- outstanding operation identities, kept separate from actual charges.

The opportunity snapshot in the result retains potential/accepted/verified rewards,
original expected value/score, payment fields and rejection reason. Metrics are calculated
from current state on each read, so accepted/rejected/paid outcomes and late cost records
appear without stale cached totals. No forecast is rewritten as an observed fact and no
uncalibrated historical success probability is automatically inferred.

These are recorded-cost metrics, not a claim that every bill has arrived. Outstanding
reservations are estimates, and unmeasured costs may exist even without a reservation.
Rejected/accepted-but-unpaid work can have negative net verified value because costs were
incurred with zero verified revenue. Costs must be explicitly attributed to the opportunity;
unallocated shared costs are not guessed. Cross-currency arithmetic fails explicitly;
no exchange rate/conversion is invented. Opportunity/ledger reads are separate snapshots,
not a cross-repository accounting transaction.

Example: potential USD 100, accepted USD 90 and recorded actual costs USD 1 yield zero
verified revenue and net USD -1 while ACCEPTED. Independently verified USD 85 changes revenue
to USD 85 and net to USD 84. Later recorded costs of USD 9 change net to USD 75 while the
original forecast remains unchanged.

## Persistence compatibility and limitations

SQLite uses the existing snapshot storage and explicit codec allowlist; no dependency or
database DDL is added. Pre-5C non-PAID Opportunity snapshots load with no payment evidence,
and old outcomes load with an unknown rejection reason. Unknown/malformed shapes still fail.
Legacy PAID snapshots without independent proof fail closed with UNSUPPORTED rather than
creating revenue or inventing evidence. Their original bytes remain intact. They require an
explicit future data migration/re-verification workflow; no destructive reset, automatic
downgrade or evidence fabrication is included. Old verified-result snapshots without proof
are also rejected. Back up local files before upgrading; older code cannot read new shapes.

V1 still represents one final outcome and one independently verified payment per submission.
Partial-payment accumulation, payment reversals/refunds, acceptance revisions, currency
conversion, global performance dashboards and historical model calibration are not added.
Independent source/finality/recipient contracts must be verified before a production payment
adapter is implemented. Existing marketplace docs do not establish those settlement contracts.

## Verification and live prerequisites

Tests run offline with fake verifier/gateway and real temporary SQLite files. They demonstrate
ACCEPTED != PAID, potential/accepted rewards != verified revenue, unknown payment staying at
zero, rejection reasons, mismatched proof/currency/time rejection, late-cost metrics,
recovery, evidence rehydration and concurrent duplicate-payment protection.

No user credentials or action are needed for automated tests. A live verification test would
need a verified independent provider/ledger read contract, configured authorized recipient,
read-only access where required, and an actual test payment reference. Credentials must be
configured locally. Do not report a marketplace claim as verified revenue while these
contracts/evidence are unavailable. No live payment or external action ran in this milestone.

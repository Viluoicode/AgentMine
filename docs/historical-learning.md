# Historical Learning Dataset (Milestone 5D)

This milestone retains observations and exposes descriptive statistics. It does not train a
model, update ScoringPolicy, generate a historical SignalEstimate or change ScoreOpportunity.
Capture and reporting are explicit application use cases; importing modules starts no work.

## Capture and provenance

`CaptureHistoricalObservation(opportunities, evaluations, ledger, history, clock).execute(`
`capture_id, opportunity_id, ledger_id, source, task_type=None, classification_evidence=None)`
loads authoritative saved opportunity, discovery observation, evaluation records and budget.
It persists an immutable HistoricalObservation with a per-opportunity sequence and captures:

- supported task type, or explicit unknown, with classification evidence;
- a configured source identity, original source-item reference and discovery time;
- potential reward/currency, subjective predicted probability and full scoring forecast;
- predicted cost, score, recommendation, policy and prediction timestamp/reference;
- attributed actual cost records, recorded total and outstanding operation identities;
- execution-attempt flag, skipped flag/reason, lifecycle state and outcome/rejection reason;
- accepted reward and independently verified reward/payment evidence through the aggregate;
- capture time, opportunity revision, ledger identity/revision and forecast provenance.

`source` is an operator/composition-supplied stable grouping identity, for example the
configured source adapter identity. Existing OpportunityObservation.source_reference identifies
a listing, not a provider. No provider identity is guessed from URLs, ID prefixes or prose.
Once bound, a source, source item and ledger cannot be renamed for that opportunity's history.

Planned tasks supply their task type and task-reference evidence automatically. A skipped
opportunity that never had a plan needs explicit task_type/classification_evidence to join a
Research/Data cohort. Otherwise its task type stays unknown and is counted separately. This
avoids classifying an unplanned listing from its description without a verified rule.

Predictions come from a retained EvaluationRecord matching the aggregate scoring assessment,
created no later than execution start (or capture time for unattempted work). Records after
execution are excluded even if capture happens after the outcome. The first attempted
observation freezes its prediction, including a missing prediction; later backfills cannot
rewrite it. The full assessment keeps subjective probability rationale and scoring policy.
A legacy aggregate's naked score/value is not reconstructed into an invented forecast.

An attempt means execution actually started, not a recommendation, plan, approval or submit
intent. Attempted and skipped can both be true when work was later abandoned. Missing outcome
is not rejection; acceptance is not payment. Verified reward exists only with the existing
PAID/independent-evidence invariant. Potential reward remains a separate field.

Recorded actual total is None if there are no actual records. A recorded zero is known zero
on that recorded-cost basis. Reservations never become actual costs. Costs are attributed
explicitly to opportunity; shared/unallocated costs and currency conversions are not guessed.
Unmeasured costs may still exist even after every recorded reservation settles.

## Sequence, retries and current dataset

HistoricalRepository owns immutable snapshots, append concurrency and latest/as-of reads.
SQLiteHistoricalRepository uses existing local snapshots and an atomic latest pointer.
The immutable observation and pointer advance in one transaction. A failed write rolls back
both; stale concurrent writers conflict. Identical capture-ID retries return the retained
observation. Changed scope/content under an existing ID conflicts. Refreshes use a new capture
ID, advance the sequence and preserve prior observations.

Successors cannot regress opportunity/ledger revisions, lifecycle history or capture time,
drop recorded actual costs, change provenance, reclassify a known task type or rewrite an
attempt's prediction. Equal opportunity/ledger revisions cannot conceal changed snapshots.
Existing storage shapes are unchanged; no migration or new database table is required.

Statistics select one latest observation per opportunity BEFORE applying task/source filters.
Repeated capture, retries, accepted-to-paid updates and late-cost refreshes do not inflate
sample counts. HistoricalQuery supports task_type, source, as_of and exclude_opportunity.
The as_of query selects only snapshots captured by that time; past labels do not gain future
payment/outcome information. Equal capture times use sequence ordering. As-of reconstructs
what was captured, not missing events never captured at their true historical time.

## Descriptive statistics and formulas

`GetHistoricalStatistics(history).execute(query)` returns overall, Research, Data, unknown-task,
source-specific and per-currency cost statistics. Rates are Decimal fractions in [0, 1],
not percentages; 0.5 means 50%. No resolved samples produces None, not 0%.

- attempts: count of latest observations with an execution;
- accepted: attempted observations with ACCEPTED outcome, including PAID work;
- rejected: attempted observations with REJECTED marketplace outcome;
- paid: independently verified paid observations, a subset of accepted;
- acceptance_rate = accepted / (accepted + rejected);
- unresolved_attempts = attempts - accepted - rejected;
- skipped: all latest skipped opportunities, including any skipped after an attempt.

Pending, abandoned-without-outcome and never-attempted work are excluded from the acceptance
rate denominator and reported separately. Skipped opportunities are not labeled failures.
Acceptance rate is not a calibrated probability of eventual payment; paid counts remain
separate. Small samples, selective attempts and unresolved outcomes introduce selection and
censoring bias. No confidence interval or automatic policy recommendation is invented.

Cost statistics expose sample counts so different cohorts are visible:

| Metric | Cohort/formula |
| --- | --- |
| average_predicted_cost | Mean known predicted total across attempted opportunities |
| average_actual_cost | Mean known recorded actual total across attempted, accepted/rejected opportunities with no outstanding reservations |
| cost_prediction_error | Mean(actual - predicted) on the paired actual-cost cohort with both values known |
| mean_absolute_cost_error | Mean(abs(actual - predicted)) on that same paired cohort |

Positive signed error means underestimation; negative means overestimation. Empty cohorts
return None. Unresolved/outstanding actual costs are excluded from actual/error averages;
prediction averages may include attempts with pending outcomes. Never compare these averages
without their predicted_samples, actual_samples and paired_samples. All cost summaries are
separate per currency. Decimal arithmetic uses a local precision context; no conversion or
percentage error with a zero denominator is assumed. These are recorded-cost statistics,
not a guarantee all provider/infrastructure bills have arrived.

## Composition and future scoring interface

Construct SQLiteHistoricalRepository(SQLiteDatabase(path)) explicitly and inject it into
capture/reporting; the existing bootstrap does not silently enable capture. Call capture at
useful boundaries such as skip, execution, outcome, payment and late-cost updates. There is
no background scheduler or automatic backfill of all stored opportunities in this milestone.
Capturing once after completion still preserves the matching stored pre-attempt forecast,
but cannot reconstruct missing past observation times.

Application owns HistoricalPerformance.statistics(HistoricalQuery), implemented by
GetHistoricalStatistics. A future scoring policy can depend on this read-only port, request
a source/task cohort, exclude its own opportunity and set as_of to prevent later-label use.
It receives rates, denominators and unknowns rather than an automatic scoring signal.
Any conversion into a historical-performance estimate requires a separate approved policy.
Production scoring weights, thresholds and historical signals are unchanged.

## Validation and limits

Offline tests cover known numerical cohorts, pending/accepted/paid/skipped states, latest-only
counting, as-of/exclusion, missing predictions/costs/classification, recorded zero costs,
provenance/forecast immutability, post-attempt prediction leakage, SQLite reopen, competing
writers, transaction rollback and currency separation. No dependency, paid call, live source,
ML library or training job is introduced.

Statistics cover explicitly captured opportunities only. Independent source/ledger reads are
separate snapshots, not an atomic transaction across all repositories. The local adapter scans
history for as-of statistics; pagination, exports, retention/deletion, anonymization and large
analytical stores are not added. V1's single execution/final outcome/payment model and trusted
local-store assumptions remain. High-quality evidence does not remove provider-verification
limits or turn subjective predictions into objective truth.

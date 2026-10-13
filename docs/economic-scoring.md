# Economic engine and opportunity scoring (Milestone 2D)

## Economic calculation

`EconomicAssessment` is a pure, immutable Domain calculation:

```
expected gross value = potential reward * predicted success probability
expected net value = expected gross value
                   - estimated AI cost
                   - estimated tool cost
                   - estimated infrastructure cost
                   - estimated transaction cost
```

`EconomicInputs` retains the probability prediction, its rationale/evidence,
four nonnegative cost estimates and cost rationale/evidence. All money must use
one explicit currency. No currency conversion or provider pricing is assumed.
Monetary calculations use finite Decimal arithmetic without currency rounding.
Negative expected net values are meaningful and retained.

Probability is a **subjective forecast**, not a measured fact or guarantee. Its
intended meaning is the likelihood of ultimately receiving the stated potential
reward for this opportunity. It must be a finite Decimal in [0, 1], with a rationale;
unknown probability cannot produce a numeric assessment. Refine the prediction or
keep the opportunity un-evaluated. There is no default probability or LLM call.
Cost estimates must be explicitly supplied, including explicitly estimated zeros.
An unavailable estimate must not be converted to zero.

These forecasts do not create accepted reward, actual cost, budget reservations or
verified revenue. Only evidenced payment and the existing PAID transition create
verified revenue. The North Star uses verified reward and actual costs, not this
forecast. Budget authorization is still a separate policy and ledger operation.

## Initial scoring policy

`ScoringPolicy` requires a version, rationale and positive currency-specific net
value target. There is deliberately no default monetary target. Bootstrap/caller
must supply the value appropriate to its operating objectives. Store the entire
policy snapshot with each assessment; version alone cannot reconstruct a decision.

Each supplied `SignalEstimate` has a Decimal value in [0, 1] or explicit `None`, a
rationale and optional evidence references. They are estimates; evidence references
do not themselves authenticate a source. Inputs have these directions:

| Component | Desirability (0 unfavorable, 1 favorable) | Default weight | Initial rationale |
| --- | --- | ---: | --- |
| Economics | clamp(expected net / net value target, 0, 1) | 40 | Economic value is the largest single component |
| Risk | 1 - risk | 15 | Prefer lower uncertainty/loss exposure |
| Competition | 1 - competition | 10 | Competition is a secondary attractiveness signal |
| Deadline | deadline favorability | 10 | Prefer sufficient delivery time |
| AI suitability | AI suitability | 15 | Prefer work suited to supported AI assistance |
| Historical performance | historical performance | 10 | Allow limited influence from relevant prior outcomes |

```
component points = weight * desirability
score = sum(component points), rounded once to 0.01 using half-even rounding
```

Score arithmetic uses an independent 50-digit Decimal context. Money calculations
remain separate. Positive finite Decimal weights must sum exactly to 100. Thresholds
must be finite and ordered within [0, 100]. The defaults are explicit engineering
heuristics, not statistically fitted coefficients. They prioritize economics while
retaining capability/risk constraints. All weights and thresholds are configurable.

A missing signal stays `None`; its points are zero, and its weight is not
redistributed. This is a conservative score contribution, not an assertion that the
unknown signal is bad or known. Any missing signal caps recommendation at WATCH
(unless expected net is nonpositive, which takes precedence). In particular, no
history means unknown historical performance, not an invented success rate.

## Recommendations and explanations

Rules apply in this order to the stored, rounded score:

| Condition | Recommendation | Machine-readable reason |
| --- | --- | --- |
| Expected net <= 0 | REJECT | NONPOSITIVE_EXPECTED_NET_VALUE |
| Any scoring signal unknown | WATCH | UNKNOWN_SIGNALS |
| Score >= attempt threshold (default 80) | ATTEMPT | ATTEMPT_THRESHOLD_MET |
| Score >= recommend threshold (default 60) | RECOMMEND | RECOMMEND_THRESHOLD_MET |
| Otherwise | WATCH | BELOW_RECOMMEND_THRESHOLD |

Each `ScoringAssessment` stores economics, raw signals, policy, component names,
desirabilities, weights, points, final score, recommendation and reason code.
Thus callers can render the actual calculation and threshold comparison, including
which signals are unknown. REJECT is an economic recommendation, distinct from a
submission being REJECTED. ATTEMPT does not authorize execution, spending or submission.
Planning remains an explicit caller action; eligibility, budget, QA and human approval
guards still apply. This milestone does not add an autonomous decision scheduler.

Example: reward USD 100, predicted probability 0.8, costs USD 10/5/3/2 gives gross
USD 80 and net USD 60. With target USD 100, zero risk/competition and other signals
equal to 1, points are 24 + 15 + 10 + 10 + 15 + 10 = 84: ATTEMPT.
Verified revenue remains USD 0.

## Application and persistence

`EvaluateOpportunity.execute(reference, EconomicInputs)` refreshes source availability,
calculates the domain assessment and saves the guarded EVALUATED aggregate.
`ScoreRequest` supplies signals/evidence, not a caller-selected score.
`ScoreOpportunity` receives an injected policy, calculates the domain scoring
assessment, saves an immutable `EvaluationRecord` and the SCORED aggregate.
The record validates its summary score/value against the stored calculation.

Identical completed retries reuse snapshots. Changed signals, policy or evidence
under the same evaluation identity conflict. A saved audit record can recover a
failed aggregate write without changing its timestamp. Records and aggregates still
lack a cross-repository transaction. The repository port must preserve all calculation
fields; no production persistence adapter is added here.

Earlier Domain methods accepting explicit ExpectedValue/Decimal remain for existing
guarded domain workflows, including caller-supplied budget-resume assessments. All
aggregate/resume scores are now bounded to [0, 100]. The application economic/scoring
path requires calculated assessments. Legacy budget resumption clears old structured
assessments when applying a fresh supplied value/score, preventing stale explanations
from being presented as current. Automated resume/re-evaluation remains future work.

## Limitations

No empirical probability calibration, confidence intervals, historical aggregation,
competition measurement, risk taxonomy or deadline-to-signal conversion is implemented.
Callers supply explained normalized signals; raw marketplace facts are not guessed.
Eligibility independently rejects expired or insufficient-time opportunities according
to its policy; a favorable deadline score cannot override those rules.

Success probability may already incorporate competition, history and risk, so using
those signals again can double-count correlated factors. The weighted score ranks
attractiveness heuristically; it is neither a probability nor expected money. The
absolute net value target saturates economics and is sensitive to currency and chosen
operating objectives. WATCH for missing history can constrain cold-start activity;
changing this requires an explicit policy decision, not silent neutral imputation.

Forecasts assume a single all-or-nothing reward and incurred estimated costs; they
do not model partial payment, conditional branch costs, refunds, human labor/time,
taxes, reward volatility, payment finality or dynamic prices. External cost/marketplace
contracts remain unresolved. No billing, AWS, marketplace or LLM integration is added.

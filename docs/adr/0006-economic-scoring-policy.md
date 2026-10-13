# ADR 0006: Explicit economic forecasts and explainable scoring policy

## Status

Accepted for the requested Milestone 2D implementation. Initial heuristic parameters
are documented and configurable; this is not evidence of empirical calibration.

## Context

The application accepts caller-selected ExpectedValue and score. Those inputs cannot
reconstruct the reward/probability/cost calculation or explain a recommendation.
The product requires estimated net value without confusing it with verified revenue.

## Decision

Domain immutable assessments derive expected gross/net value from explicit subjective
probability and four-category cost estimates. A versioned scoring policy derives
bounded components, weighted score and ordered explainable recommendations. A monetary
target is required; weights/thresholds have documented configurable defaults. Unknown
signals remain unknown and cap recommendations at WATCH. No empirical truth is claimed.

Application calculates via these domain objects, retains aggregate snapshots and
immutable evaluation records through existing ports, and preserves retry/conflict
semantics. Scores throughout existing domain workflows are bounded to [0, 100].
This supersedes the economic/scoring caller-assertion portion of ADR 0004. QA remains
caller-supplied. No external SDK, adapter or dependency is introduced.

## Consequences

Decisions are reconstructable from stored inputs, components and policy snapshots.
Forecasts remain distinct from actual ledger costs and verified revenue. Recommendations
do not replace eligibility, budget or approval authorization. Calibration, cold-start
policy and normalized signal generation need future product/data decisions.
Cross-repository atomicity and automatic budget-resume orchestration remain unresolved.
See [policy and limitations](../economic-scoring.md).

## Alternatives

An undocumented composite constant would hide policy choices. A statistically fitted
model is premature without verified historical data. Provider-generated scores would
reduce deterministic testability. Neutral imputation would guess missing knowledge.

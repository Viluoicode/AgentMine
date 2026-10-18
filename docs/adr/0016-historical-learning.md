# ADR 0016: Auditable historical observations and descriptive performance port

Status: Implemented for the requested Milestone 5D scope.

## Context

AgentMine retains forecasts, costs, outcomes and verified payment, but lacks a joined learning
dataset. Latest-state counting must avoid duplicate samples, future-label leakage, guessed
source identities/task types and treating missing cost as zero. Historical performance must
remain separate from production scoring until a policy is approved.

## Decision

Add immutable domain HistoricalObservation and descriptive statistics with explicit sample
counts. Application capture reads existing repositories and stores revisions, provenance,
matching pre-attempt forecasts and observed financial outcomes. Bind source identities from
explicit composition, preserve unknown task types, and freeze predictions once attempted.

Application owns HistoricalRepository and read-only HistoricalPerformance. SQLite appends
observations and advances a latest pointer atomically. Statistics deduplicate per opportunity,
support as-of/exclusion queries, separate currencies and report resolved-only acceptance rates.
Keep actual-cost/error cohorts explicit and maintain original forecasts.

## Consequences

Capture is explicit; no automatic scoring feedback, ML training, dependency or external call.
Retries and later observations cannot inflate attempts. Audits retain prior states and costs.
Statistics describe selected captured samples and are subject to incomplete cost data,
selection/censoring bias and trusted evidence-source limitations. A future policy must decide
whether/how to use these counts as a historical scoring signal.

## Alternatives

Counting every snapshot overweights frequently polled work. Treating skips/pending outcomes
as rejection biases rates. Reconstructing forecasts after outcomes leaks labels. Grouping
providers from URL/ID strings or filling missing costs with zero invents knowledge. Training
or changing scoring now exceeds this milestone.

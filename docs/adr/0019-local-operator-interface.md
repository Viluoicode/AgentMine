# ADR 0019: Minimal local operator CLI and separate financial views

Status: Implemented for the requested Milestone 7A scope.

## Context

Application approval workflows and persistence exist, but no operator entry point
exposes them. Forecast rewards must not appear as earnings. Existing repository
ports do not supply a complete consistent reporting snapshot.

## Decision

Use a standard-library terminal CLI, with a new application-owned read port and
SQLite snapshot adapter for a single-ledger workspace. Keep aggregation in an
application use case and rendering in Presentation. Display forecast and verified
economics in separate blocks, preserve currencies/unknowns and label cost coverage.
Compute operating mode through Domain. Reuse existing review/decision use cases.

Default offline source refresh fails closed. Explicit opt-in can compose the existing
Superteam read adapter; tests inject a fake. Configure one local actor outside bounty
content; no multi-user authentication or web frontend. Never submit automatically.

## Consequences

No dependencies or Domain changes. All controls can be tested offline. Full dashboard
reads are bounded-local only; multiple ledgers fail rather than omit costs. DynamoDB
reporting needs a separately designed implementation of the new read port. Operator
identity relies on trusted local access. Production API approval still requires a
verified fresh source. See [interface semantics and usage](../operator-interface.md).

## Alternatives

A complex frontend or public API adds authentication/deployment requirements that
are not needed here. Summing GSI queues can silently omit entries. A generic financial
total would conflate potential rewards, forecasts, verified payments and currencies.

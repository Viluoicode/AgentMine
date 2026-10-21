# ADR 0020: Explicit local initialization and use-case-based ingestion

Status: Implemented for the requested operator workspace follow-up to Milestone 7A.

## Context

The operator CLI required an existing populated SQLite file, but normal startup only
validated configuration. Test databases were temporary. Operators could not initialize
a persistent workspace or ingest real opportunities from the CLI. Placeholder commands
also caused PowerShell parser errors when copied literally.

## Decision

Expose `workspace init` with explicit currency and four budget limits. Application's
`InitializeWorkspace` uses existing conditional ledger/audit commits; identical policy
retries retain history, while different policy/mode fails. Local composition prepares
the database and checks the single-ledger configuration. Do not invent default budgets,
seed opportunities or create payment evidence.

Expose explicit live, bounded Superteam discovery using the already implemented source.
Application's `LoadWorkspaceOpportunities` checks the workspace, then coordinates existing
DiscoverOpportunities and NormalizeOpportunity. Stable IDs retain advanced aggregates.
Raw responses remain in the existing archive adapter. Keep eligibility, economics,
execution and protected actions as separate workflows requiring their real inputs.

## Consequences

Operators can create a persistent empty dashboard without credentials. Loading real
data requires an authorized Superteam key and `--live`; tests use fixture transports.
No new dependency, Domain change, external API contract or AWS service. No automatic
earnings, task execution or submission. Bootstrap initialization is intended for one
operator running serially; concurrent initialization with different ledger IDs is not
serialized across processes. Repository CAS still protects the same ledger ID. Discovery
and normalization are separate writes, so a failure can leave partially advanced records;
safe retries preserve current state. Existing source normalization and pagination limits
remain. See [commands and limits](../operator-interface.md).

## Alternatives

Reusing pytest temporary databases is not a persistent operator workflow. Writing model
snapshots directly would bypass existing use cases. Automatically guessing eligibility,
success probability or rewards would corrupt business semantics. A full workflow runner
or a fixture-seeding product command would expand the requested scope.

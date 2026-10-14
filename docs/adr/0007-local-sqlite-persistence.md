# ADR 0007: Local SQLite persistence with versioned snapshots

## Status

Accepted for the requested Milestone 3A implementation. Prior ADRs specified repository
semantics but had not selected a persistence technology. The milestone authorizes a
simple local database such as SQLite.

## Context

Application workflows already depend on five repository protocols. Persistence must
retain immutable evidence and complete aggregates, enforce optimistic revisions,
claim submission intents atomically and commit budget state/audit together. Domain
and Application must remain unchanged in this milestone.

## Decision

Implement the protocols with standard-library sqlite3. Use explicit bootstrap injection,
file-backed storage, short per-operation transactions and BEGIN IMMEDIATE for writes.
Store versioned tagged JSON snapshots plus indexed operational query projections.
Retain exact Decimal values and complete init-disabled aggregate state in an allowlisted
infrastructure codec. Store every budget commit in the same transaction as its snapshot.
Keep immutable identity conflicts and submission dispatch ownership within transactions.

Expose additional operational read patterns on concrete local adapters, because adding
Application query ports would violate this milestone's unchanged-inner-layers constraint.
Those capabilities can acquire application-owned read ports in a later milestone when
new use cases need them. No cloud API, ORM or third-party runtime package is required.

## Consequences

Existing use cases run against either test memory repositories or durable SQLite through
the same protocols. Small local datasets have straightforward persistence and auditability.
Snapshots couple the storage format to explicit model versions and require future
migrations. Exact score ordering and cost totals currently scan local snapshots; no
cross-workflow transaction or external exactly-once guarantee is claimed. SQLite locking
serializes competing writers and rejects stale revisions without silently overspending.
See [local persistence](../local-persistence.md) for query semantics and limitations.

## Alternatives

JSON files alone require custom locking/atomic multi-record writes. Pickle permits unsafe
deserialization and opaque persistence. An ORM or cloud database would add dependencies
and setup not required for this local milestone. Fully normalized tables for every
nested value object add migration/mapping complexity before those query needs exist.

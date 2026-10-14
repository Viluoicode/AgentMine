# Local persistence (Milestone 3A)

SQLite implements all five existing Application repository protocols using Python's
standard-library `sqlite3`. Domain and Application source files are unchanged. No ORM,
driver package, AWS service, marketplace or paid provider is introduced.

## Opening and injecting the adapters

```python
from pathlib import Path
from agentmine.bootstrap.local import open_local_repositories
from agentmine.application.use_cases import NormalizeOpportunity

repositories = open_local_repositories(Path("agentmine.sqlite3"))
normalize = NormalizeOpportunity(repositories.opportunities)
# normalize.execute(existing_opportunity_reference)
```

Opening explicitly creates/initializes the database. The parent directory must exist.
Importing modules and the existing default CLI do not create a database or start work.
The caller supplies the path; there is no hidden environment/configuration singleton.
Each operation owns and closes its connection. File-backed storage is required;
`:memory:` is intentionally unsupported because connections have independent lifetimes.

`LocalRepositories` exposes opportunities, evaluations, executions, submissions and
ledger. Inject them wherever their existing Application protocols are accepted. Other
ports (source, clock, provider, gateway, verifier) remain separate dependencies.
The integration flow injects the same test-only service fakes with either memory or
SQLite repositories, including reopening SQLite adapters between workflow steps.

## Stored data and access patterns

| Data/access pattern | Adapter method | Semantics |
| --- | --- | --- |
| Opportunity by ID | opportunities.get(reference) | Complete aggregate and revision, or None |
| Lifecycle status | opportunities.list_by_status(status) | Current exact lifecycle state |
| Eligible | opportunities.list_eligible() | ELIGIBLE, ready for evaluation; not every later state with an eligible assessment |
| Highest scoring | opportunities.list_highest_scoring(limit=20) | All scored snapshots, descending exact Decimal score, reference tie-break; includes terminal states |
| Source | opportunities.list_by_source(source_reference) | Exact original source reference, ordered by opportunity ID |
| Waiting for budget | opportunities.list_waiting_for_budget() | WAITING_FOR_BUDGET, with original phase/request/task state |
| Awaiting human review | opportunities.submissions_awaiting_review() | READY_FOR_HUMAN_REVIEW opportunities; Submission objects exist only after approval/dispatch |
| Accepted but unpaid | opportunities.accepted_but_unpaid() | ACCEPTED opportunities, excluding PAID |
| Verified revenue | opportunities.verified_revenue(currency) | Sum of Domain verified_revenue for current PAID snapshots in the selected currency |
| Evaluation history | evaluations.for_opportunity(reference) | Immutable full calculations/components/policy, ordered by evaluation time then ID |
| Execution history | executions.for_opportunity(reference) | Executions ordered by start time then ID |
| Work evidence | executions.get_deliverable/get_qa/get_content | Version-bound deliverable/QA and immutable content |
| Execution recovery | executions.get_work_request/get_work_response | Complete command/provider-response journals |
| Submission recovery | submissions.get_request/attempts_for/get | Intent, chronological observations and confirmed submission |
| Outcomes | submissions.get_outcome(submission_reference) | Immutable accepted/rejected outcome and evidence |
| Budget state | ledger.get(ledger_reference) | Policy, mode, authorizations, actual records and released operations |
| Budget/cost audit | ledger.history(ledger_reference) | Every committed BudgetCommit, ordered by revision, including audit_event=None changes |
| Costs by period | ledger.costs_by_period(reference, start, end, category=None) | Actual CostRecords, aware instants, half-open [start, end), ordered by UTC instant then operation ID |
| Monthly cost | ledger.monthly_cost(reference, year, month, category=None) | Actual costs in the budget's configured calendar timezone, all four categories by default |

Additional read methods are local adapter capabilities, not new Application ports.
Source references currently identify source items; the existing contract has no separate
marketplace/provider identifier. This milestone does not invent one or infer it from
URLs. General provider grouping requires a future inner-layer contract decision.

Money is retained as Decimal text and is summed through Domain Money operations.
Actual-cost reports never include estimates or outstanding reservations. An empty known
ledger month returns zero in the ledger currency; an unknown ledger returns None.
Period/history/list queries return empty tuples when no records match. Revenue is
reported explicitly per currency without conversion; an unmatched currency returns zero.
Accepted/potential rewards cannot enter the verified-revenue sum. The model has no
verified-payment timestamp, so no monthly revenue attribution is invented.

## Transactions, identity and durability

The schema uses versioned JSON snapshot rows with typed kind/ID, revision, SHA-256
checksum and indexed parent/time/status/source projections. All queries bind user values.
Decimals never pass through SQLite REAL. Ranking uses exact Python Decimal comparisons;
cost reports read a budget's actual records. This favors correctness and a small local
dataset; ranking scans opportunities and financial reports scan the selected ledger.

Writes use BEGIN IMMEDIATE, SQLite's default rollback journal and synchronous=FULL.
Each connection has a bounded lock timeout (default five seconds). Opportunity and
budget saves compare the expected revision within the write transaction. A competing
stale writer gets PortError(CONFLICT), with no write. Budget snapshot and full audit
commit in one transaction; an audit failure rolls the snapshot back too.

Immutable IDs accept identical semantic retries and reject changed content. Deliverable
and QA keys include version. Submission claim atomically creates the immutable intent:
only its first creator receives True. An existing saved intent also prevents dispatch.
Attempt observations are deduplicated by full semantic equality and ordered by observed
UTC time. Repeated reads/writes never invoke external providers. These mechanisms do
not by themselves guarantee exactly-once effects in external systems.

Database errors become safe structured PortError(UNAVAILABLE) failures and structured
error logs; raw payloads and credentials are not logged. Snapshot corruption is
INVALID_RESPONSE. Unknown schema/snapshot versions are UNSUPPORTED. Applications still
must reload/reconcile after uncertain results; the adapter does not blindly retry writes.

## Snapshot format and rehydration

Database `user_version=1` and JSON envelope version 1 are explicit. Decimal, datetime,
fixed/named timezone, timedelta, enums, tuple and frozenset have tagged encodings. Only
dataclasses/enums from a fixed set of imported model modules can be decoded; there is no
pickle, eval or dynamic import from stored data. Model field names/types are checked,
constructors validate normal inputs and calculated init-disabled fields are recomputed
and compared. The codec specifically restores persisted init-disabled Opportunity,
Budget and Task state and verifies Opportunity lifecycle history. It does not reset
aggregates to their constructor defaults or discard budget commitments/history.

The file is a trusted local application store. Checksums detect accidental payload
corruption, not an attacker who can rewrite both data and checksum. Rehydration is an
infrastructure snapshot boundary, not a new public Domain mutation API. Schema/model
changes require explicit future migration code and round-trip tests; unknown versions
fail without resetting or dropping data. Named timezone availability depends on the
Python host's zone database, just as it does for the existing Domain policy.

## Validation and remaining limits

Integration tests use real temporary SQLite files. They cover all lifecycle snapshots,
full workflow with both repository backends for Research/Data Processing, reopening,
budget restoration, all read patterns, precision/timezone boundaries, immutable IDs,
two-connection claims/reservations, stale revisions, audit rollback, lock failures and
corrupt/unsupported snapshots. No external credentials, network or paid APIs are used.
Pytest's test-only path configuration makes the existing service fakes reusable.

Transactions are per repository operation, not across the whole workflow. Outcome
records and Opportunity state can temporarily differ in a failed workflow; operational
lists reflect the committed Opportunity snapshot. General recovery, schema migrations
beyond initial creation, backup/restore tooling, encryption, retention, pagination and
large-volume query tuning are deferred. Use a local filesystem on one host; this is
not a distributed database or a cloud deployment.

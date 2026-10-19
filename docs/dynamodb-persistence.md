# DynamoDB persistence — Milestone 6B

## Access patterns before schema

The existing inner-layer repository protocols remain unchanged. Authoritative reads,
budget decisions, immutable claims and audit history require strongly consistent base
table reads. Operational lists can use eventually consistent indexes and must reload
the aggregate before acting. No repository scans a table or copies a relational join.

| Access pattern | Key/query |
| --- | --- |
| Opportunity by ID, budget by ledger ID, evidence by ID | Base PK `<kind>#hash(id)`, SK `META`, consistent GetItem |
| Opportunities by lifecycle, eligible, WAITING_FOR_BUDGET, awaiting review, accepted unpaid | GSI1PK `STATE#<state>`, GSI1SK stable identity |
| Highest scoring | GSI3PK `SCORE`, GSI3SK order-preserving decimal score plus identity |
| Source opportunities | Observation GSI2PK `SOURCE#hash(source_reference)`, GSI2SK identity; reload opportunity by ID |
| Evaluation/execution history | PK `COLL#<kind>#hash(opportunity_id)`, SK UTC timestamp + identity |
| Costs by period | PK `COLL#cost#hash(ledger_id)`, SK UTC timestamp + operation identity, bounded Query |
| Budget audit history | PK `COLL#budget_audit#hash(ledger_id)`, SK zero-padded revision |
| Submission attempts/outcome/payment checks | PK `COLL#<kind>#hash(submission_id)`, SK timestamp + content digest |
| Verified revenue per currency | PK `PAID#<currency>`, SK opportunity identity, consistent Query of paid projections |
| Approval/review and worker/QA journal | ID-addressed immutable evidence items and conditional claims |
| Historical captures/latest/as-of | ID item, per-opportunity collection, latest CAS item and strongly read HIST catalog |

## Table and indexes

One table, string `PK` and `SK`. Three sparse GSIs with string keys `GSI1PK/GSI1SK`,
`GSI2PK/GSI2SK`, `GSI3PK/GSI3SK`, KEYS_ONLY projections. The supplied schema function
returns create-table parameters for local/tests; importing or composing never creates
cloud resources. No LSI, TTL, streams, global tables, IAM or deployment is added.

Identifiers are SHA-256 encoded from canonical JSON to avoid separator collisions and
key-length problems. Full identities remain in validated payloads. Scores use padded
integer digits and exact fractional strings, not float conversion or rounding to
DynamoDB's numeric precision limit. All pages are consumed; exact Decimal ordering and
reference tie-breaking are retained. V1 ranking reads the scored index partition, not
the full table. Source means the existing exact source-item reference, not an inferred
marketplace/provider name.

Item types include opportunity/current budget, original source observation, immutable
evaluation/execution/content/deliverable/QA/work response, submission intent/receipt,
confirmation/final-outcome/payment guards, global deliverable/payment uniqueness guards,
budget commit audit and cost projections, approval snapshots, worker/QA journals and
historical observations. Item collections deliberately duplicate immutable evidence to
support strongly consistent chronological queries without an eventual GSI for safety.

## Idempotency and atomicity

Revision writes require `revision = expected`; create requires absence. Budget state,
audit and new cost projections commit in one TransactWriteItems. A stale snapshot cannot
authorize concurrent overspend. No transaction is split to evade size/action limits.
Immutable evidence accepts identical retries but rejects changed payloads. Claim creation
returns true only to the first owner. Submission intent and deliverable/version guard
are one transaction; payment proof and source/payment-ID guard are one transaction.
Final confirmation/outcome/payment guards prevent conflicting terminal evidence.

History append atomically advances the per-opportunity latest pointer with the observation
and query projections. Paid projections update atomically with the opportunity and are
decoded through the existing verified-payment domain invariant; acceptance alone adds none.
Multi-page financial totals are not a point-in-time transaction across concurrent writers.

All base reads use ConsistentRead. GSIs are eventually consistent: operational results may
be incomplete temporarily, and candidates are reloaded from the base table. A GSI is never
used for uniqueness or budget authorization. ClientRequestToken protects SDK retries within
one transaction call; persistent keys/conditions protect later retries. An ambiguous write
failure returns OUTCOME_UNKNOWN, never a successful claim. Callers must reconcile by ID.

## Bounds and deployment assumptions

Snapshots use the existing allowlisted JSON codec, checksums and exact Decimal values.
A conservative 380 KiB item / 3800 KiB transaction bound and 100-action ceiling fail explicitly
before dispatch. Large artifacts and ever-growing Budget snapshots require a future reviewed
storage strategy; this milestone does not silently truncate, offload or change domain models.
Single-operator index/catalog partitions suit V1 and are not a multi-tenant/high-throughput
design. No production credentials or live table are required for tests.

Official contracts checked for this implementation:
[transactions](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_TransactWriteItems.html),
[limits](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Constraints.html),
[read consistency](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.ReadConsistency.html).

## Validation

Integration tests use Moto's in-process DynamoDB emulation with explicit dummy credentials,
temporary tables and suite-wide network blocking. This exercises actual boto3 request shapes,
conditions, transactions, indexes and pagination, but does not establish AWS latency,
throttling, delayed index propagation or production durability. Docker is installed in the
current workspace environment but its daemon was unavailable; no container or cloud resource
has been started.

## Configuration and development setup

Optional dependencies (base installation remains dependency-free):

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,dynamodb-test]"
.\.venv\Scripts\python.exe -m pytest tests/integration/test_dynamodb_persistence.py -q -p no:cacheprovider
```

`dynamodb` supplies boto3 for the infrastructure client. `dynamodb-test` additionally
supplies Moto, strictly for tests. Without these optional test dependencies, these tests
skip explicitly; installing only the base/dev extras does not validate this adapter.
No live endpoint option is accepted by this test fixture: it constructs the client inside
`mock_aws()` with dummy credentials. No user credentials, Docker daemon, AWS account,
or operator action is needed for the emulated suite.

Composition is explicit and does not read environment variables or construct an SDK client:

```python
from agentmine.bootstrap.dynamodb import dynamodb_repositories

# client is an explicitly configured boto3 low-level DynamoDB client supplied by the caller.
# The table must already have the documented keys/indexes.
repos = dynamodb_repositories(client, table="agentmine", page_size=100)
# Inject repos.opportunities / evaluations / executions / submissions / ledger into
# the SAME existing application use cases. Extra fields expose approvals, history,
# research, data and QA journals.
```

The bootstrap does not create tables. `table_definition(name)` returns the exact schema
used by Moto; future deployment tooling can apply it after separate resource approval.
Production composition must explicitly configure region, credentials, endpoint/retry
policy, permissions and capacity. None is guessed from marketplace data.

Physical uniqueness guards:

| Item | PK | SK | Atomic partner |
| --- | --- | --- | --- |
| Submission intent | `submission_request#hash(id)` | `META` | Deliverable owner |
| Deliverable owner | `SUBMISSION_VERSION#hash(deliverable_id, version)` | `OWNER` | Submission intent |
| Confirmed attempt guard | `submission_confirmation#hash(submission_id)` | `META` | Attempt history |
| Final outcome guard | `outcome_guard#hash(submission_id)` | `META` | Outcome observation history |
| Verified payment guard | `payment_guard#hash(submission_id)` | `META` | Observation and payment owner |
| Payment owner | `PAYMENT_OWNER#hash(verification_source, payment_reference)` | `OWNER` | Verified observation |
| Historical latest | `historical_latest#hash(opportunity_id)` | `META` | Capture ID, per-opportunity history, HIST catalog |

Hashes use canonical JSON arrays, so composite identities cannot collide through delimiter
ambiguity. Snapshot digests detect changed/corrupt data; they are not digital signatures or
evidence that an external payment happened. Existing PaymentVerifier remains that boundary.

The shared codec now lives in `infrastructure/snapshots.py`; `sqlite/codec.py` keeps a
compatibility re-export. Snapshot versions and SQLite data format are unchanged. The adapter
does not migrate existing SQLite databases, launch a runner, train a model, or modify scoring.

## Execution report — 2026-10-19

| Check | Result |
| --- | --- |
| `python -m pytest tests/integration/test_dynamodb_persistence.py -q -p no:cacheprovider` | 15 passed on Moto 5.2.4 / boto3 1.43.114 |
| `python -m pytest -q -p no:cacheprovider` | 851 passed in 23.57 seconds; no skipped optional tests in this environment |
| `python -m ruff check .` | Passed |
| `python -m ruff format --check .` | 208 files already formatted |
| `python -m mypy` | Passed, 164 source files |
| `git diff --check` | Passed |

The existing Research/Data application workflow runs unchanged against injected DynamoDB
repositories through PAID. Additional tests cover worker/QA/approval journals, exact ranking,
source/state/period/revenue access, one-item query pages, stale revisions, concurrent budget
and submission ownership, rollback after an audit condition failure, conflicting terminal
evidence, duplicate payment attribution, historical latest/as-of capture, immutable writes,
size/key/action limits, checksum failure and sanitized ambiguous/read failures. A stale GSI
candidate is explicitly injected because Moto does not simulate delayed index propagation.

Temporary-directory sandbox access and a transient approval-review capacity failure initially
prevented the full suite; the final authorized rerun completed successfully. There is no
remaining approval blocker. Actual AWS/API spend: $0; no real account, table or payment was used.

# Remediation 01 — Submission cancellation race (F01)

Date: 2026-10-25. Scope: F01 only from [the full audit](full-repository-audit.md).
Status: **F01 RESOLVED** for the guarded submission workflow and both adapters.
No production gateway,
paid call, dependency, cloud resource, commit or push is introduced.

## Root cause and original failure window

Original API order:

1. Read approved Opportunity and revision.
2. Check content digest, QA, approval/version/target.
3. Refresh source availability.
4. Claim an immutable submission request/version separately from the aggregate.
5. Invoke SubmissionGateway.submit.
6. Persist response and receipt.
7. CAS the old Opportunity to SUBMITTED.

A cancellation could commit between steps 1 and 4, including during refresh.
The submission claim did not condition on the Opportunity revision. Step 5 still
sent, and step 7 then detected the stale revision. This protected the database
from overwrite but could not undo the external effect. Ordinary retry from SKIPPED
could not apply the retained receipt.

Two deterministic tests were added and executed before production changes. Both
failed against the original implementation (exit 1): cancellation still produced
one send instead of zero, and the gateway did not observe an in-flight state.
The latter assertion inside the gateway callback was wrapped by the original
application error handling into OUTCOME_UNKNOWN. These were expected failures,
not failures caused by an unavailable new import or dependency.

## Chosen cancellation/claim semantics

The deciding point is a **single durable transaction**, not a final reread:

```text
APPROVED_FOR_SUBMISSION
    cancellation CAS wins → SKIPPED; dispatch transaction conflicts; no intent/send
    API dispatch transaction wins → SUBMISSION_IN_FLIGHT + immutable intent
        fresh skip → invalid domain transition
        stale cancellation CAS → revision conflict
        matching confirmed receipt → SUBMITTED
```

Application's new `SubmissionDispatch` binds the approved snapshot/revision and
exact request (deliverable, passed QA, approval, target and content reference).
The existing byte-digest check still runs before it. SubmissionRepository gains
only `claim_dispatch(dispatch) -> bool` for this atomic requirement. True grants
one send. False means an identical retained intent exists: observe/reconcile only.
Unknown transaction outcome grants no send permission.

`SUBMISSION_IN_FLIGHT` means authorization/intent is durably established. It does
not assert a successful send, acceptance, payment or even that network I/O started.
Approval and the request remain immutable evidence. Cancellation cannot silently
erase an intent that already won. A pending/FAILED/UNKNOWN API attempt retains the
in-flight state; there is no automatic release, mode fallback or repeated send.

SubmitTask reloads the transaction's revision for receipt completion. Permission
comes exclusively from the atomic claim. A returned confirmation remains stored
before receipt/aggregate completion, so a later revision conflict can be repaired
from that confirmation without another gateway call. `submission_result.py` needed
no change: its evidence-first ordering is retained.

## SQLite and DynamoDB consistency

| Property | SQLite | DynamoDB |
| --- | --- | --- |
| Atomic claim/state | BEGIN IMMEDIATE contains request/version uniqueness and Opportunity CAS | One TransactWriteItems creates request, deliverable/version owner and revision-conditioned Opportunity |
| Cancellation already committed | Retained snapshot/revision comparison fails; entire transaction rolls back, including inserted request | Preparatory strong read or transaction revision condition fails; no request/version owner is committed |
| Claim already committed | Domain rejects fresh skip; stale writer loses CAS | Same domain rule and conditional revision write |
| Same ID retry | False for identical intent; changed payload conflicts | Same, including conflict reconciliation by stable ID |
| Different IDs / same version | Transactional uniqueness rejects the loser | Transactional version-owner key rejects the loser |
| Indexes | Lifecycle index updates with Opportunity | Lifecycle index changes, existing score/source index attributes preserved |
| Restart/unknown commit | Persisted intent survives reopen, no new send right | Persisted intent survives fresh adapter construction; ambiguous write never returns dispatch permission |

No separate service, process-local production lock, database schema, snapshot field
or DynamoDB table/index is added. The new domain state is a business safety boundary;
SQL/SDK transaction details remain in infrastructure. Both workflow repositories
must use the same authoritative file/table.

Old snapshots/histories remain readable by the new code. The existing approved →
SUBMITTED transition remains valid for MANUAL/legacy evidence. New enum snapshots
are not readable by older binaries; do not downgrade a workspace with new states.
Existing legacy API intents are observation-only in SubmitTask: claim_request or
save_request alone cannot authorize a new API send.

## Changed files

Production:

- `src/agentmine/domain/opportunity.py`: new guarded in-flight transition.
- `src/agentmine/application/contracts/submission.py`: typed SubmissionDispatch.
- `src/agentmine/application/ports/repositories.py`: narrow atomic claim contract.
- `src/agentmine/application/use_cases/settlement.py`: API dispatch uses that contract;
  recovery accepts in-flight intents, and only the successful owner can send.
- `src/agentmine/infrastructure/sqlite/submissions.py`: one transaction for request
  ownership and Opportunity CAS; reuse intent checks inside the same connection.
- `src/agentmine/infrastructure/dynamodb/submissions.py`: one conditional transaction
  for both kinds of authority; preserve relevant index projections.

Tests/fixtures:

- `tests/integration/test_submission_cancellation.py`: new regression suite.
- `tests/unit/application/fakes.py`: fake implements the extended contract with a
  bound opportunity store and rollback on save failure; it is not used as evidence
  for real concurrency isolation.
- `tests/unit/application/test_use_cases.py`: bind the fake stores and assert new
  unknown-attempt state.
- `tests/unit/application/test_submission_system.py`: assert in-flight retention;
  inject completion failure after dispatch rather than blocking the earlier claim.
- `tests/integration/local_cases.py`, `tests/unit/domain/conftest.py`: add a valid
  new-state snapshot and preserve existing legacy/manual histories.

Documentation: [ADR 0021](../adr/0021-atomic-submission-dispatch.md), its ADR index
entry, and this report. The original audit is retained as historical evidence;
F02–F11 are not remediated or reclassified here.

## New regression coverage

The new file contains **24 parameterized cases**, using real SQLite and Moto
DynamoDB adapters with fake, receipt-retaining external gateways. Calls to
reconcile only read a fake remote receipt; they cannot fabricate a new send.

| Required scenario | Test / assertions |
| --- | --- |
| Cancellation during refresh | `test_cancel_during_refresh_prevents_claim_and_external_send`: both adapters; zero sends/reconciles, no new request, SKIPPED retained |
| Cancellation immediately before authorization | `test_cancel_immediately_before_atomic_authorization`: transaction rejects old revision without leaking an intent; approval evidence preserved |
| Claim wins before cancellation | `test_claim_wins_cancellation_is_rejected_before_receipt_returns`, `test_claim_first_blocks_fresh_and_stale_cancellation`: fresh domain skip and stale CAS rejected; immutable intent retained |
| Receipt after concurrent state revision | `test_receipt_after_concurrent_revision_recovers_on_reopen`: compatible CAS changes revision; confirmation persists, reopen repairs completion with no reconcile or resend |
| Ambiguous external result | `test_timeout_after_effect_reconciles_only_after_reopen`: send takes effect before timeout, one send total and observation-only receipt recovery |
| Concurrent same ID | `test_concurrent_api_attempts_send_at_most_once`: barrier aligns refreshes; at most one authorized sender, durable result reused |
| Concurrent different IDs / same version | Same test's different-ID branch; one owner and one send, conflicting identity cannot bypass lock |
| Restart with existing claim | `test_restart_after_claim_never_grants_a_second_send`: both with and without a prior remote effect; only reconcile, preserve unknown when no proof exists |
| Cancellation after DynamoDB read | `test_dynamodb_cancel_between_preflight_read_and_transaction`: inject cancellation after strong read but before transaction; conditional write still rejects claim |
| Lost commit acknowledgement | `test_ambiguous_claim_commit_never_grants_dispatch`: committed claim plus raised OUTCOME_UNKNOWN yields zero sends; reopen retains authority |
| Partial SQLite write | `test_sqlite_partial_claim_write_rolls_back`: inserted intent is rolled back when aggregate CAS fails; no dispatch |

Existing approval, digest/version, MANUAL, UNSUPPORTED, retry, accounting and
architecture suites remain active. A new state also adds four parameterized cases
to existing lifecycle/rehydration/revision/revenue tests. No assertions were removed
to hide a failure.

## Verification commands and results

Existing `.venv\Scripts\python.exe`; no dependency installation. Each table command
starting with `-m` uses `.\.venv\Scripts\python.exe` as its executable.

| Command | Result |
| --- | --- |
| `-m pytest tests/integration/test_submission_cancellation.py -q -p no:cacheprovider` before production edits | Exit 1: 2 expected failures reproducing F01 |
| `-m pytest tests/integration/test_submission_cancellation.py tests/unit/application/test_submission_system.py tests/integration/test_submission_system_sqlite.py tests/integration/test_resilience.py tests/unit/test_architecture.py -q --tb=short -p no:cacheprovider` | Exit 0: **88 passed in 15.55s** |
| `-m pytest tests/unit/test_architecture.py -q -p no:cacheprovider` | Exit 0: **29 passed** |
| `-m pytest -q -ra --tb=short -p no:cacheprovider` | Exit 0: **987 passed in 36.89s**, no failed/skipped tests or pytest warning summary |
| `-m ruff check .` | Exit 0: passed |
| `-m ruff format --check .` | Exit 0: **239 files already formatted** |
| `-m mypy` | Exit 0: no issues, **182 source/test files** |
| `git diff --check` | Exit 0; Windows LF/CRLF conversion warnings only |

The full-suite total increased from 959 to 987 (24 new regression cases plus four
existing parameterized tests now covering the added lifecycle state).
Interim checks found
old-state expectations and missing fixture coverage for the new enum; these were
updated to assert the chosen semantics. The completion-failure test now faults
after the atomic claim, preserving its intended receipt-recovery coverage.

Tests retain the repository's network block. Moto is an emulator, not live AWS
concurrency verification. No real marketplace send or paid inference occurred.

## Remaining concurrency/recovery limits

- Local transactions cannot atomically commit an arbitrary external API call.
  Process death after authorization but before dispatch is indistinguishable on
  restart from some post-dispatch failures. Keep the intent and reconcile using
  independent evidence; do not clear it or change IDs to force a resend.
- Gateway implementations must honor observation-only reconcile and bound receipts.
  Direct database writes, unconditional overwrites, non-shared stores or manual
  actions outside AgentMine can defeat invariants; they are outside these ports'
  guarded contract. No exactly-once external-effect guarantee is claimed.
- Source terms/status may change after refresh. F07's broader freshness concern
  and the absent production gateway/verifier/deployment remain separate findings.
- Legacy SKIPPED-plus-confirmation data created before this fix is not silently
  rewritten or resubmitted. Existing evidence remains inspectable; use deliberate
  operator reconciliation rather than inventing a new history or approval.
- Known FAILED/UNKNOWN API intents remain locked for review. General release,
  compensation, migration, billing reconciliation and operator recovery tooling
  are not introduced as part of F01.
- Equivalent transaction semantics are implemented and exercised locally for both
  adapters. Production DynamoDB behavior still needs its existing separate deployment
  validation; no production resource was used to establish it here.

## Architecture impact and disposition

Dependency direction remains Presentation → Application → Domain. Application owns
the new dispatch requirement, Domain owns cancellation legality, Infrastructure
implements its atomic persistence. No business rule moves into Lambda or a database
schema. Scope is the narrow atomic request/Opportunity coordination needed for F01.

**F01 is RESOLVED** under the documented shared-store, conditional-write and gateway
contracts. Cancellation and dispatch authorization now have a common atomic
decision point, and regression tests demonstrate both winning orders. This is not
a claim of live AWS/provider validation or automatic repair of historical data.
Stop after reporting; operator review remains required before further remediation
or any live experiment. This change does not declare AgentMine production-ready.

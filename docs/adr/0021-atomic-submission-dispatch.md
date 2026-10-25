# ADR 0021: Atomic API submission intent and in-flight opportunity

Status: Implemented for the explicitly requested F01 remediation.
Extends ADR 0014's API dispatch authorization; MANUAL and UNSUPPORTED retain their
existing behavior. No production gateway or AWS deployment is added.

## Context

SubmitTask read an approved Opportunity, refreshed source availability, claimed
an independent submission intent, called the gateway, retained its response and
conditionally advanced the aggregate. A concurrent cancellation could commit
between the initial read and intent creation. The later CAS rejected an aggregate
overwrite, but could not undo an already issued external send.

Separate rereads cannot close that race. The cancellation write and dispatch
authorization need a common authoritative revision/transaction boundary.

## Decision

Introduce the domain state `SUBMISSION_IN_FLIGHT` and `Opportunity.begin_submission`.
An approved opportunity can be cancelled or can enter that state. Once in flight,
its only lifecycle successor is SUBMITTED on a matching confirmed receipt; it
cannot be skipped, revised or reapproved. This state means durable dispatch
authorization, not proof that network I/O occurred or is still running.

Application owns the typed `SubmissionDispatch` contract and extends
SubmissionRepository with `claim_dispatch`. A successful new API claim must
atomically persist BOTH:

1. Immutable request and deliverable/version ownership.
2. The approved Opportunity's conditional transition to SUBMISSION_IN_FLIGHT.

The payload binds the exact approved snapshot/revision, deliverable, QA, consent
and content reference. Existing digest verification remains before authorization.
Only True from this operation permits a single gateway.submit. An identical
existing intent returns False and permits observation-only reconciliation, never
a second send. Ambiguous transaction outcomes raise OUTCOME_UNKNOWN and confer
no dispatch permission. Repository ports in one workflow must share one store.

SQLite performs request uniqueness and aggregate CAS inside one BEGIN IMMEDIATE
transaction. DynamoDB performs request creation, deliverable ownership and the
revision-conditioned Opportunity write in one TransactWriteItems. Its initial
strong read is preparatory, not authorization; the transaction's condition is the
deciding point. Existing lifecycle/score indexes remain consistent with that write.

Cancellation before this transaction wins: the revision fails and no intent is
committed. Claim first wins: a fresh cancellation fails the domain transition,
and a cancellation calculated from an older snapshot fails the repository CAS.
There is no separate in-memory lock or hidden global state.

After claim, SubmitTask reloads the committed revision for response persistence.
That read does not grant permission. Response/receipt persistence precedes the
aggregate completion write. If another compatible CAS changed the revision, retry
reuses confirmation evidence without resending. A pre-send process death is still
ambiguous to a new process; it reconciles rather than acquiring another send right.

## Compatibility and limitations

- Existing MANUAL packaging, operator receipt and UNSUPPORTED behavior are unchanged.
  The approved-to-submitted transition stays valid for manual/legacy evidence.
- Legacy claim_request/save_request remains available for intent persistence and
  old data. It never authorizes a new API send in SubmitTask. Existing API intents
  are observation-only on retry; no automatic migration or second send.
- No snapshot field or database/table schema changes. Old histories remain readable.
  Older binaries do not know the new enum value and must not be used to read/run a
  workspace with in-flight states; this is not a supported downgrade.
- Claim and external HTTP cannot commit atomically. A crash/timeout after the
  claim retains the intent and approval evidence. FAILED/UNKNOWN attempts stay
  locked; no automatic intent release or cancellation is invented.
- A nonconforming gateway, direct database modification, missing shared authority
  or manual external clicks are outside these guarantees. Keep live submission
  unconfigured until its existing separate contract/deployment gates are satisfied.
- Historical SKIPPED-plus-receipt inconsistencies are not silently rewritten.
  Retain proof and reconcile deliberately; do not forge a new lifecycle history.

## Alternatives

Rereading before POST leaves a new TOCTOU window. Saving the intent and opportunity
separately leaves a partial-write window. An external lock service, microservice,
queue or generic transaction framework is unnecessary for these existing stores.
Automatically clearing ambiguous claims risks duplicate external submissions.

## Verification

Deterministic regressions first reproduced cancellation sending once and absent
in-flight state on the original implementation. Offline tests then exercise both
adapters, concurrent same/different-ID requests, stale/fresh cancellation, a
revision change before receipt application, lost claim acknowledgement, timeout,
transaction rollback and repository reopen. Moto is not a live AWS transaction
validation. See the F01 remediation report for commands and results.

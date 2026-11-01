# ADR 0030: Atomic offline manual handoff and provisional receipt

Date: 2026-11-01
Status: Accepted for F03-B2 offline scope only

## Context

ADR 0029 binds immutable submission material to separate, applied operator consent.
That consent grants no external permission. Legacy manual package creation cannot
atomically own an approved Opportunity against cancellation. A crash must never
permit a replacement ID or a blind resend.

## Decision

Use narrow Application contracts, use cases and a ManualHandoffRepository port.
SQLite implements transactional ownership; Presentation only parses and maps data.
Domain lifecycle and API-only SubmissionDispatch are unchanged.

Production composition uses UnverifiedManualChannel. There is no enabled real
channel, configuration switch, mock fallback or live authorization. An explicitly
injected OFFLINE_TEST_ONLY permission fixture can exercise local intent semantics.
Every CLI view says offline only, external_action_authorized=false and
external_send_verified=false. No workflow calls a gateway or payment verifier.

Preparation resolves the retained envelope, applied exact-scope approval, exact
worker/QA/content evidence, actor and sole ledger. Existing WorkerPreflight refreshes
source terms, deadline and deterministic eligibility, including only its existing
narrow evidence-bound manual eligibility policy. Preparation persists a draft and
immutable submission-ID binding without moving lifecycle. Confirmation explicitly
requires --confirm and repeats preflight. Unknown or known account mutations are
unsupported; NONE_DECLARED plus the scoped offline permission is required.

## Transactions and identity

All write transactions use BEGIN IMMEDIATE in the authoritative SQLite workspace.

1. Prepare: compare exact approved Opportunity and budget revision; retain draft
   and submission-to-draft identity atomically.
2. Confirm: compare all retained context/approval/QA and approved snapshot again;
   reject an existing unowned legacy intent; insert stable submission intent,
   provider/account/listing owner and handoff claim; CAS Domain.begin_submission
   to SUBMISSION_IN_FLIGHT atomically.
3. Capture: reuse B1 immutable evidence/capture transaction. Evidence is always
   OPERATOR_REPORTED / UNVERIFIED, never independent platform evidence.
4. Retain: attach the exact provisional receipt to the original claim atomically.
5. Complete: check original claim, capture and exact in-flight snapshot; persist
   manual SubmissionResult and Submission, CAS Domain.submit to SUBMITTED and
   write completion marker atomically. No Outcome or reward is created.

An existing claim returns original evidence without another preflight, fresh
permission, send instruction or renewed authority. There is no expiry, release,
replacement ownership, reconciliation scheduler or automatic retry of an external
action. Historical receipt completion needs the original ownership and exact local
snapshot, not a new source authorization or unchanged current budget revision.

## Failure semantics

| Boundary | Durable state | Allowed recovery |
| --- | --- | --- |
| Prepare rolled back | No draft/identity | Retry original IDs |
| Prepare committed, acknowledgement lost | Original draft | Read same IDs |
| Cancellation wins | Changed approved snapshot | Block confirmation |
| Claim rolls back | Approved; no claim/intent | Retry original IDs after checks |
| Claim committed, acknowledgement lost | In-flight original owner | Read original claim; never resend |
| Human action unknown | Sticky in-flight owner | Inspect only; no replacement ID |
| Evidence retained, receipt not attached | Provisional B1 evidence | Re-record identical evidence/IDs |
| Receipt retained, completion fails | Receipt pending/blocked | Same receipt retry; never send |
| Completion transaction fails | In-flight + retained receipt | Same-ID completion retry |
| Completion committed, acknowledgement lost | SUBMITTED history | Return original evidence |
| Current revision changed | Receipt retained, completion blocked | Inspect; no overwrite/release |

## Consequences and limits

No schema migration or dependency is needed; existing typed snapshot codec gains
an allowlisted contract module. Budgets, costs, commitments and released identities
are not rewritten. Completed readback does not move a later lifecycle backward.

A local operator assertion cannot prove a human clicked Submit. CONFIRMED in the
legacy attempt vocabulary means a retained manual receipt only; its description
and CLI explicitly disclaim independently verified send. SUBMITTED is not ACCEPTED
or PAID. Operator-reported/synthetic receipts contribute zero verified revenue.
Real channel selection, permitted account operations, outcomes, payment verification
and generic backup reconciliation remain separately gated work.

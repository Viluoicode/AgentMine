# ADR 0031: Independently authenticated outcome evidence

Date: 2026-11-01
Status: Implemented for F03-B3 offline foundation only

## Context

B1 preserves immutable submission scope/provisional captures. B2 owns a sticky
manual handoff and an operator-reported, UNVERIFIED receipt. Domain already owns
Submission, Outcome, ACCEPTED/REJECTED transitions and independent payment rules.
The legacy gateway observation path is not an authenticated outcome contract for
the B3 workflow. No independently verified marketplace outcome integration exists.

## Decision

Reuse existing Domain Outcome without adding a parallel domain or approval system.
Application contracts retain eight semantic event kinds: SUBMISSION_REPORTED,
SUBMISSION_RECEIVED, APPLICATION_SELECTED, UNDER_REVIEW, DELIVERABLE_ACCEPTED,
DELIVERABLE_REJECTED, DISPUTED, UNKNOWN. Only independently verified deliverable
acceptance/rejection can map to a final Outcome. Selection never maps to acceptance.
No accepted reward amount is inferred from the potential reward or reported text.

An OutcomeEvent binds the exact retained B2 receipt/handoff, envelope, account,
provider, listing, channel, Submission and Deliverable/version. Existing B1 metadata
and capture bind provider-event identity, operator actor, provenance, event/observed/
server-capture timestamps, SHA-256 and import contract. The event parser and
verification contracts are explicitly versioned. These are AgentMine contracts,
not claims about a marketplace's API or parser.

All imports stay OPERATOR_REPORTED / UNVERIFIED, even when the payload resembles a
provider response or is a test fixture. OutcomeEvidenceVerifier is a read-only port
that must independently authenticate the full correlation and semantic stage.
Its accepts(decision) method authenticates authority on retained-decision recovery;
a persisted VERIFIED label alone cannot enable finalization under an unconfigured
composition. Application checks exact request and time binding. Host/store/adapter
implementations remain trusted; hashes do not authenticate a hostile local writer.

Production bootstrap hardwires UnavailableOutcomeVerifier: BLOCKED and accepts=False.
No production test-verifier class, plugin loader, authority flag, credential option
or enabled external source is added. Explicit test-only dependency replacement can
exercise authoritative acceptance/rejection inside isolated SQLite tests. It is not
evidence of real authentication, marketplace compatibility, acceptance or earnings.

## Persistence and recovery

Use one authoritative SQLite workspace and existing typed snapshots. No schema
migration or new dependency. BEGIN IMMEDIATE serializes immutable writes and CAS.

| Boundary | Durable evidence / recovery |
| --- | --- |
| Capture | B1 atomically stores provisional metadata and bounded text; failed capture leaves neither |
| Event | Atomic provider/account/listing/event owner plus immutable event; conflicting identity rejected; capture may already exist provisionally |
| Request | Immutable verification ID, event and exact SUBMITTED Opportunity snapshot before verifier call |
| Decision | Immutable result/status/authority/rationale/time bound to request; identical concurrent observations retain first decision timestamp |
| Final application | Check exact retained decision/event/receipt/submission and current snapshot; atomically write existing Domain Outcome, CAS Opportunity and completion receipt |
| Lost acknowledgement | Read original event/request/decision/application; never resend or mint replacement ownership |
| Stale/terminal state | Retain evidence/decision, report CONFLICT; no overwrite, rebase or payment |

Report imports can be retained historically after finalization. New finalization
requests require SUBMITTED and the exact current submission/version. The first
terminal outcome wins; another verification identity cannot overwrite it. Applied
historical readback is read-only. An unknown request with no decision remains UNKNOWN;
non-authoritative decisions remain UNKNOWN/UNVERIFIED/BLOCKED. Failed final CAS leaves
a retained decision for inspection and original-ID recovery, not renewed send rights.
B2 claims, cancellation semantics, commitments and financial records remain unchanged.

## CLI and consequences

`submission outcome record/show/verify/status` accepts only bounded strict report
JSON and stable IDs. It never accepts authority, final Outcome, reward or payment
from the operator. Default verify returns BLOCKED; status exposes lineage, provisional
trust, decision authority/rationale, and conflict/unknown/application state separately.
No URL is fetched, account mutated, external submission or paid call dispatched.

Only test-only independently authoritative responses exercise Domain.record_outcome.
ACCEPTED is not PAID. Outcome accepted_reward remains unknown rather than copying a
forecast. No ledger, costs, payment, verified reward or revenue is written by B3.
Real provider authentication, outcome contract/namespace/finality, independent payment,
FX, fees, F08 reconciliation and all live activation remain separately gated.

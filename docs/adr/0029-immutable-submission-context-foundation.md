# ADR 0029: Immutable submission context and exact-version review ownership

## Status

Implemented for **F03-B1**, 2026-10-31. Applies the approved B1 policies from
[F03-A](../audits/remediation-06-submission-payment-plan.md). No handoff, external
submission, account mutation, outcome verification or payment capability is enabled.

## Context

Existing operator reviews bind deliverable/version/content and a destination
Reference. They do not by themselves freeze the effective account, channel,
submission mode or outbound representation. Retained Data results and applied
versioned QA already provide authoritative local evidence. F01's API claim/cancel
transaction must remain the only existing API dispatch authority for legacy flows.

## Decision

Application owns a frozen SubmissionEnvelope derived from the actual completed
Data run, WorkerResult, exact deliverable, applied QA inspection/report, immutable
source observation and retained source/terms/eligibility evidence. It includes
explicit vendor-neutral account/channel identities, MANUAL or API-intended mode,
disclosure declarations, known/unknown account side effects, outbound text,
artifact selection and optional declared published artifact references.

Preparation accepts only scope inputs and an execution reference; the operator
cannot supply a replacement execution, QA, approval, ledger or financial outcome.
Actor and ledger must match the retained specification and trusted composition.
Unknown channel/mode definitions fail. Location metadata uses a conservative HTTPS
grammar, without userinfo, query secrets or fragments. A local path cannot be a
published-artifact reference. These checks establish neither network availability
nor platform/account permission. Unknown side effects remain visible and cannot
authorize future dispatch.

The application computes a versioned canonical SHA-256 representation of the
complete immutable envelope, including identity and exact version. The existing
ApprovalScope destination becomes `submission-context:<digest>`, resolving to the
envelope in local persistence. Changing account/channel/mode/outbound bytes or
version changes the scope. Identical bytes in another version never share approval.
The outbound representation has its own deterministic digest. No provider SDK or
database serialization defines these business bindings.

Reuse PrepareOperatorReview/GetOperatorReview/DecideOperatorReview. Context-scoped
reviews require a matching stored envelope, actor, ledger and original Opportunity
snapshot; review/show-review display the resolved envelope. A conflicting review
ID cannot be rebound. APPROVE remains separate from preparation and uses the
existing applied Opportunity transition. A saved decision alone is not applied
consent: inspection checks the exact approved value and expected revision.
Historical envelope readback remains available; a stale consent is not current
action permission.

B1 approval is **offline scope consent**. For a resolved context only, it validates
retained local evidence instead of calling the live OpportunitySource. Legacy
review refresh behavior remains unchanged. Fresh source/account/eligibility checks
are a later handoff responsibility. To prevent scope consent entering legacy action
paths, SubmitTask and RecordManualSubmission explicitly reject the reserved context
namespace with UNSUPPORTED before any claim, source call or receipt transition.
There is no B1 handoff/send command or provider factory. No API-intended metadata
selects a gateway. Domain and F01 claim_dispatch contracts/transactions are unchanged.

SQLite implements the narrow application repository port. BEGIN IMMEDIATE checks
the current Opportunity revision and retained execution/plan/result/specification,
finish marker, content, observation, applied QA and recorded cost. One matching
budget ledger is required. Account/channel definitions, envelope and scope index
commit together. Equal identity retries return original immutable records, including
after lost acknowledgement; conflicting definitions fail. No submission owner,
authorization, reservation or lifecycle record is created by preparation.

Evidence imports use a separate provisional model. Allowed trust labels are
operator-reported, unverified-source and explicitly test-fixture; allowed states
are UNKNOWN, UNVERIFIED and CONFLICT. Metadata binds envelope, optional reported
submission/event hints, configured actor, provider/account, provenance, event/
observation/capture timestamps, digest and parser/contract version. Metadata and
bounded capture commit atomically; readback checks capture integrity. No evidence
import constructs Domain Outcome/PaymentEvidence or changes revenue. A source
label, screenshot hash or operator claim is not independent verification.

Capture time is server-owned: concurrent identical imports may compute different
candidate times. The first committed timestamp wins; all successful callers read
back that original metadata. Every other payload field and capture byte must match.

## Consequences and trust limits

No Domain change, new dependency, provider integration, generic UnitOfWork or
workflow engine. Bootstrap shares the authoritative SQLite workspace, ledger,
actor and real runtime history. Presentation parses bounded strict JSON and renders
escaped values; it does not mutate lifecycle or infer financial facts.

Envelope/capture rows can contain private operator-approved data. No credential,
session, key or authorization field exists in the input schema; recognizable
private-key/API-key/Bearer material is rejected. Arbitrary sensitive free text
cannot be perfectly classified. The single operator remains responsible for
data minimization and truthful disclosures, and the host/database are trusted.
Digests are consistency/ownership bindings, not authentication against a hostile
authorized writer. Existing workspace ACL/retention/backup responsibilities remain.

Raw B1 evidence never upgrades legacy manual packages or earlier review authority.
Existing legacy commands remain compatible but cannot consume reserved B1 scopes.
New snapshot kinds require the updated binary; no downgrade/reset migration.
Future handoff must independently establish fresh permission, account effects and
applied consent. Unknown account mutations block that future capability. No asset,
network, payment verifier, FX or partial-payment decision is made here.

## Alternatives

Binding only a URL or content digest loses account/mode/version authority. A second
approval engine duplicates operator policy. Letting offline consent flow through
legacy SubmitTask would activate capabilities that B1 does not authorize. Treating
operator evidence as verified settlement corrupts revenue. A general capture or
workflow framework is unnecessary for this bounded local foundation.

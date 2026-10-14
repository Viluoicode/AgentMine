# Application ports (Milestone 2A)

Application owns the protocols in `src/agentmine/application/ports` and immutable
contracts in `application/contracts`. They import only Application, Domain and
the standard library. Infrastructure will implement them; bootstrap will inject
implementations into future use cases. No use case, concrete adapter, fake,
network operation or provider integration is introduced by this milestone.

## Responsibilities and ownership

| Port | Responsibility | Decisions retained by inner layers |
| --- | --- | --- |
| OpportunitySource | Bounded discovery with opaque continuation; refresh open/deadline facts and observation time | Application maps stable identities and provenance; Domain owns eligibility, scoring, lifecycle and resumption |
| OpportunityRepository | Load/save complete Opportunity snapshots with revision checks | Domain transitions; Application chooses when to persist |
| EvaluationRepository | Store immutable assessments and retrieve chronological opportunity history | Application finalizes assessments from deterministic checks/advice; Domain owns financial distinctions |
| ExecutionRepository | Store execution evidence, versioned deliverables and QA results | Domain validates execution, QA/version bindings; Application resolves/stores content separately in future work |
| SubmissionRepository | Persist submission intent before side effects, attempt journal, confirmed receipts and outcomes | Application coordinates retries/reconciliation; Domain validates approval/receipt/outcome bindings |
| CostLedgerRepository | Atomically commit budget snapshot plus supplied decision/measurement audit event using expected revision | Domain authorizes/records; Application commits authorization before paid I/O |
| LLMProvider | Evaluate opportunity economics, draft supported Research/Data work, advise on QA; return measured cost when known | Domain owns spending policy; Application checks advice/evidence and applies transitions; human approval remains human |
| SubmissionGateway | Submit exact approved content/version, reconcile an unknown attempt, observe acceptance/rejection | Domain owns submission requirements and lifecycle; Application journals and correlates results |
| PaymentVerifier | Independently observe evidenced payment for an accepted submission | Domain alone advances to PAID and exposes verified revenue |
| Clock | Supply timezone-aware UTC time | Application passes explicit instants into Domain; budget policy chooses its calendar timezone |

Protocols are synchronous for the current Python application boundary. There is no
runtime wiring or hidden singleton. Async orchestration is deferred until a concrete
runtime needs it; adapter internals do not determine business method names.

## Typed contracts and evidence

Discovery returns `OpportunityObservation` with a discovered domain opportunity,
source identity, requirements, observed time, open status and checked deadline.
Sources must not transition aggregates or infer eligibility. `None` deadline means
confirmed absence when `deadline_known=True`. Unknown deadlines use
`deadline_known=False`; `is_open=None` represents unknown open status. These cannot
authorize work: eligibility returns reason codes and later use cases reject
unresolved availability. Continuations are opaque references belonging to
the selected source; an exhausted batch has no continuation. Results must respect
the requested limit. Stable source-to-domain identity mapping is an adapter/application
responsibility, not a vendor identifier exposed as a storage schema.

`EvaluationRecord` records a final eligibility/economic assessment with evidence,
score and timestamp. It is an application audit record, not a second domain policy.
LLM evaluation returns `EvaluationAdvice`, work returns `DeliverableDraft`, and QA
returns `QAAdvice`. Advice never establishes eligibility, authorizes spending,
approves submission or creates verified revenue. No model/provider options or raw
SDK dictionaries cross the port.

AI requests require an AI-category authorization matching the operation,
opportunity and task scope. Work uses an existing supported domain Execution;
QA additionally binds execution, deliverable and content reference. Responses carry
operation identity and evidence. `actual_cost=None` means measurement unavailable,
never zero and never the estimate. Future use cases must correlate the full response
scope/currency, retain the reservation until reconciled, and record actual costs
through Domain even when greater than the estimate. A local authorization object
does not prove its reservation was persisted or enforce a provider hard spend cap.

Submission intent binds passed QA, exact approved deliverable version, target and
content reference. The same reference is used for all retries/reconciliation.
Confirmed results contain an evidenced domain Submission; human-action-required
and unknown results cannot contain a receipt. Unknown attempts must be reconciled
before another submission. Reconciliation observes existing effects and must not
create a new submission. Outcomes without a decision remain `None`, never assumed
rejected or accepted. Payment can be VERIFIED only with a VERIFIED_PAYMENT Reward
bound to the submission; accepted/potential rewards cannot satisfy that contract.
Application must still correlate the returned submission, content, approval,
currency and observation time against the request before applying Domain actions.

## Persistence and errors

- Missing reads return `None`; outages/malformed data are errors, not missing records.
- Opportunity/budget revisions begin at 1. `expected_revision=None` means create only;
  a positive revision means compare-and-swap. Success increments the revision;
  a stale or already-existing create raises `PortError(CONFLICT)` without partial writes.
- Cost ledger commits atomically retain the supplied audit event and complete budget
  state (including estimated commitments, actual records and releases). Audit event
  snapshot mismatch is rejected by the contract. `audit_event=None` is reserved for
  initialization, policy/mode changes and releases; their snapshot history must remain
  auditable. Denied/approval-required decisions must also be journaled, not discarded.
- After an uncertain conditional-write outcome, reload and reconcile committed state;
  do not blindly replay a stale save or paid action. Application must re-evaluate
  authorization on a conflict before external spending.
- Immutable record saves with identical identity/content are idempotent. Reuse of an
  identity with different content raises CONFLICT. Deliverable/QA identity includes
  version. Evaluation histories and submission attempt histories are chronological;
  duplicate identical observations do not create duplicate entries. Intent identity
  is the stable submission reference. Outcome identity is the submission reference.
- Full aggregate round trips must preserve init-disabled fields, lifecycle/history,
  evidence and wait state. Reconstructing only constructor fields is insufficient.

Adapters translate failures into `PortError` with a safe message, business operation
and code: UNAVAILABLE, UNSUPPORTED, INVALID_RESPONSE, CONFLICT or OUTCOME_UNKNOWN.
UNAVAILABLE does not imply retrying a non-idempotent operation is safe. When an
external effect may have happened, report UNKNOWN/OUTCOME_UNKNOWN and reconcile.
Domain validation continues to raise structured DomainError. No provider exception,
credentials or raw payload should become the public error message.

These are required implementation semantics, not guarantees supplied by Protocol
declarations. Adapter contract tests will have to prove them. Ledger atomicity does
not imply a transaction across all repositories; workflow crash recovery remains
future application design.

## Unresolved external contracts

No marketplace discovery/submission/outcome API or permission model has been verified.
Automated submission, idempotency support and reconciliation may be unavailable;
adapters must report UNSUPPORTED/human action/unknown rather than invent endpoints.
Payment evidence authenticity, settlement/finality, partial payments, conversion and
verification source remain unresolved; no wallet is introduced.

AI capabilities, pricing, exact billing measurement, hard caps, cancellation and
timeout reconciliation are unresolved. Estimated prices cannot be promoted to actual
cost. Content storage/resolution and digest verification must bind actual bytes to
the approved reference before submission; a reference alone is not authenticity.
Persistence serialization/rehydration, audit retention, atomic-write mechanism and
cross-repository recovery require adapter/use-case design. This milestone specifies
business requirements without claiming any vendor supports them.

## Validation

Unit tests exercise scope/evidence, financial status, revision and audit contract
validation. Static AST tests enforce Domain/Application import direction, including
nested imports and type-only imports, and test forbidden-import examples. This is a
static import guard, not a sandbox against arbitrary dynamic Python execution.
Existing domain/e2e tests remain active. Adapter conformance tests and fakes are
deferred until adapters/use cases exist; no paid API calls occur in tests.

## Milestone 2B extensions

OpportunityRepository now retains original source observations for stable provenance.
ExecutionRepository stores immutable referenced content and work request/response
journals; content and command identities must reject conflicting reuse. Content uses
an application-computed UTF-8 SHA-256 digest. SubmissionRepository.claim_request
atomically creates intent and returns true for its sole dispatch owner; identical
existing requests return false, conflicting requests raise CONFLICT. This is a
business concurrency requirement, with no chosen database implementation.

Use cases and test-only fakes now exist. Production implementations, real external
contract verification and adapter conformance remain deferred. See
[core use cases](application-use-cases.md).

## Milestone 2D evaluation records

EvaluationRecord now retains the complete ScoringAssessment: economic inputs,
calculated values, signals, components, recommendation/reason codes and policy
snapshot. Summary expected_value/score must match that calculation. Existing
EvaluationRepository ownership, immutable-identity conflicts and chronological
history requirements remain unchanged. Future adapters must preserve these fields.
LLMProvider evaluation advice remains advisory and is unused by the deterministic
EvaluateOpportunity/ScoreOpportunity path. No production adapter is introduced.

## Milestone 3A local implementation

All existing repository protocols now have concrete SQLite adapters. Domain/Application
source and Protocol declarations are unchanged. Real-file integration tests validate
snapshot rehydration, conditional commits, budget/audit atomicity, intent ownership and
idempotency. Additional operational queries are local adapter methods pending future
application-owned read ports. See [local persistence](local-persistence.md).

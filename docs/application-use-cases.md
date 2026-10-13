# Core application use cases (Milestone 2B)

Thirteen synchronous use cases are exported by `agentmine.application.use_cases`.
Each receives its required ports explicitly and exposes a typed `execute` method.
No adapter, external SDK, environment read or runtime integration is constructed.
Domain models and guarded public actions remain the lifecycle/policy authority.

## Implemented operations

| Use case | Inputs and coordinated behavior |
| --- | --- |
| DiscoverOpportunities | DiscoveryRequest; validate batch bounds/discovered snapshots, preserve source provenance, create missing aggregates without downgrading rediscovered work |
| NormalizeOpportunity | Opportunity reference; apply domain normalization transition to an already business-shaped source observation |
| CheckEligibility | EligibilityCheckRequest and injected EligibilityEngine; refresh facts, evaluate deterministic rules and persist resolved/pending assessments |
| EvaluateOpportunity | Reference and EconomicInputs; refresh source facts, calculate and persist Domain EconomicAssessment |
| ScoreOpportunity | ScoreRequest signals and injected ScoringPolicy; refresh, calculate explainable score, persist full EvaluationRecord and aggregate |
| PlanTask | PlanTaskRequest; restrict task type, refresh open/deadline facts and create a supported Task with checked deadline |
| ExecuteTask | ExecuteTaskRequest; refresh facts, authorize/commit AI budget, journal execution, invoke injected work provider, retain response, record known actual cost, store content/deliverable and advance to QA_PENDING |
| RunQA | Reference and resolved QAResult; persist version-bound assessment and apply domain pass/rework branch |
| RequestHumanApproval | Reference; return verified-content HumanReviewRequest for the current passing deliverable, without granting approval or sending a message |
| ApproveSubmission | Reference and explicit HumanApproval; refresh availability, validate approval time and apply domain approval binding |
| SubmitTask | Opportunity/submission references; validate approved content, atomically claim intent, submit once or reconcile, correlate receipt, persist confirmed submission |
| TrackOutcome | Reference; observe pending/accepted/rejected outcome, correlate identity/time, persist evidence and apply outcome transition |
| VerifyPayment | Reference; observe payment for accepted submission, correlate identity/time and apply verified payment; pending/unverifiable observations do not create revenue |

Milestone 2C implements deterministic eligibility from normalized facts and participant
capabilities. Milestone 2D calculates economics and scoring from explicit forecasts
and a documented policy; QA remains a supplied resolved assessment. Neither forecasts
nor advice assert eligibility/payment. See [eligibility engine](eligibility-engine.md)
and [economic scoring](economic-scoring.md).
Source observations are already business-shaped: normalization here is the guarded
milestone transition, not marketplace parsing. Final evaluation audit is saved when
scoring completes. Evaluation and QA make no paid calls.

ExecuteTask calls the **injected** LLMProvider port; the repository supplies no real
LLM implementation or wiring. Tests use only FakeProvider. This is orchestration of
a contract, not a Research/Data engine, code execution environment or real provider
integration. Inputs/pricing/spending-approval evidence are supplied explicitly.

## Freshness, approval and finance

Before new eligibility, evaluation, scoring, planning, execution, approval or submission
work, refresh through the stored source reference. Refresh identity must match and its
observation time must fall within the call's clock interval. Closed/expired opportunities
fail explicitly without advancing; expiration equality also rejects work. ExecuteTask
rejects a changed deadline instead of executing an outdated plan. Expired rejection
does not invent a new general-purpose expiration domain state.

Paid dispatch happens only after revision-checked ledger commit and IN_PROGRESS
persistence. Denial is audited and moves Opportunity/Task to WAITING_FOR_BUDGET.
Spending approval required is returned separately, leaving PLANNED and dispatching
nothing. Free discovery-to-plan/outcome functions have no budget dependency.
Unknown actual cost remains an outstanding estimate. Known actuals use Budget.record,
including explicit audit issues for overruns; estimates never become actual charges.
Provider response evidence and content are journaled through ExecutionRepository.

Content uses `sha256:` of exact UTF-8 text. Review and submission check actual bytes
against the approved content reference; swapping bytes under an unchanged reference
is rejected. QA and human approval remain bound to the complete deliverable version.
Approval timestamps must not precede execution or be in the future. Authentication of
the human actor and evidence authenticity remain future presentation/adapter work.
HumanReviewRequest is returned to the caller, with no email, UI or notification integration.

Acceptance continues to yield zero verified revenue. Payment verification must return
a verified-payment Reward for the matching submission/currency before Domain advances
to PAID. No billing provider, settlement API, wallet or currency conversion exists.

## Idempotency and failure boundaries

Same-input retries of completed operations return the existing snapshot where safe;
changed immutable identities fail explicitly. Opportunity saves retain expected revisions;
conflicts propagate without an automatic retry loop. Audit/record writes preceding an
aggregate save can remain after a conflict: there is no cross-repository transaction.

Execution journals the complete command and response. Dispatch is preceded by an
Opportunity compare-and-swap to IN_PROGRESS. An IN_PROGRESS execution without a cached
response reports OUTCOME_UNKNOWN and never blindly calls the provider again. Cached
responses can recover failed cost/completion writes without redispatch. A failed
pre-dispatch Opportunity save retains its reservation and supports a same-input retry
using the original execution journal. Automatic release of ambiguous reservations is
deliberately absent; unknown billing needs reconciliation.

SubmissionRepository.claim_request atomically creates the intent and grants dispatch
only once; identical retries return false, changed content conflicts. Other callers
reconcile rather than submit again, including after a deadline when a prior effect may
already exist. Gateway errors retain an unknown attempt. Confirmed receipt persistence
can be recovered before the aggregate transition. Real adapter concurrency/idempotency
guarantees still require contract tests; the test fake is not a production repository.

ApplicationError separates NOT_FOUND, EXPIRED, CLOSED, UNSUPPORTED_TASK and INVALID_STATE
from structured DomainError and PortError. No vendor exception or raw payload is used
by these coordinators. Durable budget decisions/measurements and work/submission
journals provide structured audit records; operational logging configuration remains
unwired at this stage.

## Limits and validation

No automated QA policy, scheduler, general replan, failed-QA
execution rework, provider/billing reconciliation or automatic budget-wait resumption
coordinator is implemented. Domain's guarded budget-resume capability remains intact;
regular use cases cannot bypass it. Pending outcome/payment observations are returned
as unchanged aggregates; a durable observation history for those pending checks is
future work. Updated source reward/requirements parsing also remains adapter/policy work.

Tests use separate instance-local fakes for all ten ports and prove the requested
discovery-to-plan flow and ineligible, budget-denied, unsupported and expired paths.
They additionally cover all thirteen operations through payment, QA failure, content
tampering, unknown external effects, conditional-write failures, recovery, overrun
recording, unknown cost, spending approval and idempotency. Static import guards keep
Application independent of infrastructure/presentation/bootstrap and Domain independent
of Application. No real external calls, dependencies or infrastructure are added.

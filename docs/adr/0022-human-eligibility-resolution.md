# ADR 0022: Evidence-bound human eligibility resolution

Status: Implemented for F04 remediation only. Extends ADR 0005; distinct from
ADR 0013's deliverable/submission or spending consent.

## Context

Deterministic eligibility returns REQUIRES_HUMAN_REVIEW for a manual submission
channel, but rerunning the engine cannot resolve that reason. Existing operator
approval requires a completed, passing deliverable and cannot resolve eligibility.
The original Opportunity retained an assessment, not the full reviewed context.

## Decision

Use explicit EligibilityResolution / ManualEligibilityEvidence domain values and
APPROVE / REJECT choices. Only MANUAL_SUBMISSION_REQUIRED is human-resolvable in
this implementation, and only when it is the sole remaining review reason after
all deterministic checks. Require nonblank destination, instruction, access and
requirements evidence references, an explicit requirements-satisfied attestation,
actor, timestamp and rationale. Keep the original MANUAL fact; do not relabel it
AUTOMATIC. Known blockers, UNKNOWN and security-sensitive reviews are not overrides.

Application prepares an immutable EligibilityReview: complete normalized facts,
profile, assessment/reasons, policy/rules version, current requirements/source
content version and Opportunity snapshot/revision. New review IDs publish a new
Opportunity revision, invalidating older context even when reason codes are equal.
Same-ID identical preparation returns the recorded snapshot, not a refreshed grant.
The preparation runs normal deterministic checks; a resolved deterministic result
is persisted and reported as not needing a human review.

At decision time, require the exact authoritative Opportunity revision, refresh
source identity/status/deadline/content version/requirements, rerun the engine at
the current time, then apply the narrow domain resolution policy. Commit decision
and Opportunity transition together through an application-owned repository port.
SQLite uses one write transaction; DynamoDB uses one conditional transaction. One
decision wins; identical retry reads back the original audit without new consent.

OpportunitySource.refresh may return optional terms_reference and current
requirements. Unknown metadata stays None and cannot authorize a new resolution.
Superteam derives its reference from SHA-256 of the existing detail response bytes;
no undocumented version endpoint or new HTTP route is invented. Exact-body hashing
is conservative and may invalidate review after harmless response changes.

Use the existing local operator trust boundary and AGENTMINE_OPERATOR_ID. Add thin
eligibility prepare/show/decide commands; parse explicit facts/profile JSON rather
than infer permissions from source prose. No web interface, role hierarchy, paid
AI, automatic submission or generic approval engine.

## Consequences

Approval moves only ELIGIBILITY_CHECK → ELIGIBLE and records the original manual
reason plus HUMAN_ELIGIBILITY_APPROVED. Rejection moves to INELIGIBLE with an audit
reason. Neither creates task, QA, HumanApproval, Submission, payment or revenue.

Only successful resolution and state change persist together; stale or contradictory
decisions cannot leave a partial consent. Source changes cannot be locked atomically
with local persistence; the decision binds the freshly observed context. Other
workflows retain their own existing freshness requirements (F07 is not closed).

Evidence references and facts/profile are trusted operator/adapter assertions, not
automatic verification of third-party documents or remote identity authentication.
Keep underlying captures/checklists and private profile data appropriately protected.
Unsupported rules versions fail closed; future rule/schema changes need an explicit
compatibility/migration decision. No existing snapshot is reset.

## Alternatives

Turning MANUAL into AUTOMATIC lies about the mechanism. A boolean override bypasses
unknown/blocked rules. Reusing submission approval grants the wrong authority.
Writing decision and state separately creates partial audit/recovery windows.
Generalizing every review reason would expand policy and risk permitting fees,
uncertain AI permission or other sensitive actions without a sufficient contract.

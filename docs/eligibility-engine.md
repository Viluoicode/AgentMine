# Eligibility engine (Milestone 2C)

EligibilityEngine is a pure Domain policy. It receives EligibilityFacts,
ParticipantProfile, an explicit timestamp and configured EligibilityPolicy. It
does no I/O, NLP parsing, LLM call, budget spending or provider-specific work.
Application CheckEligibility coordinates stored provenance, source refresh, engine
evaluation and conditional Opportunity persistence.

## Result contract

Eligibility has four statuses: ELIGIBLE, INELIGIBLE, UNKNOWN and
REQUIRES_HUMAN_REVIEW. Its nonempty `reasons` tuple contains unique EligibilityReason
enums with stable uppercase machine values. `reason` remains text for compatibility.
Engine results include every applicable issue in fixed criterion order. A complete
pass has the sole reason ALL_RULES_PASSED. Existing direct domain assessments default
to MANUAL_ASSESSMENT; the application no longer accepts asserted assessments.

Decision precedence is **INELIGIBLE > UNKNOWN > REQUIRES_HUMAN_REVIEW > ELIGIBLE**.
A known blocker rejects even with other absent facts. Without a blocker, missing
evidence takes precedence over a review flag so resolving human review alone cannot
imply eligibility. All contributing reasons are retained; there is no early exit.

## Deterministic criteria

| Criterion | Known result | Missing knowledge |
| --- | --- | --- |
| Open status | Closed → INELIGIBLE / OPPORTUNITY_CLOSED | OPEN_STATUS_UNKNOWN |
| Deadline | At or before evaluation instant → INELIGIBLE / DEADLINE_EXPIRED | DEADLINE_UNKNOWN |
| AI participation | Prohibited → INELIGIBLE; required disclosure without commitment → INELIGIBLE; explicit review policy → REQUIRES_HUMAN_REVIEW | AI_POLICY_UNKNOWN / AI_DISCLOSURE_UNKNOWN |
| Geography | Excluded country or outside nonempty allow list → INELIGIBLE / COUNTRY_RESTRICTION; exclusion wins overlap | GEOGRAPHIC_RESTRICTIONS_UNKNOWN / COUNTRY_UNKNOWN |
| Account | Required and confirmed unmet → INELIGIBLE / ACCOUNT_REQUIRED | ACCOUNT_REQUIREMENT_UNKNOWN / ACCOUNT_STATUS_UNKNOWN |
| Identity | Required and confirmed unmet → INELIGIBLE / IDENTITY_REQUIRED | IDENTITY_REQUIREMENT_UNKNOWN / IDENTITY_STATUS_UNKNOWN |
| Physical presence | Required → INELIGIBLE / PHYSICAL_PRESENCE_REQUIRED; V1 executes digital work | PHYSICAL_PRESENCE_UNKNOWN |
| Task and skills | Only canonical research/data_processing labels supported; missing required skill → INELIGIBLE | TASK_TYPE_UNKNOWN / REQUIRED_SKILLS_UNKNOWN / PARTICIPANT_SKILLS_UNKNOWN |
| Submission | Unsupported → INELIGIBLE; known manual mechanism → REQUIRES_HUMAN_REVIEW / MANUAL_SUBMISSION_REQUIRED | SUBMISSION_SUPPORT_UNKNOWN |
| Time remaining | Positive duration below configured minimum → INELIGIBLE / INSUFFICIENT_TIME_REMAINING; equality passes | Unknown deadline remains DEADLINE_UNKNOWN |
| Payment demands | Upfront fee → REQUIRES_HUMAN_REVIEW / SUSPICIOUS_PAYMENT_REQUIREMENTS; private credentials demanded → INELIGIBLE / SENSITIVE_CREDENTIALS_REQUIRED | PAYMENT_REQUIREMENTS_UNKNOWN |
| Prohibited actions | Any Constitution-prohibited action → INELIGIBLE / PROHIBITED_ACTION | PROHIBITED_ACTIONS_UNKNOWN |

NOT_REQUIRED account/identity requirements ignore unavailable participant details.
Verified empty required skills need no skill inventory. Verified empty geographic
allow/exclusion sets mean unrestricted; unknown restrictions are `None`. Country
codes are two uppercase ASCII letters, without a country-registry claim. Skills are
exact canonical strings with no fuzzy/case-insensitive inference. An unclassified
task is `None`; a declared unsupported task is rejected.

ProhibitedAction enumerates crypto mining, trading, token creation, autonomous
wallets, coding execution, security exploitation, multi-agent swarm, SaaS and
multi-tenancy. Research about a subject is not automatically the prohibited action;
facts describe actions actually required. Private-credential demands mean handing
secrets to the requester, not ordinary authentication through a future adapter.
No payment or physical action is performed.

## Knowledge and time

Deadline distinguishes UNKNOWN, NONE (verified absence) and AT (aware instant).
Remaining time uses UTC instants, including different offsets/repeated local hours.
The minimum time is a nonnegative timedelta explicitly supplied by configuration;
the engine invents no universal duration, effort estimate or financial formula.
Facts default to unknown. Booleans use `None` for unknown, never string truthiness.
Immutable sets and domain enums are validated. Malformed types, negative thresholds,
naive timestamps and contradictory deadline values raise structured DomainError.

Source contracts allow `is_open=None` and `deadline_known=False`. For compatibility
with 2A, `deadline_known=True` remains the default: `deadline=None` with that flag is
an assertion of no deadline. New adapters must set false for missing/uncertain source
deadlines; false cannot carry a date. Discovery retains unknown observations.
CheckEligibility overrides caller open/deadline facts with a fresh correlated source
observation. Other work-starting use cases reject unknown availability with
ApplicationError(UNRESOLVED).

Other requirements and participant capabilities are normalized typed inputs, not
fetched, inferred from prose or externally verified. Uncertain AI terms, geography,
account/identity evidence, skills, submission, payment or actions must remain unknown.
No marketplace API, legal rule, identity provider or payment contract is assumed.
Freshness and authenticity of those inputs need later adapter design.

## Lifecycle and application API

Use `CheckEligibility(repository, source, clock, engine).execute(
EligibilityCheckRequest(facts, profile))`. This replaces the 2B caller-supplied
Eligibility API. Imports remain available from the use-case package and planning
module. The engine needs no LLMProvider, CostLedgerRepository or infrastructure.

NORMALIZED enters ELIGIBILITY_CHECK. UNKNOWN and REQUIRES_HUMAN_REVIEW are stored
in that state; changed pending assessments can be recorded. Fresh resolved facts
can advance to ELIGIBLE/INELIGIBLE. Identical decisions are idempotent and still
refresh before evaluation. Reclassifying advanced/terminal aggregates remains
forbidden. Only ELIGIBLE can enter evaluation/planning. Budget-wait resume rejects
both unknown and human-review eligibility.

Human-review status grants no permission. No override, notification or review
resolution interface is added: future reviewed facts must satisfy the rules.
Manual-submission review remains pending until that workflow is explicitly designed.
Deliverable approval is a separate gate.

## Validation and limits

Domain tests cover all criteria, missing versus verified-empty data, capabilities,
all prohibited actions, status combinations, complete reasons, payment flags,
deadline/minimum-time boundaries, offsets/repeated hours, invalid inputs and immutable
results. Fake-only application tests verify source precedence, pending/resolution,
lifecycle blocking, closure/expiry, freshness/identity, unknown ingestion and conflicts.
Existing workflow/domain/import-boundary checks remain active; no paid call occurs.

The aggregate stores latest eligibility and state history, not full histories of
fact/profile/policy inputs. Durable audit retention remains an adapter requirement.
Continuous reclassification, automatic budget resumption and external evidence
verification are outside this milestone.

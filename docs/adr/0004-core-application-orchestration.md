# ADR 0004: Core application orchestration and explicit assessments

## Status

Accepted for Milestone 2B under the requested implementation scope.

## Context

Ports and guarded domain models exist, but no workflows coordinate persistence,
budget authorization, human review or external observations. Eligibility, valuation,
scoring and QA formulas have not been specified. Provider contracts remain uncertain.

## Decision

Implement thirteen explicit injected use cases. Use supplied typed eligibility,
economic, scoring and QA assessments until dedicated policies are defined. Call an
injected work provider without implementing/wiring any real LLM execution. Return
a review package to the human-facing caller; require explicit approval.

Extend OpportunityRepository to retain source provenance and ExecutionRepository to
retain digest-bound content and work command/response evidence. Add atomic submission
intent claiming. Authorize/commit spending before dispatch, persist IN_PROGRESS before
provider calls, and reconcile existing submission intents. Preserve unknown outcomes
and costs without blind replay or guessed revenue. Leave Domain unchanged.

## Consequences

All workflows run with test-only fakes. Ports gain business persistence capabilities,
not vendor APIs. Conditional writes and journals help recover specific failure windows
but do not provide a cross-repository transaction or general recovery scheduler.
Automatic policies, rework/replanning, budget-resume orchestration and real adapter
semantics remain future work. See [use cases](../application-use-cases.md).

## Alternatives

Inventing eligibility/economics formulas would silently expand product policy. Moving
orchestration into marketplace/AWS adapters would invert dependency direction. A general
workflow framework, service bus or transaction framework would exceed the current need.

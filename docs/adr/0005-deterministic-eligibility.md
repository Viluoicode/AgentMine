# ADR 0005: Deterministic eligibility with explicit unknowns

## Status

Accepted for Milestone 2C under the requested scope. Supersedes ADR 0004's
caller-asserted eligibility path; other economics/score/QA policies remain.

## Context

Eligibility was a supplied status plus free text. AgentMine needs deterministic
checks, machine-readable reasons and explicit incomplete/human-review outcomes
without AI/vendor contracts. Unresolved results must not advance or resume work.

## Decision

Put immutable normalized facts, profile/policy inputs and a pure engine in Domain.
Evaluate all criteria, retain reason codes and use precedence INELIGIBLE > UNKNOWN
> REQUIRES_HUMAN_REVIEW > ELIGIBLE. Block prohibited actions/physical execution;
review suspicious upfront fees and manual submission. Use configured minimum time
and UTC instants, with distinct unknown/no-deadline knowledge. Do not infer terms
from marketplace prose.

CheckEligibility refreshes source open/deadline facts and invokes Domain. Source
contracts explicitly represent unknown availability. Persist unresolved decisions
in ELIGIBILITY_CHECK; allow pending assessment records but never downstream work.
Budget resume also requires resolved eligibility. Legacy direct domain assessments
carry MANUAL_ASSESSMENT for compatibility.

## Consequences

CheckEligibility changes to a facts/profile request plus injected engine. No LLM,
dependency, infrastructure or marketplace behavior is added. Review resolution,
continuous reclassification and evidence verification remain future work. See
[eligibility engine](../eligibility-engine.md).

## Alternatives

LLM classification introduces cost/nondeterminism for these checks. Missing facts
treated as permissive silently authorize uncertain work. A generic rules framework
or new service adds abstractions beyond this fixed V1 policy.

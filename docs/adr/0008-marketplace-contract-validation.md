# ADR 0008: Verified read contracts and explicit marketplace gaps

Status: Accepted for the requested Milestone 3B research and limited adapter scope.
Currency/prize expansion and production activation are not approved by this ADR.

## Context

Superteam documents an Agent API and publishes source schemas. Algora and Opire do
not provide a current external bounty API contract verified by this investigation.
Existing Opportunity requires a concrete potential Money amount; Superteam token,
prize-pool and negotiated reward data cannot always satisfy that boundary honestly.

## Decision

Implement only Superteam's documented read routes with injected transport/time/archive.
Preserve raw successful responses before parsing. Admit only representable fixed project
offers; retain other items with machine-readable normalization issues. Use partial
eligibility facts, never infer task type or payment. Keep full-window pagination
explicitly unsupported rather than invent a cursor. Provide disabled Algora/Opire
OpportunitySource skeletons. Domain/Application and dependency direction stay unchanged.
See [contract evidence and matrix](../marketplace-contracts.md).

## Consequences

Offline fixtures test parsing and port conformance without accounts or paid calls.
Discovery coverage is limited, especially for USDC and prize bounties. No deployment,
automatic polling, posting, payment verification or authenticated smoke test is included.
Future decisions must address token valuation, individual prize selection, source API
permission/stability, idempotent submission and independently evidenced payment.

## Alternatives

Scraping or guessed legacy APIs cannot establish a supported contract. Mapping USDC
to USD, taking a pool as one worker's reward or substituting zero would corrupt economics.
Changing Domain to suit a vendor in this validation stage would expand scope prematurely.

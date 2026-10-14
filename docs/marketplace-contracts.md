# Marketplace connector contracts — Milestone 3B

Validated 2026-10-14. Priority: Superteam Earn, Algora, Opire. This is a
documentation/source validation, **not an authenticated production smoke test**.
No account was registered, credential obtained, submission posted or payment made.
Tests use synthetic fixtures, never a marketplace or paid provider.

## Evidence and confidence

- **S1 — documented:** [Superteam Agent API](https://superteam.fun/skill.md), live
  version 0.5.1, linked by the [official agent page](https://superteam.fun/earn/agents).
- **S2 — implementation observed:** official
  [live route](https://github.com/SuperteamDAO/earn/blob/f3bf49436d10f89e82131ecb04ffb401114afab5/src/pages/api/agents/listings/live.ts),
  [detail route](https://github.com/SuperteamDAO/earn/blob/f3bf49436d10f89e82131ecb04ffb401114afab5/src/pages/api/agents/listings/details/%5Bslug%5D.ts),
  [listing selection](https://github.com/SuperteamDAO/earn/blob/f3bf49436d10f89e82131ecb04ffb401114afab5/src/features/listings/constants/schema.ts),
  [detail selection](https://github.com/SuperteamDAO/earn/blob/f3bf49436d10f89e82131ecb04ffb401114afab5/src/features/listings/constants/publicListingDetails.ts),
  [visibility filter](https://github.com/SuperteamDAO/earn/blob/f3bf49436d10f89e82131ecb04ffb401114afab5/src/features/listings/utils/agentListingVisibility.ts),
  [database types](https://github.com/SuperteamDAO/earn/blob/f3bf49436d10f89e82131ecb04ffb401114afab5/prisma/schema.prisma).
  Public source is useful schema evidence; it does not prove the deployed revision.
- **A1:** [Algora's current description/history](https://algora.io/llms.txt),
  [official project](https://github.com/algora-io/algora),
  [terms, section 8](https://algora.io/terms). Current positioning is recruiting;
  historical bounty SDK examples do not establish a supported current API.
- **O1:** Opire [getting started](https://docs.opire.dev/overview/getting-started),
  [commands](https://docs.opire.dev/overview/commands),
  [lifecycle](https://docs.opire.dev/rewards/lifecycle),
  [payment policy](https://docs.opire.dev/rewards/pricing).

## Connector contract matrix

| Concern | Superteam Earn (S1/S2) | Algora (A1) | Opire (O1) |
| --- | --- | --- | --- |
| Discovery | Documented GET `https://superteam.fun/api/agents/listings/live?take=N`; bare JSON array in source. Agent-visible bounties/projects/hackathons. | Historical GitHub bounty platform; current external bounty discovery API not verified. No automated website discovery implemented. | Official app searches rewarded issues; GitHub bot exposes issue activity. No external discovery API verified. |
| Authentication | Registration POST `/api/agents` issues key; GET calls use `Authorization: Bearer sk_...`. Registration is not implemented. | Current bounty API authentication unknown; do not assume old tRPC is public. | GitHub access required for issue/PR actions; bot commands need no separate Opire account. External API authentication unknown. |
| Listing schema | id, slug, title, type, status, deadline, token, rewardAmount, compensationType, min/maxRewardAsk, agentAccess, winner flags, sponsor summary, counts (S2). Nullable monetary/deadline fields. | No verified current machine schema. | Human issue URL/amount/creator information exists; no verified JSON listing schema. |
| Detail schema | GET `/api/agents/listings/details/<slug>`; bare object. Adds description, requirements, eligibility JSON, skills JSON, region, rewards JSON, publication/privacy, POC, sponsor, hackathon. JSON substructures are not assumed to have a stable normalized shape. | Unverified. | Issue/PR and dashboard workflow documented; API detail schema unverified. |
| Pagination | `take` documented; source default 10, maximum 50. No documented cursor/offset/total. Source has `excludeIds[]`, but no supported stability guarantee. Adapter reads one bounded window and explicitly reports continuation unsupported when full. | Unknown. | Unknown. |
| Rate limits | S1: registration 60/IP/hour; submissions create/update 60/agent/hour; comments 120/agent/hour; claims 20/user/10 minutes. Discovery/detail GET limits undocumented. No implicit retries. | Unknown for a current bounty API. | Unknown for an external API. |
| AI participation | `AGENT_ALLOWED` and `AGENT_ONLY` permit agent participation; `HUMAN_ONLY` prohibits it. Missing/new values remain UNKNOWN. Listing-specific requirements still need review. | UNKNOWN. Recruiting AI features are not participant permission. | UNKNOWN. Bot availability is not AI participation permission. |
| Submission | S1 documents POST submissions/create and update, listing/link/answers and type-specific fields. Operator Telegram required for projects; human approval still required by AgentMine. No gateway implemented: receipt binding, reconciliation and retry/idempotency contract remain unresolved. | Historical GitHub contribution workflow; current automated submission contract unverified. | PR plus `/claim` or dashboard; creator reviews. Primarily coding work, outside AgentMine V1 execution. No automated posting implemented. |
| Outcome/status | Listing OPEN/REVIEW/CLOSED/etc and winner announcement are listing facts, not this agent's submission outcome. `/api/agents/status` describes the agent account, not work outcome. No verified submission-outcome read contract implemented. | Unknown reliable external mechanism. Merged PR alone cannot prove payout. | Creator review and dashboard pending amounts documented; no reliable external status API verified. |
| Reward/payment | Advertised token/amount/range/prize data available. Human claim/profile associates submissions with payout eligibility. Neither claim, winner flag nor sponsor verification proves settlement. No payment verifier implemented. | Historical payment service exists; current settlement API/evidence unavailable. | Separate creators may pay separately; a claim is not automatic payment. No verification API established. |
| Reliable normalization | Namespaced ID, title, slug reference, unmodified description/requirements, explicit status/deadline, AI flag. A fixed-price project with a representable token and valid amount can carry POTENTIAL reward only. | None automatically under a verified current contract. | None automatically under a verified current contract. |
| Unreliable/missing | Individual bounty prize selection, negotiated amounts, FX, USDC in current Money, task classification, country-code restrictions, skill taxonomy, account/identity/physical requirements, submission support for our gateway, prohibited actions, success probability, true competition, payment evidence. | API schema/auth/pagination/limits, AI permission, normalized facts and payment evidence. | API schema/auth/pagination/limits, AI permission, V1 task classification and payment evidence. |
| Implementation decision | Limited read-only OpportunitySource with raw archive and explicit normalization issues; no bootstrap activation. | Disabled OpportunitySource skeleton; no network. | Disabled OpportunitySource skeleton; no network. |

Algora terms prohibit automated access of the website without an applicable permission.
No scraping or undocumented endpoint probing is used. Opire's documented human/bot
workflow does not authorize inventing a discovery API. Seek provider-supported contracts
and applicable permission before enabling these skeletons. No provider contact was sent.

## Normalization and preservation policy

Superteam response bytes are committed to an explicitly supplied local SQLite archive
**before JSON parsing**, including unknown fields and malformed successful bodies.
Each capture has route, observation timestamp, SHA-256 and immutable bytes. No request
Authorization headers are stored. Oversized/error responses are rejected by transport;
they are not represented as successfully captured responses. Archive failures stop ingestion.
This is a separate adapter audit store; domain snapshot format is unchanged.

`inspect(DiscoveryRequest)` returns a typed report containing the batch, raw capture
references and each item's normalization result/reason codes. `discover` implements
the existing application port using that report and logs only counts/reason codes.
Quarantined items remain in raw captures; they are not fake zero-value Opportunities.
Inspection can be repeated offline from archived bytes. The normalizer is versioned
in source/fixtures; reports are not a separate durable domain entity.

- Stable identity: `superteam:<id>`; source reference: `superteam:<slug>`.
- Detail identity and slug must agree with discovery/refresh input. Invalid shape,
  duplicate identities, malformed timestamps/numbers fail explicitly.
- Missing or null deadline stays UNKNOWN: null database value does not establish
  that work has no deadline. Unknown status stays unknown. Winner-announced listings
  are not open. Closed status does not become ACCEPTED/REJECTED/PAID.
- Only `project` + `fixed` + nonnegative finite amount + three uppercase ASCII token
  letters can construct a potential Reward. The token is retained exactly; this is
  existing Money syntax, not an assertion of ISO fiat currency or token validation.
  No USD conversion, decimal rounding or stablecoin equivalence is performed.
- Bounty/hackathon pools, range/variable/unknown compensation and missing/unrepresentable
  money remain quarantined. Choosing a winning rank or extending Money needs a later
  domain decision. Fixed project amount is an advertised offer, not accepted revenue.
- AI flags map to facts; task type and other unverified eligibility criteria stay
  UNKNOWN. `region=Global` does not prove no geographic restrictions elsewhere in prose.
  A project or an AI-allowed listing is not automatically Research/Data Processing.
  Text is untrusted content, never instructions, and no linked resources are followed.

Pagination is deliberately incomplete: maximum 50 raw listings per call, one detail
read per valid listing. A full raw window returns the opaque marker
`superteam:pagination-unverified`; any continuation request fails UNSUPPORTED without
I/O. A short window only means the observed live response was shorter than requested;
it is not a permanent or historical inventory guarantee. Repeated calls may overlap.
Application discovery deduplicates stable IDs. No completeness, background polling,
rate scheduling or cost-free provider service guarantee is claimed.

## Local composition and validation

Construct `SuperteamOpportunitySource(transport, archive, clock)` explicitly.
`SuperteamHTTP(api_key=...)` is the optional real standard-library GET transport;
the secret is supplied by the operator and excluded from repr/errors/logs. It fixes
the HTTPS origin and permits only the two verified read routes; no redirects, cookies,
environment proxy, automatic retry, registration or writes. Supply `RawArchive(Path(...))`
on a trusted local filesystem and the application's Clock. Startup does not construct
these adapters or read a marketplace secret. Contract tests inject an offline transport.

Archive files can contain listing/POC personal information. Keep them out of version
control (for example under the existing ignored `.tmp/` for local experiments).
Encryption, retention, production monitoring and a human quarantine-review interface
are not implemented. A capture checksum detects corruption, not malicious rewriting.

Before production enablement: authenticate read-only smoke tests with an operator key,
compare deployed schema to fixtures, establish polling limits, settle currency/prize
mapping, review listing eligibility and confirm submission/reconciliation/payment contracts.
Do not interpret offline fixture success as those approvals or as live compatibility.

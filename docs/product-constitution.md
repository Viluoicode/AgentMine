# AgentMine Product Constitution

This document records the product scope supplied by the project owner in this
conversation. No separate pre-existing Constitution was available in the workspace.
It does not approve unresolved architecture decisions or external API contracts.

## Product and V1 goal

AgentMine is a budget-aware semi-autonomous work-to-earn AI agent.

Discover real digital bounty opportunities → determine eligibility → evaluate
economic attractiveness → perform supported work → QA the deliverable → request
human approval → submit through supported mechanisms → track outcome → verify
reward → calculate net verified value.

## North Star

Verified Reward − AI Cost − Tool Cost − Infrastructure Cost − Transaction Cost.

## Scope

V1 supports Research and Data Processing.

V1 excludes crypto mining, trading, token creation, autonomous wallets, coding agent
execution, security exploitation, multi-agent swarm, SaaS, and multi-tenancy.

## Architecture constraints

Clean Architecture / Hexagonal Architecture is mandatory. AWS and marketplaces are
replaceable infrastructure adapters. Core business rules belong in Domain/Application.
The eventual AWS workshop uses Lambda, DynamoDB and Bedrock, without placing AWS
logic or dependencies in Domain.

Human approval precedes submission. Uncertain external contracts must be documented,
not invented. Automated tests must not make real paid API calls.

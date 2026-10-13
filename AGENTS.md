# AgentMine engineering rules

Read all repository documentation, including `docs/product-constitution.md`, before
implementation. User instructions take precedence. Do not expand product scope.

Before implementing: inspect the repository, explain existing behavior, identify
exact files to change, and state architectural implications. Make the smallest
coherent change, run relevant checks, and report changes and remaining limitations.

Use Clean Architecture / Hexagonal Architecture:
Presentation → Application → Domain. Infrastructure implements inner-layer ports.
Domain must not depend on AWS, boto3, Bedrock, DynamoDB, Lambda, FastAPI, Superteam,
Algora, Opire, HTTP clients, database libraries, or external AI SDKs.

Use Python 3.12+, strong typing, explicit domain models and use cases, dependency
inversion, structured errors/logging, separate configuration, applicable idempotency,
auditability, and testability. No hidden global state, unnecessary abstractions,
premature microservices, god classes, or generic utils.py dumping ground.
Automated tests must never make real paid API calls.

Uncertain external API contracts must not be invented. Preserve the appropriate
port/adapter boundary and document unresolved assumptions.

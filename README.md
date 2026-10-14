# AgentMine

AgentMine is a budget-aware semi-autonomous work-to-earn AI agent. V1 is intended to
discover real digital bounties, determine eligibility, assess economics, perform
supported Research/Data Processing, QA deliverables, request human approval,
submit through supported mechanisms, track outcomes, verify rewards, and calculate
net verified value.

The North Star is **Verified Reward − AI Cost − Tool Cost − Infrastructure Cost
− Transaction Cost**.

See [Product Constitution](docs/product-constitution.md) for scope and
[architecture](docs/architecture.md) for dependency rules.

## Architecture principles

- Clean Architecture / Hexagonal Architecture: Presentation → Application → Domain.
- Infrastructure implements ports defined by inner layers.
- Domain has no AWS, marketplace, database, HTTP, framework, or external AI dependencies.
- Bootstrap owns configuration and explicit dependency wiring; no hidden global state.
- Business rules belong in Domain/Application. Adapters remain replaceable.
- Python 3.12+, strong typing, structured errors, testability and auditability.
- Automated tests never make real paid API calls.

## Development setup

Use Python 3.12 or newer. From the repository root, on Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

On systems with `python3`:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

Runtime dependencies: none. Development tools: pytest, Ruff, mypy. Setuptools is
the packaging build backend. The development extra currently resolves tool versions
from the package index; a reproducible tool lock is not yet provided.

`.env.example` documents supported settings. No dotenv dependency or implicit file
loading is used. Defaults are `development` and `INFO`. Export overrides explicitly:

```powershell
$env:AGENTMINE_ENVIRONMENT = "development"
$env:AGENTMINE_LOG_LEVEL = "INFO"
.\.venv\Scripts\python.exe -m agentmine.bootstrap.main
```

The installed `agentmine` command invokes the same bootstrap. At Milestone 1A,
startup only validates configuration. Log level is reserved for later logging setup;
no work is executed and no adapters are instantiated.

## Checks

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m pytest
```

On other systems, replace the interpreter path with `.venv/bin/python`.

Tests are organized under `tests/unit`, `tests/integration`, `tests/contract`, and
`tests/e2e`. Application contract validation lives in unit tests; Milestone 3A integration tests exercise real local SQLite adapters. External
adapter contract tests remain deferred.

## Current milestone status

Milestone 1A provides package structure, packaging, configuration validation,
bootstrap, test structure, static-check configuration, and documentation.
Milestone 1B adds immutable core domain models, guarded lifecycle transitions,
explicit reward stages, local budget accounting, operating modes, and evidence
binding for QA, approval, submission and payment. See [domain model](docs/domain-model.md).
Execution engines, complete operational logging, external payment verification
and provider/marketplace adapters remain future work.

Milestone 1C adds daily/monthly AI authorization, task limits, spending-approval
thresholds, separate estimate/actual accounting, derived modes and guarded
WAITING_FOR_BUDGET resumption. AI exhaustion preserves free operations. See
[budget domain](docs/budget-domain.md). Reservations exist within domain snapshots; Milestone 3A adds conditional atomic
SQLite persistence across local callers.

Milestone 2A adds ten application-owned ports, typed request/response contracts,
structured boundary errors and Domain/Application import guards. No adapter or
use case was implemented in 2A. See [application ports](docs/application-ports.md) for
ownership, idempotency, concurrency requirements and unresolved external contracts.

Milestone 2B adds all thirteen core application use cases with injected ports,
typed workflow contracts and test-only fakes. Tests cover discovery-to-plan,
rejection paths, approval/submission/payment and selected failure recovery. Eligibility,
economics, scoring and QA assessments remain explicit inputs; no real LLM execution
or external integration is implemented. See [use cases](docs/application-use-cases.md).

Milestone 2C adds a pure deterministic eligibility engine with all twelve required
criteria, four statuses and machine-readable reasons. CheckEligibility consumes
facts/profile inputs and refreshes source availability before applying domain rules.
Unknown/human-review decisions remain pending and cannot authorize work. See
[eligibility engine](docs/eligibility-engine.md).


Milestone 2D adds deterministic expected-net-value calculations and an explainable
0-100 opportunity score with REJECT/WATCH/RECOMMEND/ATTEMPT recommendations. Domain
retains subjective predictions, cost estimates, signal components and policy snapshots;
Application calculates and persists assessments through existing ports. No forecasts
create verified revenue. See [economic scoring policy](docs/economic-scoring.md).

Milestone 3A adds local SQLite implementations of all repository ports, complete
snapshot rehydration, atomic budget/audit commits, submission intent claiming and
operational/financial queries. Domain/Application remain unchanged. The standard-library
sqlite3 adapter needs no new dependency. See [local persistence](docs/local-persistence.md)
for explicit bootstrap setup, access patterns, guarantees and limits.

AWS Lambda, DynamoDB and Bedrock are future infrastructure choices. No AWS or
marketplace integration is included. See [milestones](docs/milestones.md) and
[ADR directory](docs/adr/README.md).

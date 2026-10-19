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
`tests/e2e`. Application contract validation lives in unit tests; Milestone 3A integration
tests exercise real local SQLite adapters. Milestone 3B contract tests use synthetic
Superteam fixtures, fake HTTP and local raw archives without network or credentials.

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

Milestone 3B records the [connector contract matrix](docs/marketplace-contracts.md)
for Superteam Earn, Algora and Opire. Superteam has a limited read-only discovery/detail
adapter with exact raw capture and conservative normalization. USDC, prize pools and
negotiated rewards remain quarantined; full pagination is explicitly unsupported.
Algora/Opire are disabled skeletons pending verified contracts/access permission.
No adapter is activated at startup; no authenticated marketplace smoke test, automated
submission or payment verifier is included. No runtime dependencies were added.

Milestone 3C hardens the Superteam adapter: duplicate source rows are fetched once,
repeat SQLite ingestion preserves original provenance/lifecycle, missing facts remain
UNKNOWN, agent access is checked again on refresh, and HTTP failures have safe machine
reasons. An optional `python -m agentmine.bootstrap.superteam_smoke --live` probe reads
only when explicitly invoked with an operator-provided environment key. It has not
been run against production. See [adapter setup, offline tests and smoke instructions](docs/superteam-source.md).
All default pytest tests block network connections. Currency/prize, full pagination
and slug-rename migration limitations remain explicit; Domain/Application are unchanged.

Milestone 4A adds opt-in Bedrock and offline Mock LLM providers, strict structured
output validation, persisted budget authorization and usage accounting. Planning
assistance is part of structured Research/Data drafts; AI QA requires explicit
deterministic-QA insufficiency. See [LLM setup and limitations](docs/llm-infrastructure.md).
The optional `bedrock` extra supplies boto3; base installation remains dependency-free.
No live Bedrock invocation or automatic startup integration is enabled.

AWS Lambda and DynamoDB remain future infrastructure choices. See [milestones](docs/milestones.md) and
[ADR directory](docs/adr/README.md).

Milestone 4B adds [ResearchWorker](docs/research-worker.md): validated Research plans,
approved-tool evidence collection, source provenance, separate facts/analysis/uncertainties,
portable report/source/findings artifacts and durable recovery checkpoints. Tools and LLMs
remain injected; no live search integration, submission or new dependency is introduced.

Milestone 4C adds [DataWorker](docs/data-worker.md): deterministic CSV/JSON collection,
extraction, categorization, normalization, validation and lookup enrichment. AI is optional
and limited to explicitly designated semantic fields. Outputs preserve row/field provenance;
SQLite checkpoints support cost accounting and recovery. No new dependency or submission.

Milestone 4D adds [Deliverable QA](docs/deliverable-qa.md): deterministic checks first,
Research/Data validation next, and budget-authorized AI review only for semantic requirements.
Reports preserve reasons and evidence. PASS means READY_FOR_HUMAN_REVIEW; human approval
and submission remain separate. No dependencies or live integrations were added.

Milestone 5A adds the [human approval boundary](docs/human-approval.md): immutable operator
review packages, APPROVE/REJECT/REQUEST_REVISION audit, scoped spending consent and guarded
rework. Approval never automatically submits. One local operator; no IAM, wallet or sensitive
account executor is added.

Milestone 5B adds [Submission System](docs/submission-system.md): API/MANUAL/UNSUPPORTED
modes, approved manual packages, operator receipt recording and retained response metadata.
Retries reuse receipts or reconcile; changing IDs cannot resend the same deliverable version.
All modes require human approval. No production marketplace POST adapter or live send is added.

Milestone 5C adds [Outcome and Payment Tracking](docs/outcome-payment-tracking.md): retained
outcome/payment observations, rejection reasons, independent settlement evidence and current
recorded-cost economic metrics. ACCEPTED remains distinct from PAID; only proven payment
creates verified revenue. Legacy PAID data lacking proof requires explicit re-verification.
No production payment verifier, wallet action or dependency is added.

Milestone 5D adds [Historical Learning Dataset](docs/historical-learning.md): immutable
observations joining stored forecasts, attributed costs, attempt/skip decisions and verified
outcomes. Read-only statistics cover Research/Data acceptance, cost prediction errors and
source cohorts, with latest/as-of deduplication. Capture is explicitly invoked. No model is
trained and production scoring behavior is unchanged; no dependency is added.

Milestone 6A proves the [local end-to-end flow](docs/local-e2e.md) for Research and Data
through QA, explicit simulated human approval, fake submission/payment, verified revenue
and net value. SQLite persistence and worker journals survive reopen/retries. Budget
exhaustion preserves discovery; restored work is refreshed/revalidated before resuming.
Run `python -m pytest tests/e2e -q -s -p no:cacheprovider` for execution reports.
All external effects are fixtures, external API spend is $0, and no AWS deployment starts.

Milestone 6B adds optional [DynamoDB persistence](docs/dynamodb-persistence.md), preserving
existing Domain/Application contracts. Access-pattern keys, sparse GSIs, transactional
budget/audit writes and submission/payment uniqueness guards are tested with Moto's
in-process DynamoDB emulator. Install `.[dev,dynamodb-test]` to run these tests; without
the optional dependencies they skip explicitly. No live AWS table or deployment is created.

Milestone 6C adds [thin Lambda runtime handlers](docs/lambda-runtime.md) for discovery,
normalization, outcome tracking and payment verification. Explicit dependency factories
compose existing use cases; versioned events, correlation logs and sanitized raised errors
stay at the presentation/runtime boundary. Tests use fakes and DynamoDB emulation. No new
dependency or AWS deployment; production external adapter wiring remains explicit.

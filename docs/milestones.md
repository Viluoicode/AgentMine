# Milestones

## Milestone 3C: Superteam OpportunitySource Adapter

Scope: harden the existing verified GET adapter, collapse duplicate external IDs,
preserve raw metadata and original ingestion provenance, quarantine missing/forbidden
agent participation, expose structured read failures, and provide a gated live smoke CLI.
No new endpoint, submission mechanism, currency conversion or pagination contract is assumed.

Validation: saved synthetic fixtures, normalization/failure tests, duplicate ingestion
through reopened SQLite, offline smoke-command tests and a suite-wide network block.
Production smoke is optional and was not executed. Domain/Application and runtime
dependencies remain unchanged. See [setup and limitations](superteam-source.md).

## Milestone 3B: Marketplace Integration Validation

Research and contract matrix cover Superteam Earn, Algora and Opire, in that order.
Official documentation and public source support a limited Superteam GET adapter;
live authenticated compatibility remains untested. Raw successful responses are
archived before parsing. Fixed project offers map only when their reward fits existing
Money semantics; other offers retain explicit normalization issues. Full pagination,
submission/outcome/payment automation and unsupported source APIs remain disabled.
Algora/Opire have documented no-I/O skeletons. See [contracts](marketplace-contracts.md).

Validation: synthetic source-backed fixtures, strict normalization, raw retention,
safe transport errors/routes, existing application-port usage and full regression checks.
No domain/application edit, dependency installation or paid API call is required.

## Milestone 1A: Project Foundation

Scope: Python 3.12+ project, Clean Architecture packages, dependency management,
configuration foundation, four test areas, Ruff/mypy/pytest configuration,
bootstrap skeleton, documentation, ADR directory, and local environment example.

Acceptance: packaging installs, bootstrap validates settings, relevant tests pass,
and linting, formatting and strict type checking pass.

Excluded: business behavior, cloud infrastructure, AI integrations and marketplaces.

## Later milestones

Execution engines, automated QA procedures, human interfaces,
external submission/payment verification and adapters remain future work. Domain
records of those concepts are provided by Milestone 1B. Exact scope and changed
files must be reviewed per milestone.

## Milestone 1B: Core Domain Model

Models: Opportunity, Reward, ExpectedValue, Cost, Eligibility, Budget, BudgetPolicy,
OperatingMode, Task, TaskType, Execution, Deliverable, QAResult, HumanApproval,
Submission and Outcome. See [domain model](domain-model.md).

Acceptance: valid lifecycle paths and financial distinctions have unit coverage;
invalid transitions, negative reward/cost, unsupported work, SCOUT_ONLY execution,
evidence mismatch and budget overspend fail explicitly. Lint, format and strict
type checks pass. No new dependency or infrastructure is introduced.

## Milestone 1C: Budget and Operating Mode Domain

Scope: configurable AI daily/monthly ceilings, task limit, spending-approval
threshold, estimate authorization, actual recording, derived modes, budget wait
and guarded resumption. Free operations continue when AI budget is exhausted.

Acceptance: tests cover normal authorization, ceilings, SAVER/SCOUT_ONLY, overruns,
period/policy restoration and expired waiting tasks. Lint, format and strict typing
pass. No billing/provider API or infrastructure is integrated.

## Milestone 2A: Application Ports

Application-owned OpportunitySource, five repository ports, LLMProvider,
SubmissionGateway, PaymentVerifier and Clock use typed business contracts.
Contracts define revision-checked opportunity writes, atomic ledger/audit commits,
budget-scoped AI requests, submission reconciliation and evidenced payment results.
See [application ports](application-ports.md).

Acceptance: contract validation, architecture import guards, existing tests,
Ruff formatting/lint and strict mypy pass. No concrete infrastructure, use case,
new dependency or unnecessary fake is introduced. External contract verification
and adapter conformance remain deferred.

## Milestone 2B: Core Application Use Cases

Thirteen injected coordinators cover discovery through verified payment using typed
commands/domain actions. Explicit supplied assessments avoid inventing eligibility,
economics, scoring or QA policy. No real LLM execution or external adapter exists.
See [use cases](application-use-cases.md).

Acceptance: fake-only tests demonstrate discovery to planning and ineligible,
budget-denied, unsupported and expired rejection paths, plus a complete conceptual
submission/payment path and recovery safeguards. Existing domain/architecture tests,
Ruff and strict mypy remain passing. No new dependency or infrastructure is added.

## Milestone 2C: Eligibility Engine

Pure deterministic rules cover open/deadline facts, AI policy, geography,
account/identity, physical presence, task/skills, submission support, time remaining,
suspicious payment demands and prohibited actions. Four statuses carry unique
machine-readable reasons. UNKNOWN preserves missing facts; human review grants
no automatic permission. See [eligibility engine](eligibility-engine.md).

Acceptance: extensive rule/combination/boundary and fake application tests cover
pending resolution and downstream/budget-resume guards alongside existing checks.
No LLM call, dependency or concrete adapter is introduced.

## Milestone 2D: Economic Engine and Opportunity Scoring

Scope: deterministic reward/probability/four-category-cost calculation, explicit
subjective predictions, normalized signals, 0?100 weighted scoring, explainable
recommendations and stored components/policy snapshots. Numeric input tests and
fake-only application persistence/retry tests verify forecasts never create revenue.
See [policy and limitations](economic-scoring.md). No dependency or infrastructure added.

## Milestone 3A: Local Persistence Adapter

All five repository ports have SQLite implementations for opportunities, evaluations,
executions, submissions/outcomes and budget/cost state. Local queries support lifecycle,
source, scores, waiting/review/unpaid work, execution history, actual costs and verified
revenue. Integration tests cover real files, reopen/retry, concurrency, atomic rollback,
financial boundaries and the same Application workflow with either repository backend.
Domain/Application are unchanged. No third-party dependency or external integration is added.
See [local persistence](local-persistence.md).

Milestone 4A: implemented opt-in Bedrock/Mock LLM providers, strict local schemas,
budget authorization and usage accounting. No live invocation. See
[LLM infrastructure](llm-infrastructure.md) and [ADR 0009](adr/0009-structured-budgeted-llm.md).

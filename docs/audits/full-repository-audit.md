# AgentMine — Comprehensive Post-Implementation Audit

## 1. Executive Summary

**Final verdict: NOT_READY.** Is AgentMine ready for a controlled real-world bounty
experiment? **NO, in its current repository-delivered form.**

AgentMine implements substantial business logic: guarded state transitions, typed
ports/use cases, deterministic eligibility and economics, reserved/actual cost
accounting, workers, evidence-bearing QA, operator review, durable submission
claims and payment-evidence invariants. These are functional components, not empty
skeletons. They support a meaningful, fully offline demonstration.

However, there is no shipped operational composition taking a real opportunity
through the complete Research/Data workflow. No production submission/outcome
gateway or independent payment-verification adapter exists. Manual submission
packages exist, but manual eligibility review has no application resolution path.
Rework after QA/operator revision has no executable application workflow. AWS
adapters exist, but the cloud composition and shared paid-dispatch/raw-source
durability are incomplete.

An additional, newly reproduced defect is significant: cancellation during the
pre-submission refresh can leave the opportunity SKIPPED while one external send
has already occurred and confirmation evidence is retained. The stale-state check
happens too late to prevent dispatch, and ordinary retry cannot repair that state.
This is a trusted concurrent-writer scenario, not a demonstrated remote exploit.

**Findings: P0 = 0; P1 = 6; P2 = 5; P3 = 0.** Counts include confirmed missing
functionality/operational evidence as well as defects; those types are distinguished
in section 14. No P0 was established within the inspected entry points and trust
model. This does not prove the absence of other defects.

Current checks: **959 tests passed**, including unit, contract, integration and
local E2E; lint, format and strict type checking passed. Passing tests did not
cover the newly reproduced cancellation interleaving. No real bounty, reward,
authenticated marketplace read, paid inference or deployment was performed.

## 2. Audit Scope and Limitations

Review date: **2026-10-25**, Asia/Bangkok. Baseline commit:
`21c5d7c44916d9a35d47ff305f6949991ca97140`. Working tree was clean initially.
Only this report is added. No production/test code, existing data, resources,
dependencies or previous documentation were modified. No remediation is started.

The latest audit request defines an experimental goal of at least one legitimate
Research/Data reward worth USD 1 or more. That target is not a guarantee and has
not been achieved by any evidence examined here. The checked-in Constitution
defines the same work-to-verified-value scope but does not itself establish a real
reward or a USD conversion policy.

Evidence types used throughout:

- **Observed:** source/AST/file-layout inspection, including all 125 production
  Python modules for imports, classes and empty implementations; focused manual
  review of business, persistence and side-effect boundaries; AGENTS.md,
  architecture, all 20 ADRs, product requirements and test configuration.
- **Executed:** safe offline checks and three in-memory diagnostic probes described
  below. Test fakes are used deliberately; no probe sends a real request.
- **External documentation:** public primary-source pages, accessed read-only.
  These establish documented contracts, not authenticated/deployed compatibility.
- **Unverified:** real provider behavior, real source availability/eligibility,
  model output quality, independent payment authenticity, live AWS concurrency,
  host/IAM permissions, production costs, load and restore procedures.

The network fixture in `tests/conftest.py:10–19` blocks ordinary outbound sockets
while tests execute. This is not a general sandbox against arbitrary code. No
untrusted downloaded script was executed. Debug-log filenames were inventoried;
their contents, credentials, private keys and sensitive environment values were
not harvested. No exhaustive secret-content or vulnerability scan is claimed.

No live read-only integration was attempted because no authorized test account/key
was required or supplied for this audit. Public documentation retrieval is not a
live API smoke test. Python **3.14.2** was used; compatibility with every supported
Python 3.12+ release was not independently tested.

## 3. Repository Inventory

| Area | Observed implementation |
| --- | --- |
| Packaging | `pyproject.toml:1–29`: setuptools, Python >=3.12, no base runtime dependencies; dev pytest/Ruff/mypy, optional boto3 and Moto extras; console command points at validation-only bootstrap. |
| Domain | 20 modules including package initializer: Opportunity/Task/Execution, Money/Reward/ExpectedValue, Budget/Policy/operating modes, eligibility, economics/scoring, QA, approval, payment, history/statistics and metrics. |
| Application | 50 modules including initializers: typed contracts, nine port modules, BudgetManager/ApprovalGuard, use cases, Research/Data workers and deterministic/AI QA. |
| Infrastructure | 42 modules including initializers: SQLite and DynamoDB repositories/journals, tagged snapshot codec, Superteam read transport/normalizer/raw archive, disabled Algora/Opire, Bedrock/Mock providers, pricing/security/dispatch journal. |
| Presentation | Four modules including initializer: operator CLI, Lambda event parser and Lambda handlers. No FastAPI/web frontend. |
| Bootstrap | Eight modules including initializer: local/DynamoDB composition, operator CLI, read-only Superteam smoke, Lambda factory, configuration and validation-only main. |
| Storage | `infrastructure/sqlite/database.py:33–69`: schema version 1, snapshots table and indexes, FULL synchronous writes and BEGIN IMMEDIATE. `infrastructure/snapshots.py:46–270`: allowlisted JSON rehydration and narrow legacy handling. Separate raw-archive and LLM-call SQLite stores. DynamoDB key/index schema is in `infrastructure/dynamodb/store.py`, composed by bootstrap. No general migration/rollback framework. |
| Tests | Unit, contract, integration and E2E; collection counts: 678 / 158 / 116 / 7 respectively. Fixtures include Superteam/Bedrock contracts and synthetic Research/Data opportunities. SQLite tests use real files; DynamoDB uses Moto. |
| Docs | 51 Markdown documents under docs before this report, including 20 numbered ADRs. Workshop/security/architecture/resilience/readiness reports are historical claims checked against source here, not treated as independent validation. |
| Configuration | `bootstrap/config.py:1–54`, `.env.example`: immutable validated settings, explicit environment mapping; .env is not automatically loaded. Operator has explicit live-source opt-in and configured actor. |
| CI/deployment | No tracked CI workflow, lock/requirements artifact, deployment template, Dockerfile or Terraform/SAM/CDK resource configuration was found. Lambda callables require deployment-owned wiring. |

No production `pass` body or `raise NotImplementedError` was found by AST inspection.
Protocol ellipses are declarations. Algora/Opire deliberately raise UNSUPPORTED;
they must not be counted as completed connectors. Mock defaults such as “Mock
research draft” are deliberate synthetic outputs, not real research execution.

No confirmed dead-module/god-class/generic-utils violation was established.
Largest classes are Opportunity (368 lines), Budget (291), SnapshotCodec (225),
ResearchWorker (212). They are cohesive but deserve maintenance attention. Mere
size, repeated boundary validation or conditional-write guards is not evidence of
duplicated domain policy. A whole-repository usage proof was not established for
every exported symbol. `OperatingMode.prefers_deterministic` is currently only a
policy signal; there is no automatic engine-selection consumer in production code.

## 4. Clean Architecture Assessment

**The dependency direction is substantially correct.** Source inspection and the
executed AST guards support:

```text
Presentation → Application → Domain
Infrastructure → Application ports / Domain values
Bootstrap → explicitly composed layers
```

- Domain import roots are its own package plus standard-library value/model tools;
  no AWS, HTTP, database, framework or marketplace adapter imports were found.
- Application uses typed contracts/ports and Domain, not concrete SDK/storage
  adapters. Workers/QA live in Application; pure rules live in Domain.
- SQLite/DynamoDB classes structurally implement inner protocols. Runtime SDK
  request shapes, transactions, keys, transport errors and normalization stay in
  infrastructure. Repository uniqueness/CAS guards preserve port guarantees rather
  than invent eligibility/scoring policy.
- CLI review preparation/read is application-owned; Lambda parsing, mapping,
  dependency resolution and correlation logging are thin presentation behavior.
- Composition factories are explicit, not ambient service locators. No hidden
  global mutable SDK client or application state was found.
- `tests/unit/test_architecture.py:10–171` checks layers, nested/type-only imports,
  several standard-library I/O escapes and a static import graph. No static cycle
  was detected. Dynamic reflection and all implicit import mechanisms are not proven.

Snapshot rehydration restores private aggregate state in infrastructure
(`infrastructure/snapshots.py:159–270`). This is a deliberate trusted-storage coupling,
not a remote deserialization sandbox. Database writers are trusted. Checksums do
not authenticate hostile modifications. Large snapshots/codec migrations and
trusted direct domain mutation are risks to manage, not newly confirmed architecture
violations. No major dependency-direction violation merits a separate finding.

## 5. Functional Completeness Matrix

Statuses describe the capability at the stated boundary, not provider certification.
`IMPLEMENTED_AND_TESTED` means executed offline behavior is meaningful for that
local/pure capability. Real integrations remain PARTIAL or explicitly unverified.
Paths below are relative to `src/agentmine/` unless prefixed `tests/`.

| # | Capability | Status | Implementation evidence / relevant files | Executed test evidence | Missing functionality / production limit |
| --- | --- | --- | --- | --- | --- |
| 1 | Opportunity discovery | PARTIAL | `application/use_cases/planning.py:31–65`; Superteam `inspect:58–101` | `tests/contract/test_superteam_source.py`; workspace integration | Real HTTP code exists, but no authenticated smoke; bounded window, not complete inventory. |
| 2 | Source normalization | IMPLEMENTED_AND_TESTED | `infrastructure/marketplaces/superteam_normalization.py:131–192`; application normalization is a lifecycle transition | Superteam normalization contracts | Only fixed-price projects with representable three-letter assets; USDC/pools/ranges quarantined. Partial eligibility facts. |
| 3 | Deduplication | IMPLEMENTED_AND_TESTED | Superteam `inspect:67–86`; discovery stable-ID/provenance and orphan recovery | Source duplicate/reopen tests; `tests/integration/test_resilience.py` | Changed ID/slug mapping conflicts rather than automatically migrating; no complete source census. |
| 4 | Eligibility checks | IMPLEMENTED_AND_TESTED | `domain/eligibility_rules.py:1–151`; `application/use_cases/eligibility.py:16–39` | Domain eligibility + application eligibility tests | Deterministic facts are supplied assertions; no general review-resolution path (F04). |
| 5 | AI participation checks | PARTIAL | Normalizer `agent_policy:122–128`; Superteam refresh `112–117` | Unknown/prohibited policy contract tests | Current source AI policy checked, but other changed requirements are not refreshed (F07). |
| 6 | Economic evaluation | IMPLEMENTED_AND_TESTED | `domain/economics.py`; `planning.py:81–95` | `tests/unit/domain/test_economics_scoring.py` exact numerical cases | Forecast probability/cost inputs are subjective or caller-supplied, not empirically verified. |
| 7 | Scoring | IMPLEMENTED_AND_TESTED | `domain/scoring.py`; `planning.py:99–149` | Component, threshold, unknown-signal, rounding tests | Heuristic policy; recommendation does not enforce automatic task selection or spending. |
| 8 | Budget authorization | IMPLEMENTED_AND_TESTED | `application/budget_manager.py:32–88`; `domain/budget.py:205–316` | Budget, approval, real SQLite lock, conditional-write tests | Requires trusted pricing/complete cost estimates and intact authoritative ledger. |
| 9 | Reservation/accounting | IMPLEMENTED_AND_TESTED | Budget outstanding/record/release `128–180,318–400`; repository ledger commits | Budget/overrun/idempotency + SQLite/DynamoDB tests | Unknown costs reserved; no real billing/refund reconciliation. Local journal and ledger are separate transactions. |
| 10 | FULL | IMPLEMENTED_AND_TESTED | `domain/budget.py:182–203` | Normal authorization and E2E cases | Within explicit limits, not unlimited operation. |
| 11 | SAVER | IMPLEMENTED_AND_TESTED | Budget mode `182–203`, stricter new AI ceiling `284–292` | Saver transition/limit tests | Actual stricter spending rule exists; automatic cheap-provider/engine switching does not. |
| 12 | SCOUT_ONLY | IMPLEMENTED_AND_TESTED | Budget `263–294`; free use cases have no LLM dependency | E2E exhaustion + Bedrock outage continuity | Free business operations can still consume infrastructure resources; no claim of zero total real cost. |
| 13 | Budget wait/recovery | PARTIAL | `domain/opportunity.py:271–390`; `domain/revalidation.py` | Four E2E restore branches; domain resume tests | Guarded domain capability, no application/CLI resume coordinator; E2E manually persists separate ledger/opportunity writes. |
| 14 | ResearchWorker | PARTIAL | `application/workers/research.py:58–269` | Research unit/reopen/halfway tests | Real orchestration and artifacts; no concrete production ResearchTool, no live research-quality validation or runtime wiring. |
| 15 | DataWorker | IMPLEMENTED_AND_TESTED | `application/workers/data.py:27–150`, transform/semantic modules | Data validation, no-model, recovery tests | Bounded supplied CSV/JSON data; no external collection adapter; semantics remain unverified. |
| 16 | Deliverable generation | IMPLEMENTED_AND_TESTED | Application worker artifact modules and content digests | Research/Data/E2E artifact/QA assertions | In-memory text bundles persisted locally; no general production artifact publication/export workflow. |
| 17 | Source provenance | IMPLEMENTED_AND_TESTED | `application/contracts/research.py`; worker `100–163,230–259`; DataCell evidence | Source-binding, unknown/verified evidence tests | Captured source authenticity is a trusted adapter assertion, not proof of factual truth. |
| 18 | Deterministic QA | IMPLEMENTED_AND_TESTED | `application/qa/checks.py`; `use_cases/deliverable_qa.py:58–112` | Missing format/field/content, consistency and evidence tests | Explicit trusted criteria required; no automatic complete understanding of bounty prose. |
| 19 | AI-assisted QA | PARTIAL | `application/qa/ai_review.py:30–129`; Bedrock review port | QA response, outage, schema/budget tests | Adapter path exists; real model quality/compatibility not verified; unresolved review remains explicit. |
| 20 | Human approval | IMPLEMENTED_AND_TESTED | `use_cases/operator.py:34–244`; local CLI | Approval scopes, conflicts, three decisions, SQLite reopen | Local trusted actor attribution; not remote authentication. Revision execution incomplete (F05). |
| 21 | Submission authorization | PARTIAL | `use_cases/settlement.py:52–126`; digest/QA/current approval binding | All-mode no-approval/tamper tests; audit race probe | Prior approval required, but concurrent cancellation can precede actual send (F01). |
| 22 | Submission idempotency | IMPLEMENTED_AND_TESTED | SQLite `submissions.py:20–54`; DynamoDB `31–50` | Concurrent/different-ID claims, timeout/reopen retry tests | Local ownership tested; external integration absent. No exactly-once guarantee for arbitrary services/manual clicks. |
| 23 | Outcome tracking | PARTIAL | `use_cases/settlement.py:195–232`; durable observation history | Outcome tests + SQLite/DynamoDB histories | Business coordination implemented; no concrete production outcome gateway. |
| 24 | Payment verification | PARTIAL | `settlement.py:236–269`; `domain/payment.py:18–40`; Opportunity `449–516` | Pending/unverifiable/duplicate-proof tests | Validation of a verifier assertion exists; actual independent verification adapter MISSING. Fake proof is not real revenue. |
| 25 | Historical outcome learning | IMPLEMENTED_AND_TESTED | `use_cases/history.py:22–161`; domain history/statistics; both stores | History unit/SQLite/DynamoDB tests | Dataset + descriptive statistics only; explicit capture, no ML or automatic scoring update, as intended. |
| 26 | Local operator interface | IMPLEMENTED_AND_TESTED | `presentation/operator_cli.py`; bootstrap `48–125` | Workspace/operator CLI integration | Init/discover/normalize/dashboard/review/decide; not all lifecycle controls or provider wiring. |
| 27 | Local E2E workflow | IMPLEMENTED_AND_TESTED | `tests/e2e/local_flow.py:143–365`; `test_local_agentmine.py` | Six business cases executed separately, plus bootstrap in full suite | Real code with synthetic marketplace/model/action/payment boundaries. This is not an operational runner. |
| 28 | AWS integration | PARTIAL | DynamoDB adapters; Bedrock provider; Lambda factory `37–62` | Moto SDK integration, fake Bedrock contracts, direct handler tests | No deployable cloud wiring, real AWS verification or shared cloud LLM/raw journal. |

No top-level capability is classified solely from the existence of a port. In
particular, the real SubmissionGateway/PaymentVerifier implementations are **MISSING**;
their exercised external behavior is **MOCK_ONLY**. Bedrock's real client path is
**IMPLEMENTED_NOT_VERIFIED** against AWS, within the broader PARTIAL integration.

## 6. Budget and Economics Assessment

### Verified controls

`BudgetPolicy` requires four explicit nonnegative same-currency limits
(`domain/budget.py:36–66`). Daily/monthly AI periods use an explicit timezone.
Task ceilings aggregate categories and outstanding estimates; pending estimates
carry across periods. Estimates and actual costs remain separate. Recording
overruns retains incurred cost and audit issues rather than rejecting/hiding it.

BudgetManager commits the decision before dispatch. SQLite uses conditional
revisions under write transactions; DynamoDB commits state, audit and cost
projections transactionally. The concurrent two-writer tests were exercised in the
full run. Moto proves adapter behavior under emulation, not live DynamoDB isolation.

The Bedrock adapter checks persisted authorization twice, including after exact
input token preflight (`infrastructure/llm/bedrock.py:88–118`). Paid dispatch claims
precede Converse (`119–133`). Known usage is journaled/recorded before output
validation (`134–155`). No automatic SDK retry is configured (`44–59`). Unknown
cost/outcome retains claims/reservations. A preflight is itself external data
exposure in live operation, although no live preflight occurred in this audit.

SCOUT_ONLY denies new positive-cost requests, including tools, while zero-cost
deterministic operations continue. SAVER enforces a stricter AI request ceiling;
cheap-engine preference is not automatically implemented. Already funded pending
authorization is treated differently from a new reservation; do not describe mode
labels alone as a provider invoice cap.

`Budget.release` exists (`318–332`): it releases an outstanding commitment, not a
refund or negative cost. There is no application-level evidence-based release or
billing reconciliation workflow. A caller must not release an uncertain operation
merely to restore availability. Actual provider overruns, tariff errors and
unmeasured infrastructure costs remain possible despite authorization controls.

### Recovery and selection limits

Resume requires refreshed identity/time/open/deadline, resolved eligibility,
expected value and score, then authorization. Expired/closed/ineligible work is
skipped/cancelled without new spend. The domain trusts supplied assessment facts;
it does not fetch or independently prove them. No explicit minimum economic
attractiveness/recommendation gate is enforced by PlanTask/resume. Recommendations
are advisory; a complete production composition must select work intentionally.

The E2E harness performs refresh, deterministic eligibility and recalculation, then
commits budget and opportunity separately (`tests/e2e/test_local_agentmine.py:314–357`).
No reusable application resumption coordinator exists. Structured economic/scoring
assessments are cleared on resume while scalar forecast/score are updated
(`domain/opportunity.py:375–386`); this is not a retained fresh full forecast audit.

### Revenue and actual net value

The formula is correctly represented: forecast reward × subjective probability
minus four estimated cost categories. Verified revenue instead requires PAID and
matching PaymentEvidence (`domain/opportunity.py:449–516`). Acceptance, winner flags,
potential reward and expected net do not create revenue. Rejection reasons persist.
Repository proof ownership prevents crediting a single source/payment ID to two
submissions through the verified-payment use case.

`EconomicMetrics.net_verified_value` subtracts recorded actual costs. Attribution is
by opportunity in `use_cases/metrics.py:17–34`; workspace reporting includes the
sole ledger's recorded totals. Unattributed/unmeasured real costs do not magically
appear. No invoice ingestion, FX conversion, partial-payment aggregation or USD
valuation of token rewards is implemented. Therefore the USD 1 experimental target
and complete actual net value cannot currently be certified (F03/F09).

## 7. Marketplace Integration Assessment

Public documentation was rechecked during this audit; no authenticated API was
called. The direct Superteam skill URL initially failed in the web reader because
it served an unsupported Markdown content type. Its official agent page and
official repository copy were accessible; this was a documentation-tool limitation,
not evidence that the API was down.

| Integration | Actual connector/status | HTTP/auth | Contract evidence | Pagination/rates/data/AI | Submission/payment |
| --- | --- | --- | --- | --- | --- |
| Superteam Earn | Concrete read-only source; disabled by default in operator composition, explicitly enabled with live flag/key | Fixed HTTPS host and two GET route shapes, bearer auth, finite timeout, bounded response; `superteam_http.py:52–97` | **Verified against official documentation**, not live read-only integration. Synthetic fixtures only for runtime contracts | One window capped at 50; continuation explicitly UNSUPPORTED. 429 classified but no automatic rate limiter/Retry-After/backoff scheduler. Malformed data archived/rejected, IDs/dedup checked, AI ALLOWED/ONLY admitted and unknown/human-only quarantined. Eligibility detail mapping incomplete | No concrete production gateway/outcome reader/verifier. Generic API/MANUAL contracts do not establish a vendor integration |
| Algora | `deferred.py:12–19`, intentionally disabled | No HTTP/auth implementation | **Unsupported** connector. Public primary page describes recruiting/history; it does not verify a current V1 bounty API | No schema/pagination/rate/AI contract implementation | None |
| Opire | `deferred.py:22–31`, intentionally disabled | No HTTP/auth implementation | **Unsupported** connector. Official docs describe GitHub issue/PR claim workflow, not a verified AgentMine Research/Data API | No schema/pagination/rate/AI contract implementation | None |
| Other sources | No additional concrete production OpportunitySource found | Fixture/FakeSource in tests only | **Mock-only** | Supplied clock/status/data | Fake settlement |

The official Superteam agent page describes authenticated discovery/detail reads,
AI participation categories and a separate human payout-claim step. It also documents
submission payloads, but this does not resolve durable receipt/reconciliation or
independent settlement semantics for AgentMine. [Official agent documentation](https://superteam.fun/earn/agents),
[official skill source](https://github.com/SuperteamDAO/earn/blob/main/public/skill.md).

Algora's current public description positions it as recruiting and records its bounty
history; this is insufficient to enable a bounty adapter. [Official Algora description](https://algora.io/llms.txt).
Opire describes issue/PR claims and separately decided payments; this does not establish
AI permission or a Research/Data discovery API. [Official Opire getting started](https://docs.opire.dev/overview/getting-started).

No listing count, paid opportunity availability, deployed JSON shape, GET quota or
provider uptime is asserted from these documentation reads. Lack of verified
contracts must remain UNKNOWN/UNSUPPORTED rather than trigger scraping or guessed APIs.

## 8. Worker and Deliverable Assessment

**Research:** real approved-tool orchestration, per-step budget/claim checks,
checkpointed source evidence, schema validation, facts/analysis/uncertainties and
report/sources/findings artifacts exist (`workers/research.py:68–269`). The source
inventory comes from captured tool observations, not model-invented URLs. Facts
are attributed excerpts from captures marked verified by the trusted tool;
“verified content provenance” does not prove all source assertions true. Model
analysis is explicitly unverified. No production tool collects external research;
the end-to-end reader returns `tests/e2e/fixtures/research.txt`. The default Mock
draft is placeholder text, not evidence of useful real research.

**Data:** real deterministic collection from supplied CSV/JSON snapshots,
extraction, categorization, normalization, validation and lookup enrichment exist.
Semantic fields are opt-in and constrained by row IDs/column sets; AI cannot add
arbitrary rows or rewrite unrelated columns (`workers/data_semantic.py`, particularly
`apply_semantics`). Missing values and validation issues remain visible; no general
fabrication-to-fill-schema path was found. Deterministic Data records zero AI
usage, while explicitly warning that infrastructure is not measured.

Plans bound supported task types, inputs/columns/counts/constraints; plain text
artifacts use fixed names and checksums. No worker invokes shell code, submits,
creates approvals or verifies revenue. CSV formula escaping, literal Markdown,
UTF-8/size bounds and approved tool locators reduce unsafe-data risk. JSON values
are still untrusted data if later exported into another executable context.

**Usefulness verdict:** DataWorker can produce useful bounded CSV/JSON from valid
real input. ResearchWorker can assemble a reusable evidence-first report given a
real approved tool and suitable synthesis. Neither was evaluated by an independent
bounty provider, against a real bounty specification, or with a real model here.
Artifact format/provenance correctness is not proof of commercially acceptable
analysis. Runtime worker selection/publication and rework remain F02/F05.

## 9. Human Approval and Submission Assessment

The normal submission path requires APPROVED_FOR_SUBMISSION, current deliverable,
passed QA, bound target and exact content digest (`settlement.py:72–91`). Approval
scopes/review decisions are immutable and persisted; DecideOperatorReview compares
opportunity and ledger revisions, reviewed content and fresh source availability
(`operator.py:193–235`). QA PASS alone never submits.

Legacy `ApproveSubmission` accepts an explicit HumanApproval assertion from a
trusted caller (`approval.py:40–57`), rather than requiring a recorded operator
review decision. This is an intentional trusted API, not exposed to marketplace
text or unauthenticated remote events. It is not a new demonstrated remote bypass;
future public wiring must not treat arbitrary callers as the operator.

API submission claims once per ID AND deliverable/version. Retries reconcile or
reuse retained confirmation; changing IDs cannot get a second local claim.
UNSUPPORTED performs no external action. MANUAL generates instructions/content
and remains HUMAN_ACTION_REQUIRED until RecordManualSubmission stores an
operator-reported receipt (`manual_submission.py:21–100`). A package is not a send,
receipt is not acceptance, and acceptance is not payment. A person can still send
twice outside AgentMine. Rejected/expired tasks normally fail state/freshness checks;
recovering an already-issued intent deliberately does not issue another send.

**Confirmed race F01:** a concurrent cancellation after SubmitTask's initial read
but before gateway dispatch is not coupled to its durable claim. Source refresh
can observe a fresh listing while the authoritative local aggregate has changed.
Gateway invocation precedes the final conditional aggregate write. See the
executed reproduction and precise evidence in sections 12/14.

The existing concurrency tests protect claim uniqueness and immutable decisions,
not cancellation-versus-dispatch ordering. The normal CLI has no generic concurrent
cancel command; reproducing this requires another trusted workflow/writer using
the public domain skip transition and repository port. It is still a real
use-case/data-integrity gap for future controlled orchestration.

## 10. AWS Integration Assessment

| Concern | Observed reality |
| --- | --- |
| Lambda | Thin real Python handlers and strict events exist. Factory exposes four workflows, not the complete work loop (`bootstrap/lambda_runtime.py:37–62`). Direct calls tested; no deployed entrypoint exports/resources. |
| DynamoDB | Concrete repository/journal implementations, sparse GSIs, authoritative consistent base reads, conditional revisions/claims and transactional ownership. SDK exercised through Moto, no live table. |
| Access patterns | Explicit lifecycle/source/ranking, execution/cost histories, pending review, accepted-unpaid, paid projections and evidence queries. No relational joins/table scan reproduction. Eventual GSI candidates reload authority. Multi-page totals are not a global transaction. |
| Bounds | Store rejects >380 KiB items and >100 actions/>3800 KiB transactions (`store.py:166–189`). Growing budget/history/artifact snapshots have no offload/compaction design; fail-closed limits are not unlimited capacity. |
| Bedrock | Actual optional SDK factory, Converse/CountTokens path, bounded schemas, minimized untrusted input, pre-dispatch budget checks and token-derived cost. Fake SDK tests only. |
| Shared cloud state | Bedrock uses SQLite LLMJournal and Superteam uses SQLite RawArchive; no shared cloud adapters for those authorities (F06). DynamoDB worker journals do not replace them. |
| IAM/secrets | Permissions/roles and safe input/secret boundaries are described, not provisioned or tested against AWS. No operator credential was read here. Runtime actor ID is not cloud authentication. |
| Trigger/scheduling | Versioned direct/custom EventBridge-shaped events are parsed; no configured schedule, autonomous poller or deployment trigger. Event parsing is not a deployed scheduler. |
| Logging | Correlation-aware sanitized JSON at Lambda boundary; safe structured metadata elsewhere. No demonstrated production retention/detection/log-level policy. |
| Deployability | No shipped deployment-owned factory, resource template, IAM configuration or release packaging/runbook. Do not deploy the examples as a completed cloud system. |

AWS-specific SDK types/keys/model configuration do not leak into Domain/Application.
The intended three primary workload services are a design choice, not evidence of
an existing deployment. A local V1 experiment does not require AWS migration first;
F06 is specifically a cloud-enablement blocker.

## 11. Test Execution Results

Configuration inspected before execution: `pyproject.toml:31–58` points at `tests/`,
adds the application-fake import path, requires strict pytest markers/configuration,
Ruff E/F/I/UP/B and strict mypy over source/tests. No default paid integration test
was found. No skip was used to hide a failure.

All commands below ran from the repository root with the existing venv. Counts
for non-test commands are not applicable, rather than invented test passes.

| Exact command / execution | Exit | Passed | Failed | Skipped | Warnings / limitation |
| --- | ---: | ---: | ---: | ---: | --- |
| `.\.venv\Scripts\python.exe -m pytest -q -ra -p no:cacheprovider` — final captured run | 0 | 959 | 0 | 0 | 79.17s; no pytest warning summary. Real SQLite + Moto/fakes, no live provider. |
| `.\.venv\Scripts\python.exe -m pytest tests/e2e/test_local_agentmine.py -q -s -p no:cacheprovider` | 0 | 6 | 0 | 0 | 5.57s; JSON synthetic reports, including Research/Data and four wait/resume cases; not real earnings. |
| `.\.venv\Scripts\python.exe -m ruff check .` | 0 | N/A | N/A | N/A | All checks passed. |
| `.\.venv\Scripts\python.exe -m ruff format --check .` | 0 | N/A | N/A | N/A | 236 files already formatted. No files reformatted. |
| `.\.venv\Scripts\python.exe -m mypy` | 0 | N/A | N/A | N/A | No issues, 181 checked source/test files. |
| `.\.venv\Scripts\python.exe -m pip check` | 0 | N/A | N/A | N/A | No broken requirements. Compatibility only, not advisory/integrity scan. |
| `.\.venv\Scripts\python.exe --version` | 0 | N/A | N/A | N/A | Python 3.14.2. |
| In-memory `pytest.main(['--collect-only','-qq','-p','no:cacheprovider'])` with a counting plugin | 0 | N/A | N/A | N/A | 959 collected: unit 678, contract 158, integration 116, E2E 7. Collection is not execution proof. |
| Three inline Python diagnostic probes via `@'…'@ \| .\.venv\Scripts\python.exe -` | 0 each | N/A | N/A | N/A | Cancellation race, MANUAL pending eligibility, failed-QA retry. Expected failures caught, synthetic state only; details below. |

An earlier full-suite invocation's output was combined with large source reads
and truncated by the tool. Its counts were not used as evidence. The
full command was rerun for the untruncated result above. A later attempt to poll
the already-closed initial process returned “Unknown process id”; this was an audit
output-capture error, not a test failure. An earlier separate E2E output session
was also unavailable when polled; the six-case command was rerun and its complete
reports/result captured. No result from prior audit reports is substituted for
these executions. Whitespace, all 16 required sections, 28 matrix rows, finding
counts and referenced Python paths/start lines were checked with a read-only
local report-validation script (exit 0); `git diff --check` also returned 0.

### Quality of test evidence

Meaningful assertions include exact financial arithmetic, lifecycle/currency/
version rejection, multiple budget categories, no dispatch after denied authorization,
QA ordering, scope/content tampering, payment proof uniqueness, SQLite transaction
rollback/real locking, concurrent claims, checkpoint reopen and no repeated external
calls after timeouts. E2E starts from discovery, not a pre-seeded PAID aggregate.
Parameterization is useful here; test quantity alone is not the conclusion.

Limitations: Bedrock SDK responses are synthetic, Superteam transport is offline,
research data is tiny and fixture provenance is explicitly synthetic, settlement
comes from fake services, operator choices are simulated. DynamoDB tests do not
prove deployed AWS behavior. The previously documented intermittent Moto transaction
issue did not appear in the captured run; a pass does not resolve the emulator limit.
Some integration tests import unit fakes/helpers and directly compose domain
transitions; useful for adapter substitution, but not a shipped runtime acceptance test.

No measured line/branch coverage percentage is reported. No load/soak, disk-loss,
live provider compatibility, real payout, production permissions or backup restore
test was executed. Missing regressions include the cancellation dispatch interleaving,
application-level MANUAL resolution and actual rework/resume operational paths.

## 12. Security and Resilience Findings

### Executed cancellation probe (F01)

The executed probe used the existing test helpers and fake gateway, writing only
in-memory fake repositories. The following equivalent script reproduces its
interleaving and output. No implementation/test file was edited.

```powershell
@'
import sys
from dataclasses import replace
sys.path.insert(0, 'tests/unit/application')
from test_use_cases import world, approved
from agentmine.application.contracts.records import OpportunitySave
from agentmine.domain.values import Reference
w = world.__wrapped__()
approved(w)
original_source = w.source
class CancelDuringRefresh:
    def discover(self, request):
        return original_source.discover(request)
    def refresh(self, request):
        result = original_source.refresh(request)
        old = w.opportunities.get(w.reference)
        w.opportunities.save(OpportunitySave(
            old.value.skip('Operator cancelled before dispatch'), old.revision))
        return result
command = replace(w.submit_task(), source=CancelDuringRefresh())
for attempt in (1, 2):
    try:
        command.execute(w.reference, Reference('audit-send'))
    except Exception as error:
        print(attempt, type(error).__name__, error.code.value,
              w.gateway.submits, w.current().state.value,
              [a.status.value for a in w.submissions.attempts])
'@ | .\.venv\Scripts\python.exe -
```

Equivalent output from the executed probe:

```text
first call: conflict; send_calls=1; state=skipped; attempts=[confirmed, unknown]
retry: ApplicationError invalid_state; send_calls remains 1
```

The immutable claim prevents a second dispatch, but does not prevent the first
dispatch from using a stale locally cancelled aggregate. The later CAS protects
state from overwrite, not the external effect. Stored confirmation remains
recoverable evidence; the ordinary SubmitTask retry cannot apply it from SKIPPED.

### Other executed probes

- **F04:** create an eligible-facts request with `submission=SubmissionSupport.MANUAL`,
  discover/normalize, call CheckEligibility twice. Both calls returned
  `eligibility_check / requires_human_review / [MANUAL_SUBMISSION_REQUIRED]`.
  Source/profile facts were otherwise the standard passing fixture. Code search
  found no application resolver for this pending decision. Directly asserting a
  different status through domain/repository APIs is not a supported resolution flow.
- **F05:** plan, ExecuteTask, then RunQA with FAILED. Retrying the original command
  raised `ApplicationError invalid_state`, provider calls stayed 1. This is safe
  against repeat spend, but no application use case performs the required new-version
  execution. New execution IDs cannot evade the PLANNED precondition. Domain.finish
  can accept correctly prepared rework; orchestration is the missing component.

### Controls and residual risks

| Threat/failure | Evidence-based result |
| --- | --- |
| Marketplace tells model to reveal credentials / ignore policy | `llm/operations.py:72–120` minimizes inputs and encloses source text in untrusted data; `security.py:8–62` separates fixed policy and filters known secrets/escaped values. Contract adversarial tests pass. No credential/environment-reading tool exposed. Arbitrary secret text deliberately supplied by a trusted caller and semantic persuasion remain unverified risks. |
| Marketplace causes paid dispatch | Source text cannot mutate BudgetPolicy or SDK parameters. CountTokens/max-output funding and persisted authorization block the tested long-prompt path. Pricing remains trusted configuration; in-flight policy changes cannot cancel an already issued external call. |
| Unapproved submission | Normal paths reject without version-bound passing QA/approval. No model tool or Lambda event grants human consent. F01 is a concurrent cancellation gap after prior valid approval, not proof of approval-free marketplace control. |
| Prohibited action/code execution | Only Research/Data task types; deterministic eligibility checks prohibited actions/credentials/physical requirements. No shell/eval/subprocess/wallet executor found. Model plans remain text. Private Python callers/host/database writers remain trusted. |
| Attacker URLs/files | Fixed Superteam host/routes, no redirects; research locators require exact composition approval. Receipt URLs are metadata, not fetched. Future real tools/exporters must add their own network/file protections. |
| Retry storms / provider outage | Transport and Bedrock disable automatic retries; unknown effects preserve ownership and require reconciliation. Free pipelines continue in tests. Cloud event retry policy and operator cadence remain deployment choices. |
| Database partial failure | Actual SQLite lock, orphan discovery, checkpoint, receipt/aggregate failures covered; real file reopen works. Separate store writes do not create a global transaction. F01 and evidence-before-checkpoint crash windows remain. |
| Fake payment / duplicate revenue | Reward stage alone is insufficient; typed independent proof, matching submission/currency/time and source/payment ownership enforced. No real proof authentication adapter exists; trusted fake proof is intentionally accepted only in tests. |
| Private data/logs | Application logs generally use codes/IDs/counts and Lambda sanitizes exceptions. SQLite source/worker files can retain sensitive content, hashes are not signatures; SDK debug logging or sensitive identifiers can leak data. Host ACL/encryption/retention/log contents not verified here. |

No destructive exploitation, real external action or paid call was used. Risks not
reproduced as vulnerabilities are not promoted to confirmed security defects.

## 13. End-to-End Reality Check

The separately executed E2E test is locally executable and uses these boundaries:

| Stage | Actual implementation / boundary |
| --- | --- |
| Discover / normalize | Real use cases and SQLite; synthetic marketplace observation from saved fixture, not Superteam HTTP. |
| Eligibility / evaluate / score | Real deterministic domain calculations; supplied fake profile/facts/signals. No LLM. |
| Budget / plan | Real BudgetManager/reservation and public PlanTask; persisted SQLite. |
| Execute Research | Real ResearchWorker; fixture-only reader and MockLLMProvider. No real research collection/model. |
| Execute Data | Real deterministic DataWorker on supplied JSON; zero model work calls. |
| QA | Real deterministic/domain QA against retained artifact bundle. AI QA tested separately with fake provider. |
| Approval | Real review/decision persistence; test explicitly supplies simulated operator decision. Production needs an actual operator. |
| Submit | Real approval/claim/retry orchestration; fake gateway creates synthetic receipt. Production external send unsupported until mechanism is established. |
| Outcome | Real state/history logic; fake acceptance event, accepted reward USD 90. |
| Payment | Real proof-validation/uniqueness logic; fake pending/unverifiable then synthetic independent proof USD 85. No money received. |
| Net value | Real Decimal accounting over synthetic recorded costs: USD 85 minus USD 10 = USD 75; external API spend reported zero. |

Both Research and Data traversed DISCOVERED → NORMALIZED → ELIGIBLE → EVALUATED →
SCORED → PLANNED → IN_PROGRESS → QA_PENDING → READY_FOR_HUMAN_REVIEW →
APPROVED_FOR_SUBMISSION → SUBMITTED → ACCEPTED → PAID. Budget cases separately
show discovery continuing during SCOUT_ONLY and refreshed open/expired/closed/
ineligible resumption behavior. These are simulations of external facts, not earnings.

Explicit answers:

1. **Discover a real eligible opportunity?** Implemented bounded real-read path,
   but **not demonstrated**. Source facts are incomplete, common asset/reward
   shapes quarantine, and no authenticated smoke or available eligible task exists
   in this audit evidence.
2. **Produce a useful deliverable?** **Yes for bounded supplied Data input;
   conditional for Research.** Engines produce meaningful structured artifacts,
   but real source/model/provider acceptance quality remains unverified.
3. **Obtain operator approval?** **Yes**, via the local review CLI on properly
   prepared state; authenticated local host assumed. Full state preparation is not
   exposed by a production workflow command.
4. **Submit through a verified supported channel?** **Not demonstrated.** MANUAL
   packaging/receipt works locally, but there is no selected verified real channel
   or complete manual-eligibility path; no real API gateway implementation.
5. **Distinguish acceptance from payment?** **Yes**, enforced and tested.
6. **Verify an actual reward?** **No shipped real verifier.** A port and robust
   evidence validation do not authenticate real-world settlement themselves.
7. **Calculate actual net value?** **Yes for recorded verified reward/cost inputs;
   not complete real operating profit.** Missing invoices/costs and asset-to-USD
   valuation remain unknown. No USD 1 real reward has been evidenced.

## 14. Prioritized Findings (P0–P3)

**P0: none established. P1: six. P2: five. P3: none assigned.** “Confirmed gap”
means repository functionality/evidence is absent; it is not a claim of exploitable
production behavior. Risk-only concerns are separately identified in section 12.

| ID | Priority / type | Title and precise evidence | Impact | Minimum remediation recommendation | Verification criteria |
| --- | --- | --- | --- | --- | --- |
| F01 | P1 / confirmed defect, reproduced | Stale cancellation does not prevent submission dispatch. `application/use_cases/settlement.py:52–54,124–126,159–170`; `submission_result.py:43–66`; `domain/opportunity.py:138–139,242–253`. Section 12 reproduction | One send after local cancellation; CAS failure leaves SKIPPED + confirmed receipt, ordinary retry cannot reconcile state. Requires concurrent trusted writer | Define claim/cancel linearization with authoritative opportunity revision/state before dispatch; retain evidence reconciliation for effects already issued. Do not rely only on a second non-atomic read | Regression interleaving cancellation/claim/dispatch: cancellation wins → zero sends; claim wins → explicit non-cancellable/in-flight semantics and recoverable receipt; no duplicate sends |
| F02 | P1 / confirmed functionality gap | Complete runtime orchestration exists only in tests. `bootstrap/main.py:8–10`; `bootstrap/operator.py:72–84`; `application/use_cases/execution.py:42–49,127`; `tests/e2e/local_flow.py:247–365` | Operator cannot run real supported workers through the delivered discover-to-settlement runtime. Test composition is not deployment | Compose existing workers/use cases into a bounded single-operator local workflow, with trusted plan/evidence inputs and explicit steps. Include guarded wait/resume persistence; avoid scope expansion | New operational entrypoint on isolated local workspace completes deterministic real input through review; no fixture payment/model accidentally selected for real state; interruption/replay verified |
| F03 | P1 / confirmed integration gap | No production submission/outcome gateway or independent PaymentVerifier. Only protocols in `application/ports/services.py:49–70`; no concrete implementations in infrastructure; `settlement.py:195–269` consumes injected assertions | Cannot establish supported real receipt/outcome/payment or USD 1 verified experiment result | Select one permitted Research/Data opportunity and supported API or MANUAL channel; verify receipt/outcome contracts, supply an independently sourced settlement adapter and explicit currency/valuation policy. No wallet automation needed | Authorized read-only compatibility evidence, offline captured fixtures, approved manual/API send procedure and independently validated actual settlement; acceptance/pending still contribute zero revenue |
| F04 | P1 / confirmed functionality gap, reproduced | MANUAL eligibility remains human-review pending with no resolver. `domain/eligibility_rules.py:117–123,140–151`; `use_cases/eligibility.py:24–39`; operator decisions in `use_cases/operator.py:197–212` apply to approval scopes, not eligibility | Intended manual submission fallback cannot naturally progress through eligibility; source-specific disclosure/review cases share the gap | Add explicit auditable resolution of permitted eligibility-review reasons while preserving unresolvable UNKNOWN and INELIGIBLE facts; do not relabel MANUAL as API | Genuine MANUAL facts → recorded human resolution → ELIGIBLE without bypassing prohibited/unknown restrictions, then manual package; denial/stale resolution tests |
| F05 | P1 / confirmed functionality gap, reproduced | QA/revision returns IN_PROGRESS but ExecuteTask cannot run rework. `domain/opportunity.py:392–431`; `application/use_cases/execution.py:54–78,165–176`; immutable worker journals | Operator REQUEST_REVISION and QA fail have no supported application path to produce a new version; retries safely stop | Define explicit revision execution coordinating existing task, new paid operation where justified, newer deliverable and fresh QA/approval; preserve earlier evidence and idempotency | QA fail and operator revision both produce v2 through supported use case, v1 approval unusable, exactly one additional authorized execution, no identity mutation |
| F06 | P1 / confirmed AWS-enablement gap | Bedrock requires SQLite LLMJournal (`infrastructure/llm/bedrock.py:81–85,119–143`; `journal.py:13–40`); source requires SQLite archive (`marketplaces/superteam.py:40–48`) | Independent Lambda-local files cannot share global dispatch ownership/raw evidence. Unsafe if paid/cloud ingestion is enabled as-is; local protected single-store operation differs | Add shared durable conditional claim/raw-retention adapters behind appropriate infrastructure boundaries; explicit production composition. Keep paid cloud path disabled meanwhile | Separate instances share claims, duplicate/concurrent invocation cannot make a second paid call; raw captures survive instance replacement; real test-environment conditional-write validation |
| F07 | P2 / confirmed freshness limitation, security consequence unverified | Refresh checks only identity/time/open/deadline; Superteam additionally checks AI policy. `use_cases/context.py:45–82`; `superteam.py:103–126`; eligibility facts otherwise caller-supplied | Changed country/identity/requirements/prohibited-action terms can leave a stale eligible plan | Bind reviewed requirements/eligibility evidence to a source version or require explicit operator revalidation before real work/submission; do not invent a vendor version API | Changed restriction after eligibility blocks work or requires new recorded review; unchanged terms permit normal bounded execution |
| F08 | P2 / confirmed recovery/operations gap | Unknown claims are sticky; release is a raw domain method. `domain/budget.py:318–332`; `llm/journal.py:16–40`; execution `71–77`; no backup/reconciliation entrypoints found | Recoverable evidence may require ad hoc intervention; inconsistent restore can lose financial/duplicate authority | Provide minimal evidence-driven incident/backup/restore and safe release/reconciliation procedures covering all stores; never clear claims to force retry | Isolated restore drill preserves costs/claims/proofs, ambiguous-send/cost case reconciles without another action; recorded RPO/RTO and owner |
| F09 | P2 / confirmed accounting completeness limitation | `application/use_cases/metrics.py:17–34`, `domain/metrics.py:47–77`, worker unmeasured-infrastructure warning; flat model tariff is configured | Net value is correct only on recorded-cost basis; complete actual operating profit and USD valuation cannot be asserted | For experiment, establish explicit cost capture/attribution and independent tariff/billing reconciliation; preserve UNKNOWN and no guessed FX | Known invoices/observations reconcile across all four categories; unmeasured cost visible; late costs update metrics; USD threshold supported by evidence |
| F10 | P2 / confirmed release-assurance gap | `pyproject.toml:1–26` has broad dependency ranges; inventory found no lock/CI/deployment release config | New installs can differ; no automated release gate/advisory evidence or Python-version matrix | Review reproducible dependency/build inputs, add an offline test/static release gate and advisory triage for chosen runtime; no unnecessary runtime dependency | Clean rebuild of selected release reproduces tested versions; unit/integration/contract/E2E/static checks run; advisory findings disposition recorded |
| F11 | P2 / missing deployment/security evidence | Logging/handler controls exist, but effective IAM/host ACL, encrypted backup access, retention, INFO collection and incident cadence not demonstrated. `presentation/lambda_handlers.py`; `bootstrap/config.py`; raw/worker SQLite stores | Sensitive retained evidence or stalled/unknown financial work may be unmanaged in a real run; no actual leakage/permission exploit established | Choose protected single-operator runtime; verify access/secrets/logging controls and simple operational checks for outstanding/overdue/stalled work | Operator walkthrough finds safe correlation/audit records, enforces restricted workspace access and follows a simulated incident without exposing payloads |

## 15. Recommended Remediation Roadmap

Recommendations only; **do not implement automatically**.

1. **First: close F01 at the submission boundary.** Agree on cancellation-versus-claim
   semantics and add the reproduced interleaving as a regression before external
   submission is ever enabled. Preserve confirmation evidence independently of
   whether a local lifecycle transition can still apply.
2. **Choose one bounded local experiment (F02/F03/F04).** Select a legitimate
   Research/Data opportunity with known AI permission, explicit manual or API
   mechanism and independently checkable settlement. A manual channel is reasonable
   only after eligibility review can resolve honestly. Verify source access/read
   contracts without assuming bounty availability or income.
3. **Complete minimal operator orchestration and revisions (F02/F05/F07).** Reuse
   existing domain/ports/workers, add no frontend or services, explicitly refresh
   requirements and bind budget/QA/review steps. Include wait/resume and v2 flow.
4. **Make the experiment auditable (F08–F11).** Protect workspace/journals, preserve
   backups, rehearse unknown-effect reconciliation, record all actual costs and
   chosen currency evidence, fix release reproducibility and basic monitoring.
5. **Validate the chosen local path before any paid effect.** Dry-run with realistic
   supplied data, then separately authorize any live read, paid model or human
   submission. Real verification requires actual independent settlement evidence;
   it cannot be replaced by a fake verifier or an operator's acceptance claim.
6. **Cloud is a later, separate gate (F06).** Shared durable journals/archives,
   explicit IAM/deployment/trigger configuration and appropriate AWS test-environment
   concurrency evidence precede enabling paid work across Lambda instances.

The economic experiment may fail to earn a reward even after these engineering
gates close. Record that outcome honestly; do not change success probability,
accepted reward or verification semantics to manufacture success.

## 16. Production Readiness Verdict

**NOT_READY**

**Ready for a controlled real-world bounty experiment: NO.** The current repository
supports credible offline learning and component validation, but does not deliver
the operational source-to-independent-payment experiment or complete manual/rework
paths. The reproduced dispatch/cancellation race also needs resolution before live
submission. A protected, supervised local experiment could become viable after
the local gates above are demonstrated; AWS deployment is not a prerequisite for
that narrower experiment.

No actual earned reward, complete real net value, live provider compatibility or
production security is claimed. Wait for operator review and approval of the
recommended remediation; this audit changes only its own report.

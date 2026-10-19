# Local End-to-End Flow — Milestone 6A

## Run locally

From the repository root with the existing development environment:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/e2e -q -s -p no:cacheprovider
```

No keys, account, network, paid model, real submission, payment, or user interaction
is required. The explicit operator decision is simulated by the test through the real
approval use case and SQLite approval repository. Production submission still requires
a real operator decision. No AWS deployment has been started.

`-s` prints JSON execution reports: scenario, persisted lifecycle checkpoints, mock
operator, dispatch count, synthetic financial values, and external API spend. Omit it
for concise pytest output. To retain a machine-readable pytest result, append
`--junitxml=.tmp/milestone-6a.xml` after creating `.tmp` if necessary.

## Composition and scope

`tests/e2e/local_flow.py` explicitly composes the existing application and domain APIs
with file-backed SQLite repositories and worker/QA/approval journals. Tests reopen
repository adapters after each lifecycle stage and compare rehydrated aggregates.
Worker retries use reopened journals; submission and payment retries use durable results.

The external boundaries are synthetic saved marketplace/research/data fixtures,
MockLLMProvider, a fixture research reader, fake submission gateway, fake payment
verifier, and an explicit clock. Marketplace JSON is an AgentMine test-port fixture,
not an asserted vendor API contract or production capture. Root pytest network blocking
remains enabled. No credential lookup or Bedrock client construction occurs.

Each complete path starts with an empty database and discovery, not a prebuilt completed
aggregate. Deterministic eligibility/economics/scoring, real ResearchWorker/DataWorker,
DeliverableQA, operator review/decision, SubmitTask, TrackOutcome, VerifyPayment and
GetEconomicMetrics all run. Research produces report.md/sources.json/findings.json
from exact local evidence and one mock synthesis. Data deterministically produces
CSV/JSON with row provenance and constraints, making zero model calls. Artifact bundles
are retained in SQLite and checked by QA before approval.

Budget authorization precedes planning in the main scenarios using an explicit future
task ID; dispatch rechecks the same persisted reservation. Research's estimate is USD 1
and its mock actual is USD 0. Deterministic Data has estimate/actual USD 0. Estimates
are never booked as actual expenses.

This milestone is an acceptance-test composition, not a new production runner or scheduler.
The existing ExecuteTask dispatches LLM drafts rather than selecting Research/Data workers.
The test composes worker execution with public `Opportunity.start/finish` and repository
ports. Budget resume likewise uses the existing guarded domain operation after refresh,
fresh eligibility and recalculated economics/score. It persists the returned budget audit
and opportunity through existing ports. It does not mutate private fields or bypass QA,
approval, spending or payment invariants. Domain/Application source and scoring policy are
unchanged; no dependency or new architecture decision is introduced.

## Execution report

Validated on 2026-10-18 with the project environment. Six new acceptance cases pass,
plus the existing bootstrap E2E test (7 E2E tests total).

Final checks, all using `.venv\Scripts\python.exe`:

| Command | Result |
| --- | --- |
| `-m pytest tests/e2e -q -s --tb=short -p no:cacheprovider` | 7 passed; JSON scenario reports printed |
| `-m pytest -q -p no:cacheprovider` | 836 passed (14.21 seconds) |
| `-m ruff check .` | Passed |
| `-m ruff format --check .` | 191 files already formatted |
| `-m mypy` | Passed, 149 source files |
| `git diff --check` | Passed |

The first sandboxed pytest attempt could not access the system temporary directory;
the same offline tests then ran successfully with temporary-directory access. Initial
test-harness typing/API-name issues were corrected before these final checks. No
dependencies were installed or production code changed.

| Scenario | Observed result |
| --- | --- |
| Research | DISCOVERED → NORMALIZED → ELIGIBLE → EVALUATED → SCORED → PLANNED → IN_PROGRESS → QA_PENDING → READY_FOR_HUMAN_REVIEW → APPROVED_FOR_SUBMISSION → SUBMITTED → ACCEPTED → PAID |
| Data Processing | Same full lifecycle, deterministic validated CSV/JSON, no LLM work call |
| Exhausted budget, still open | Derived SCOUT_ONLY; free discovery/normalization/eligibility/evaluation/scoring continue; paid execution denied without model call; WAITING_FOR_BUDGET persists; another listing ingested; explicit policy restoration; fresh status/deadline/eligibility/economics/score; resume through PAID |
| Expired while waiting | Refresh after restoration yields SKIPPED with EXPIRED task; no execution, submission, verification or reservation |
| Closed while waiting | Refresh yields SKIPPED with CANCELLED task; no execution or reservation |
| Newly ineligible | Fresh AI participation facts yield INELIGIBLE with CANCELLED task; no execution or reservation |

QA PASS leaves approval absent, and submitting at that point raises an error without
calling the gateway. The simulated operator's identity, timestamp, decision and reason
survive SQLite reopen. Only the subsequent explicit SubmitTask call sends to the fake
gateway. Retrying sends exactly once. Acceptance and pending/unverifiable payment retain
zero revenue. A completed payment retry reuses persisted evidence without another poll.

Financial assertions (USD, entirely synthetic):

| Stage | Potential reward | Accepted reward | Verified revenue | Recorded cost | Net verified value |
| --- | ---: | ---: | ---: | ---: | ---: |
| ACCEPTED | 100 | 90 | 0 | 0 | 0 |
| Payment PENDING / UNVERIFIABLE | 100 | 90 | 0 | 0 | 0 |
| Independently evidenced fake PAID | 100 | 90 | 85 | 0 | 85 |
| Late synthetic AI/tool/infra/transaction costs 1/2/3/4 | 100 | 90 | 85 | 10 | 75 |

The exhaustion scenario records a separate synthetic prior USD 1 charge to consume its
USD 1 budget. Restoration raises daily/monthly limits while preserving that cost history.
It is not attributed to the new task. All these ledger numbers are test observations;
**actual external API spend is USD 0, and no real reward is received**. Unmeasured local
computer/electricity costs are not claimed to be verified zero production infrastructure
expenses. Net values retain the existing recorded-cost accounting semantics.

## Limits and operator actions

No action is needed from the project owner for these tests. To inspect results, run the
command above; pytest creates isolated temporary SQLite files, leaving existing databases
untouched. This is not yet an interactive operator UI or automatic continuous agent.

Composition proves the happy path and selected budget/revalidation branches. It does not
prove process-crash atomicity across the separate ledger/opportunity writes, production
research truth, vendor compatibility, actual payment authenticity, or cloud deployment.
Existing unit/integration suites cover additional retry, failure and concurrency cases.
Resume currently retains refreshed scalar value/score while clearing structured scoring
assessments per the existing domain contract; no fresh historical forecast is invented.

Before any future live run, verified production source/submission/payment contracts,
configured credentials and real operator review will be needed. Those are separate work;
passing this local gate does not initiate or authorize AWS deployment.

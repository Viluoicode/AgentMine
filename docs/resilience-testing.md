# AgentMine resilience testing

Date: 2026-10-22. Tests use synthetic inputs, fake providers, real temporary SQLite
files and the existing DynamoDB emulator. Network connections are blocked by
`tests/conftest.py`. No production service, paid API or financial action is invoked.

## Discovered issue and focused fix

**HIGH — Discovery could remain stuck after a partial database write.**

`DiscoverOpportunities` saves immutable source evidence before creating the
Opportunity aggregate. A temporary failure in the second write leaves evidence
without an aggregate. Rediscovery typically changes the observation timestamp;
trying to overwrite the immutable evidence then failed with CONFLICT indefinitely.
The original data survived, but ordinary retry could not recover it.

Reproduced against SQLite with a failed aggregate save, database reopen, a later
timestamp and an updated source title. The new regression failed before the fix
(`Immutable identity reused`) and passed afterward.

`application/use_cases/planning.py` now completes the missing aggregate from the
already retained observation. It checks source identity before recovery, does not
overwrite provenance, and never downgrades an existing advanced aggregate. Changed
source identities still fail explicitly. Recovery does not assert eligibility or
current availability; subsequent existing use cases must refresh those facts.

No domain rule, repository port, schema, dependency or retry scheduler changed.
Concurrent writers still use the repositories' conditional writes; a losing writer
may receive a conflict and retry discovery safely.

## Scenario matrix

The full suite executes all the tests below; existing scenarios were reused where
they already exercise the required fault rather than duplicating them.

| Requested failure | Injection and evidence | Safe result |
| --- | --- | --- |
| Superteam unavailable | `contract/test_superteam_source.py::test_detail_failure_is_not_empty_success_or_partial_ingestion`; HTTP 503 and other errors | Explicit failure, no invented empty-success result or partially ingested adapter batch. |
| Marketplace timeout | `contract/test_marketplace_transport_archive.py::test_network_errors_are_safe_and_connections_close` | Timeout/incomplete response sanitized; connection closed, no blind transport retry. |
| Malformed marketplace response | `test_invalid_envelopes_are_archived_before_failure`, `test_bad_detail_is_archived_and_database_is_unchanged` in Superteam contract tests | Invalid input rejected; raw evidence retained, opportunity unchanged. |
| Duplicate opportunity | Saved duplicate fixture and reopen/advanced-state tests in Superteam contracts; new discovery recovery test | Stable IDs deduplicate; no lifecycle downgrade or metadata replacement. |
| Bedrock unavailable | `integration/test_resilience.py::test_bedrock_outage_preserves_reservation_and_free_pipeline_continues` | One attempted dispatch, reservation retained, uncertain execution not redispatched; another listing reaches SCORED through free use cases. |
| Invalid LLM output | `contract/test_llm.py::test_invalid_results_still_record_usage`, schema/source validation tests in ResearchWorker | No invalid deliverable accepted; measured usage remains recorded even when output is rejected. |
| Budget exhausted | `e2e/test_local_agentmine.py::test_scout_continuity_and_refreshed_resume` and domain budget tests | SCOUT_ONLY, paid execution denied, WAITING_FOR_BUDGET retained; discovery and deterministic processing continue. |
| Budget restored | Same E2E test, open case | Cost history preserved; fresh status/deadline/eligibility and recalculated score precede resumption. |
| Temporary database failure | New orphan-discovery, execution checkpoint and submission write-boundary tests; real SQLite write lock | Failed authorization dispatches nothing. After recovery, persisted evidence is reused; no hidden cost-history reset. |
| Worker fails halfway | `integration/test_research_recovery.py::test_halfway_failure_reopens_and_keeps_first_source`; existing ambiguous-call and Data recovery tests | Source one survives interruption before source two's claim. Reopen completes each source once, synthesizes once and records costs once. Ambiguous external calls remain blocked for reconciliation. |
| QA failure | `unit/application/test_deliverable_qa.py::test_free_failure_prevents_ai`, `test_optional_ai_and_recovery` | Deterministic failure avoids AI; failed/revision results return work to revision, not submission. PASS only reaches human review. |
| Submission timeout | New `test_submission_failure_reopen_and_changed_id_never_resend`, timeout case | Fake remote receipt exists before timeout; durable intent prevents resend, observation-only reconciliation retrieves that receipt. |
| Submission retry | Same test, attempt/receipt/opportunity write failures; existing application retry tests | Recover after database reopen from retained result or remote reconciliation; repeated completion reuses receipt. |
| Duplicate submission attempt | Same test with changed submission ID; SQLite/DynamoDB claim/concurrency tests | Same deliverable/version cannot acquire another intent. External dispatch count remains exactly one in the tested recovery paths. |
| Accepted but unpaid | Same new submission tests and local E2E pending/unverifiable payment cases | ACCEPTED remains separate from PAID. Pending/unverifiable payment creates zero verified revenue. Missing accepted amount is not guessed. |
| Expires while waiting for budget | E2E restoration expired case; `domain/test_budget_resume.py::test_expired_task_while_waiting_never_reserves_spending` | Task EXPIRED, opportunity SKIPPED, no new reservation, execution or submission. |

Paths in the matrix are relative to `tests/` unless stated otherwise.

## Safety properties checked

- **No duplicate API submission:** durable claims survive failed attempt writes and
  reopen; retries reconcile or reuse evidence. The new gateway fake stores receipts
  separately and reconciliation only reads them, making its external effect count
  independent of local persistence success.
- **No silent overspending:** a real SQLite lock prevents authorization persistence
  and dispatch. Unknown provider cost keeps its commitment. Existing overrun tests
  require actual costs and explicit limit/estimate-exceeded issues to be retained.
  Authorization is not a guarantee about a provider's eventual invoice.
- **No fake verified revenue:** acceptance and potential reward never credit revenue;
  pending/unverifiable evidence remains unpaid. Independent payment evidence and
  payment uniqueness are covered by the settlement suites.
- **Recoverable state survives:** reopen tests retain source observations, work
  responses, incurred costs, submission intent/results and worker checkpoints.
- **LLM outage does not disable unrelated work:** after an actual Bedrock adapter
  timeout through its stub client, discovery, normalization, deterministic eligibility,
  evaluation and scoring run in the same process and database without another LLM call.

## Changes and validation

Changed production file: `src/agentmine/application/use_cases/planning.py`.
Added `tests/integration/test_resilience.py` (10 parameterized cases) and one halfway
recovery case to `tests/integration/test_research_recovery.py`. This report is linked
from README. No dependency introduced.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/test_resilience.py tests/integration/test_research_recovery.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
git diff --check
```

Focused recovery tests: **15 passed**. Full suite: **959 passed in 31.44 seconds**.
Ruff passed; formatting checked 233 files; mypy passed for 181 source files.
`git diff --check` passed (Git may emit LF/CRLF conversion warnings on Windows).

## Recovery limits

These are fault-injection tests, not proof against every crash schedule, disk loss
or real provider behavior. Reopening adapters tests durable state but does not
simulate hardware power loss. A provider effect followed by a crash before its
response checkpoint remains uncertain: AgentMine preserves the claim/reservation
and refuses blind redispatch. It needs independent receipt/billing evidence; no
provider reconciliation contract is invented here.

Submission is not guaranteed exactly once across arbitrary external services. The
tested guarantee is that AgentMine does not issue a second send for a claimed
deliverable/version, provided the durable shared journal is retained and all callers
use these use cases. Manual actions outside AgentMine cannot be deduplicated by it.

No automatic outage recovery scheduler, new endpoint, live gateway or billing
integration was added. DynamoDB emulator behavior is not a substitute for production
concurrency validation; the previously documented emulator caveat remains applicable.
The operator does not need credentials or additional manual steps for these tests.

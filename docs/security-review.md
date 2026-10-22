# AgentMine security review

Review completed: 2026-10-22. Scope: the current local CLI, Domain/Application,
SQLite/DynamoDB persistence, marketplace adapter, Bedrock/Mock providers, workers,
QA, approval, submission and Lambda boundaries. No feature, dependency, cloud resource,
live inference, submission or financial action was added. Existing unrelated changes
to `docs/data-worker.md` and untracked debug logs were left untouched.

## Threat model and evidence limits

An attacker can control marketplace descriptions, titles, linked URLs and research/data
content, including text later sent to a model. Model responses are also untrusted.
The local operator account, explicit composition, provider implementation and authoritative
repositories are trusted boundaries, not a sandbox against arbitrary Python code or a
host administrator. Local operator attribution is not remote authentication.

This review combines source/document inspection, offline adversarial tests and existing
regression tests. It is not a production penetration test, a complete CVE audit, or proof
that a real model will resist every semantic injection. No credentials, private keys or
live workspace data were required. Installed package metadata was inspected; secrets and
private files were not harvested. Production IAM, host ACLs, SDK logging and provider
retention settings have not been validated in a deployed environment.

## CRITICAL

No confirmed CRITICAL vulnerability in the reviewed current entry points. This is not
an assertion that none can exist in future wiring or external providers.

## HIGH

### H-01: Marketplace-controlled prompt length bypassed the funded LLM estimate — FIXED

**Location:** `infrastructure/llm/bedrock.py:BedrockLLMProvider._invoke`, using
`infrastructure/llm/pricing.py:BedrockSettings.estimate`.

**Path:** authorized Research/Data/evaluation/QA request -> attacker-controlled input
within the 64,000-byte content limit -> fixed configured input-token estimate -> Converse.
The estimate did not depend on the actual prompt. A small persisted reservation could
therefore dispatch input whose cost exceeded that reservation, task/period limits or the
human spending threshold. Accounting only detected the overrun after the billable call.
This requires opt-in live Bedrock composition and an otherwise authorized workflow;
discovery alone never invokes a model.

**Offline reproduction:** the new
`test_large_untrusted_prompt_cannot_spend_beyond_reservation` supplies a roughly 29 KB
untrusted input. The synthetic tariff charges USD 2 for a stubbed 2,000-token input and
USD 0.2 for maximum output, while the operation reserves USD 1 and the static estimate
is USD 0.3. Before the fix, the test failed with `DID NOT RAISE PortError`: the fake
Converse client was called. These are controlled contract values, not a claim about a
real tokenizer or current AWS prices.

**Fix:** after the existing initial budget/safety checks, count the exact model, system
prompt and user messages through Bedrock Runtime CountTokens. Require the existing
reservation to cover counted input plus maximum output at the configured tariff.
Re-read current authorization after counting and before claiming/invoking inference.
Invalid, unsupported or unavailable token counting denies inference without fallback.
The adapter never increases the reservation, changes policy or manufactures approval.
Paid-call claims, unknown-outcome handling and honest overrun recording remain intact.

The AWS [CountTokens contract](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_CountTokens.html)
specifies counts for the same inference input. AWS documents the count operation as
unbilled, with model-specific support in its
[token-counting guide](https://docs.aws.amazon.com/bedrock/latest/userguide/count-tokens.html).
The installed botocore service model also confirms the request/response shapes.

**Residual limits:** prices remain trusted configuration; flat tariffs do not cover every
billing dimension. CountTokens also transmits validated input to Bedrock. Unsupported
models/SDKs/permissions now fail closed. In-flight policy changes cannot cancel an already
dispatched request. Higher-level worker/execution claims may need operator reconciliation
after a preflight failure; this review does not add a retry/release workflow.

## MEDIUM

### M-01: Pattern filtering is not a confidentiality or semantic-injection proof — OPEN

**Locations:** `infrastructure/llm/security.py:ContentSafety`,
`infrastructure/llm/operations.py:prepare/decode`, `application/workers/data_semantic.py`,
`application/qa/ai_review.py`.

Arbitrary secret formats, encoded secrets, personal data and paraphrased policy can evade
regex checks. A trusted caller that supplies private data as task/source text can send it
to Bedrock; a model may repeat it in a schema-valid report. An attacker can also influence
analysis or semantic QA without breaking JSON shape. Schema validation authenticates
neither truth nor compliance with natural-language instructions.

No path was found from marketplace text to reading process credentials: the provider
receives allowlisted business fields, not environment/configuration, and has no tools.
Known secret/private-key patterns and caller-supplied forbidden values are rejected,
including after JSON unescaping. Keep source inputs public/explicitly approved, configure
known forbidden values where appropriate, and retain human review. Broader data-classification
and semantic red-team evaluation remain future security work; do not promise universal DLP.

### M-02: Local stored evidence relies on host permissions and retention — OPEN

**Locations:** `infrastructure/marketplaces/raw_archive.py`,
`infrastructure/sqlite/database.py`, worker journals, `infrastructure/snapshots.py`.

Raw marketplace captures can retain contact information and attacker-supplied sensitive
strings. Worker checkpoints retain supplied source text and drafts. SQLite files/backups
are not encrypted or retention-managed by AgentMine. Another account with file access
can read them; a writer can replace data and its checksum. Hashes are not signatures.

Protect the workspace and backups with OS access controls and encryption appropriate to
the operator's machine; keep captures out of version control. Do not load downloaded
database files as trusted workspaces. No host compromise was established and no file
permission/encryption feature was introduced in this review.

### M-03: Refresh does not revalidate every changed marketplace requirement — OPEN

**Locations:** `application/use_cases/context.py:refresh`,
`application/use_cases/eligibility.py`, `infrastructure/marketplaces/superteam.py:refresh`.

Work-starting flows recheck identity, open status and deadline; Superteam also checks
current agent participation. Other eligibility facts and planned requirements are explicit
caller assertions. A listing author can change geographic, identity or prohibited-action
terms after eligibility. The availability-only refresh contract cannot establish that
all those facts remain current. This can leave stale permission assumptions even though
it does not grant shell/wallet/submission capabilities.

Review current requirements before live execution/submission. Unknown facts must remain
UNKNOWN. Full requirement-version/freshness handling needs a separately verified source
contract and application policy; this review does not invent that API or expand the port.

## LOW

### L-01: Receipt URL validation is syntactic, not destination trust — OPEN

`application/contracts/submission.py:SubmissionResult` accepts HTTP(S) strings without
establishing trusted host, userinfo, redirect behavior or public-network destination.
These values are retained metadata and are not fetched or automatically opened. An
operator can still be socially engineered by a deceptive URL. A future fetcher or clickable
UI must independently validate scheme/host/redirects and protect against SSRF; a stored
receipt URL must never become an authorized tool target merely because it starts with HTTPS.

### L-02: Dependency resolution is not reproducible or advisory-gated — OPEN

`pyproject.toml` has no base runtime dependencies, but development tools/build backend
and optional boto3/Moto/transitives are not locked with hashes. A new installation can
resolve different code. Current environment metadata includes boto3/botocore 1.43.114
and Moto 5.2.4. `pip check` validates dependency compatibility, not absence of vulnerabilities.
No exhaustive advisory scan or package integrity attestation was performed, and no
specific exploitable dependency CVE is claimed. Before production, use reviewed reproducible
dependency resolution and an advisory scan; no dependency was installed/upgraded here.

### L-03: External debug logging can expose payloads — OPEN

AgentMine's examined runtime/LLM/source logs use codes/counts/correlation metadata rather
than raw provider messages. Nevertheless, enabling SDK wire/debug logging outside these
modules can expose request bodies or credentials; supplied identifiers can themselves
contain sensitive text. Keep SDK wire logging disabled and identifiers non-sensitive.
The repository does not enforce a process-wide logging policy or inspect arbitrary
operator-generated debug logs. This is a deployment control, not a confirmed marketplace
route to reading secrets.

## Explicit attack-path review

| Attempt | Observed boundary and result |
| --- | --- |
| Reveal credentials/private keys/environment | Synthetic environment secret is absent from CountTokens/Converse requests and application logs. Direct and escaped known secret output is rejected. No filesystem/environment tool is exposed. Arbitrary secrets already supplied as content remain M-01. |
| Ignore policy / inject a system role | Role-breaking JSON and policy-override text remain inside one JSON-encoded user payload. Model/system/SDK arguments remain composition-owned. Real semantic persuasion remains M-01. |
| Spend money / increase budget | Long input found H-01 and is now blocked before inference. Current SCOUT_ONLY, insufficient reservation, forged spending approval and threshold/cap tests deny dispatch. Source/model content cannot change BudgetPolicy. |
| Submit without human approval | All three submission modes reject before a matching HumanApproval and passed QA. QA PASS stops at human review. Exact content digest/version/destination checks prevent payload substitution. Trusted legacy ApproveSubmission is not exposed as a model tool or remote endpoint. |
| Duplicate external actions | Durable SQLite/DynamoDB intent ownership includes deliverable/version, not only caller-chosen submission ID. Unknown calls reconcile instead of resend. Paid LLM claims prevent retries after uncertain dispatch. Manual clicks and broken provider implementations remain outside local exactly-once guarantees. |
| Perform prohibited actions | Only Research/Data execution types; deterministic eligibility blocks declared prohibited actions and unresolved facts. No shell, code runner, wallet or sensitive-account executor exists. Natural-language model plans remain text, not dispatched commands. |
| Fetch attacker URL / metadata endpoint | Superteam uses a fixed HTTPS host and route allowlist, rejects redirects and does not inherit proxies. Research checks exact composition-approved tool/locator before I/O; model URLs are not automatically fetched. Future real ResearchTool adapters must enforce network/redirect safety. |
| Forge lifecycle/payment state | Discovery rejects advanced-state source snapshots; public domain transitions require evidence. Unknown/accepted rewards do not become verified revenue. Lambda input cannot supply approvals/payment proofs or select adapters. A writable authoritative database is a trusted-host compromise, not authenticated external evidence. |
| Unsafe file/data payload | Workers return fixed-name text artifacts, not arbitrary file writes; no eval, subprocess, pickle or task-selected imports. CSV values receive formula-prefix escaping and columns are constrained; research Markdown uses literal blocks. CSV/JSON, row counts, fields and content sizes are bounded. JSON retains original untrusted values and must not later be interpreted as executable content. |

## Architecture and deployment implications

Only the Bedrock infrastructure adapter and its fake SDK seam change. Application
LLMProvider, Domain, schema/persistence and business policies are unchanged. CountTokens
uses the existing Bedrock service, with verified request shape; no new AWS service or
dependency is needed. MockLLMProvider and local SQLite workflows remain available.

Do not expose operator CLI/use cases as unauthenticated remote or model tools. The single
operator's configured ID is audit attribution, not IAM. Production gateways/verifiers are
still absent. The existing AWS review's shared durable LLM journal and raw-archive gaps
remain deployment blockers: independent Lambda-local journals cannot guarantee globally
unique paid dispatch. No cloud composition or resources were added to bypass those gates.

## Validation

Before the fix, the focused long-prompt regression failed as expected after a sandbox
temporary-directory error was resolved by running the offline test with filesystem
permission. After the fix, the initial Bedrock contract suite passed 41 tests.
Additional tests cover four injection payloads, environment/log isolation and a mode
change during token counting. All provider/token-count values are stubs; pytest blocks
network connections. No operator credentials or manual actions are needed to run them.

Commands run with the existing `.venv\Scripts\python.exe`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/contract/test_llm.py -k large_untrusted_prompt -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests/contract/test_llm.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests/contract/test_llm.py -x -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests/integration/test_dynamodb_persistence.py::test_two_budget_writers_cannot_reserve_same_revision -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m pip list --format=json
.\.venv\Scripts\python.exe -m pip check
git diff --check
```

The changed test file was formatted with Ruff. Focused final Bedrock contracts:
**46 passed**. Ruff lint/format passed, mypy passed (180 source files), and pip check
reported no broken requirements. Diff whitespace checks passed with Windows line-ending
warnings only.

The first full run reported **928 passed, 1 failed** in the pre-existing Moto test
`test_two_budget_writers_cannot_reserve_same_revision`: one transaction reported success,
but the stored budget reverted to revision 1. The isolated rerun passed. Inspection of
installed Moto 5.2.4 `DynamoDBBackend.transact_write_items` found whole-table deepcopy
backup/restore without transaction locking in that method, consistent with a losing
concurrent transaction restoring stale state. This is a supported explanation, not a
production DynamoDB reproduction. AgentMine still emits conditional budget/audit writes
in one transaction. No production locking workaround, test skip, assertion weakening
or dependency upgrade was applied. Moto tests alone do not establish real concurrency
isolation; verify against an appropriate DynamoDB test environment before deployment.

Final full-suite rerun: **929 passed in 55.15 seconds**, with no skips or failures.
The earlier intermittent Moto failure remains disclosed above; a passing rerun does
not erase that validation limitation. External API spend for this review: **USD 0**.

Changed files: `src/agentmine/infrastructure/llm/bedrock.py`,
`tests/contract/test_llm.py`, `docs/llm-infrastructure.md`, `README.md`, and this report.
Dependencies introduced: none. Architecture deviations: none. Before any future live
Bedrock use, the operator must confirm model/region CountTokens support, scoped permissions,
current tariff and shared durable journals. No live test or deployment is authorized by
this review, and no user action is needed for the completed offline verification.

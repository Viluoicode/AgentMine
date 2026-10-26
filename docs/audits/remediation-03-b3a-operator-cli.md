# F02-B3-A: Local operator CLI and runtime composition

Date: 2026-10-26 (Asia/Bangkok). Verdict: **PASS_WITH_LIMITATIONS** for this local
CLI checkpoint. All final verification gates below passed. F02 overall remains
open. No commit/push or F02-B3-B implementation.

## Implementation and architecture

Before this change, the CLI could initialize/load/display workspaces and perform
eligibility/submission review, but B2's deterministic worker had no operator command.
The new groups reuse the existing module entrypoint and application workflows:

| Commands | Application behavior |
| --- | --- |
| `dashboard`, `opportunity show` | Existing opportunity inventory; current revision/state, task, eligibility, forecast/scoring, required approvals and separately labelled verified revenue |
| `opportunity eligibility/evaluate/score/plan` | Existing CheckEligibility, EvaluateOpportunity, ScoreOpportunity and PlanTask; explicit inputs, no guessed facts or invented score |
| `work prepare/show` | New PrepareDataSpecification/GetDataSpecification: approved bounded local inputs, retained evidence, exact digest and immutable specification |
| `work execute` | Existing ExecuteWorkerTask; explicit IDs/revision/confirmation; source/preflight/budget/start/result/finish safeguards unchanged |
| `work recover` | Resolve the existing stored binding and invoke ExecuteWorkerTask with original identities; no new execution fallback |
| `work status` | Read current Opportunity state and retained results/recovery reason; completed history is not current QA readiness |
| `work export` | Export existing artifacts through an application port to an explicit local destination; no submission |

Production composition uses one SQLiteDatabase for all repositories, approvals,
runtime and DataJournal. BudgetManager uses the chosen authoritative ledger;
ExecuteWorkerTask constructs DataWorker with llm=None. The real entrypoint validates
one matching workspace ledger before runtime I/O. Source-disabled default fails
closed. Explicit read-only Superteam opt-in reuses the existing verified adapter.
No MockLLM, fake marketplace, provider fallback, Bedrock, gateway or verifier is
constructed in this runtime composition.

Preparation requires PLANNED state, an existing EvaluationRecord, explicit normalized
facts/policy, approving actor and approved input digests. It captures current source
context and runs B2 WorkerPreflight before saving. There are at most two detail
refreshes during preparation; execution independently revalidates again through B2.
Same-ID preparation reads/verifies the same files/context and preserves the original
approval time; it never mutates an immutable specification or renews consent.

No Domain, B2 execution/lifecycle, BudgetManager or DataWorker rule was changed.
See [ADR 0025](../adr/0025-local-data-operator-cli.md),
[ADR 0024](../adr/0024-deterministic-data-execution.md) and the
[F02-A plan](remediation-03-runtime-plan.md).

## Changed files and existing work

New production files:

- `application/contracts/local_runtime.py`: typed approved input, prepare and export records.
- `application/ports/local_runtime.py`: DataInputReader and ArtifactExporter.
- `application/use_cases/local_runtime.py`: focused prepare/read/recover/export use cases.
- `bootstrap/local_runtime.py`: explicit real local dependency composition.
- `presentation/runtime_inputs.py`: strict bounded economics/scoring/data JSON parsing.
- `presentation/runtime_cli.py`: runtime parsers, application invocation and escaped output.
- `infrastructure/local_data_inputs.py`: safe exact approved local byte capture.
- `infrastructure/local_artifact_export.py`: local no-clobber artifact/manifest publication.

The paths above are relative to `src/agentmine/`. Existing files changed for wiring:
`src/agentmine/bootstrap/operator.py` and `src/agentmine/presentation/operator_cli.py`.
Added `tests/integration/test_runtime_operator_cli.py`, ADR 0025 and this report;
updated `docs/adr/README.md` and `docs/operator-interface.md` with links.

B2 changes/reports/tests were already uncommitted at task start and were preserved.
They are not claimed as new B3-A implementation. No dependency or database schema
was introduced, no workspace reset occurred and no existing test was weakened.

## Commands and inputs

Commands below use PowerShell from the repository root. They describe real operator
steps, not fixture seeding. Select an actual retained opportunity from the dashboard.
Provide truthful current facts/evidence and forecasts; a missing prerequisite must
stay blocked. Do not copy invented eligibility or payment into a real workspace.

```powershell
$python = ".\.venv\Scripts\python.exe"
$base = @("-m", "agentmine.bootstrap.operator", "--db", ".tmp/agentmine.sqlite3", "--ledger", "local")
& $python @base work --help
& $python @base opportunity --help
& $python @base dashboard
$opportunity = "ID_FROM_YOUR_DASHBOARD"
& $python @base opportunity show --opportunity $opportunity
```

Use an initialized single-ledger workspace. Existing `workspace init` and
`workspace discover --source superteam --live --limit 1` remain available; see
[the operator guide](../operator-interface.md). Initialization creates no offers,
approval, cost or revenue. Do not reinitialize with another policy to alter budgets.

For actual source checks, configure authorized `AGENTMINE_SUPERTEAM_API_KEY` securely
and set one local audit actor. The global refresh options precede the command:

```powershell
$env:AGENTMINE_OPERATOR_ID = "local-operator"
$live = @("--live-superteam-refresh", "--archive", ".tmp/agentmine.sqlite3.raw.sqlite3")
& $python @base @live opportunity eligibility --opportunity $opportunity --facts .tmp/facts.json --minimum-time-seconds 3600
& $python @base @live opportunity evaluate --opportunity $opportunity --inputs .tmp/economics.json
& $python @base @live opportunity score --opportunity $opportunity --evaluation evaluation-001 --inputs .tmp/scoring.json
& $python @base @live opportunity plan --opportunity $opportunity --task task-001 --description "Process the approved dataset according to reviewed requirements"
```

These are separate actions, not run-all. Stop on UNKNOWN, INELIGIBLE or other
blocked state. Only deterministic Data is planned by this CLI. For MANUAL, use the
existing F04 eligibility prepare/show/decide workflow and retain its actual review
ID; do not relabel it AUTOMATIC to continue. Skip reapplying the eligibility command
after that decision; proceed with evaluation/scoring/planning. Submission approval
is an entirely different future boundary.

`facts.json` uses the existing explicit facts/profile schema documented in the
[F04 operator guide](remediation-02-eligibility-review.md#9-operator-use-and-limitations).
All allowances must be supported by reviewed requirements and the real profile.
Omitted facts remain UNKNOWN; open/deadline values come from the source. No JSON
field can provide a successful Eligibility object or an authorization.

`economics.json` requires exactly these fields (cost_evidence is optional):

```json
{
  "currency": "USD",
  "predicted_success_probability": {
    "value": "0.5", "rationale": "Subjective operator prediction; replace with your reviewed assumption",
    "evidence": []
  },
  "estimated_cost": {"ai": "0", "tool": "0", "infrastructure": "0.01", "transaction": "0"},
  "cost_rationale": "Example local-work forecast; replace with justified estimates, not billing claims",
  "cost_evidence": []
}
```

These example amounts/probability are not automatic policy or objective facts. Use
the opportunity's actual currency; no FX/USDC conversion is supplied. Deterministic
Data requires zero AI estimate. Other estimates do not become actual costs.

`scoring.json` uses explicit policy target/version/rationale and five subjective
signal objects. Unknown values should be null, not a guessed favorable number:

```json
{
  "policy": {"version": "operator-v1", "net_value_target": "10", "currency": "USD", "rationale": "Explicit operator target; replace as appropriate"},
  "signals": {
    "risk": {"value": null, "rationale": "Not assessed"},
    "competition": {"value": null, "rationale": "Not assessed"},
    "deadline": {"value": null, "rationale": "Not assessed"},
    "ai_suitability": {"value": null, "rationale": "Not assessed"},
    "historical_performance": {"value": null, "rationale": "No verified history"}
  }
}
```

Known signal values are decimal strings in [0,1]; optional evidence is an array of
references. The existing Domain scoring defaults/unknown-signal limits apply.
There is no new formula, automatic ATTEMPT recommendation or success guarantee.

Choose a protected **local** input root and approved UTF-8 CSV/JSON without BOM.
Compute the exact file digest after reviewing it, then create a bounded manifest:

```powershell
(Get-FileHash .tmp/inputs/data.json -Algorithm SHA256).Hash.ToLowerInvariant()
```

Example `data-spec.json` shape; replace digest/time/provenance with actual values:

```json
{
  "sources": [{
    "id": "input-001", "path": "data.json", "sha256": "REPLACE_WITH_64_LOWERCASE_HEX_DIGITS",
    "format": "json", "locator": "operator:approved-dataset",
    "collected_at": "2026-10-26T00:00:00+00:00"
  }],
  "columns": [{"name": "name", "path": ["name"], "kind": "text", "required": true}],
  "unique_by": ["name"], "min_records": 1, "max_records": 1000,
  "constraints": []
}
```

The intentionally invalid digest placeholder must be replaced. Source paths are
relative to the selected root. Preserve real collection/provenance information;
future timestamps fail. Each file is at most 1,000,000 bytes, at most ten files;
metadata/facts manifests are at most 64,000 bytes. Duplicate/extra JSON keys, boolean
counts, unsafe paths, linked/reparse files and unsupported semantic/executable
fields fail. PowerShell 5 UTF-8 writing may add a BOM: convert deliberately before
reviewing/hashing, not after approval. No input normalization or silent file repair.

Columns support existing kind/required/case, allowed_values, minimum/maximum,
max_length and lookup/lookup_evidence fields. Constraints use left/comparison/right
with existing equal/less_or_equal rules. Semantic fields are unsupported.

```powershell
& $python @base @live work prepare --opportunity $opportunity --spec-id spec-001 --inputs .tmp/data-spec.json --input-root .tmp/inputs --facts .tmp/facts.json --minimum-time-seconds 3600 --evaluation evaluation-001 --approve-inputs
& $python @base work show --spec-id spec-001
# Add --eligibility-review ACTUAL_REVIEW_ID to prepare for a resolved MANUAL case.
$state = & $python @base opportunity show --opportunity $opportunity | ConvertFrom-Json
$revision = $state.opportunity_revision
& $python @base @live work execute --spec-id spec-001 --execution-id exec-001 --operation-id operation-001 --deliverable-id deliverable-001 --expected-revision $revision --confirm
& $python @base work status --execution-id exec-001
```

Prepare records input/scope approval only and never starts work. Show displays exact
digests, scope, source requirements and evidence; it does not reread input files.
Files edited after approval cannot change frozen snapshots. Repreparing that ID
with changed input/metadata is rejected; use a new reviewed specification when needed.

Start requires --confirm and stable IDs. New start compares the revision; identical
retry retains original execution/operation/deliverable identity. Output distinguishes
`command_status` COMPLETED/BLOCKED/RECOVERABLE from `opportunity_state` PLANNED,
IN_PROGRESS or QA_PENDING. Work status separates `execution_history_completed`,
current business state, retained results and `recovery_reason`. COMPLETED history
never implies QA PASS, submission approval or earnings.

```powershell
& $python @base @live work recover --execution-id exec-001 --confirm
# For retained-result completion, no source call is needed; @live may be omitted.
New-Item -ItemType Directory -Force .tmp/exports | Out-Null
& $python @base work export --execution-id exec-001 --directory .tmp/exports/exec-001
```

Recover requires an existing run. Without a result it revalidates before deterministic
replay; with a result it repairs cost/finish without recomputation. Unknown AI claims
stay blocked. QA_PENDING cannot advance through this checkpoint: inspect/export,
then wait for the separately authorized QA workflow. Do not reset state or change
IDs to force rework/resume.

Export publishes fixed existing artifacts and manifest.json locally, never opens
URLs/apps or submits. Parent directory must exist. Existing identical content is
idempotent; conflicting/unrelated files cause failure without overwrite. Atomic
no-clobber publication requires local hard-link support. A crash may leave partial
files without a final manifest; inspect before retrying. Never delete claims or
financial evidence to repair an export. Validation-only artifacts remain diagnostics.

## Verification

New offline CLI tests were written first and initially failed **10 cases** because
the runtime composition/`work` command were missing (TypeError/argparse failures).
This is missing-capability acceptance evidence, not reproduction of an old defect.

Tests use real SQLite, actual application calculations/DataWorker/BudgetManager and
explicitly injected fake read-only source observations only in test composition.
They cover prepare/show/execution, full eligibility-to-plan commands, missing/changed
inputs/digests, traversal/link rejection, strict JSON, unavailable/changed source,
expired/ineligible cases, missing approval/economic evidence, actor/ledger guards,
reopen/same-ID recovery, export/no-overwrite and absence of mock/paid/action fallback.
Existing operator/F04/architecture and full-suite regressions remain active.

Commands used the configured environment and repository network block. No tests
required a live provider, marketplace key, paid call, real submission or payment.

| Command | Actual result |
| --- | --- |
| `.\.venv\Scripts\python.exe -m pytest tests/integration/test_runtime_operator_cli.py -q --tb=short -p no:cacheprovider` before production edits | Exit 1: 10 expected missing-capability acceptance failures |
| Same focused command after all changes | Exit 0: **26 passed in 12.71s** |
| `.\.venv\Scripts\python.exe -m pytest tests/integration/test_runtime_operator_cli.py tests/integration/test_operator_interface.py tests/integration/test_eligibility_operator.py tests/unit/test_architecture.py -q --tb=short -p no:cacheprovider` | Exit 0: 60 passed in 17.86s, before six further CLI cases |
| `.\.venv\Scripts\python.exe -m pytest -q -ra --tb=short -p no:cacheprovider` after final code/test changes | Exit 0: **1146 passed in 95.99s**, no skips or warning summary |
| `.\.venv\Scripts\python.exe -m ruff check .` | Exit 0: all checks passed |
| `.\.venv\Scripts\python.exe -m ruff format --check .` | Exit 0: 274 files already formatted |
| `.\.venv\Scripts\python.exe -m mypy` | Exit 0: no issues in 209 source/test files |
| Operator `work --help` and `opportunity --help` with explicit --db/--ledger | Exit 0; parser help requires no credentials/source/work |
| `git diff --check` | Exit 0: no whitespace errors; Windows line-ending conversion warnings only |

An earlier full run passed 1140 tests before the final six cases; it is not used as
the final result. Interim formatting/type/static feedback was corrected without
removing assertions or skipping tests. The final full suite covers all original
B1/B2/F01/F04, architecture and CLI compatibility tests as well as the new cases.
Report links/sections/whitespace and absence of mock/test imports in the new
production composition were also checked by a read-only validation script (exit 0).

## Limitations and disposition

- Real source access requires an authorized key and explicit live opt-in; no live
  marketplace or earned reward was verified. Existing source normalization,
  pagination/currency and strict body-version limitations remain.
- Operator facts, estimates and profile assertions are not automatically verified.
  A source can change after refresh; B2 and later approval boundaries remain distinct.
- This is a trusted local single-operator interface, not remote IAM or a filesystem
  sandbox against malicious host writers. Use real local drives; obvious UNC roots
  are rejected, but mapped-drive/host ACL classification is not authenticated here.
- No encrypted storage/backup reconciliation or automatic export cleanup is added.
  Filesystems without required no-clobber hard-link support fail rather than use an
  unsafe overwrite fallback.
- No QA orchestration, Research, paid AI, budget policy/resume (F02-B4), F05 revisions,
  submission/payment, web frontend, workflow framework or AWS deployment.

No operator action/key is needed for offline tests. A real walkthrough needs the
operator to choose an eligible supported opportunity, verify facts/forecasts and
approve genuine local input snapshots. No mock can replace those missing inputs.
Stop after this checkpoint for operator review. Do not begin F02-B3-B.

# Remediation 02: Human eligibility review resolution (F04)

Date: 2026-10-25. Scope: F04 only. No deployment, paid calls, commit or push.

## 1. Root cause

The deterministic engine correctly returned REQUIRES_HUMAN_REVIEW with
MANUAL_SUBMISSION_REQUIRED, but no application workflow could resolve it.
Repeating the check preserved the pending result. Existing human approval concerns
deliverables/submission or spending, and cannot serve as eligibility consent.

## 2. Reviewable and non-reviewable reasons

Only MANUAL_SUBMISSION_REQUIRED can be approved, and only as the sole remaining
review reason after recomputing every deterministic check. Approval requires
explicit evidence references for the destination, instructions, account access
and satisfied manual requirements, plus an affirmative requirements attestation.
The submission fact remains MANUAL.

AI prohibition, closed/expired opportunities, unsupported task types, prohibited
actions, unmet mandatory restrictions, UNKNOWN facts and credential demands cannot
be approved. AI_POLICY_REVIEW_REQUIRED and suspicious upfront-payment reviews are
also outside this narrow approval policy. A rejection records INELIGIBLE and its
original reasons; it grants no permission. Changed or unknown source context
requires a fresh review even for rejection.

## 3. Domain and application design

Domain owns immutable ManualEligibilityEvidence and EligibilityResolution values,
APPROVE/REJECT choices and the narrow resolution policy. Required rationale is
bounded, timestamps must be timezone-aware, and evidence must be explicit.

PrepareEligibilityReview runs the existing engine and records an immutable review
of facts, participant profile, reasons, policy, engine version, source requirements,
content version and Opportunity snapshot/revision. A new review ID advances the
Opportunity revision even if its reason codes are unchanged, invalidating older
facts/profile/policy contexts. A deterministic result is stored without creating a
pending review. Same-ID identical preparation reads back its original snapshot.

ResolveEligibilityReview checks the configured operator, authoritative revision,
fresh source identity/status/deadline/content and requirements, then recomputes
eligibility at decision time. It commits the decision and resulting Opportunity
together through an application port. GetEligibilityReview exposes the recorded
facts, reasons and decision. Infrastructure implements storage and source refresh;
the CLI parses typed input, invokes these use cases and renders quoted content.

See [ADR 0022](../adr/0022-human-eligibility-resolution.md). Dependency direction
remains Presentation → Application → Domain; infrastructure implements inner ports.
No AWS or marketplace model was added to Domain/Application.

## 4. Changed files

Paths below are relative to the repository root.

| Area | Files | Purpose |
| --- | --- | --- |
| Domain | `src/agentmine/domain/eligibility_review.py`, `eligibility_rules.py`, `work.py` | Evidence, resolution policy, rules version and audit reason codes |
| Application contracts | `src/agentmine/application/contracts/eligibility.py`, `opportunities.py` | Immutable review/commit contracts and optional source context |
| Application ports | `src/agentmine/application/ports/eligibility_review.py`, `services.py` | Atomic resolution persistence and source context responsibility |
| Application workflows | `src/agentmine/application/use_cases/eligibility.py`, `eligibility_review.py` | Reusable inspection; prepare, inspect and resolve review |
| Persistence | `src/agentmine/infrastructure/sqlite/eligibility_review.py`, `src/agentmine/infrastructure/dynamodb/eligibility_review.py`, `src/agentmine/infrastructure/snapshots.py` | Atomic adapters and explicit snapshot types/legacy compatibility |
| Source adapter | `src/agentmine/infrastructure/marketplaces/superteam.py`, `superteam_normalization.py` | Hash captured detail response and reuse requirements extraction |
| Composition | `src/agentmine/bootstrap/local.py`, `dynamodb.py`, `operator.py` | Wire ports and existing single-operator boundary |
| Presentation | `src/agentmine/presentation/operator_cli.py`, `eligibility_inputs.py` | Minimal eligibility commands and bounded explicit JSON parsing |
| Tests | `tests/unit/application/test_eligibility_review.py`, `fakes.py`, `tests/integration/test_eligibility_review_persistence.py`, `test_eligibility_operator.py`, `tests/contract/test_superteam_source.py` | Regression, persistence, concurrency, CLI and source contract coverage |
| Documentation | This report, `docs/adr/0022-human-eligibility-resolution.md`, `docs/adr/README.md`, `docs/operator-interface.md` | Policy, evidence and operator entry points |

No dependencies or AWS services were introduced. No database reset is required.
Older OpportunityStatus snapshots load the two optional source-context fields as
None; missing context cannot authorize resolution. Existing snapshot semantics
and deterministic eligibility rules were not weakened.

## 5. Test-first regression evidence

Before production edits, a deterministic regression reproduced repeated manual
checks remaining pending and asserted the missing resolution use case. Its initial
run failed as expected: **1 failed**, because the resolution workflow was absent.
The final regression exercises actual prepare/resolve behavior with fake ports,
proving the transition to ELIGIBLE without submission approval.

Additional tests cover auditable rejection; AI prohibition; unsupported/prohibited
actions; unmet requirements; UNKNOWN facts; sensitive reviews; closed/expired or
changed source; missing source version; stale Opportunity revision; changed
facts/profile/policy; missing evidence; idempotent and conflicting retries;
concurrent decisions; restart/readback; CLI attribution and terminal escaping.

## 6. Persistence and concurrency guarantees

SQLite stores immutable reviews and decisions using the existing snapshot store.
Resolution uses BEGIN IMMEDIATE and writes the Opportunity and decision in one
transaction, checking the exact reviewed snapshot first. A fault injected between
the writes rolls both back.

DynamoDB uses existing item storage with eligibility_review and
eligibility_resolution item types. A conditional transaction checks the
Opportunity revision and absent decision while updating both together. Existing
index attributes are preserved and the lifecycle index is updated. No new table
or GSI is required. Tests exercise the same behaviors against SQLite and Moto's
DynamoDB environment, including a revision race at commit.

One contradictory decision wins; identical retries read back the immutable audit.
Different review IDs cannot grant conflicting authority from an older context:
preparation advances the Opportunity revision. Preparation and review storage are
separate writes; a failure may leave an invalidated older review and require
re-preparation, but cannot leave a partial eligibility grant.

## 7. Authorization and audit boundaries

The configured AGENTMINE_OPERATOR_ID supplies decision attribution; the facts file
cannot select an actor. This remains the existing trusted local single-operator
boundary, not remote authentication or multi-user IAM. Protect the host, database
and environment. Audit retains actor, time, rationale, choice, evidence references,
facts/profile, source context, rules/policy and Opportunity revision.

Approval changes eligibility only. It creates no task, deliverable, QA pass,
HumanApproval, submission, payment, verified revenue or spending authorization.
Submission still requires its separate existing human approval boundary.

## 8. Verification

Commands use the existing development environment; tests require no production
API, AWS credentials or paid model calls. Final results are recorded below.

```powershell
.\.venv\Scripts\python.exe -m pytest -q -ra --tb=short -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
git diff --check
```

Focused eligibility, operator approval, SQLite/DynamoDB, Superteam contract and
architecture checks previously passed together: **252 passed**. Explicit
architecture checks passed: **29 passed**. CLI group/decision help exited 0.

Final verification after all production edits:

| Check | Actual result |
| --- | --- |
| Full pytest suite | 1041 passed in 49.98s; no skips or warnings reported |
| Ruff check | All checks passed |
| Ruff format check | 250 files already formatted |
| Strict configured mypy | No issues in 191 source files |
| `git diff --check` | Exit 0; no whitespace errors |

The full suite includes the focused tests and architecture checks above. No live
provider or paid API was required. An earlier combined tool-output capture was
truncated; the full suite and static checks were rerun to obtain these results.

## 9. Operator use and limitations

The new commands are `eligibility prepare`, `eligibility show` and
`eligibility decide`. Inspect their required arguments first:

```powershell
.\.venv\Scripts\python.exe -m agentmine.bootstrap.operator eligibility --help
.\.venv\Scripts\python.exe -m agentmine.bootstrap.operator eligibility prepare --help
.\.venv\Scripts\python.exe -m agentmine.bootstrap.operator eligibility decide --help
```

Use an existing normalized/pending Opportunity ID and local workspace/ledger.
`prepare` requires `--opportunity`, `--review-id`, `--facts` (local JSON file) and
`--minimum-time-seconds` (your policy choice). `show --review-id` is local readback.
`decide` requires `--review-id`, `--decision APPROVE|REJECT` and `--reason`.
APPROVE additionally requires `--manual-destination`, `--instructions-evidence`,
`--access-evidence`, `--requirements-evidence` and `--manual-requirements-met`.
Set AGENTMINE_OPERATOR_ID before deciding. Do not put credentials in evidence.

Facts JSON accepts `facts` and `profile` objects. The following is **synthetic test
data**, not safe defaults for real opportunities. Every allowance/empty set/false
must be supported by the current source and your actual participant profile:

```json
{
  "facts": {
    "ai_policy": "allowed",
    "geography": {"allowed": [], "excluded": []},
    "account": "not_required",
    "identity": "not_required",
    "physical_presence": "not_required",
    "task_type": "research",
    "required_skills": [],
    "submission": "manual",
    "payment": {"upfront_fee": false, "secret_credentials": false},
    "prohibited_actions": []
  },
  "profile": {}
}
```

Omitted facts remain UNKNOWN. Source refresh supplies open/deadline facts; the
input cannot override them. Profile optionally accepts country, skills,
account_requirement_met, identity_requirement_met and will_disclose_ai.

Prepare/decide need a supported fresh source. The default disabled source fails
closed. For a deliberate real Superteam review, use the existing global
`--live-superteam-refresh` opt-in and configured authorized key/archive as described
in [the operator guide](../operator-interface.md); this performs read-only refresh,
not submission. Retain real captures/checklists for evidence and inspect `show`
before deciding. No operator action or key is needed for offline regression tests.

Remaining limitations:

- Facts/profile and evidence references are trusted operator/adapter assertions;
  the system does not independently verify documents or account access.
- Sources without known requirements and version metadata cannot grant resolution.
- Superteam's version is a hash of exact captured response bytes, not an invented
  provider version API. Harmless changes can invalidate a review.
- External content cannot be locked atomically with local storage. Resolution binds
  the freshly observed context; broader later-workflow freshness is not solved here.
- Identical decision retry is historical readback, never a renewed freshness grant.
- New rules versions require an explicit compatibility/migration decision; unknown
  versions fail closed. Review data may contain private profile information.
- DynamoDB evidence is local/Moto, not a production AWS test; no live marketplace
  or production authorization validation was performed.

## 10. F04 status

**RESOLVED**: supported, evidence-bound human resolution exists for otherwise
eligible manual submission opportunities, with audit, stale-context protection,
idempotency and atomic persistence. This is not a production-readiness claim.
F02, F03, F05 and other findings remain outside this remediation. Stop here for
operator review; do not automatically proceed to another finding.

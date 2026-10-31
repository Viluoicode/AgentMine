# F03-B1: Immutable submission context and evidence foundation

Started 2026-10-29; continued/final verification 2026-10-31, Asia/Bangkok.
Base commit: `9748fc6f275dfdb68466785a9dbf95ccfda48912`.

## Scope and initial state

Implements only the approved manual-first offline B1 foundation. Existing Data
runtime/versioned QA, real SQLite, review/decision components and Domain lifecycle
are reused. Read AGENTS.md, Constitution, F03-A, original F01/F03/F07/F08 findings,
F02-B5/F05-B4/FIX1 reports, relevant ADRs and current source before choosing the
bounded change. Current code takes precedence over milestone descriptions.

The untracked F03-A report `remediation-06-submission-payment-plan.md` was present
at task start and is preserved. No dependency installation, external integration,
account action, paid call, handoff, submission or payment is performed. No commit
or push. B2 and later checkpoints are not started.

## Implementation and changed files

| File | Responsibility |
| --- | --- |
| `src/agentmine/application/contracts/submission_context.py` (new) | Frozen envelope/request, account/channel/outbound/public-reference models, versioned canonical scope digest, provisional evidence and consent view |
| `src/agentmine/application/ports/submission_context.py` (new) | Narrow immutable prepare/read/scope/evidence port; no dispatch or financial policy |
| `src/agentmine/application/use_cases/submission_context.py` (new) | Derive envelope from authoritative retained work/QA/source, actor/ledger validation, provisional capture import/read and exact applied-consent inspection |
| `src/agentmine/application/contracts/operator.py` | Optional resolved envelope on the nonpersisted recorded-review response; existing OperatorReview snapshot shape unchanged |
| `src/agentmine/application/use_cases/operator.py` | Resolve/check reserved context scopes in existing review/get/decide; retain existing decision policy and applied transition; local context approval performs no source call |
| `src/agentmine/application/use_cases/settlement.py` | Reject reserved B1 scope before legacy SubmitTask claims or calls a gateway |
| `src/agentmine/application/use_cases/manual_submission.py` | Reject reserved B1 scope before legacy manual receipt can create SUBMITTED |
| `src/agentmine/infrastructure/sqlite/submission_context.py` (new) | Same-workspace atomic immutable account/channel/envelope/scope and evidence/capture storage, current revision/evidence checks and integrity readback |
| `src/agentmine/infrastructure/snapshots.py` | Add explicitly allowed context/evidence model module; no dynamic loading or legacy-authority migration |
| `src/agentmine/presentation/submission_context_cli.py` (new) | Strict bounded offline prepare/show/evidence/consent commands and escaped context display |
| `src/agentmine/presentation/operator_cli.py` | Route context commands and show resolved scope through existing review/show-review |
| `src/agentmine/bootstrap/operator.py` | Explicit real SQLite/runtime history/QA/actor/ledger composition; trusted actor and workspace guards |
| `tests/integration/test_submission_context.py` (new) | Real file-backed acceptance, version ownership, consent, evidence, CLI, concurrency, fault/reopen and zero-action tests |
| `docs/adr/0029-immutable-submission-context-foundation.md`, ADR index | Exact-version ownership and trust/transaction decision |
| This report | Test-first evidence, verification, recovery and limitations |

No Domain, existing F01 submission repository/claim transaction, worker algorithm,
QA engine, financial model or cloud implementation changed. Application depends
on ports and Domain. SQLite enforces consistency; it does not choose eligibility,
account permission, outcome or payment. The canonical encoder is feature-scoped
and independent of infrastructure snapshot serialization.

## Binding and trust semantics

The envelope retains the exact original Opportunity snapshot/revision, completed
run/specification/Task, returned WorkerResult and artifact bytes/digests, exact
deliverable lineage/version/content, applied QA inspection/report, observation,
source terms and original eligibility/economic evidence. It is derived from the
current completed Data execution; callers cannot submit replacement authority.

Scope binds the envelope identity, account/provider, effective account, explicit
channel/listing/destination, descriptive MANUAL/API-intended mode, exact outbound
text/artifact selection, declared published references and disclosure/effect
declarations. Preparation from a historical execution is rejected if it is no
longer current; already-retained historical envelopes remain immutable/readable.

Existing review IDs bind `submission-context:<canonical SHA-256>` in their scope.
Review/show-review display the resolved object before APPROVE. Changed account,
channel, mode, bytes or version requires a different scope/new review. Reusing an
account/channel ID with a different definition conflicts. Identical v1/v2 bytes
cannot transfer QA or submission consent. A stored decision whose Opportunity
transition has not committed is reported unapplied; same-decision recovery can
complete the existing transition. Stale/later snapshots are not current consent.

This is local scope approval, not a fresh source/account permission check. Context
approval avoids live reads; legacy review behavior is preserved. All B1 views
explicitly report external_action_authorized=false / UNAVAILABLE_B1. Unknown account
effects remain visible and cannot authorize later dispatch. Legacy SubmitTask and
RecordManualSubmission reject the reserved namespace so an injected legacy gateway
or manual-package path cannot consume B1 consent. No handoff/send is implemented.

Published-reference metadata requires HTTPS and the selected artifact digest; a
local path is rejected. Availability/content at that remote URL is unverified and
never fetched. Credentials remain outside the schema/configured elsewhere; no
secret/session/private-key/authorization fields are accepted. Recognizable secret
patterns in metadata/outbound/captures/retained local inputs are refused. This is
not a perfect secret classifier: truthful input selection, minimization, host ACLs,
protected storage and local operator trust remain required.

Evidence is separate provisional metadata plus a digest-bound bounded capture.
UNKNOWN/UNVERIFIED/CONFLICT and operator/unverified-source/test-fixture labels never
become Domain final outcomes or payment proofs. Event/submission references are
reported hints, not authenticated provider facts. The configured actor and envelope
account/provider are enforced. Event time may be unknown; future/inverted chronology
fails. Capture time is application-supplied and preserved on retries. Metadata
readback fails if capture integrity is missing/corrupt. No evidence text is executed,
sent to an LLM or interpreted as ACCEPTED/PAID authority.

## CLI commands

Commands below are available offline under the existing operator module. IDs refer
to actual retained records; these examples do not create opportunities or payments.
Configure AGENTMINE_OPERATOR_ID locally. One existing matching workspace/ledger is
required; no fixture provider is installed or silently selected.

```powershell
$env:AGENTMINE_OPERATOR_ID = 'local-operator'
.\.venv\Scripts\python.exe -m agentmine.bootstrap.operator --db .tmp/agentmine.sqlite3 --ledger local submission prepare --context-id context-001 --execution-id execution-001 --inputs context.json
.\.venv\Scripts\python.exe -m agentmine.bootstrap.operator --db .tmp/agentmine.sqlite3 --ledger local submission show --context-id context-001
# Copy the exact scope_reference returned by prepare/show into the existing review command.
.\.venv\Scripts\python.exe -m agentmine.bootstrap.operator --db .tmp/agentmine.sqlite3 --ledger local review --opportunity opportunity-001 --review-id review-001 --destination SCOPE_REFERENCE_FROM_SHOW
.\.venv\Scripts\python.exe -m agentmine.bootstrap.operator --db .tmp/agentmine.sqlite3 --ledger local show-review --review-id review-001
.\.venv\Scripts\python.exe -m agentmine.bootstrap.operator --db .tmp/agentmine.sqlite3 --ledger local decide --review-id review-001 --decision APPROVE
.\.venv\Scripts\python.exe -m agentmine.bootstrap.operator --db .tmp/agentmine.sqlite3 --ledger local submission consent --review-id review-001
.\.venv\Scripts\python.exe -m agentmine.bootstrap.operator --db .tmp/agentmine.sqlite3 --ledger local submission evidence-record --context-id context-001 --evidence-id note-001 --inputs note.json
.\.venv\Scripts\python.exe -m agentmine.bootstrap.operator --db .tmp/agentmine.sqlite3 --ledger local submission evidence-show --evidence-id note-001
```

Context JSON requires exactly mode/account/channel/outbound; the account has
id/provider/effective_account. Channel requires id/provider/listing/kind/destination/
permission_note/disclosed_data/effects/account_effects. Outbound requires text,
artifact_names and published_artifacts (possibly empty). Public references contain
name/location/sha256. No version, actor, approval or authorization field is accepted.
Channel kinds: manual_form/manual_message/api_intended; effects:
unknown/none_declared/known (known requires explicit effects). API mode requires
api_intended. Location grammar deliberately excludes credentials/query/fragment.

Evidence JSON requires kind/trust/state/observed_at/provenance/text. Optional fields:
submission/observing_source/event/event_at. Actor/provider/account/capture time come
from trusted composition/envelope. Input files are bounded to 64,000 bytes; duplicate
keys, unknown fields and non-JSON numeric constants fail. There is no arbitrary
capture-URL fetch, browser automation or filesystem publication.

## Transaction and recovery matrix

| Boundary | Invariants / recovery |
| --- | --- |
| Prepare read | Derive only from completed current retained work, exact applied QA and known local source context; no source/gateway/provider I/O |
| Prepare commit | BEGIN IMMEDIATE compares Opportunity revision and retained evidence, one ledger/recorded real cost; account/channel/envelope/scope commit together |
| Same ID / concurrent equal proposal | Original immutable record returned; first application timestamp retained; changed scope/payload conflicts |
| Different contexts / shared account/channel | Equal identity definitions may be reused; definitions cannot be overwritten; scopes/reviews remain distinct |
| Failure after each prepare write | All four record kinds roll back; no orphan index, context, claim, approval or budget change |
| Lost prepare acknowledgement | Reopen/read original context or retry same payload/ID; never create authority under replacement IDs |
| Review preparation | Existing immutable review records exact scope; no external action. Missing/incorrect context/actor/ledger/snapshot fails |
| Decision saved / lifecycle save fails | Applied-consent view is false; retry original decision, not another workflow/approval. No handoff becomes available |
| Context evidence/capture | Both commit atomically; exact duplicate readback is idempotent; conflicting metadata or body fails |
| Lost evidence acknowledgement / concurrent equal import | First server capture time wins; all successful callers read original metadata/capture; all other payload fields and bytes must match |
| Capture missing/corrupt | Fail readback rather than declare complete evidence; no guessed capture or payment |
| Later version / lifecycle change | Existing historical envelope remains readable; old review/consent cannot approve current version |
| Legacy dispatch/manual receipt with B1 scope | UNSUPPORTED before dispatch/receipt transition; F01 legacy claim/cancel semantics otherwise unchanged |

No transaction spans source, human, provider or worker execution. Inspection never
releases claims or changes ledger/policy. No legacy manual package is overwritten
or migrated into envelope authority. New snapshot kinds require the updated binary;
no reset/downgrade migration is introduced.

## Test-first and verification evidence

Initial acceptance test was written before production changes and executed:

```text
python -m pytest tests/integration/test_submission_context.py -q --tb=short -p no:cacheprovider
```

It failed collection with ModuleNotFoundError for submission_context (1 error in
1.27s). This establishes missing capability, not independent reproduction of all
later cases. A second test-first safety probe explicitly tried existing SubmitTask
with new scope consent: API reached the legacy path and MANUAL created a package;
both cases failed the desired no-dispatch/no-intent assertion (2 failed in 3.52s).
The reserved-scope guards were added afterwards.

A final concurrency test reproduced differing server capture timestamps for
otherwise identical evidence imports (1 failed in 3.01s). The adapter now retains
the first committed capture time and the application returns that original stored
metadata. Other payload differences still conflict. The earlier in-progress full
suite was deliberately interrupted before this correction; it is not counted as
passed. Final verification reruns the complete suite against the corrected code.

Interim feedback exposed missing canonical timedelta/timezone handling and an eager
test-construction mistake that supplied a malformed digest in unrelated cases.
These were corrected without weakening scope or evidence validation. One disposable
diagnostic temp-directory attempt hit sandbox permissions and was not treated as
product evidence. All pytest results below use the approved temporary-directory
execution environment and repository network guard.

Tests use real file-backed SQLite, DataWorker, DeliverableQA, current review/decision
components and CLI composition. FakeSource/FakeClock and deliberate faults are
explicit test-only dependencies. New scope approval never refreshes the fake
source either; it does not establish live source freshness. No production workspace
is seeded. No real external send, payment or paid API call is used.

| Check | Result |
| --- | --- |
| Interim foundation suite before final added edge cases | 45 passed in 64.65s |
| Foundation + required regression/architecture selection before final capture-time correction | 364 passed in 342.37s |
| Final foundation + architecture after capture-time correction | 84 passed in 73.67s |
| Full pytest, final code, `-m pytest -q -ra --tb=short -p no:cacheprovider` | 1367 passed in 294.54s, exit 0; log `.tmp/f03-b1-full-final-20261031.log` |
| Ruff check / format check | All checks passed; 323 files already formatted |
| Strict mypy | Success, 240 source files |
| Real module `submission --help`, `submission prepare --help`, `submission evidence-record --help` | Exit 0; no workspace or provider created |
| git diff --check / report whitespace/fences | Exit 0; report/ADR whitespace and code-fence checks passed |

Focused selection covers new submission_context plus submission_cancellation,
submission_system_sqlite, outcome_payment_sqlite, operator_approval_sqlite,
eligibility_review_persistence, eligibility_operator, data_revision_foundation,
data_revision_execution, revision_operator_qa, runtime_operator_cli,
operational_deliverable_qa, budget_control, budget_control_persistence (all under
tests/integration), and tests/unit/test_architecture.py. All pytest commands use
`.\.venv\Scripts\python.exe`, `-q -ra --tb=short -p no:cacheprovider`.
No unexecuted check is counted as passed.

## Limitations and verdict

**PASS_WITH_LIMITATIONS** for the approved offline B1 foundation. All final gates
above were executed and passed. Declared account permission,
disclosures, effects and public URLs remain unverified. Future handoff must fail
on unknown mutations and revalidate source/eligibility/account/consent/financial
authority. All B1 scopes currently lack action capability, even after APPROVE.

Only current completed deterministic Data parents with applied operational PASS
are supported. Research, legacy/incomplete QA and generic remote artifacts are not
silently adopted. This checkpoint does not extend manual eligibility resolution,
F05 rework limitations, paid resume, asset/network representation, FX, partial
payments, backup/reconciliation, AWS or provider contracts. Historical consent is
inspectable but not automatically reactivated or superseded. F03-B2 and later gates
remain unopened. Envelopes retain complete local snapshots, duplicating private
work evidence and growing the workspace; no pruning or encryption feature is added.
No production readiness or verified-profit claim. Stop for
operator review; no commit or push.

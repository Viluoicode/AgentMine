# F03-B3: Authoritative Outcome Evidence and Verification Foundation

Date: 2026-11-01 (Asia/Bangkok).
Base commit: `19eda48fd8b9692e87b0e2f0e59ee8f93207b6e5` (offline manual handoff documentation); source baseline also
includes B2 code committed as `8ad0e43` with an unrelated rework message.
Verdict: **PASS_WITH_LIMITATIONS ? offline evidence foundation only**.

## Scope and cleanup

At operator request, the accidental F05-B4 re-audit changes were removed first.
The F05-B4 report was restored byte-for-byte from its pre-session copy (verified
against HEAD after line-ending normalization). Only that session's named reaudit
scripts/logs/isolated databases were deleted within the resolved `.tmp` workspace
root. Existing committed F05 audit/FIX1 history, B2 code/documents and older audit
artifacts were preserved. `git status --short` was empty before B3 changes.
No production code or test was changed as part of that cleanup.

This checkpoint implements outcome-evidence foundation only. No live source,
submission, account mutation, paid API, payment settlement, FX or automatic revenue
recognition is enabled. No dependency was introduced. No commit or push.

## Current inventory and architectural decision

Existing Domain `Outcome` models ACCEPTED/REJECTED with optional accepted reward
and rejection reason. `Opportunity.record_outcome` owns final transitions;
`verify_payment` separately requires independent payment evidence. The SQLite
SubmissionRepository already stores immutable Domain outcomes. Legacy TrackOutcome
consumes an injected gateway observation; it is not independent authentication for
B3 and was not silently reused as a verification source.

B1 provides immutable envelope/account/channel/scope and provisional capture
metadata, content digests and timestamps. B2 provides exact handoff ownership,
Domain Submission and an applied operator-reported receipt. These are reused, not
replaced. B3 accepts only a retained applied B2 receipt; legacy/unowned packages and
unfinished manual handoffs do not qualify. No new approval system or parallel
Outcome domain is created.

Application owns event/verification contracts and orchestration. Infrastructure
implements the repository and verifier ports; SQLite transactions enforce exact
identity and CAS. Presentation parses bounded JSON and projects evidence; bootstrap
wires one authoritative workspace, operator and ledger. Domain is unchanged.
The snapshot codec adds only an explicit allowlisted contract module.

## Changed files

New files, under `src/agentmine/`:

- `application/contracts/outcome_evidence.py`: event vocabulary, immutable report,
  exact receipt binding, request/decision/view and typed diagnostics.
- `application/ports/outcome_evidence.py`: evidence persistence and independent
  read-only verification responsibilities.
- `application/use_cases/outcome_evidence.py`: report/get/verify/status coordination.
- `infrastructure/sqlite/outcome_evidence.py`: immutable ownership, captures linkage,
  request/decision retention and atomic final Outcome application.
- `infrastructure/outcome_verifier.py`: production BLOCKED verifier; accepts=False.
- `presentation/outcome_evidence_cli.py`: narrow record/show/verify/status commands.
- `bootstrap/outcome_evidence.py`: explicit default-denied composition.

Updated source: `bootstrap/operator.py`, `presentation/submission_context_cli.py`,
`infrastructure/snapshots.py`. Also added
`tests/integration/test_outcome_evidence.py`,
`docs/adr/0031-authoritative-outcome-evidence.md`, this report, and updated ADR index.
No Domain, legacy gateway/payment contract, F01 dispatch or B2 ownership rule changed.

## Event semantics and trust matrix

Every event binds the full original B2 receipt/handoff, envelope, Submission,
account/effective account, provider, listing, channel and deliverable/version. B1
metadata binds provider event, provenance, actor, event/observation/server capture
time and original text digest. Event parser and verification contracts are versioned.
Provider/event strings supplied by operators are correlation hints, not authenticity.

| Evidence / event | Trust / verification | Domain effect |
| --- | --- | --- |
| Operator note, screenshot text, URL, provider-looking payload, synthetic capture | OPERATOR_REPORTED / UNVERIFIED; default verifier BLOCKED | None |
| SUBMISSION_REPORTED / SUBMISSION_RECEIVED | Provisional unless independently authenticated | Never final acceptance |
| APPLICATION_SELECTED | Selection is distinct from deliverable acceptance, even under authenticated stage classification | None |
| UNDER_REVIEW / DISPUTED / UNKNOWN | Nonfinal; UNKNOWN retained explicitly | None |
| Independently authenticated DELIVERABLE_ACCEPTED | VERIFIED decision by trusted configured verifier | Existing Domain ACCEPTED only |
| Independently authenticated DELIVERABLE_REJECTED | VERIFIED decision by trusted configured verifier | Existing Domain REJECTED, rationale retained |
| Test-only authoritative verifier | Explicit isolated test dependency replacement; not real marketplace proof | Exercises the two final transitions in tests only |
| Any acceptance or submission | Not payment evidence | No PAID, verified reward or revenue |

The production composition has no enabled authenticating adapter and no authority
flag or verifier-selection hook. It always returns BLOCKED. A retained VERIFIED
label also cannot finalize when reopened under default composition: the configured
verifier must accept the retained decision's authority. Already applied historical
readback remains read-only. The authoritative fixture class lives only in tests.

No accepted reward amount is copied from potential reward or parsed from report text.
Accepted reward remains unknown (None). This is intentionally narrower than financial
settlement. No ledger, actual cost, commitment, released identity, payment or revenue
is written by B3. Application selection and deliverable acceptance are never aliases.

## Transactions, state and recovery

```text
retained applied B2 receipt
  -> provisional B1 capture
  -> immutable OutcomeEvent + provider-event owner
  -> immutable verification request with exact SUBMITTED snapshot
  -> independent verifier decision retained
  -> only authenticated final deliverable event:
       CAS SUBMITTED -> ACCEPTED or REJECTED + immutable Outcome + application receipt
```

All SQLite write boundaries use BEGIN IMMEDIATE. No transaction spans a provider
operation. The new verifier is read-only and cannot dispatch external effects.

| Boundary / failure | Persistent state and recovery |
| --- | --- |
| Capture write failure | B1 metadata/capture transaction rolls back; original report can retry |
| Capture committed, event attachment fails | Provisional capture retained; identical ID retry attaches event |
| Duplicate provider event / changed event payload | Immutable owner or event conflict; no second final authority |
| Request committed, verifier fails before decision | UNKNOWN request remains inspectable; original-ID read-only retry |
| Decision write failure | Request retained; no Outcome; identical read-only verification may retry |
| Decision committed, apply fails | Decision retained, FINALIZATION_PENDING or CONFLICT; original IDs only |
| Outcome / Opportunity / marker write failure | Entire final application rolls back; no partial Domain Outcome |
| Lost capture/final acknowledgement | Read original evidence/receipt; no send or replacement identity |
| Concurrent equal verification | First immutable decision timestamp wins; one final application |
| Stale Opportunity revision / unrelated submission | Exact snapshot comparison fails; decision/capture retained, CONFLICT |
| Existing terminal Outcome | New application blocked/conflicting; no overwrite or terminal rebase |
| Changed configured verifier authority | Retained decision cannot activate finalization under default composition |
| Historical applied readback | Returns original evidence; does not mutate later lifecycle |

Canonical reported event ownership is scoped by provider, effective account, listing
and provider-event identifier. A future real adapter must establish its official
canonical event namespace/authentication and cross-account/listing replay policy;
operator IDs are not certified global provider identifiers. Conflicting imports may
leave an additional unattached B1 provisional capture. They never gain Outcome authority.
Local host/store/port implementations remain trusted; hashes are consistency checks,
not protection against an authorized malicious writer.

B2 claims remain sticky, including after a final test-only Outcome. B3 does not
release ownership, infer a new send permission, cancel work or alter F01 behavior.

## CLI and operator behavior

Executed real module help:

```powershell
.\.venv\Scripts\python.exe -m agentmine.bootstrap.operator submission outcome --help
```

Observed exit 0 with `record`, `show`, `verify`, `status`. Commands for an existing
retained handoff use the usual explicit workspace/ledger/operator prefix:

```text
submission outcome record --handoff-id handoff-1 --evidence-id outcome-1 --inputs report.json
submission outcome show --evidence-id outcome-1
submission outcome verify --evidence-id outcome-1 --verification-id verification-1
submission outcome status --verification-id verification-1
```

These are syntax examples, not a claim that a real provider/handoff was verified.
Mutation commands require the existing trusted local operator identity. Report JSON
allows only provider_event, event_type, event_at, observed_at, provenance and text.
The existing strict parser limits input to 64,000 bytes and rejects unknown/duplicate
fields and non-JSON constants. There is no authority, acceptance decision, reward,
payment or credential field. Event_type is a **reported classification**, not trusted
proof. No supplied URL is fetched.

Show displays provisional event trust, exact lineage and timestamps/digest. Verify/
status additionally display the separate verification status, authority/rationale,
application marker, current lifecycle and UNKNOWN/CONFLICT/BLOCKED diagnostic.
Default verification returns nonzero/BLOCKED and preserves the report; it does not
silently fall back to fake authority. Unit/integration tests use explicit verifier
replacement, not a production CLI flag or provider factory.

## Provider feasibility boundary

No real marketplace outcome adapter or endpoint was invented. Existing configured
Superteam discovery/detail/source checks do not establish authenticated final
**deliverable** acceptance/rejection. An application/winner selection, copied URL,
operator receipt or caller-supplied provider response is insufficient.

Before production finalization is enabled, an independently reviewed permitted
read-only contract must establish:

1. Authenticated origin/authority for the relevant provider and authorized account,
   with permitted access and a reproducible trusted capture/authentication method.
2. Exact listing/submission/account and submitted deliverable/version correlation,
   including how retained outbound content maps to provider receipt/event identity.
3. Documented semantic distinction between application selection, received/review,
   deliverable acceptance/rejection, dispute and unknown; rejection rationale.
4. Canonical event namespace, parser/contract version, observation/event chronology,
   replay/conflict and finality policy, backed by authorized saved fixtures.
5. A configured verifier that independently checks these facts and authenticates
   retained decisions on recovery. A reference/string/hash alone is not proof.

This evidence is unavailable in this checkpoint; default finalization remains
BLOCKED. Fixture success is not provider feasibility evidence. Independent payment,
asset/currency/FX/fees and reward recognition remain F03-B4 and later work.

## Test-first evidence and verification

Before production changes:

```text
python -m pytest tests/integration/test_outcome_evidence.py -q --tb=short -p no:cacheprovider
```

Observed expected collection failure: ModuleNotFoundError for the new
application.contracts.outcome_evidence (1 error in 1.47s). This establishes the
missing capability; it does not claim every subsequently added edge case was red
before production edits. During development, import ordering, bounded formatting
and typed test-helper annotations were corrected without weakening behavior.

Tests use real file-backed SQLite, B2/Domain/Application/CLI and real retained worker
and QA evidence. FakeSource/FakeClock and TestOnlyAuthoritativeVerifier are explicitly
test-only; repository-wide socket guards prohibit live network/provider calls.
Coverage includes all reported event types; provisional acceptance/selection; wrong
actor/ledger/account/listing/version/submission/digest/event; duplicate identities;
unknown/wrong verifier decisions; concurrent verification; crash at each capture,
event, request, decision and final-transaction write; lost acknowledgement; stale/
unrelated snapshots; terminal immutability; retained-decision authority on reopen;
no payment/PAID/revenue; unchanged financial rows and B2 ownership; strict CLI and
absence of an authority flag. Full regressions include F01/F04/F05/B1/B2 and budget.

Interim B3 run: **36 passed in 410.28s**. That run began before the final retained-
decision authority gate and three extra acceptance cases; it is not substituted for
final-code verification.

Final focused command:

```text
python -m pytest tests/integration/test_outcome_evidence.py tests/unit/test_architecture.py -q --tb=short -p no:cacheprovider
```

Executed result: **68 passed in 458.28s** (39 B3 cases + 29 architecture cases),
exit 0. Final static checks: `ruff check .` passed; `ruff format --check .` reported
343 files already formatted; `mypy --strict` reported no issues in 256 source files;
`git diff --check` exited 0 with only an ADR README LF/CRLF conversion warning.
The module help command above also completed with exit 0.

The single final full-suite command is:

```text
python -m pytest -q -ra --tb=short -p no:cacheprovider
```

It runs the relevant F01/F04/F05/B1/B2/runtime/QA/budget regressions unchanged as
part of the entire suite. Its completed result is recorded below. Logs:
`.tmp/f03-b3-focused-final.log`, `.tmp/f03-b3-full.log`.
Final full-suite count and verdict are recorded below.
No unexecuted check is counted as passed. A single full-suite result will be listed
separately from focused and architecture results.

## Limitations

- Production outcome finalization is deliberately unavailable without a genuinely
  authenticated provider contract. No live compatibility was tested or claimed.
- No legacy/unowned submission migration, arbitrary API lane or manual override.
- Immutable blocked decisions are historical evidence, not renewable authority;
  changing real verification policy requires a separately reviewed workflow.
- No F08 reconciliation, proof-of-host integrity, coordinated multi-store disaster
  recovery, supersession or claim release is introduced.
- No payment work, real reward experiment, AWS or paid capability was started.

No commit or push. Stop for operator review after final verification.


## Final verification and verdict

| Check | Executed result |
| --- | --- |
| Single full-suite invocation on final production/test code | **1439 passed in 846.49s (14m06s), exit 0**, no skips reported |
| Final focused B3 + architecture invocation | **68 passed in 458.28s**, exit 0 (39 B3 + 29 architecture) |
| Ruff check | All checks passed |
| Ruff format check | 343 files already formatted |
| Strict mypy | No issues in 256 source files |
| git diff --check | Exit 0; only Git LF/CRLF conversion warning |
| Real module outcome help | Exit 0; four intended subcommands |

These are separate invocations, not counts added together. No production/test code
changed after the single full suite started. Relevant F01 cancellation, F04
eligibility, F05 rework, F03-B1/B2, runtime/QA/budget and existing payment-separation
regressions were executed as part of that full run, not reported as a fabricated
additional focused run. The interim 36-case run is development evidence only.

| Acceptance gate | Verdict |
| --- | --- |
| Operator/provider-looking reports cannot finalize | PASS; all eight event classifications remain provisional by default |
| APPLICATION_SELECTED cannot become DELIVERABLE_ACCEPTED | PASS; even the test-only verified selection produces no Outcome |
| Exact original handoff/submission/account/listing/version and actor/ledger | PASS; retained binding checks and negative cases |
| Digest, provider-event and verification identity immutability | PASS; conflicting/duplicate attempts fail closed |
| Concurrent equal verification / original-ID recovery | PASS; one applied Outcome and original retained decision |
| Capture/request/decision/final-transaction crash boundaries | PASS; fault after each write, original-ID recovery and lost acknowledgements |
| Stale/unrelated snapshot or terminal Outcome overwrite | PASS containment; evidence retained, CONFLICT/BLOCKED and no rebase |
| Unknown and unconfigured authority | PASS containment; UNKNOWN retained, default BLOCKED, retained fixture decision cannot activate default composition |
| No payment, paid provider, external send or financial mutation | PASS within executed offline tests and composition; zero verified revenue |
| Real authoritative marketplace Outcome finalization | BLOCKED by design; no authenticated provider contract configured |

**PASS_WITH_LIMITATIONS** for the requested offline-first F03-B3 foundation. This
is not production readiness, live marketplace verification or reward earning.
Existing Domain Outcome/lifecycle and payment separation are reused unchanged.
No new dependencies or Clean Architecture deviations were introduced. Operator
review is required before any separately scoped provider activation; no action or
credential was needed for these offline tests. No commit or push. F03-B4 payment
work was not started. Stop for operator review.

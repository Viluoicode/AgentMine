# F05-B4-FIX1: Authoritative revision recovery diagnostics

Started: 2026-10-28; final verification: 2026-10-29, Asia/Bangkok. Base commit:
`ca8faa0cd2c237d0fcab90536112dc6ca7fb3de9`.

## Scope and reproduced defect

This checkpoint fixes only the LOW diagnostic finding from the F05-B4 audit.
The existing untracked `remediation-05-b4-operational-e2e-audit.md` was present
before work and is preserved unchanged. AGENTS.md, Product Constitution, the audit,
ADR 0028 and current revision/runtime/recovery/CLI contracts and tests informed
the change. No commit or push; no other remediation is started.

Before production changes, a new parametrized integration test used real
file-backed SQLite and the real operator CLI composition to prepare and approve
v2. One case interrupted the worker after durable start; the other interrupted
finish after retaining the real DataWorker result and its cost. Both then saved
the same Opportunity value with a newer repository revision, preserving the
execution ID while invalidating the original start authority.

The test-first command was:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/test_revision_operator_qa.py -k matches_exact_started_snapshot -q --tb=short -p no:cacheprovider
```

Observed: **2 failed, 23 deselected in 10.43s**. Revision show returned
RESULT_MISSING / FINISH_PENDING instead of the expected STALE_PARENT. These are
reproduced failures, not inferred from the historical audit.

## Root cause and exact change

`SQLiteRevisionRuntimeRepository.inspect` previously checked only whether an
incomplete run's current Opportunity still referenced the same execution. That
comparison missed a newer repository revision and other changes to the aggregate.

The existing `RevisionRun.started_snapshot` reconstructs the exact authoritative
post-start value through Domain `begin_rework`, using the frozen parent,
execution, eligibility and scoring evidence. Its revision is the parent revision
plus one. `ExecuteDataRevision` already compares the current Versioned Opportunity
against this snapshot before replay or retained-result completion.

The SQLite read projection now makes the same comparison:

```python
run is not None and op != run.started_snapshot
```

A mismatch uses the existing `RevisionReason.STALE_PARENT`. No enum, public
contract, persisted schema, CLI command or lifecycle transition is added. The
comparison runs inside the existing single SQLite read transaction.

| Situation | Before | After |
| --- | --- | --- |
| Legitimate started run, no result | IN_PROGRESS / RESULT_MISSING | Unchanged |
| Legitimate retained result, finish pending | RESULT_RETAINED / FINISH_PENDING | Unchanged |
| Same execution but newer Opportunity revision, no result | IN_PROGRESS / RESULT_MISSING, misleading | IN_PROGRESS / STALE_PARENT, blocked diagnostic |
| Same execution but newer revision, result retained | RESULT_RETAINED / FINISH_PENDING, misleading | RESULT_RETAINED / STALE_PARENT, blocked diagnostic |
| Completed current or historical version | COMPLETED / NONE | Unchanged; later lifecycle changes do not invalidate completed history |

`status` remains the existing durable checkpoint, not execution permission.
`recovery_reason=STALE_PARENT` is the revision view's existing blocking reason.
`work status` continues to return BLOCKED/STATE_CHANGED, and revision recovery
continues to return BLOCKED/STATE_CONFLICT. These typed vocabularies express the
same stale authority; no status strings are parsed and no new permission is inferred.

## Changed files and architecture

| File | Change |
| --- | --- |
| `src/agentmine/infrastructure/sqlite/data_revision.py` | Replace incomplete-run execution-only comparison with exact started snapshot comparison |
| `tests/integration/test_revision_operator_qa.py` | Add missing/retained-result stale revision cases; extend completed/current/historical revision-show checks |
| This report | Reproduction, explanation, verification and limitations |

Application/Domain own the snapshot and recovery semantics; Infrastructure now
projects those existing semantics accurately. No new architecture decision or ADR
is needed. B1 ownership/consent/allocation/start/finish transactions, B2 execution
and recovery, first-run runtime, budget settlement and QA logic are unchanged.
Unknown-effect precedence and the completed-history branch are preserved.
No dependencies were introduced or installed.

## Regression coverage and side effects

The new test exercises both legitimate pending states before inducing staleness,
then compares revision show, work status and recovery. It rejects worker dispatch
during inspection and stale recovery. Whole-database SQL dumps before/after these
operations must match, including lifecycle, budget snapshots, actual costs,
commitments, claims and retained history.

The existing v2 FAIL -> v3 PASS test now also inspects v2 immediately after finish,
and both completed v2 and current v3 after fresh v3 QA. Their exact versions remain
visible with COMPLETED/NONE, no worker call and no database changes. Historical QA
readback assertions remain in place. Source/clock and deliberate failures are
explicit test fixtures; SQLite, CLI composition, DataWorker and DeliverableQA are
real local implementations. No live source, paid provider, external submission or
payment is used.

## Executed verification

Commands use `.\.venv\Scripts\python.exe`; pytest uses the repository network
guard. Only completed checks are counted as passed.

The earlier full-suite session stopped exposing its final result after the turn
resumed; that invocation is not counted as passed. The full suite was rerun to
obtain an observable completion result.

| Check | Result |
| --- | --- |
| Test-first reproduction above | 2 expected failures in 10.43s |
| Focused revision/status/recovery and regression selection below, including architecture tests | 221 passed in 225.44s |
| Full pytest, `-m pytest -q -ra --tb=short -p no:cacheprovider` | 1312 passed in 358.57s, exit 0 |
| Ruff check | All checks passed |
| Ruff format check | 314 files already formatted; initial check identified one test formatting change, corrected with Ruff before this final check |
| Strict mypy | Success, 234 source files |
| git diff --check / final report checks | Exit 0; report whitespace and fenced-block checks passed |

Focused selection, with `-q -ra --tb=short -p no:cacheprovider`:

```text
tests/integration/test_revision_operator_qa.py
tests/integration/test_data_revision_foundation.py
tests/integration/test_data_revision_execution.py
tests/integration/test_runtime_operator_cli.py
tests/integration/test_operational_deliverable_qa.py
tests/integration/test_budget_control.py
tests/integration/test_budget_control_persistence.py
tests/unit/test_architecture.py
```

## Verdict and limitations

**PASS** for the scoped diagnostic correction. Stale snapshots remain blocked;
no reconciliation, supersession,
claim release, new workflow or external provider is introduced. Existing F05 local
scope exclusions and F03/F06/F07/F08 and F02-C/B4-2 dependencies remain applicable.
No production readiness, live marketplace compatibility or earnings claim follows.
No commit or push. Stop for operator review; do not start another checkpoint.

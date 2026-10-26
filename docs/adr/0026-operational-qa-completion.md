# ADR 0026: Approved QA criteria and conditional inspection completion

## Status

Implemented for F02-B3-B only. Extends ADR 0012 and runtime ADRs 0023–0025.
The new consistency boundary is necessary; no new QA engine or Domain rule.

## Context

Runtime specifications did not retain acceptance criteria. DeliverableQA already
computes ordered evidence-based reports and saves them before lifecycle changes,
but its legacy application path reloads the Opportunity when applying a result.
An operational inspection needs frozen criteria, version ownership and conditional
application of that report, including safe readback after later approval/revision.

## Decision

Retain optional immutable DataAcceptanceCriteria in WorkSpecification at preparation:
explicit formats and QARequirement values. Approval covers the same specification
actor/time and exact inputs. Old specifications load None and fail closed for QA;
do not derive criteria from outputs or attach weaker criteria after execution.

RunOperationalDataQA loads the authoritative run, plan, result, Execution,
versioned deliverable and hash-bound content. It checks frozen criteria and existing
source/eligibility/economic preflight before a new inspection. Construct QAInspection
from those records, never from a caller's QA outcome. Compose DeliverableQA with
SQLiteQAJournal, no LLM and no paid QA budget.

Add a narrow application OperationalQARepository, implemented by SQLite:

- Claim one inspection per deliverable/version; retain its original Opportunity
  snapshot/revision, actor/time and execution binding. Persist ownership, inspection
  and binding atomically. Changed identities conflict; legacy unbound evidence is
  not silently adopted.
- Reuse SQLiteQAJournal's canonical inspection/report records. Reports persist
  first, independently of completion, so a failure retains recoverable evidence.
- Apply a retained matching report against its exact original Opportunity snapshot.
  Atomically store the existing lifecycle QAResult, Domain transition and applied
  marker. Human-review outcomes retain QA_PENDING and gain only the marker.
- A completed inspection retry reads the original report/marker and performs no
  state change, even after subsequent submission approval or revision. Stale unapplied
  revisions conflict rather than automatically rebasing a decision.

Extend DeliverableQA with an optional bound-completion path; its existing algorithms
are unchanged. Extract its exact QAReport-to-QAResult mapping once for reuse by
legacy and operational application paths, retaining the legacy JSON representation.
No generic transaction framework or second lifecycle is introduced.

Use the existing SQLite snapshot schema/codec and BEGIN IMMEDIATE, without locks
over source reads or QA computation. A first claim without a report may rerun the
same deterministic inspection after preflight; a retained report retries only its
completion. Concurrent equal calls can receive a conflict and retry the same ID;
different inspection IDs cannot replace the version's owner.

## Consequences

PASS reaches READY_FOR_HUMAN_REVIEW, not approval. FAIL/NEEDS_REVISION preserves
existing Domain IN_PROGRESS behavior and requires F05 rework; first-run execution
explicitly blocks that replay. REQUIRES_HUMAN_REVIEW remains QA_PENDING. A semantic
criterion is retained honestly: existing QA reports unavailable semantic review
with no AI provider; it is never relaxed or passed automatically.

Source refresh is required for new/recomputed inspections. Completion of an already
retained report is local evidence recovery, not renewed source or submission
permission. Existing review/decide and their source/content/ledger checks remain
separate. No submission, payment, budget resume, revision execution or AWS work.

Only the new local composition uses this operational repository. Legacy direct
DeliverableQA callers remain compatible; this does not retrofit transactional QA
application into every old adapter/cloud workflow. All local components share the
authoritative workspace. Hashes/host access remain trusted-storage boundaries.

## Alternatives

Generating criteria from a successful output makes PASS circular. A caller-selected
QA status fabricates evidence. Applying reports against a newly read revision can
overwrite intervening decisions. A process lock or a new orchestration service
does not replace the shared-store conditional completion requirement.

# ADR 0025: Explicit local Data commands and approved filesystem boundaries

## Status

Implemented for the requested F02-B3-A checkpoint. Extends ADRs 0023/0024 and
0019/0020. No QA orchestration or F02-B3-B is included.

## Decision

Extend the existing operator module with `opportunity` assessment/inspection and
`work prepare/show/execute/recover/status/export`. Dashboard remains the inventory.
Presentation parses bounded declarative JSON and renders escaped JSON. Application
owns preparation/read/recovery/export use cases and ports; bootstrap wires real
SQLite repositories/journals, BudgetManager and ExecuteWorkerTask on the same
SQLiteDatabase and configured ledger. ExecuteWorkerTask constructs the existing
DataWorker with llm=None. No mock/provider registry or workflow engine is added.

Production entrypoint validates exactly one matching ledger before new runtime
commands. Existing legacy composition callers remain compatible. Source defaults
to DisabledOpportunitySource; explicit live opt-in selects the existing Superteam
read adapter only. No marketplace schema/endpoint or participation fact is invented.

Mutating new commands require AGENTMINE_OPERATOR_ID. Preparation additionally
requires --approve-inputs; start/recover require --confirm. Work specifications
retain actor/time, source context, evidence and exact snapshots/digests. Repeated
same-ID preparation verifies the same inputs/context without refreshing consent.
Recovery looks up original bindings; it never generates replacement identities.

Reuse CheckEligibility, EvaluateOpportunity, ScoreOpportunity and PlanTask rather
than manufacturing successful assessments. Prepare requires a retained evaluation
and full B2 preflight. Execute/recover always invoke the B2 use case. Unknown,
expired, changed or unavailable evidence blocks work. MANUAL eligibility uses the
existing F04 decision/reference, distinct from submission approval.

Input files are explicit approved UTF-8 CSV/JSON under a chosen root, bounded to
existing DataSource limits with expected SHA-256. The reader rejects traversal,
absolute/alternate-stream source paths, symlinks/reparse points, obvious UNC roots,
nonregular files, incompatible extensions and changed digests. It captures bytes
without newline/encoding normalization. No arbitrary URLs, filesystem discovery,
scripts or model-selected tools are used. Root contents must be approved local data.

Export is an application capability implemented by a local filesystem adapter.
Only fixed worker artifact names are published, with digests and a local-only
manifest. Existing conflicting files are never overwritten. Each new file is
written/fsynced to a private temporary file and atomically hard-linked into place
without replacing a target; the manifest is last. Unsupported filesystems fail
closed. A crash can leave an incomplete directory, not a successful external action.
Identical complete or matching partial exports can be retried; unrelated/conflicting
content requires inspection or a different destination, never automatic deletion.

## Consequences

Opportunity business state, command BLOCKED/RECOVERABLE outcomes, and completed run
history are separate output fields. Data execution stops at QA_PENDING; exporting
does not mean QA PASS, submission, acceptance, payment or earnings. Forecasts and
verified revenue remain separately labelled. Read commands do not refresh or run work.

No Domain/B2 execution rule or database schema changes, new dependency, paid AI,
AWS deployment, revision or budget-resume workflow. Inputs/profile assertions and
local identity still depend on a trusted single-operator host. Host ACL, mapped
drive classification, malicious concurrent host writers and complete cross-file
backup/security controls remain operational responsibilities, not a sandbox claim.

## Alternatives

Raw serialized aggregates would allow caller-selected authority. Fixture/mocked
production defaults would hide unavailable providers. A giant handler doing Domain
transitions, automatic run-all/approval, web frontend or new framework would exceed
the bounded local task. Export overwrite/rename fallback could destroy operator
files; no-clobber publication is preferable even when a filesystem cannot support it.

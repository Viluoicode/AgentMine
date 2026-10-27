# ADR 0027: Explicit local budget-policy consent and atomic application

## Status

Implemented for the explicitly approved F02-B4-1 scope on 2026-10-26.
Implements the approved subset of the
[B4-A plan](../audits/remediation-03-b4-budget-recovery-plan.md), extending ADRs
0002, 0007 and 0023-0026. Paid wait/resume remains deferred.

## Context

The existing Budget preserves authorizations, actual records and released operation
identities through policy changes. SQLiteCostLedgerRepository atomically stores a
budget snapshot and audit revision, but there was no operator policy proposal,
explicit consent record or original-change receipt. Resetting a ledger or reapplying
an old policy after an acknowledgement failure would corrupt operational authority.

The current local worker is deterministic Data with zero AI cost. Budget exhaustion
does not create a paid wait for it. A budget-policy action must not become implicit
permission to resume work, release an unresolved commitment, spend or submit.

## Decision

Application owns BudgetPolicyChange, BudgetPolicyDecision,
BudgetPolicyChangeReceipt and typed conflict/recovery classifications. Four focused
use cases inspect, prepare, get and apply. Operator input supplies bounded policy
values/mode, reason, change ID and expected ledger revision; never a Budget snapshot
or authorization. The configured actor is injected by bootstrap.

Preparation stores an immutable before/after policy and requested mode, original
ledger revision, actor, reason and timestamp. It does not change the ledger.
Apply requires explicit confirmation and the same actor/change ID. The retained
proposal is the exact approved delta; editing its original input file cannot change
it. Application derives the updated Budget using existing Domain methods.

Currency and calendar timezone are immutable for this checkpoint. CLI accepts all
six numeric policy fields as bounded plain decimal strings and a requested mode;
currency/timezone are inherited from the authoritative ledger, not caller input.
Application also rejects changes to them if called without the CLI.

BudgetControlRepository defines a narrow atomic boundary. SQLite implements it on
the same database as the existing authoritative ledger and runtime. One
BEGIN IMMEDIATE transaction verifies the retained proposal and full current budget
snapshot/revision, then writes:

1. Updated `budget` snapshot with CAS.
2. Existing `budget_audit` entry with BudgetCommit (audit_event=None).
3. Immutable `budget_policy_decision` recording actor and approval time.
4. Immutable `budget_policy_receipt` binding proposal/decision/resulting revision.

`budget_policy_change` is retained separately by prepare. These new snapshot kinds
reuse the current codec/schema. No existing cost/authorization/released-ID history
is rewritten or replaced. The adapter verifies current ledger/audit agreement and
validates receipt links to the original proposal, decision and historical budget
audit before readback. All history-preserving calculations remain in Domain and
Application contracts; storage only implements consistency and identity checks.

An identical applied ID returns its original receipt even after later policy or
cost changes. It never writes the old policy again. Conflicting payload, actor or
revision fails explicitly. Two different proposals against one revision cannot both
apply. A confirmation of an unchanged policy is a financial no-op with one new audit
revision and receipt; retry adds neither. No transaction spans external I/O.

Inspection is conservative and read-only. It shows current policy/modes, actuals,
outstanding estimates, remaining amounts and retained runtime/wait evidence.
Unlinked operations, legacy waits and paid evidence remain explicitly unresolved
or unsupported. Local paid journals are inspected only for retained evidence; the
separate Bedrock usage journal and real billing are not reconciled. Zero recorded
AI cost never means zero infrastructure/tool/transaction cost.

## Consequences

Local CLI adds `budget show` and `budget policy prepare/show/apply`. Mutating commands
require the configured operator; apply requires --confirm. Existing DataWorker,
BudgetManager, Domain lifecycle, QA and eligibility/spending/submission approval
systems remain unchanged. Derived mode may stay SCOUT_ONLY despite requested FULL.
Limits below existing commitments show negative remaining and overcommit warnings;
commitments are not cancelled. Source freshness is still checked by existing work
commands, not bypassed by policy consent.

No dependency, provider, task resume, reservation release, settlement, cloud adapter,
schema migration or workflow framework. Local host/store trust and growing full
snapshot audits remain existing limitations. Cross-store reconciliation and unknown
paid effects remain F08; paid runtime/resume, F03 and F05 remain separate gates.

## Alternatives

Reusing workspace initialization would risk reset semantics. Separate policy and
decision/receipt commits would leave ambiguous consent after a crash. Reusing a
SPENDING or submission approval would conflate different permissions. A generic
transaction framework or new accounting ledger is unnecessary for this local scope.

"""Explicit operator policy control; no dispatch, release, settlement or resume."""

import logging
from dataclasses import dataclass, replace

from agentmine.application.contracts.budget_control import (
    BudgetControlError,
    BudgetPolicyApplication,
    BudgetPolicyChange,
    BudgetPolicyChangeReceipt,
    BudgetPolicyChangeView,
    BudgetPolicyDecision,
    BudgetRecoveryClassification,
    BudgetRecoveryItem,
    BudgetRecoveryView,
    PolicyConflictReason,
)
from agentmine.application.ports.budget_control import BudgetControlRepository
from agentmine.application.ports.services import Clock
from agentmine.domain.budget import BudgetPolicy, OperatingMode
from agentmine.domain.opportunity import OpportunityState
from agentmine.domain.values import Reference


@dataclass(frozen=True, slots=True)
class InspectBudgetRecovery:
    repository: BudgetControlRepository
    ledger_reference: Reference
    clock: Clock

    def execute(self) -> BudgetRecoveryView:
        snapshot = self.repository.read(self.ledger_reference)
        budget = snapshot.ledger.value
        now = self.clock.now()
        paid = set(snapshot.paid_evidence_operations)
        runs = {run.run.binding.operation_reference: run for run in snapshot.runs}
        items: list[BudgetRecoveryItem] = []
        for auth in budget.outstanding:
            request = auth.request
            operation = request.context.operation_reference
            run = runs.get(operation)
            classification = BudgetRecoveryClassification.UNLINKED_OPERATION
            if (
                request.estimated_cost.amount > 0
                or operation in paid
                or (run and run.ai_evidence_present)
            ):
                classification = BudgetRecoveryClassification.RECONCILIATION_REQUIRED
            elif run is not None:
                if run.run.plan.execution.authorization != auth:
                    raise BudgetControlError(PolicyConflictReason.EVIDENCE_INVALID)
                classification = BudgetRecoveryClassification.DETERMINISTIC_RUN
            items.append(
                BudgetRecoveryItem(
                    operation,
                    classification,
                    request,
                    None if run is None else run.run.binding.execution_reference,
                    request.context.opportunity_reference,
                )
            )
        represented = {item.operation_reference for item in items}
        for operation in sorted(paid - represented, key=lambda value: value.value):
            actual = next(
                (
                    record.actual_cost
                    for record in budget.records
                    if record.cost.reference == operation
                ),
                None,
            )
            items.append(
                BudgetRecoveryItem(
                    operation,
                    BudgetRecoveryClassification.RECONCILIATION_REQUIRED,
                    None,
                    None,
                    None,
                    actual,
                )
            )
        for op in snapshot.opportunities:
            if op.state == OpportunityState.WAITING_FOR_BUDGET:
                if op.waiting_request is None:
                    raise BudgetControlError(PolicyConflictReason.EVIDENCE_INVALID)
                items.append(
                    BudgetRecoveryItem(
                        op.waiting_request.context.operation_reference,
                        BudgetRecoveryClassification.UNSUPPORTED_WAIT,
                        op.waiting_request,
                        None if op.execution is None else op.execution.reference,
                        op.reference,
                    )
                )
        monthly_spent = budget.ai_spent(now, monthly=True)
        daily_spent = budget.ai_spent(now)
        monthly_remaining = budget.policy.monthly_ai_budget - budget.ai_committed(now, monthly=True)
        daily_remaining = budget.policy.daily_ai_budget - budget.ai_committed(now)
        warnings = [
            "unmeasured_costs_unknown",
            "external_journals_not_reconciled",
            "inspection_never_authorizes_resume",
        ]
        if monthly_remaining.amount < 0 or daily_remaining.amount < 0:
            warnings.append("budget_overcommitted")
        return BudgetRecoveryView(
            self.ledger_reference,
            snapshot.ledger.revision,
            now,
            budget.policy,
            budget.requested_mode,
            budget.operating_mode(now),
            monthly_spent,
            daily_spent,
            budget.ai_committed(now, monthly=True) - monthly_spent,
            monthly_remaining,
            daily_remaining,
            budget.records,
            budget.released_operations,
            tuple(items),
            tuple(warnings),
        )


@dataclass(frozen=True, slots=True)
class PrepareBudgetPolicyChange:
    repository: BudgetControlRepository
    ledger_reference: Reference
    operator: Reference
    clock: Clock

    def execute(
        self,
        reference: Reference,
        policy: BudgetPolicy,
        mode: OperatingMode,
        expected_revision: int,
        reason: str,
    ) -> BudgetPolicyChange:
        previous = self.repository.get_change(reference)
        if previous is not None:
            candidate = replace(
                previous,
                ledger_reference=self.ledger_reference,
                actor=self.operator,
                proposed_policy=policy,
                proposed_mode=mode,
                expected_revision=expected_revision,
                reason=reason,
            )
            if candidate != previous:
                raise BudgetControlError(PolicyConflictReason.IDENTITY_CONFLICT)
            if previous.prepared_at > self.clock.now():
                raise BudgetControlError(PolicyConflictReason.EVIDENCE_INVALID)
            return previous
        snapshot = self.repository.read(self.ledger_reference).ledger
        candidate = BudgetPolicyChange(
            reference,
            self.ledger_reference,
            self.operator,
            self.clock.now(),
            reason,
            expected_revision,
            snapshot.value.policy,
            snapshot.value.requested_mode,
            policy,
            mode,
        )
        candidate.update(snapshot)
        return self.repository.prepare(candidate)


@dataclass(frozen=True, slots=True)
class GetBudgetPolicyChange:
    repository: BudgetControlRepository
    ledger_reference: Reference
    clock: Clock

    def execute(self, reference: Reference) -> BudgetPolicyChangeView:
        change = self.repository.get_change(reference)
        if change is None or change.ledger_reference != self.ledger_reference:
            raise BudgetControlError(PolicyConflictReason.NOT_FOUND)
        receipt = self.repository.get_receipt(reference)
        if receipt is not None and receipt.change != change:
            raise BudgetControlError(PolicyConflictReason.EVIDENCE_INVALID)
        current = InspectBudgetRecovery(
            self.repository, self.ledger_reference, self.clock
        ).execute()
        stale = receipt is None and current.revision != change.expected_revision
        # Projection on current liabilities; never change authority or pretend it was applied.
        snapshot = self.repository.read(self.ledger_reference).ledger
        if snapshot.revision != current.revision:
            raise BudgetControlError(PolicyConflictReason.STALE_REVISION)
        projected = snapshot.value.with_policy(change.proposed_policy).with_requested_mode(
            change.proposed_mode
        )
        monthly_remaining = projected.policy.monthly_ai_budget - projected.ai_committed(
            current.observed_at, monthly=True
        )
        daily_remaining = projected.policy.daily_ai_budget - projected.ai_committed(
            current.observed_at
        )
        return BudgetPolicyChangeView(
            change,
            receipt,
            current.revision,
            stale,
            current,
            None if stale or receipt else projected.operating_mode(current.observed_at),
            None if stale or receipt else monthly_remaining,
            None if stale or receipt else daily_remaining,
            ("budget_overcommitted",)
            if not stale
            and receipt is None
            and (monthly_remaining.amount < 0 or daily_remaining.amount < 0)
            else (),
        )


@dataclass(frozen=True, slots=True)
class ApplyBudgetPolicyChange:
    repository: BudgetControlRepository
    ledger_reference: Reference
    operator: Reference
    clock: Clock

    def execute(self, reference: Reference, *, confirm: bool) -> BudgetPolicyChangeReceipt:
        if confirm is not True:
            raise BudgetControlError(PolicyConflictReason.CONFIRMATION_REQUIRED)
        change = self.repository.get_change(reference)
        if change is None or change.ledger_reference != self.ledger_reference:
            raise BudgetControlError(PolicyConflictReason.NOT_FOUND)
        if change.actor != self.operator:
            raise BudgetControlError(PolicyConflictReason.ACTOR_MISMATCH)
        receipt = self.repository.get_receipt(reference)
        if receipt is not None:
            if receipt.change != change or receipt.decision.approved_at > self.clock.now():
                raise BudgetControlError(PolicyConflictReason.EVIDENCE_INVALID)
            return receipt
        snapshot = self.repository.read(self.ledger_reference).ledger
        if snapshot.revision != change.expected_revision:
            # A concurrent identical apply may have committed since the first receipt read.
            receipt = self.repository.get_receipt(reference)
            if (
                receipt is not None
                and receipt.change == change
                and receipt.decision.approved_at <= self.clock.now()
            ):
                return receipt
            raise BudgetControlError(PolicyConflictReason.STALE_REVISION)
        decision = BudgetPolicyDecision(reference, self.operator, self.clock.now())
        receipt = self.repository.apply(BudgetPolicyApplication(change, decision, snapshot))
        logging.getLogger(__name__).info(
            "budget_policy_applied",
            extra={
                "change_reference": reference.value,
                "actor": self.operator.value,
                "ledger_reference": self.ledger_reference.value,
                "revision": receipt.resulting_revision,
            },
        )
        return receipt

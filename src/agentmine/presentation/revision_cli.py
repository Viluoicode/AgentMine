"""Explicit operator revision commands; parsing and display, no lifecycle mutation."""

import argparse
import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import TextIO

from agentmine.application.contracts.data_revision import RevisionTrigger, RevisionView
from agentmine.application.contracts.revision_execution import PrepareRevisionRequest
from agentmine.application.contracts.runtime import ExecutionBinding
from agentmine.application.contracts.worker_execution import WorkerExecutionStatus
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.application.use_cases.data_history import (
    GetCompletedDataParent,
    GetRevisionForExecution,
)
from agentmine.application.use_cases.data_revision import (
    ApproveDataRevision,
    GetDataRevision,
    PrepareDataRevision,
)
from agentmine.application.use_cases.revision_execution import (
    ExecuteDataRevision,
    RecoverDataRevision,
)
from agentmine.domain.eligibility import EligibilityPolicy
from agentmine.domain.values import Reference
from agentmine.presentation.eligibility_inputs import read_eligibility_request
from agentmine.presentation.runtime_inputs import read_economics, read_prepare, read_scoring
from agentmine.presentation.runtime_views import encode, specification_view


@dataclass(frozen=True, slots=True)
class RevisionServices:
    prepare: PrepareDataRevision
    get: GetDataRevision
    approve: ApproveDataRevision
    execute: ExecuteDataRevision
    recover: RecoverDataRevision
    parent: GetCompletedDataParent
    for_execution: GetRevisionForExecution


def add_revision_parsers(actions: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    revision = actions.add_parser(
        "revision", help="Explicit deterministic rework; never submission"
    )
    commands = revision.add_subparsers(dest="revision_action", required=True)
    for name in ("prepare", "show", "approve", "execute", "recover"):
        command = commands.add_parser(name)
        command.add_argument("--revision-id", required=True)
        if name == "prepare":
            for field in (
                "parent-execution",
                "trigger-id",
                "spec-id",
                "evaluation",
                "inputs",
                "input-root",
                "facts",
                "economics",
                "scoring",
                "reason",
            ):
                command.add_argument("--" + field, required=True)
            command.add_argument(
                "--trigger", choices=[item.value for item in RevisionTrigger], required=True
            )
            command.add_argument("--minimum-time-seconds", type=int, required=True)
            command.add_argument("--forecast-evidence", action="append", required=True)
        if name == "approve":
            command.add_argument("--execution-id", required=True)
            command.add_argument("--operation-id", required=True)
            command.add_argument("--approve-inputs", action="store_true")
        if name in ("approve", "execute", "recover"):
            command.add_argument("--confirm", action="store_true")


def revision_view(view: RevisionView) -> dict[str, object]:
    request = view.request
    old = request.parent_run.specification
    new = request.specification
    evidence = new.execution_evidence
    assert evidence is not None and new.acceptance is not None and old.acceptance is not None
    return {
        "revision_id": request.reference.value,
        "reason": request.reason,
        "status": view.status.name,
        "execution_history_completed": view.deliverable is not None,
        "recovery_reason": view.reason.name,
        "parent": {
            "execution": request.parent_run.binding.execution_reference.value,
            "deliverable": encode(request.parent_deliverable),
            "qa": encode(request.parent_snapshot.value.qa),
            "trigger": request.trigger.value,
            "trigger_id": request.trigger_reference.value,
        },
        "scope": specification_view(new),
        "differences": {
            "inputs_changed": old.sources != new.sources,
            "record_bounds": {
                "before": [old.min_records, old.max_records],
                "after": [new.min_records, new.max_records],
            },
            "added_constraints": encode(
                tuple(item for item in new.constraints if item not in old.constraints)
            ),
            "added_formats": encode(
                tuple(item for item in new.acceptance.formats if item not in old.acceptance.formats)
            ),
            "added_columns": encode(tuple(item for item in new.columns if item not in old.columns)),
            "added_criteria": encode(
                tuple(
                    item
                    for item in new.acceptance.requirements
                    if item not in old.acceptance.requirements
                )
            ),
            "parent_inputs": [
                {
                    "id": item.reference.value,
                    "sha256": item.digest,
                    "locator": item.locator,
                    "collected_at": item.collected_at.isoformat(),
                }
                for item in old.sources
            ],
        },
        "current_forecasts_not_revenue": encode(evidence.evaluation),
        "estimated_incremental_cost": encode(
            evidence.evaluation.scoring_assessment.economics.inputs.estimated_cost
        ),
        "consent": None if view.allocation is None else encode(view.allocation.approval),
        "allocation": None
        if view.allocation is None
        else {"binding": encode(view.allocation.binding), "version": view.allocation.version},
        "deliverable": encode(view.deliverable),
        "external_submission": False,
        "payment_simulated": False,
        "revision_consent_grants_submission_approval": False,
    }


def run_revision_command(
    args: argparse.Namespace, services: RevisionServices, output: TextIO
) -> int:
    reference = Reference(args.revision_id)
    action = args.revision_action
    if action == "prepare":
        parent = services.parent.execute(Reference(args.parent_execution))
        opportunity = parent.snapshot.value.reference
        work = read_prepare(
            Path(args.inputs),
            Reference(args.spec_id),
            opportunity,
            Reference(args.evaluation),
            read_eligibility_request(Path(args.facts), opportunity),
            EligibilityPolicy(timedelta(seconds=args.minimum_time_seconds)),
            None,
        )
        policy, signals = read_scoring(Path(args.scoring))
        services.prepare.execute(
            PrepareRevisionRequest(
                reference,
                Reference(args.parent_execution),
                RevisionTrigger(args.trigger),
                Reference(args.trigger_id),
                work,
                read_economics(Path(args.economics)),
                signals,
                policy,
                args.reason,
                tuple(Reference(value) for value in args.forecast_evidence),
            )
        )
    elif action == "approve":
        if not args.approve_inputs or not args.confirm:
            raise PortError(
                PortErrorCode.UNSUPPORTED,
                "revision_consent",
                "Explicit --approve-inputs and --confirm required",
            )
        view = services.get.execute(reference)
        services.approve.execute(
            view.request,
            ExecutionBinding(
                view.request.specification.reference,
                Reference(args.execution_id),
                Reference(args.operation_id),
                view.request.parent_deliverable.reference,
            ),
            confirm=True,
        )
    elif action in ("execute", "recover"):
        operation = services.execute if action == "execute" else services.recover
        outcome = operation.execute(reference, confirm=args.confirm)
        data = {
            "command_status": outcome.status.name,
            "reason": outcome.reason.name,
            "opportunity_state": None
            if outcome.opportunity is None
            else outcome.opportunity.state.name,
            "revision": revision_view(services.get.execute(reference)),
            "external_submission": False,
            "payment_simulated": False,
        }
        print(json.dumps(data, ensure_ascii=True), file=output)
        return 0 if outcome.status == WorkerExecutionStatus.COMPLETED else 1
    print(
        json.dumps(revision_view(services.get.execute(reference)), ensure_ascii=True), file=output
    )
    return 0

"""Thin operator commands: typed input, application invocation, escaped JSON output."""

import argparse
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import TextIO

from agentmine.application.contracts.data_revision import RevisionError
from agentmine.application.contracts.operational_qa import OperationalQAStatus
from agentmine.application.contracts.runtime import (
    ExecutionBinding,
    RuntimeStatus,
)
from agentmine.application.contracts.worker_execution import (
    ExecuteWorkerRequest,
    WorkerExecutionStatus,
)
from agentmine.application.contracts.workflow import PlanTaskRequest, ScoreRequest
from agentmine.application.errors import ApplicationError, PortError, PortErrorCode
from agentmine.application.use_cases.eligibility import CheckEligibility
from agentmine.application.use_cases.local_runtime import (
    ExportDataArtifacts,
    GetDataSpecification,
    GetOperatorOpportunity,
    GetWorkerRuntime,
    PrepareDataSpecification,
    RecoverDataExecution,
)
from agentmine.application.use_cases.operational_qa import (
    GetOperationalQAStatus,
    RunOperationalDataQA,
)
from agentmine.application.use_cases.planning import EvaluateOpportunity, PlanTask, ScoreOpportunity
from agentmine.application.use_cases.worker_execution import ExecuteWorkerTask
from agentmine.domain.eligibility import EligibilityPolicy
from agentmine.domain.errors import DomainError
from agentmine.domain.opportunity import OpportunityState
from agentmine.domain.qa import QAOutcome
from agentmine.domain.scoring import ScoringPolicy
from agentmine.domain.values import Reference
from agentmine.domain.work import TaskType
from agentmine.presentation.eligibility_inputs import read_eligibility_request
from agentmine.presentation.revision_cli import (
    RevisionServices,
    add_revision_parsers,
    run_revision_command,
)
from agentmine.presentation.runtime_inputs import read_economics, read_prepare, read_scoring
from agentmine.presentation.runtime_views import encode as encode
from agentmine.presentation.runtime_views import specification_view as specification_view


@dataclass(frozen=True, slots=True)
class RuntimeServices:
    opportunity: GetOperatorOpportunity
    eligibility: Callable[[EligibilityPolicy], CheckEligibility]
    evaluate: EvaluateOpportunity
    score: Callable[[ScoringPolicy], ScoreOpportunity]
    plan: PlanTask
    prepare: PrepareDataSpecification
    specification: GetDataSpecification
    status: GetWorkerRuntime
    execute: ExecuteWorkerTask
    recover: RecoverDataExecution
    export: ExportDataArtifacts
    qa: RunOperationalDataQA
    qa_status: GetOperationalQAStatus
    revisions: RevisionServices | None = None


def add_runtime_parsers(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    opportunity = commands.add_parser(
        "opportunity", help="Inspect and explicitly assess/plan opportunities"
    )
    actions = opportunity.add_subparsers(dest="opportunity_action", required=True)
    for action in ("show", "eligibility", "evaluate", "score", "plan"):
        parser = actions.add_parser(action)
        parser.add_argument("--opportunity", required=True)
        if action == "eligibility":
            parser.add_argument("--facts", required=True)
            parser.add_argument("--minimum-time-seconds", type=int, required=True)
        elif action in ("evaluate", "score"):
            parser.add_argument("--inputs", required=True)
            if action == "score":
                parser.add_argument("--evaluation", required=True)
        elif action == "plan":
            parser.add_argument("--task", required=True)
            parser.add_argument("--description", required=True)
    work = commands.add_parser("work", help="Deterministic Data and zero-AI QA; never submission")
    actions = work.add_subparsers(dest="work_action", required=True)
    add_revision_parsers(actions)
    prepare = actions.add_parser("prepare")
    for name in ("opportunity", "spec-id", "inputs", "input-root", "facts", "evaluation"):
        prepare.add_argument("--" + name, required=True)
    prepare.add_argument("--minimum-time-seconds", required=True, type=int)
    prepare.add_argument("--eligibility-review")
    prepare.add_argument("--approve-inputs", action="store_true")
    show = actions.add_parser("show")
    show.add_argument("--spec-id", required=True)
    execute = actions.add_parser("execute")
    for name in ("spec-id", "execution-id", "operation-id", "deliverable-id"):
        execute.add_argument("--" + name, required=True)
    execute.add_argument("--expected-revision", required=True, type=int)
    execute.add_argument("--confirm", action="store_true")
    qa = actions.add_parser("qa")
    qa.add_argument("--execution-id", required=True)
    qa.add_argument("--inspection-id", required=True)
    qa.add_argument("--confirm", action="store_true")
    for name in ("status", "recover", "export"):
        parser = actions.add_parser(name)
        parser.add_argument("--execution-id", required=True)
        if name == "recover":
            parser.add_argument("--confirm", action="store_true")
        elif name == "export":
            parser.add_argument("--directory", required=True)


def runtime_view(view: RuntimeStatus, qa: OperationalQAStatus) -> dict[str, object]:
    result = view.result
    report = qa.report
    is_current = view.opportunity_snapshot.value.execution == view.run.plan.execution
    action = (
        "HISTORICAL_ONLY"
        if not is_current
        else "QA_REQUIRED"
        if qa.binding is None
        else "RETRY_SAME_INSPECTION"
        if report is None or not qa.applied
        else "F05_REWORK_REQUIRED"
        if view.opportunity_snapshot.value.state == OpportunityState.IN_PROGRESS
        else "HUMAN_QA_ACTION_REQUIRED"
        if report.outcome == QAOutcome.REQUIRES_HUMAN_REVIEW
        else "OPERATOR_REVIEW_REQUIRED"
        if view.opportunity_snapshot.value.approval is None
        else "NO_AUTOMATIC_SUBMISSION"
    )
    return {
        "execution_id": view.run.binding.execution_reference.value,
        "requested_execution_is_current": is_current,
        "deliverable": encode(view.deliverable),
        "current_execution": encode(view.opportunity_snapshot.value.execution),
        "current_deliverable": encode(view.opportunity_snapshot.value.deliverable),
        "binding": encode(view.run.binding),
        "opportunity_state": view.opportunity_snapshot.value.state.name,
        "opportunity_revision": view.opportunity_snapshot.revision,
        "execution_history_completed": view.finished,
        "recovery_reason": view.reason.name,
        "execution_control": "BLOCKED"
        if view.reason.name in ("STATE_CHANGED", "AI_EVIDENCE_PRESENT")
        else "HISTORY_COMPLETED"
        if view.finished
        else "RECOVERABLE",
        "retained_results": None
        if result is None
        else {
            "records": encode(result.records),
            "issues": encode(result.issues),
            "warnings": list(result.warnings),
            "cost": encode(result.cost),
            "artifacts": [
                {
                    "name": item.name,
                    "sha256": item.digest,
                    "bytes": len(item.content.encode("utf-8")),
                }
                for item in result.artifacts
            ],
        },
        "external_submission": False,
        "qa": {
            "inspection": None if qa.binding is None else qa.binding.reference.value,
            "applied": qa.applied,
            "report": None
            if report is None
            else {
                "reference": report.reference.value,
                "deliverable": encode(report.deliverable),
                "historical": not is_current,
                "outcome": report.outcome.value,
                "checked_at": report.checked_at.isoformat(),
                "findings": encode(report.findings),
                "artifact_content_reference": report.deliverable.content_reference.value,
            },
            "required_action": action,
        },
    }


def run_runtime_command(args: argparse.Namespace, services: RuntimeServices, output: TextIO) -> int:
    try:
        if args.command == "work" and args.work_action == "revision":
            if services.revisions is None:
                raise PortError(
                    PortErrorCode.UNSUPPORTED, "revision", "Revision services unavailable"
                )
            return run_revision_command(args, services.revisions, output)
        data: dict[str, object]
        if args.command == "opportunity":
            ref = Reference(args.opportunity)
            action = args.opportunity_action
            if action == "eligibility":
                services.eligibility(
                    EligibilityPolicy(timedelta(seconds=args.minimum_time_seconds))
                ).execute(read_eligibility_request(Path(args.facts), ref))
            elif action == "evaluate":
                services.evaluate.execute(ref, read_economics(Path(args.inputs)))
            elif action == "score":
                policy, signals = read_scoring(Path(args.inputs))
                services.score(policy).execute(
                    ScoreRequest(ref, Reference(args.evaluation), signals, ())
                )
            elif action == "plan":
                services.plan.execute(
                    PlanTaskRequest(
                        ref, Reference(args.task), TaskType.DATA_PROCESSING, args.description
                    )
                )
            current = services.opportunity.execute(ref)
            op = current.value
            data = {
                "opportunity_id": op.reference.value,
                "opportunity_state": op.state.name,
                "opportunity_revision": current.revision,
                "task": encode(op.task),
                "eligibility": encode(op.eligibility),
                "economic_forecast_not_revenue": encode(op.economic_assessment),
                "scoring": encode(op.scoring_assessment),
                "verified_revenue": encode(op.verified_revenue),
                "required_approvals": [
                    "Explicit approval of exact local input snapshots before work",
                    "Separate human submission approval after QA",
                ],
                "submission_approval": encode(op.approval),
            }
        else:
            action = args.work_action
            if action == "prepare":
                if not args.approve_inputs:
                    raise PortError(
                        PortErrorCode.UNSUPPORTED,
                        "operator_intent",
                        "Pass --approve-inputs after reviewing exact input digests and scope",
                    )
                request = read_prepare(
                    Path(args.inputs),
                    Reference(args.spec_id),
                    Reference(args.opportunity),
                    Reference(args.evaluation),
                    read_eligibility_request(Path(args.facts), Reference(args.opportunity)),
                    EligibilityPolicy(timedelta(seconds=args.minimum_time_seconds)),
                    None if args.eligibility_review is None else Reference(args.eligibility_review),
                )
                data = specification_view(services.prepare.execute(request))
            elif action == "show":
                data = specification_view(services.specification.execute(Reference(args.spec_id)))
            elif action == "status":
                data = runtime_view(
                    services.status.execute(Reference(args.execution_id)),
                    services.qa_status.execute(Reference(args.execution_id)),
                )
                if services.revisions is not None:
                    revision = services.revisions.for_execution.execute(
                        Reference(args.execution_id)
                    )
                    if revision is not None:
                        from agentmine.presentation.revision_cli import revision_view

                        data["revision"] = revision_view(revision)
            elif action == "qa":
                if not args.confirm:
                    raise PortError(
                        PortErrorCode.UNSUPPORTED,
                        "operator_intent",
                        "Explicit --confirm required for QA",
                    )
                report = services.qa.execute(
                    Reference(args.execution_id), Reference(args.inspection_id)
                )
                inspected = services.status.execute(Reference(args.execution_id))
                data = {
                    "historical": inspected.opportunity_snapshot.value.execution
                    != inspected.run.plan.execution,
                    "deliverable": encode(report.deliverable),
                    "qa_outcome": report.outcome.value,
                    "inspection_id": report.reference.value,
                    "findings": encode(report.findings),
                    "opportunity_state": services.status.execute(
                        Reference(args.execution_id)
                    ).opportunity_snapshot.value.state.name,
                    "external_submission": False,
                }
            elif action == "export":
                exported = services.export.execute(Reference(args.execution_id))
                data = {
                    "export": encode(exported),
                    "external_submission": False,
                    "note": "Local export only; QA and submission remain separate",
                }
            else:
                if not args.confirm:
                    raise PortError(
                        PortErrorCode.UNSUPPORTED,
                        "operator_intent",
                        "Explicit --confirm required to execute or recover work",
                    )
                if action == "execute":
                    outcome = services.execute.execute(
                        ExecuteWorkerRequest(
                            ExecutionBinding(
                                Reference(args.spec_id),
                                Reference(args.execution_id),
                                Reference(args.operation_id),
                                Reference(args.deliverable_id),
                            ),
                            args.expected_revision,
                        )
                    )
                else:
                    outcome = services.recover.execute(Reference(args.execution_id))
                current_state = (
                    None if outcome.opportunity is None else outcome.opportunity.state.name
                )
                if current_state is None:
                    try:
                        if action == "recover":
                            current_state = services.status.execute(
                                Reference(args.execution_id)
                            ).opportunity_snapshot.value.state.name
                        else:
                            spec = services.specification.execute(Reference(args.spec_id))
                            current_state = services.opportunity.execute(
                                spec.task.opportunity_reference
                            ).value.state.name
                    except (ApplicationError, PortError, DomainError):
                        pass  # A reporting read cannot turn a blocked outcome into permission.
                data = {
                    "command_status": outcome.status.name,
                    "reason": outcome.reason.name,
                    "opportunity_state": current_state,
                    "external_submission": False,
                    "payment_simulated": False,
                }
                print(json.dumps(data, ensure_ascii=True), file=output)
                return 0 if outcome.status == WorkerExecutionStatus.COMPLETED else 1
        print(json.dumps(data, ensure_ascii=True), file=output)
        return 0
    except RevisionError as error:
        print(
            json.dumps(
                {"status": "failed", "code": "revision_conflict", "reason": error.reason.value}
            ),
            file=output,
        )
        return 1
    except DomainError:
        raise
    except (OSError, ValueError, ArithmeticError, RecursionError):
        print(
            json.dumps(
                {
                    "status": "failed",
                    "code": "invalid_local_input",
                    "message": "Invalid, missing or unsupported operator input",
                }
            ),
            file=output,
        )
        return 2

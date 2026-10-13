"""Explicit, injected workflow coordinators. No adapters are constructed here."""

from agentmine.application.use_cases.approval import ApproveSubmission, RequestHumanApproval
from agentmine.application.use_cases.eligibility import CheckEligibility
from agentmine.application.use_cases.execution import ExecuteTask, RunQA
from agentmine.application.use_cases.planning import (
    DiscoverOpportunities,
    EvaluateOpportunity,
    NormalizeOpportunity,
    PlanTask,
    ScoreOpportunity,
)
from agentmine.application.use_cases.settlement import SubmitTask, TrackOutcome, VerifyPayment

__all__ = [
    "ApproveSubmission",
    "CheckEligibility",
    "DiscoverOpportunities",
    "EvaluateOpportunity",
    "ExecuteTask",
    "NormalizeOpportunity",
    "PlanTask",
    "RequestHumanApproval",
    "RunQA",
    "ScoreOpportunity",
    "SubmitTask",
    "TrackOutcome",
    "VerifyPayment",
]

"""C4 independent literal QA decisions and hostile evidence; all external data is test-only."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier
from typing import TypedDict, cast
from unittest.mock import patch

import pytest
from partition_qa_fakes import QAWorld, retained

from agentmine.application.contracts.data import (
    DataIssue,
    DataIssueCode,
    DataResult,
    InputPresence,
    PartitionAcceptance,
)
from agentmine.application.contracts.qa import CoverageKind, QAInspection, bundle_content
from agentmine.application.contracts.records import OpportunitySave
from agentmine.application.errors import ApplicationError, PortError, PortErrorCode
from agentmine.application.qa.checks import deterministic, domain_specific
from agentmine.application.workers.data_partition_artifacts import render_partition_artifacts
from agentmine.domain.errors import DomainError
from agentmine.domain.opportunity import OpportunityState
from agentmine.domain.qa import QAOutcome, QAReport
from agentmine.domain.values import Reference
from agentmine.infrastructure.sqlite.opportunities import SQLiteOpportunityRepository
from agentmine.infrastructure.sqlite.qa import SQLiteQAJournal


class Expectation(TypedDict):
    case: str
    min_clean: int
    max_rejected: int
    outcome: str
    code: str


FIXTURES = Path(__file__).resolve().parents[1] / "contract/fixtures/data_partition_c4"
EXPECTATIONS = cast(list[Expectation], json.loads((FIXTURES / "qa-expectations.json").read_text()))


def inspection(w: QAWorld) -> QAInspection:
    spec = w.start.specification
    criteria = spec.acceptance
    view = w.world.runtime().inspect(w.start.binding.execution_reference)
    assert criteria is not None and view is not None and view.deliverable is not None
    return QAInspection(
        Reference("c4-qa"),
        view.deliverable,
        w.start.run.plan,
        w.result,
        criteria.formats,
        criteria.requirements,
        partition_acceptance=criteria.partition_acceptance,
    )


@pytest.mark.parametrize(
    "expected",
    EXPECTATIONS,
    ids=[f"{e['case']}-{e['min_clean']}-{e['max_rejected']}" for e in EXPECTATIONS],
)
def test_literal_operational_qa_decisions(tmp_path: Path, expected: Expectation) -> None:
    w = retained(tmp_path, expected["case"], expected["min_clean"], expected["max_rejected"])
    before = w.world.budget().ledger.get(Reference("ledger"))
    report = w.qa().execute(w.start.binding.execution_reference, Reference("c4-qa"))
    assert report.outcome.value == expected["outcome"]
    assert expected["code"] in {f.code for f in report.findings}
    op = w.world.current()
    assert op.state == (
        OpportunityState.READY_FOR_HUMAN_REVIEW
        if expected["outcome"] == "PASS"
        else OpportunityState.IN_PROGRESS
    )
    assert op.approval is None and op.submission is None and op.verified_revenue.amount == 0
    assert w.world.budget().ledger.get(Reference("ledger")) == before
    assert SQLiteQAJournal(w.world.database).get_report(Reference("c4-qa")) == report
    assert w.result.valid == (not w.result.issues)


def test_literal_fixture_manifest() -> None:
    for name, digest in json.loads((FIXTURES / "sha256.json").read_text()).items():
        assert hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest() == digest


@pytest.mark.parametrize(
    "kind,expected",
    [(CoverageKind.FIELD_PRESENT, QAOutcome.PASS), (CoverageKind.COLUMN, QAOutcome.NEEDS_REVISION)],
)
def test_frozen_optional_null_column_semantics(
    tmp_path: Path, kind: CoverageKind, expected: QAOutcome
) -> None:
    w = retained(tmp_path, coverage=kind, criterion="title")
    report = w.qa().execute(w.start.binding.execution_reference, Reference("c4-qa"))
    assert report.outcome == expected


@pytest.mark.parametrize(
    "payload,presence",
    [
        ('[{"id":"a1","qty":1,"title":null}]', InputPresence.NULL),
        ('[{"id":"a1","qty":1}]', InputPresence.MISSING),
        ('[{"id":"a1","qty":1,"title":"  "}]', InputPresence.VALUE),
    ],
)
def test_optional_presence_not_confused_with_output_presence(
    tmp_path: Path, payload: str, presence: InputPresence
) -> None:
    w = retained(tmp_path, content=payload, criterion="title")
    assert w.result.records[0].cells[1].input_presence == presence
    assert w.result.records[0].cells[1].value is None
    assert (
        w.qa().execute(w.start.binding.execution_reference, Reference("c4-qa")).outcome
        == QAOutcome.PASS
    )


def test_required_null_is_rejected_not_accepted_as_optional(tmp_path: Path) -> None:
    w = retained(tmp_path, content='[{"id":"a1","qty":null}]')
    assert any(i.code == DataIssueCode.MISSING_VALUE and i.column == "qty" for i in w.result.issues)
    assert (
        w.qa().execute(w.start.binding.execution_reference, Reference("c4-qa")).outcome
        == QAOutcome.NEEDS_REVISION
    )


def hostile(w: QAWorld, damage: str) -> QAInspection:
    current = inspection(w)
    result = current.result
    assert isinstance(result, DataResult) and result.partition is not None
    assessment = result.partition
    if damage in ("value", "provenance", "presence", "missing_column", "unknown_issue"):
        row = result.records[0]
        if damage == "value":
            row = replace(row, cells=(replace(row.cells[0], value="EVIL"), *row.cells[1:]))
        elif damage == "provenance":
            row = replace(row, locator="operator:forged")
        elif damage == "presence":
            row = replace(
                row,
                cells=(replace(row.cells[0], input_presence=InputPresence.MISSING), *row.cells[1:]),
            )
        elif damage == "missing_column":
            row = replace(row, cells=row.cells[:-1])
        if damage == "unknown_issue":
            result = replace(
                result, issues=(*result.issues, DataIssue(cast(DataIssueCode, "unknown")))
            )
        else:
            result = replace(result, records=(row, *result.records[1:]))
    elif damage == "reason":
        rejected = assessment.rejected_rows[0]
        kept = tuple(i for i in rejected.reasons if i.code != DataIssueCode.INVALID_VALUE)
        removed = set(rejected.reasons) - set(kept)
        assessment = replace(
            assessment,
            rejected_rows=(replace(rejected, reasons=kept), *assessment.rejected_rows[1:]),
        )
        result = replace(
            result, partition=assessment, issues=tuple(i for i in result.issues if i not in removed)
        )
    elif damage == "first_duplicate_clean":
        first = assessment.rejected_rows[0]
        group = assessment.duplicate_groups[0]
        assessment = replace(
            assessment,
            clean_rows=(first.row,),
            rejected_rows=assessment.rejected_rows[1:],
            duplicate_groups=(replace(group, members=group.members[1:]),),
        )
        result = replace(
            result,
            partition=assessment,
            issues=tuple(
                i
                for i in result.issues
                if not (i.source == first.row.source and i.row == first.row.row)
            ),
        )
    elif damage == "coverage":
        assessment = replace(
            assessment, source_outcomes=assessment.source_outcomes[1:], evidence_complete=True
        )
        result = replace(result, partition=assessment, issues=())
    else:
        files = list(result.artifacts)
        if damage == "missing_artifact":
            files.pop()
        elif damage == "extra_artifact":
            files.append(replace(files[-1], name="extra.json"))
        elif damage == "output_key":
            values = json.loads(files[1].content)
            del values[0]["price"]
            files[1] = replace(files[1], content=json.dumps(values))
        else:
            files[0] = replace(files[0], content="corrupt")
        result = replace(result, artifacts=tuple(files))
    # A forged digest/bundle must not make altered semantic evidence authoritative.
    return replace(
        current,
        result=result,
        deliverable=replace(
            current.deliverable, content_reference=bundle_content(result).reference
        ),
    )


@pytest.mark.parametrize(
    "case,damage",
    [
        ("all_valid", "value"),
        ("all_valid", "provenance"),
        ("all_valid", "presence"),
        ("all_valid", "missing_column"),
        ("all_valid", "unknown_issue"),
        ("duplicate_and_error", "reason"),
        ("three_duplicates", "first_duplicate_clean"),
        ("partial_malformed", "coverage"),
        ("all_valid", "missing_artifact"),
        ("all_valid", "extra_artifact"),
        ("all_valid", "output_key"),
        ("all_valid", "bytes"),
    ],
)
def test_hostile_evidence_cannot_pass_with_self_consistent_digest(
    tmp_path: Path, case: str, damage: str
) -> None:
    w = retained(tmp_path, case, maximum=4)
    altered = hostile(w, damage)
    checks = deterministic(altered, bundle_content(altered.result).text)
    if all(f.outcome == QAOutcome.PASS for f in checks):
        checks += domain_specific(altered, w.world.clock.now())
    assert any(f.outcome == QAOutcome.FAIL for f in checks)


def test_coherent_forged_values_and_artifacts_do_not_prove_correctness(tmp_path: Path) -> None:
    w = retained(tmp_path)
    altered = hostile(w, "value")
    assert isinstance(altered.result, DataResult) and altered.result.partition is not None
    result = replace(
        altered.result,
        artifacts=render_partition_artifacts(
            w.start.run.plan,
            altered.result.records,
            altered.result.issues,
            altered.result.partition,
        ),
    )
    altered = replace(
        altered,
        result=result,
        deliverable=replace(
            altered.deliverable, content_reference=bundle_content(result).reference
        ),
    )
    assert any(
        f.outcome == QAOutcome.FAIL for f in deterministic(altered, bundle_content(result).text)
    )


def test_content_digest_corruption_is_failure(tmp_path: Path) -> None:
    w = retained(tmp_path)
    assert any(f.outcome == QAOutcome.FAIL for f in deterministic(inspection(w), "corrupt"))


def test_missing_replay_bytes_fails_closed(tmp_path: Path) -> None:
    w = retained(tmp_path)
    value = inspection(w)
    # Explicit misbehaving in-memory port; never mutate a stored source or production workspace.
    source = replace(w.start.run.plan.sources[0])
    object.__setattr__(source, "content", None)
    object.__setattr__(value, "plan", replace(w.start.run.plan, sources=(source,)))
    with pytest.raises(PortError):
        deterministic(value, bundle_content(value.result).text)


def test_unknown_version_and_changed_thresholds_are_not_legacy(tmp_path: Path) -> None:
    w = retained(tmp_path)
    value = inspection(w)
    assert value.partition_acceptance is not None and w.result.partition is not None
    with pytest.raises(DomainError):
        replace(value, partition_acceptance=PartitionAcceptance(2, 1, 0))
    with pytest.raises(DomainError):
        replace(w.result.partition, contract_version=99)


def test_restart_same_inspection_is_readback_no_cost_or_revalidation(tmp_path: Path) -> None:
    w = retained(tmp_path, "two_duplicates")
    report = w.qa().execute(w.start.binding.execution_reference, Reference("c4-qa"))
    ledger = w.world.budget().ledger.get(Reference("ledger"))
    w.reopen()
    with patch(
        "agentmine.application.use_cases.deliverable_qa.deterministic",
        side_effect=AssertionError("no recompute"),
    ):
        assert w.qa().execute(w.start.binding.execution_reference, Reference("c4-qa")) == report
    assert w.world.budget().ledger.get(Reference("ledger")) == ledger
    with pytest.raises(PortError):
        w.qa().execute(w.start.binding.execution_reference, Reference("other-qa"))


def test_report_crash_retries_original_evidence(tmp_path: Path) -> None:
    w = retained(tmp_path)
    original = SQLiteQAJournal.save_report

    def crash(journal: SQLiteQAJournal, report: QAReport) -> None:
        original(journal, report)
        raise PortError(PortErrorCode.OUTCOME_UNKNOWN, "test", "lost acknowledgement")

    with patch.object(SQLiteQAJournal, "save_report", crash), pytest.raises(PortError):
        w.qa().execute(w.start.binding.execution_reference, Reference("c4-qa"))
    assert w.world.current().state == OpportunityState.QA_PENDING
    saved = SQLiteQAJournal(w.world.database).get_report(Reference("c4-qa"))
    assert saved is not None
    w.reopen()
    assert w.qa().execute(w.start.binding.execution_reference, Reference("c4-qa")) == saved
    assert w.world.current().state == OpportunityState.READY_FOR_HUMAN_REVIEW


def test_stale_opportunity_after_claim_blocks_application(tmp_path: Path) -> None:
    w = retained(tmp_path)
    original = SQLiteQAJournal.save_report

    def stale(journal: SQLiteQAJournal, report: QAReport) -> None:
        original(journal, report)
        repository = SQLiteOpportunityRepository(w.world.database)
        op = repository.get(Reference("op"))
        assert op is not None
        repository.save(OpportunitySave(op.value, op.revision))

    with patch.object(SQLiteQAJournal, "save_report", stale), pytest.raises(PortError):
        w.qa().execute(w.start.binding.execution_reference, Reference("c4-qa"))
    with pytest.raises(PortError):
        w.qa().execute(w.start.binding.execution_reference, Reference("c4-qa"))
    assert w.world.current().state == OpportunityState.QA_PENDING


@pytest.mark.parametrize("change", ["threshold", "requirements", "policy", "actor", "ledger"])
def test_changed_frozen_authority_is_not_reused(tmp_path: Path, change: str) -> None:
    w = retained(tmp_path)
    service = w.qa()
    spec = w.start.specification
    assert spec.acceptance is not None and spec.output_policy is not None
    if change in ("actor", "ledger"):
        service = (
            replace(service, operator=Reference("foreign"))
            if change == "actor"
            else replace(service, ledger_reference=Reference("foreign"))
        )
    else:
        criteria = spec.acceptance
        if change == "threshold":
            criteria = replace(criteria, partition_acceptance=PartitionAcceptance(2, 1, 0))
        elif change == "requirements":
            criteria = replace(
                criteria, requirements=(replace(criteria.requirements[0], criterion="title"),)
            )
        altered_spec = (
            replace(spec, acceptance=criteria)
            if change != "policy"
            else replace(
                spec,
                columns=(replace(spec.columns[0], case=spec.columns[1].case), *spec.columns[1:]),
            )
        )
        with (
            patch.object(type(service.runtime), "get_specification", return_value=altered_spec),
            pytest.raises(PortError),
        ):
            service.execute(w.start.binding.execution_reference, Reference("c4-qa"))
        return
    with pytest.raises(PortError):
        service.execute(w.start.binding.execution_reference, Reference("c4-qa"))


def test_concurrent_inspections_have_one_owner(tmp_path: Path) -> None:
    w = retained(tmp_path)
    ready = Barrier(2)

    def attempt(identity: str) -> str:
        ready.wait(timeout=10)
        try:
            return (
                w.qa()
                .execute(w.start.binding.execution_reference, Reference(identity))
                .outcome.value
            )
        except (PortError, ApplicationError):
            return "BLOCKED"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, ("qa-a", "qa-b"))) == ["BLOCKED", "PASS"]


def test_source_refresh_unavailable_does_not_authorize_new_qa(tmp_path: Path) -> None:
    w = retained(tmp_path)
    with (
        patch.object(
            type(w.world.source),
            "refresh",
            side_effect=PortError(PortErrorCode.UNAVAILABLE, "test", "offline"),
        ),
        pytest.raises(ApplicationError),
    ):
        w.qa().execute(w.start.binding.execution_reference, Reference("c4-qa"))
    assert w.world.current().state == OpportunityState.QA_PENDING


def test_semantic_criterion_requires_human_without_ai(tmp_path: Path) -> None:
    w = retained(tmp_path, coverage=CoverageKind.SEMANTIC, criterion="Confirm product meaning")
    before = w.world.budget().ledger.get(Reference("ledger"))
    report = w.qa().execute(w.start.binding.execution_reference, Reference("c4-qa"))
    assert report.outcome == QAOutcome.REQUIRES_HUMAN_REVIEW
    assert w.world.current().state == OpportunityState.QA_PENDING
    assert w.world.current().qa is None and w.world.current().approval is None
    assert w.world.budget().ledger.get(Reference("ledger")) == before


def test_unbound_direct_inspection_and_paid_configuration_are_unavailable(tmp_path: Path) -> None:
    from qa_fakes import QAProvider

    w = retained(tmp_path)
    service = w.qa()
    with pytest.raises(PortError):
        service.validator.execute(inspection(w))
    provider = QAProvider()
    configured = replace(service, validator=replace(service.validator, llm=provider))
    with pytest.raises(PortError):
        configured.execute(w.start.binding.execution_reference, Reference("c4-qa"))
    assert provider.calls == []
    assert SQLiteQAJournal(w.world.database).get_report(Reference("c4-qa")) is None


@pytest.mark.parametrize("change", ["threshold", "result", "requirements"])
def test_retained_inspection_cannot_change_on_retry(tmp_path: Path, change: str) -> None:
    w = retained(tmp_path)
    service = w.qa()
    original = SQLiteQAJournal.save_report

    def crash(journal: SQLiteQAJournal, report: QAReport) -> None:
        original(journal, report)
        raise PortError(PortErrorCode.OUTCOME_UNKNOWN, "test", "lost ack")

    with patch.object(SQLiteQAJournal, "save_report", crash), pytest.raises(PortError):
        service.execute(w.start.binding.execution_reference, Reference("c4-qa"))
    value = service.repository.get_inspection(Reference("c4-qa"))
    assert value is not None
    if change == "threshold":
        altered = replace(value)
        object.__setattr__(altered, "partition_acceptance", PartitionAcceptance(2, 1, 0))
    elif change == "requirements":
        altered = replace(value, requirements=(replace(value.requirements[0], criterion="title"),))
    else:
        altered = hostile(w, "value")
    with (
        patch.object(type(service.repository), "get_inspection", return_value=altered),
        pytest.raises(PortError),
    ):
        service.execute(w.start.binding.execution_reference, Reference("c4-qa"))
    assert w.world.current().state == OpportunityState.QA_PENDING
    assert service.repository.applied(Reference("c4-qa")) is False


def test_applied_readback_preserves_later_operator_approval(tmp_path: Path) -> None:
    import io

    from agentmine.bootstrap.operator import compose_operator
    from agentmine.presentation.operator_cli import run_cli

    w = retained(tmp_path)
    report = w.qa().execute(w.start.binding.execution_reference, Reference("c4-qa"))
    assert w.world.current().approval is None
    services = compose_operator(
        w.world.database.path,
        Reference("ledger"),
        Reference("operator"),
        w.world.clock,
        w.world.source,
    )
    common = ["--db", str(w.world.database.path), "--ledger", "ledger"]
    assert (
        run_cli(
            [
                *common,
                "review",
                "--opportunity",
                "op",
                "--review-id",
                "c4-review",
                "--destination",
                "operator:manual-target",
            ],
            services,
            io.StringIO(),
        )
        == 0
    )
    assert (
        run_cli(
            [
                *common,
                "decide",
                "--review-id",
                "c4-review",
                "--decision",
                "APPROVE",
                "--reason",
                "Explicit test-only operator review",
            ],
            services,
            io.StringIO(),
        )
        == 0
    )
    assert w.world.current().state == OpportunityState.APPROVED_FOR_SUBMISSION
    w.reopen()
    assert w.qa().execute(w.start.binding.execution_reference, Reference("c4-qa")) == report
    assert w.world.current().state == OpportunityState.APPROVED_FOR_SUBMISSION
    assert w.world.current().submission is None and w.world.current().verified_revenue.amount == 0


@pytest.mark.parametrize("kind", ["terms", "deadline", "closed"])
def test_fresh_source_terms_and_deadline_still_required(tmp_path: Path, kind: str) -> None:
    from datetime import timedelta

    w = retained(tmp_path)
    source = w.world.source
    if kind == "terms":
        source.terms_reference = Reference("changed-terms")
    elif kind == "deadline":
        source.deadline = w.world.clock.now() - timedelta(seconds=1)
    else:
        source.is_open = False
    with pytest.raises(ApplicationError):
        w.qa().execute(w.start.binding.execution_reference, Reference("c4-qa"))
    assert w.world.current().state == OpportunityState.QA_PENDING


@pytest.mark.parametrize("human", [False, True])
def test_unacceptable_or_human_pending_history_is_not_reapplied(
    tmp_path: Path, human: bool
) -> None:
    w = retained(
        tmp_path,
        "mixed" if not human else "all_valid",
        maximum=0,
        coverage=CoverageKind.SEMANTIC if human else CoverageKind.FIELD_PRESENT,
    )
    original = w.qa().execute(w.start.binding.execution_reference, Reference("c4-qa"))
    assert original.outcome == (
        QAOutcome.REQUIRES_HUMAN_REVIEW if human else QAOutcome.NEEDS_REVISION
    )
    state = w.world.current()
    budget = w.world.budget().ledger.get(Reference("ledger"))
    w.reopen()
    assert w.qa().execute(w.start.binding.execution_reference, Reference("c4-qa")) == original
    assert w.world.current() == state
    assert w.world.budget().ledger.get(Reference("ledger")) == budget


@pytest.mark.parametrize(
    "change", ["strict", "lower_minimum", "raise_reject_limit", "drop_column_requirement"]
)
def test_v2_revision_acceptance_cannot_be_relaxed(tmp_path: Path, change: str) -> None:
    from agentmine.application.contracts.data_revision import (
        DataRevisionRequest,
        RevisionError,
        RevisionTrigger,
    )

    w = retained(tmp_path, minimum=3, maximum=2, coverage=CoverageKind.COLUMN, criterion="title")
    report = w.qa().execute(w.start.binding.execution_reference, Reference("c4-qa"))
    assert report.outcome == QAOutcome.NEEDS_REVISION
    original = w.start.specification
    evidence = original.execution_evidence
    criteria = original.acceptance
    assert evidence is not None and criteria is not None
    threshold = PartitionAcceptance(2, 4, 1)
    if change == "lower_minimum":
        threshold = PartitionAcceptance(2, 2, 2)
    elif change == "raise_reject_limit":
        threshold = PartitionAcceptance(2, 3, 3)
    criteria = replace(criteria, partition_acceptance=threshold)
    if change == "drop_column_requirement":
        criteria = replace(
            criteria,
            requirements=(replace(criteria.requirements[0], kind=CoverageKind.FIELD_PRESENT),),
        )
    proposed = replace(
        original,
        reference=Reference("future-spec"),
        acceptance=criteria,
        execution_evidence=replace(
            evidence,
            evaluation=replace(evidence.evaluation, reference=Reference("fresh-economic-evidence")),
        ),
    )
    current = SQLiteOpportunityRepository(w.world.database).get(Reference("op"))
    assert current is not None

    def construct() -> DataRevisionRequest:
        return DataRevisionRequest(
            Reference("future-revision"),
            w.start.run,
            report.deliverable,
            current,
            RevisionTrigger.QA,
            report.reference,
            proposed,
            "Test-only contract validation; no approval or dispatch",
        )

    if change == "strict":
        assert construct().specification.acceptance == criteria
    else:
        with pytest.raises(RevisionError):
            construct()

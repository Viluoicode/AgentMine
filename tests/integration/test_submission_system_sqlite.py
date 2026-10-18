"""SQLite mode persistence, cross-key dispatch claims and pre-5B snapshot compatibility."""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
from test_local_persistence import submission_request

from agentmine.application.contracts.submission import (
    ManualSubmissionPackage,
    SubmissionAttemptStatus,
    SubmissionMode,
    SubmissionRequest,
    SubmissionResult,
)
from agentmine.application.errors import PortError
from agentmine.infrastructure.sqlite.codec import SnapshotCodec
from agentmine.infrastructure.sqlite.database import SQLiteDatabase
from agentmine.infrastructure.sqlite.submissions import SQLiteSubmissionRepository


@pytest.mark.parametrize("mode", list(SubmissionMode))
def test_intent_and_metadata_reopen(tmp_path: Path, mode: SubmissionMode) -> None:
    path = tmp_path / "submissions.db"
    repo = SQLiteSubmissionRepository(SQLiteDatabase(path))
    request = replace(submission_request(), mode=mode)
    assert repo.claim_request(request)
    package = (
        ManualSubmissionPackage(
            request.reference,
            request.target,
            request.deliverable,
            request.content,
            ("Send approved content once",),
        )
        if mode == SubmissionMode.MANUAL
        else None
    )
    status = (
        SubmissionAttemptStatus.HUMAN_ACTION_REQUIRED
        if package
        else SubmissionAttemptStatus.UNKNOWN
    )
    result = SubmissionResult(
        request.reference,
        status,
        request.approval.approved_at,
        None,
        "Pending",
        "remote-id",
        '{"status":"pending"}',
        "https://example.test/submission",
        package,
    )
    repo.record_attempt(result)
    reopened = SQLiteSubmissionRepository(SQLiteDatabase(path))
    assert reopened.get_request(request.reference) == request
    assert reopened.attempts_for(request.reference) == (result,)
    assert not reopened.claim_request(request)
    with pytest.raises(PortError):
        reopened.claim_request(replace(request, reference=type(request.reference)("another-id")))


def test_different_ids_cannot_win_same_delivery(tmp_path: Path) -> None:
    path = tmp_path / "submissions.db"
    SQLiteDatabase(path)
    original = submission_request()

    def claim(index: int) -> bool:
        repo = SQLiteSubmissionRepository(SQLiteDatabase(path))
        request = replace(original, reference=type(original.reference)(f"send-{index}"))
        try:
            return repo.claim_request(request)
        except PortError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(claim, (1, 2))) == [False, True]


def test_legacy_snapshot_upgrades_are_narrow() -> None:
    codec = SnapshotCodec()
    request = submission_request()
    payload = json.loads(codec.dumps(request))
    del payload["value"]["fields"]["mode"]
    assert codec.loads(json.dumps(payload), SubmissionRequest) == request
    result = SubmissionResult(
        request.reference,
        SubmissionAttemptStatus.UNKNOWN,
        request.approval.approved_at,
        None,
        "Unknown",
    )
    payload = json.loads(codec.dumps(result))
    for key in (
        "external_submission_id",
        "marketplace_response",
        "external_url",
        "manual_package",
        "recorded_by",
    ):
        del payload["value"]["fields"][key]
    assert codec.loads(json.dumps(payload), SubmissionResult) == result
    del payload["value"]["fields"]["status"]
    with pytest.raises(PortError):
        codec.loads(json.dumps(payload), SubmissionResult)


def test_conflicting_confirmations_are_atomic(tmp_path: Path) -> None:
    from agentmine.domain.values import Reference
    from agentmine.domain.work import Submission

    request = submission_request()
    path = tmp_path / "receipts.db"
    repo = SQLiteSubmissionRepository(SQLiteDatabase(path))
    repo.claim_request(request)

    def record(index: int) -> bool:
        receipt = Submission(
            request.reference,
            request.deliverable,
            request.qa,
            request.approval,
            request.target,
            Reference(f"proof-{index}"),
            request.approval.approved_at,
        )
        result = SubmissionResult(
            request.reference,
            SubmissionAttemptStatus.CONFIRMED,
            request.approval.approved_at,
            receipt,
            "Confirmed",
            f"external-{index}",
        )
        try:
            SQLiteSubmissionRepository(SQLiteDatabase(path)).record_attempt(result)
            return True
        except PortError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(record, (1, 2))) == [False, True]
    assert len(repo.attempts_for(request.reference)) == 1

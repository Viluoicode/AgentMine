"""Explicit local operator composition. No network or paid provider by default."""

import json
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from agentmine.application.errors import PortError
from agentmine.application.ports.services import Clock, OpportunitySource
from agentmine.application.use_cases.dashboard import GetOperatorDashboard
from agentmine.application.use_cases.eligibility_review import (
    GetEligibilityReview,
    PrepareEligibilityReview,
    ResolveEligibilityReview,
)
from agentmine.application.use_cases.operator import (
    DecideOperatorReview,
    GetOperatorReview,
    PrepareOperatorReview,
)
from agentmine.application.use_cases.planning import DiscoverOpportunities, NormalizeOpportunity
from agentmine.application.use_cases.workspace import (
    InitializeWorkspace,
    LoadWorkspaceOpportunities,
)
from agentmine.domain.errors import DomainError
from agentmine.domain.values import Reference
from agentmine.infrastructure.marketplaces.disabled import DisabledOpportunitySource
from agentmine.infrastructure.marketplaces.raw_archive import RawArchive
from agentmine.infrastructure.marketplaces.superteam import SuperteamOpportunitySource
from agentmine.infrastructure.marketplaces.superteam_http import SuperteamHTTP
from agentmine.infrastructure.sqlite.approval import SQLiteApprovalRepository
from agentmine.infrastructure.sqlite.database import SQLiteDatabase
from agentmine.infrastructure.sqlite.eligibility_review import SQLiteEligibilityReviewRepository
from agentmine.infrastructure.sqlite.executions import SQLiteExecutionRepository
from agentmine.infrastructure.sqlite.ledger import SQLiteCostLedgerRepository
from agentmine.infrastructure.sqlite.operator import SQLiteOperatorReadRepository
from agentmine.infrastructure.sqlite.opportunities import SQLiteOpportunityRepository
from agentmine.presentation.operator_cli import (
    OperatorServices,
    parser,
    run_command,
    workspace_policy,
)


class UTCClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


def compose_operator(
    path: Path,
    ledger_reference: Reference,
    operator: Reference,
    clock: Clock,
    source: OpportunitySource,
    *,
    create_workspace: bool = False,
) -> OperatorServices:
    if not path.is_file():
        if not create_workspace:
            raise ValueError("Workspace file does not exist; run workspace init first")
        path.parent.mkdir(parents=True, exist_ok=True)
    database = SQLiteDatabase(path)
    opportunities = SQLiteOpportunityRepository(database)
    executions = SQLiteExecutionRepository(database)
    ledger = SQLiteCostLedgerRepository(database)
    approvals = SQLiteApprovalRepository(database)
    eligibility_reviews = SQLiteEligibilityReviewRepository(database)
    ledger_count = ledger.count() if create_workspace else 0
    if create_workspace and (
        ledger_count > 1 or (ledger_count == 1 and ledger.get(ledger_reference) is None)
    ):
        raise ValueError("Workspace must have one matching budget ledger")
    workspace = SQLiteOperatorReadRepository(database)
    return OperatorServices(
        GetOperatorDashboard(workspace, clock),
        PrepareOperatorReview(opportunities, executions, ledger, approvals, clock),
        DecideOperatorReview(opportunities, executions, ledger, approvals, source, clock, operator),
        GetOperatorReview(approvals),
        ledger_reference,
        InitializeWorkspace(ledger),
        LoadWorkspaceOpportunities(
            workspace,
            DiscoverOpportunities(source, opportunities, clock),
            NormalizeOpportunity(opportunities),
            opportunities,
        ),
        PrepareEligibilityReview(opportunities, eligibility_reviews, source, clock),
        GetEligibilityReview(eligibility_reviews),
        ResolveEligibilityReview(opportunities, eligibility_reviews, source, clock, operator),
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "workspace" and args.workspace_action == "init":
            # Validate every operator-supplied business limit before creating any file.
            workspace_policy(args)
        actor = os.environ.get("AGENTMINE_OPERATOR_ID", "")
        eligibility_decision = args.command == "eligibility" and args.eligibility_action == "decide"
        if (args.command == "decide" or eligibility_decision) and not actor.strip():
            raise ValueError("Operator identity required")
        clock = UTCClock()
        source: OpportunitySource = DisabledOpportunitySource()
        live_discovery = args.command == "workspace" and args.workspace_action == "discover"
        live_approval = args.live_superteam_refresh
        if live_discovery and not 1 <= args.limit <= 50:
            raise ValueError("Discovery limit must be between 1 and 50")
        if live_discovery and not args.live:
            raise ValueError(
                "Superteam reads are disabled by default; pass --live and a configured API key"
            )
        if live_discovery or live_approval:
            if live_approval and (args.command != "decide" or args.decision != "APPROVE"):
                if not (
                    args.command == "eligibility"
                    and args.eligibility_action in ("prepare", "decide")
                ):
                    raise ValueError(
                        "Live refresh requires submission approval or eligibility review"
                    )
            secret = os.environ.get("AGENTMINE_SUPERTEAM_API_KEY", "")
            archive_value = args.raw_archive if live_discovery else args.archive
            archive = Path(archive_value) if archive_value else Path(str(args.db) + ".raw.sqlite3")
            if not secret:
                raise ValueError("Live source requires AGENTMINE_SUPERTEAM_API_KEY")
            archive.parent.mkdir(parents=True, exist_ok=True)
            source = SuperteamOpportunitySource(SuperteamHTTP(secret), RawArchive(archive), clock)
        services = compose_operator(
            Path(args.db),
            Reference(args.ledger),
            Reference(actor or "read-only"),
            clock,
            source,
            create_workspace=args.command == "workspace" and args.workspace_action == "init",
        )
        return run_command(args, services, sys.stdout)
    except PortError as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "code": error.code.value,
                    "message": str(error),
                    "note": "Inspect workspace state before retrying.",
                }
            )
        )
        return 1
    except DomainError as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "code": error.code.value,
                    "field": error.field,
                    "message": str(error),
                }
            )
        )
        return 2
    except ValueError as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "code": "invalid_configuration",
                    "message": str(error),
                }
            )
        )
        return 2
    except OSError:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "code": "local_workspace_io",
                    "message": "Cannot access the local workspace or archive path.",
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

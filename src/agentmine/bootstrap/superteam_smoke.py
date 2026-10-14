"""Explicit read-only smoke probe. Importing or ordinary startup never performs I/O."""

import argparse
import json
import os
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from agentmine.application.contracts.opportunities import DiscoveryRequest
from agentmine.application.errors import PortError
from agentmine.infrastructure.marketplaces.raw_archive import RawArchive
from agentmine.infrastructure.marketplaces.superteam import SuperteamOpportunitySource
from agentmine.infrastructure.marketplaces.superteam_http import SuperteamHTTP, SuperteamReadError


class _UTCClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Explicit read-only Superteam contract smoke probe"
    )
    parser.add_argument(
        "--live", action="store_true", help="Explicitly enable production GET calls"
    )
    parser.add_argument("--limit", type=int, default=1, help="Raw listing window, 1 through 50")
    parser.add_argument("--archive", type=Path, default=Path(".tmp/superteam-smoke.sqlite3"))
    args = parser.parse_args(argv)
    if not args.live:
        parser.error("--live is required; no production API call was made")
    if not 1 <= args.limit <= 50:
        parser.error("--limit must be between 1 and 50")
    secret = os.environ.get("AGENTMINE_SUPERTEAM_API_KEY", "")
    if not secret:
        print(json.dumps({"status": "failed", "reason": "missing_api_key"}))
        return 2
    try:
        transport = SuperteamHTTP(secret)
        archive_path: Path = args.archive
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        source = SuperteamOpportunitySource(transport, RawArchive(archive_path), _UTCClock())
        report = source.inspect(DiscoveryRequest(args.limit))
    except SuperteamReadError as error:
        print(
            json.dumps(
                {"status": "failed", "reason": error.reason.value, "http_status": error.http_status}
            )
        )
        return 1
    except PortError as error:
        print(json.dumps({"status": "failed", "reason": error.code.value}))
        return 1
    except (OSError, ValueError):
        print(json.dumps({"status": "failed", "reason": "invalid_configuration_or_archive"}))
        return 2
    print(
        json.dumps(
            {
                "status": "read_succeeded",
                "unique_listings": len(report.items),
                "normalized": len(report.batch.observations),
                "quarantined": sum(item.observation is None for item in report.items),
                "duplicates": report.duplicate_count,
                "pagination_unverified": report.batch.continuation is not None,
                "normalization_issues": sorted(
                    {issue.value for item in report.items for issue in item.issues}
                ),
                "list_capture": report.list_capture.value,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

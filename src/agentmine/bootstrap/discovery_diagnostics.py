"""Offline composition: no environment, marketplace HTTP, LLM or workspace."""

import sys
from collections.abc import Sequence
from pathlib import Path

from agentmine.application.use_cases.discovery_diagnostics import InspectDiscoveryDiagnostics
from agentmine.infrastructure.marketplaces.discovery_diagnostics import ArchiveDiscoveryDiagnostics
from agentmine.infrastructure.marketplaces.raw_archive import RawArchive
from agentmine.presentation.discovery_diagnostics_cli import parser, run_diagnostics


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    use_case = InspectDiscoveryDiagnostics(
        ArchiveDiscoveryDiagnostics(RawArchive(Path(args.archive)))
    )
    return run_diagnostics(args, use_case, sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())

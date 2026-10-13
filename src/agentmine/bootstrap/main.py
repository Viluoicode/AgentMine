"""Startup entry point; adapter wiring will be added in later milestones."""

import os

from agentmine.bootstrap.config import load_settings


def main() -> None:
    """Validate startup configuration without initiating work or external I/O."""
    load_settings(os.environ)


if __name__ == "__main__":
    main()

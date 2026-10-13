import os
import subprocess
import sys


def test_bootstrap_starts_with_valid_configuration() -> None:
    environment = dict(os.environ)
    environment.update(AGENTMINE_ENVIRONMENT="test", AGENTMINE_LOG_LEVEL="INFO")
    result = subprocess.run(
        [sys.executable, "-m", "agentmine.bootstrap.main"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""

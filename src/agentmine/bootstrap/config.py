"""Explicit startup configuration, independent of business logic."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

Environment = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class ConfigurationError(ValueError):
    """Invalid startup setting with a machine-readable code and key."""

    code = "invalid_configuration"

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"Invalid configuration for {key}")


@dataclass(frozen=True, slots=True)
class Settings:
    """Immutable settings; no implicit environment reads or cached globals."""

    environment: Environment = "development"
    log_level: LogLevel = "INFO"

    def __post_init__(self) -> None:
        if self.environment not in ("development", "test", "production"):
            raise ConfigurationError("AGENTMINE_ENVIRONMENT")
        if self.log_level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            raise ConfigurationError("AGENTMINE_LOG_LEVEL")


def load_settings(environment: Mapping[str, str]) -> Settings:
    """Read only the supplied mapping; Settings validates values at runtime."""
    return Settings(
        environment=cast(Environment, environment.get("AGENTMINE_ENVIRONMENT", "development")),
        log_level=cast(LogLevel, environment.get("AGENTMINE_LOG_LEVEL", "INFO")),
    )

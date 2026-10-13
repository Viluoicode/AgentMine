import pytest

from agentmine.bootstrap.config import ConfigurationError, Settings, load_settings


def test_defaults_need_no_external_configuration() -> None:
    assert load_settings({}) == Settings(environment="development", log_level="INFO")


def test_explicit_configuration() -> None:
    settings = load_settings({"AGENTMINE_ENVIRONMENT": "test", "AGENTMINE_LOG_LEVEL": "DEBUG"})
    assert settings.environment == "test"
    assert settings.log_level == "DEBUG"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("AGENTMINE_ENVIRONMENT", "staging"),
        ("AGENTMINE_ENVIRONMENT", ""),
        ("AGENTMINE_LOG_LEVEL", "verbose"),
        ("AGENTMINE_LOG_LEVEL", ""),
    ],
)
def test_invalid_configuration_has_structured_error(key: str, value: str) -> None:
    with pytest.raises(ConfigurationError) as error:
        load_settings({key: value})
    assert error.value.code == "invalid_configuration"
    assert error.value.key == key
    assert str(error.value) == f"Invalid configuration for {key}"


def test_configuration_is_not_cached() -> None:
    values = {"AGENTMINE_ENVIRONMENT": "test"}
    first = load_settings(values)
    values["AGENTMINE_ENVIRONMENT"] = "production"
    assert first.environment == "test"
    assert load_settings(values).environment == "production"

"""Agent header settings parser, accessor, and config parity coverage."""

from __future__ import annotations

import pytest
import yaml
from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError

from sase.ace.tui.agent_header_settings import (
    DEFAULT_AGENT_HEADER_SETTINGS,
    AgentHeaderSettings,
    agent_header_settings_for,
    parse_agent_header_settings,
)
from tests._config_schema_helpers import REPO_ROOT, schema


def _parse(value: object) -> AgentHeaderSettings:
    return parse_agent_header_settings({"agent_header": {"collapsed_max_share": value}})


def test_default_share_is_a_third_of_the_column() -> None:
    assert DEFAULT_AGENT_HEADER_SETTINGS.collapsed_max_share == 0.35


def test_missing_or_malformed_blocks_use_the_default() -> None:
    assert parse_agent_header_settings({}) == DEFAULT_AGENT_HEADER_SETTINGS
    assert parse_agent_header_settings(None) == DEFAULT_AGENT_HEADER_SETTINGS
    assert parse_agent_header_settings("nope") == DEFAULT_AGENT_HEADER_SETTINGS
    assert (
        parse_agent_header_settings({"agent_header": True})
        == DEFAULT_AGENT_HEADER_SETTINGS
    )
    assert (
        parse_agent_header_settings({"agent_header": {}})
        == DEFAULT_AGENT_HEADER_SETTINGS
    )


@pytest.mark.parametrize(
    "value",
    [True, False, "0.4", None, [], -1, -0.01, 0.61, 1, 2.5, float("nan"), float("inf")],
)
def test_invalid_shares_fall_back_to_the_default(value: object) -> None:
    assert _parse(value) == DEFAULT_AGENT_HEADER_SETTINGS


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, 0.0), (0.0, 0.0), (0.25, 0.25), (0.6, 0.6), (0.35, 0.35)],
)
def test_valid_shares_are_kept_and_ints_coerce_to_float(
    value: float, expected: float
) -> None:
    settings = _parse(value)
    assert settings == AgentHeaderSettings(collapsed_max_share=expected)
    assert isinstance(settings.collapsed_max_share, float)


def test_settings_helper_fails_open() -> None:
    assert agent_header_settings_for(object()) == DEFAULT_AGENT_HEADER_SETTINGS

    class _App:
        _agent_header_settings = AgentHeaderSettings(collapsed_max_share=0.0)

    class _Widget:
        app = _App()

    assert agent_header_settings_for(_Widget()).collapsed_max_share == 0.0

    class _BadApp:
        _agent_header_settings = "not settings"

    class _BadWidget:
        app = _BadApp()

    assert agent_header_settings_for(_BadWidget()) == DEFAULT_AGENT_HEADER_SETTINGS


def test_config_schema_agent_header_parity() -> None:
    public_schema = schema()
    validator = Draft7Validator(public_schema)
    agent_header = public_schema["properties"]["ace"]["properties"]["agent_header"]
    default_config = yaml.safe_load(
        (REPO_ROOT / "src/sase/default_config.yml").read_text(encoding="utf-8")
    )
    share = agent_header["properties"]["collapsed_max_share"]

    assert default_config["ace"]["agent_header"] == {"collapsed_max_share": 0.35}
    assert agent_header["additionalProperties"] is False
    assert share["type"] == "number"
    assert share["default"] == DEFAULT_AGENT_HEADER_SETTINGS.collapsed_max_share
    assert share["minimum"] == 0
    assert share["maximum"] == 0.6
    for valid in (0, 0.35, 0.6):
        validator.validate({"ace": {"agent_header": {"collapsed_max_share": valid}}})
    for invalid in (
        {"collapsed_max_share": "0.35"},
        {"collapsed_max_share": -0.1},
        {"collapsed_max_share": 0.61},
        {"collapsed_max_share": True},
        {"unknown": True},
    ):
        with pytest.raises(ValidationError):
            validator.validate({"ace": {"agent_header": invalid}})

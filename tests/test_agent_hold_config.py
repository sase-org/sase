"""Tests for `sase agent hold` TTL configuration accessors."""

from __future__ import annotations

from unittest.mock import patch

from sase.config._settings import (
    DEFAULT_AGENT_HOLD_DEFAULT_TTL_SECONDS,
    DEFAULT_AGENT_HOLD_MAX_TTL_SECONDS,
    get_agent_hold_default_ttl_seconds,
    get_agent_hold_max_ttl_seconds,
)


def test_default_ttl_falls_back_when_unset() -> None:
    with patch("sase.config.core.load_merged_config", return_value={}):
        assert (
            get_agent_hold_default_ttl_seconds()
            == DEFAULT_AGENT_HOLD_DEFAULT_TTL_SECONDS
        )


def test_max_ttl_falls_back_when_unset() -> None:
    with patch("sase.config.core.load_merged_config", return_value={}):
        assert get_agent_hold_max_ttl_seconds() == DEFAULT_AGENT_HOLD_MAX_TTL_SECONDS


def test_default_ttl_parses_configured_duration_string() -> None:
    with patch(
        "sase.config.core.load_merged_config",
        return_value={"agent_hold_default_ttl": "30m"},
    ):
        assert get_agent_hold_default_ttl_seconds() == 1800.0


def test_max_ttl_parses_configured_duration_string() -> None:
    with patch(
        "sase.config.core.load_merged_config",
        return_value={"agent_hold_max_ttl": "1h"},
    ):
        assert get_agent_hold_max_ttl_seconds() == 3600.0


def test_default_ttl_falls_back_on_non_string_value() -> None:
    with patch(
        "sase.config.core.load_merged_config",
        return_value={"agent_hold_default_ttl": 7200},
    ):
        assert (
            get_agent_hold_default_ttl_seconds()
            == DEFAULT_AGENT_HOLD_DEFAULT_TTL_SECONDS
        )


def test_default_ttl_falls_back_on_unparsable_value() -> None:
    with patch(
        "sase.config.core.load_merged_config",
        return_value={"agent_hold_default_ttl": "not-a-duration"},
    ):
        assert (
            get_agent_hold_default_ttl_seconds()
            == DEFAULT_AGENT_HOLD_DEFAULT_TTL_SECONDS
        )


def test_default_ttl_falls_back_on_zero_value() -> None:
    with patch(
        "sase.config.core.load_merged_config",
        return_value={"agent_hold_default_ttl": "0s"},
    ):
        assert (
            get_agent_hold_default_ttl_seconds()
            == DEFAULT_AGENT_HOLD_DEFAULT_TTL_SECONDS
        )

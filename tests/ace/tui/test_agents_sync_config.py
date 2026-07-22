"""ACE agents-repository synchronization configuration tests."""

from __future__ import annotations

import pytest

from sase.ace.tui.actions._agents_sync_config import parse_agents_sync_config


def test_agents_sync_config_defaults() -> None:
    config = parse_agents_sync_config(None)

    assert config.check_interval_seconds == 600.0
    assert config.recompute_interval_seconds == 1800.0
    assert config.indicator is True


def test_agents_sync_config_overrides() -> None:
    config = parse_agents_sync_config(
        {
            "check_interval_minutes": 2.5,
            "recompute_interval_minutes": 12,
            "indicator": False,
        }
    )

    assert config.check_interval_seconds == 150.0
    assert config.recompute_interval_seconds == 720.0
    assert config.indicator is False


@pytest.mark.parametrize(
    "value",
    [None, "10", True, False, 0, -1, float("nan"), float("inf"), 10**400],
)
def test_agents_sync_config_rejects_invalid_intervals(value: object) -> None:
    config = parse_agents_sync_config(
        {
            "check_interval_minutes": value,
            "recompute_interval_minutes": value,
        }
    )

    assert config.check_interval_seconds == 600.0
    assert config.recompute_interval_seconds == 1800.0

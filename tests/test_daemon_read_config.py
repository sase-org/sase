"""Tests for daemon read rollout configuration."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from sase.daemon.read_config import (
    DEFAULT_ENABLED_SURFACE_GROUPS,
    daemon_fallback_diagnostics_enabled,
    daemon_read_disable_reason,
    daemon_read_surface_enabled,
)


def test_default_enabled_surface_groups_match_phase_5i_rollout() -> None:
    assert DEFAULT_ENABLED_SURFACE_GROUPS == {
        "changespecs",
        "notifications",
        "agents",
        "beads",
        "catalogs",
    }
    assert daemon_read_surface_enabled("notification_list") is True
    assert daemon_read_surface_enabled("file_history") is True
    assert daemon_read_surface_enabled("ace_agents") is False
    assert daemon_read_surface_enabled("ace_archive_search") is False


def test_surface_config_controls_logical_group() -> None:
    config = {
        "daemon": {
            "reads": {
                "enabled": True,
                "surfaces": {
                    "notifications": False,
                    "ace_agents": True,
                    "ace_archive_search": True,
                },
            }
        }
    }

    with patch("sase.daemon.read_config.load_merged_config", return_value=config):
        assert daemon_read_surface_enabled("notification_list") is False
        assert daemon_read_surface_enabled("notification_counts") is False
        assert daemon_read_surface_enabled("ace_agents") is True
        assert daemon_read_surface_enabled("ace_archive_search") is True


def test_surface_env_override_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_DAEMON_NOTIFICATIONS_READS", "0")
    with patch("sase.daemon.read_config.load_merged_config", return_value={}):
        assert daemon_read_surface_enabled("notification_list") is False


def test_fallback_diagnostics_flag_can_be_enabled() -> None:
    config = {"daemon": {"reads": {"fallback_diagnostics": True}}}

    with patch("sase.daemon.read_config.load_merged_config", return_value=config):
        assert daemon_fallback_diagnostics_enabled() is True


def test_disable_reason_reports_surface_disable() -> None:
    config = {"daemon": {"reads": {"surfaces": {"catalogs": False}}}}

    with patch("sase.daemon.read_config.load_merged_config", return_value=config):
        reason = daemon_read_disable_reason("file_history")

    assert reason is not None
    assert reason.reason == "surface_disabled"
    assert reason.message == "daemon reads disabled for catalogs"

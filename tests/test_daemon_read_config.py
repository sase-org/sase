"""Tests for daemon read rollout configuration."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from sase.daemon.read_config import (
    ACE_DAEMON_SURFACE_GROUPS,
    DEFAULT_ENABLED_SURFACE_GROUPS,
    _daemon_m1_read_through_enabled,
    daemon_read_disable_reason,
    daemon_read_surface_enabled,
    daemon_fallback_diagnostics_enabled,
)


def test_default_enabled_surface_groups_keep_ace_daemon_reads_opt_in() -> None:
    assert DEFAULT_ENABLED_SURFACE_GROUPS == {
        "changespecs",
        "notifications",
        "agents",
        "beads",
        "catalogs",
        "ace_notifications",
    }
    assert daemon_read_surface_enabled("notification_list") is True
    assert daemon_read_surface_enabled("file_history") is True
    assert daemon_read_surface_enabled("ace_notification_list") is True
    for surface in ACE_DAEMON_SURFACE_GROUPS:
        expected = surface == "ace_notifications"
        assert daemon_read_surface_enabled(surface) is expected


def test_surface_config_controls_logical_group() -> None:
    config = {
        "daemon": {
            "reads": {
                "enabled": True,
                "surfaces": {
                    "notifications": False,
                    "ace_agents": True,
                    "ace_notifications": False,
                    "ace_archive_search": True,
                },
            }
        }
    }

    with patch("sase.daemon.read_config.load_merged_config", return_value=config):
        assert daemon_read_surface_enabled("notification_list") is False
        assert daemon_read_surface_enabled("notification_counts") is False
        assert daemon_read_surface_enabled("ace_notification_pending_actions") is False
        assert daemon_read_surface_enabled("ace_agents") is True
        assert daemon_read_surface_enabled("ace_archive_search") is True
        assert daemon_read_surface_enabled("ace_agent_active") is True


def test_surface_env_override_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_DAEMON_NOTIFICATIONS_READS", "0")
    with patch("sase.daemon.read_config.load_merged_config", return_value={}):
        assert daemon_read_surface_enabled("notification_list") is False


def test_fallback_diagnostics_flag_can_be_enabled() -> None:
    config = {"daemon": {"reads": {"fallback_diagnostics": True}}}

    with patch("sase.daemon.read_config.load_merged_config", return_value=config):
        assert daemon_fallback_diagnostics_enabled() is True


def test_m1_read_rollout_stays_enabled_when_m0_is_disabled() -> None:
    config = {
        "daemon": {
            "rollout": {
                "milestones": {
                    "m0_shadow_indexing": False,
                    "m1_read_through": True,
                }
            },
            "reads": {"enabled": True, "surfaces": {"notifications": True}},
        }
    }

    with patch("sase.daemon.read_config.load_merged_config", return_value=config):
        assert _daemon_m1_read_through_enabled() is True
        assert daemon_read_disable_reason("notification_list") is None


def test_m1_rollout_disable_routes_reads_direct() -> None:
    config = {
        "daemon": {
            "rollout": {"milestones": {"m1_read_through": False}},
            "reads": {"enabled": True, "surfaces": {"notifications": True}},
        }
    }

    with patch("sase.daemon.read_config.load_merged_config", return_value=config):
        reason = daemon_read_disable_reason("notification_list")

    assert reason is not None
    assert reason.reason == "m1_read_through_disabled"


def test_disable_reason_reports_surface_disable() -> None:
    config = {"daemon": {"reads": {"surfaces": {"catalogs": False}}}}

    with patch("sase.daemon.read_config.load_merged_config", return_value=config):
        reason = daemon_read_disable_reason("file_history")

    assert reason is not None
    assert reason.reason == "surface_disabled"
    assert reason.message == "daemon reads disabled for catalogs"

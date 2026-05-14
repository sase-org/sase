"""Tests for local daemon read facade fallback routing."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.daemon.client import LocalDaemonClient
from sase.daemon.read_facade import read_or_fallback

from tests._daemon_read_facade_helpers import (
    FakeDaemonTransport,
    _notification_page,
    _rpc_error,
)


def test_read_or_fallback_uses_daemon_when_capability_is_available() -> None:
    transport = FakeDaemonTransport(
        capabilities=["notifications.read"],
        reads={"notification_list": [_notification_page([{"id": "daemon"}])]},
    )
    client = LocalDaemonClient(transport=transport)

    result = read_or_fallback(
        "notification_list",
        client=client,
        daemon_loader=lambda daemon: daemon.notification_list(),
        direct_loader=lambda: _notification_page([{"id": "direct"}]),
    )

    assert result.used_daemon is True
    assert result.value["notifications"] == [{"id": "daemon"}]
    assert result.debug_json()["daemon"]["fallback_reason"] is None


def test_read_or_fallback_honors_environment_disable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_NO_DAEMON", "1")
    transport = FakeDaemonTransport(capabilities=["notifications.read"])

    result = read_or_fallback(
        "notification_list",
        client=LocalDaemonClient(transport=transport),
        daemon_loader=lambda daemon: daemon.notification_list(),
        direct_loader=lambda: "direct",
    )

    assert result.value == "direct"
    assert result.used_daemon is False
    assert result.fallback_reason == "daemon_disabled"
    assert transport.requests == []


def test_read_or_fallback_honors_global_config_disable() -> None:
    transport = FakeDaemonTransport(capabilities=["notifications.read"])

    with patch(
        "sase.daemon.read_config.load_merged_config",
        return_value={"daemon": {"reads": {"enabled": False}}},
    ):
        result = read_or_fallback(
            "notification_list",
            client=LocalDaemonClient(transport=transport),
            daemon_loader=lambda daemon: daemon.notification_list(),
            direct_loader=lambda: "direct",
        )

    assert result.value == "direct"
    assert result.used_daemon is False
    assert result.fallback_reason == "daemon_reads_disabled"
    assert transport.requests == []


def test_read_or_fallback_honors_m1_rollout_disable() -> None:
    transport = FakeDaemonTransport(capabilities=["notifications.read"])

    with patch(
        "sase.daemon.read_config.load_merged_config",
        return_value={
            "daemon": {
                "rollout": {"milestones": {"m1_read_through": False}},
                "reads": {"enabled": True},
            }
        },
    ):
        result = read_or_fallback(
            "notification_list",
            client=LocalDaemonClient(transport=transport),
            daemon_loader=lambda daemon: daemon.notification_list(),
            direct_loader=lambda: "direct",
        )

    assert result.value == "direct"
    assert result.used_daemon is False
    assert result.fallback_reason == "m1_read_through_disabled"
    assert transport.requests == []


def test_read_or_fallback_honors_force_direct_config() -> None:
    transport = FakeDaemonTransport(capabilities=["notifications.read"])

    with patch(
        "sase.daemon.read_config.load_merged_config",
        return_value={"daemon": {"reads": {"force_direct": True}}},
    ):
        result = read_or_fallback(
            "notification_list",
            client=LocalDaemonClient(transport=transport),
            daemon_loader=lambda daemon: daemon.notification_list(),
            direct_loader=lambda: "direct",
        )

    assert result.value == "direct"
    assert result.used_daemon is False
    assert result.fallback_reason == "force_direct"
    assert transport.requests == []


def test_read_or_fallback_honors_surface_disable_config() -> None:
    transport = FakeDaemonTransport(capabilities=["notifications.read"])

    with patch(
        "sase.daemon.read_config.load_merged_config",
        return_value={
            "daemon": {
                "reads": {
                    "enabled": True,
                    "surfaces": {"notifications": False},
                }
            }
        },
    ):
        result = read_or_fallback(
            "notification_list",
            client=LocalDaemonClient(transport=transport),
            daemon_loader=lambda daemon: daemon.notification_list(),
            direct_loader=lambda: "direct",
        )

    assert result.value == "direct"
    assert result.used_daemon is False
    assert result.fallback_reason == "surface_disabled"
    assert transport.requests == []


@pytest.mark.parametrize(
    ("error_code", "expected_reason"),
    [
        ("unsupported_capability", "unsupported_capability"),
        ("projection_degraded", "projection_degraded"),
        ("cursor_expired", "cursor_expired"),
        ("snapshot_expired", "snapshot_expired"),
    ],
)
def test_read_or_fallback_converts_daemon_read_errors_to_direct_loader(
    error_code: str,
    expected_reason: str,
) -> None:
    transport = FakeDaemonTransport(
        capabilities=["notifications.read"],
        read_errors={"notification_list": _rpc_error(error_code)},
    )

    result = read_or_fallback(
        "notification_list",
        client=LocalDaemonClient(transport=transport),
        daemon_loader=lambda daemon: daemon.notification_list(),
        direct_loader=lambda: "direct",
    )

    assert result.value == "direct"
    assert result.used_daemon is False
    assert result.fallback_reason == expected_reason


def test_read_or_fallback_uses_direct_loader_when_daemon_unavailable() -> None:
    result = read_or_fallback(
        "notification_list",
        client=LocalDaemonClient(Path("/tmp/sase-missing-daemon.sock"), timeout=0.01),
        daemon_loader=lambda daemon: daemon.notification_list(),
        direct_loader=lambda: "direct",
    )

    assert result.value == "direct"
    assert result.used_daemon is False
    assert result.fallback_reason == "daemon_not_running"


@pytest.mark.parametrize(
    ("response", "expected_reason"),
    [
        (
            {
                "schema_version": 2,
                "request_id": "req_test",
                "snapshot_id": None,
                "payload": {"type": "capabilities", "data": {}},
            },
            "unsupported_server_version",
        ),
        (
            {
                "schema_version": 1,
                "request_id": "req_test",
                "snapshot_id": None,
                "payload": {
                    "type": "capabilities",
                    "data": {
                        "schema_version": 1,
                        "capabilities": ["notifications.read"],
                        "compatibility": {
                            "supported_client_schema_range": {"min": 1, "max": 1},
                            "projection_read_schema_version": 99,
                            "projection_write_schema_version": 1,
                        },
                    },
                },
            },
            "projection_schema_mismatch",
        ),
    ],
)
def test_read_or_fallback_converts_compatibility_errors_to_direct_loader(
    response: dict[str, Any],
    expected_reason: str,
) -> None:
    class CompatibilityTransport:
        requests: list[dict[str, Any]]

        def __init__(self) -> None:
            self.requests = []

        def request(self, envelope: dict[str, Any]) -> dict[str, Any]:
            self.requests.append(envelope["payload"])
            return response

    transport = CompatibilityTransport()

    result = read_or_fallback(
        "notification_list",
        client=LocalDaemonClient(transport=transport),
        daemon_loader=lambda daemon: daemon.notification_list(),
        direct_loader=lambda: "direct",
    )

    assert result.value == "direct"
    assert result.used_daemon is False
    assert result.fallback_reason == expected_reason
    assert [request["type"] for request in transport.requests] == ["capabilities"]


def test_read_or_fallback_checks_capabilities_before_routing() -> None:
    transport = FakeDaemonTransport(capabilities=["health.read"])

    result = read_or_fallback(
        "notification_list",
        client=LocalDaemonClient(transport=transport),
        daemon_loader=lambda daemon: daemon.notification_list(),
        direct_loader=lambda: "direct",
    )

    assert result.value == "direct"
    assert result.fallback_reason == "unsupported_capability"
    assert [request["type"] for request in transport.requests] == ["capabilities"]


def test_ace_read_surface_uses_ace_gate_and_underlying_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_DAEMON_ACE_NOTIFICATIONS_READS", "1")
    transport = FakeDaemonTransport(
        capabilities=["notifications.read"],
        reads={"notification_counts": [{"priority": 1}]},
    )

    result = read_or_fallback(
        "ace_notification_counts",
        client=LocalDaemonClient(transport=transport),
        daemon_loader=lambda daemon: daemon.notification_counts(),
        direct_loader=lambda: {"priority": 0},
    )

    assert result.used_daemon is True
    assert result.surface == "ace_notification_counts"
    assert result.value == {"priority": 1}
    assert [request["type"] for request in transport.requests] == [
        "capabilities",
        "read",
    ]
    assert transport.requests[-1]["data"]["surface"] == "notification_counts"


def test_ace_agent_read_surface_uses_ace_gate_and_underlying_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_DAEMON_ACE_AGENTS_READS", "1")
    transport = FakeDaemonTransport(
        capabilities=["agents.read"],
        reads={"agent_recent": [{"agents": []}]},
    )

    result = read_or_fallback(
        "ace_agent_recent",
        client=LocalDaemonClient(transport=transport),
        daemon_loader=lambda daemon: daemon.agent_recent(project_id="demo"),
        direct_loader=lambda: {"agents": ["direct"]},
    )

    assert result.used_daemon is True
    assert result.surface == "ace_agent_recent"
    assert result.value == {"agents": []}
    assert [request["type"] for request in transport.requests] == [
        "capabilities",
        "read",
    ]
    assert transport.requests[-1]["data"]["surface"] == "agent_recent"


@pytest.mark.parametrize(
    ("surface", "capability", "daemon_loader", "read_surface"),
    [
        (
            "changespec_list",
            "changespecs.read",
            lambda daemon: daemon.changespec_list(),
            "changespec_list",
        ),
        (
            "agent_active",
            "agents.read",
            lambda daemon: daemon.agent_active(project_id="demo"),
            "agent_active",
        ),
        (
            "bead_list",
            "beads.read",
            lambda daemon: daemon.bead_list(project_id="demo"),
            "bead_list",
        ),
        (
            "file_history",
            "catalogs.read",
            lambda daemon: daemon.file_history(project_id="demo"),
            "file_history",
        ),
        (
            "notification_list",
            "notifications.read",
            lambda daemon: daemon.notification_list(),
            "notification_list",
        ),
    ],
)
def test_default_enabled_m1_read_surfaces_can_use_daemon(
    surface: str,
    capability: str,
    daemon_loader: Any,
    read_surface: str,
) -> None:
    transport = FakeDaemonTransport(
        capabilities=[capability],
        reads={read_surface: [_notification_page([])]},
    )

    result = read_or_fallback(
        surface,
        client=LocalDaemonClient(transport=transport),
        daemon_loader=daemon_loader,
        direct_loader=lambda: {"direct": True},
    )

    assert result.used_daemon is True
    assert result.fallback_reason is None
    assert [request["type"] for request in transport.requests] == [
        "capabilities",
        "read",
    ]
    assert transport.requests[-1]["data"]["surface"] == read_surface

"""Tests for local daemon read facades and fallback routing."""

from __future__ import annotations

import dataclasses
import shutil
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.bead.project import BeadProject
from sase.daemon.client import LocalDaemonClient
from sase.daemon.read_facade import read_or_fallback
from sase.daemon.read_models import (
    bead_list_from_dict,
    notification_list_from_dict,
)
from sase.notifications import store as notification_store

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "rust_daemon_epic1" / "sources"


class FakeDaemonTransport:
    def __init__(
        self,
        *,
        capabilities: list[str] | None = None,
        reads: dict[str, list[dict[str, Any]]] | None = None,
        read_errors: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.capabilities = capabilities or []
        self.reads = reads or {}
        self.read_errors = read_errors or {}
        self.requests: list[dict[str, Any]] = []

    def request(self, envelope: dict[str, Any]) -> dict[str, Any]:
        payload = envelope["payload"]
        self.requests.append(payload)
        payload_type = payload["type"]
        if payload_type == "capabilities":
            return _response(
                "capabilities", {"schema_version": 1, "capabilities": self.capabilities}
            )
        if payload_type == "read":
            surface = payload["data"]["surface"]
            if surface in self.read_errors:
                return _error_response(self.read_errors[surface])
            data = self.reads[surface].pop(0)
            return _response("read", {"surface": surface, "data": data})
        raise AssertionError(f"unexpected fake daemon request: {payload_type}")


def test_all_phase_5a_read_client_methods_emit_contract_surfaces() -> None:
    calls = [
        ("changespec_list", lambda client: client.changespec_list()),
        ("changespec_search", lambda client: client.changespec_search(query="demo")),
        (
            "changespec_detail",
            lambda client: client.changespec_detail("changespec:demo:one"),
        ),
        ("agent_active", lambda client: client.agent_active(project_id="demo")),
        ("agent_recent", lambda client: client.agent_recent(project_id="demo")),
        ("agent_archive", lambda client: client.agent_archive(project_id="demo")),
        (
            "agent_search",
            lambda client: client.agent_search(project_id="demo", query="run"),
        ),
        (
            "agent_detail",
            lambda client: client.agent_detail(project_id="demo", agent_id="run-1"),
        ),
        ("notification_list", lambda client: client.notification_list()),
        ("notification_detail", lambda client: client.notification_detail("notif-1")),
        ("notification_counts", lambda client: client.notification_counts()),
        (
            "notification_pending_actions",
            lambda client: client.notification_pending_actions(),
        ),
        ("bead_list", lambda client: client.bead_list(project_id="demo")),
        ("bead_ready", lambda client: client.bead_ready(project_id="demo")),
        ("bead_blocked", lambda client: client.bead_blocked(project_id="demo")),
        (
            "bead_show",
            lambda client: client.bead_show(project_id="demo", bead_id="demo-1"),
        ),
        ("bead_stats", lambda client: client.bead_stats(project_id="demo")),
        ("xprompt_catalog", lambda client: client.xprompt_catalog(project_id="demo")),
        ("editor_catalog", lambda client: client.editor_catalog(project_id="demo")),
        ("snippet_catalog", lambda client: client.snippet_catalog(project_id="demo")),
        ("file_history", lambda client: client.file_history(project_id="demo")),
    ]
    reads = {surface: [{}] for surface, _call in calls}
    transport = FakeDaemonTransport(reads=reads)
    client = LocalDaemonClient(transport=transport)

    for expected_surface, call in calls:
        assert call(client) == {}
        payload = transport.requests[-1]
        assert payload["type"] == "read"
        assert payload["data"]["surface"] == expected_surface


def test_notification_list_request_matches_contract_shape() -> None:
    transport = FakeDaemonTransport(
        reads={"notification_list": [_notification_page([])]}
    )
    client = LocalDaemonClient(transport=transport)

    client.notification_list(
        include_dismissed=True,
        query="plan",
        sender="mentor",
        unread=False,
        limit=7,
        cursor="cur-1",
    )

    assert transport.requests[-1] == {
        "type": "read",
        "data": {
            "surface": "notification_list",
            "data": {
                "schema_version": 1,
                "page": {"schema_version": 1, "limit": 7, "cursor": "cur-1"},
                "include_dismissed": True,
                "query": "plan",
                "sender": "mentor",
                "unread": False,
            },
        },
    }


def test_iter_read_items_follows_next_cursor() -> None:
    transport = FakeDaemonTransport(
        reads={
            "notification_list": [
                _notification_page([{"id": "one"}], next_cursor="cur-2"),
                _notification_page([{"id": "two"}]),
            ]
        }
    )
    client = LocalDaemonClient(transport=transport)

    items = list(
        client.iter_read_items(
            "notification_list",
            lambda cursor: {
                "schema_version": 1,
                "page": {"schema_version": 1, "limit": 1, "cursor": cursor},
            },
            items_key="notifications",
        )
    )

    assert [item["id"] for item in items] == ["one", "two"]
    cursors = [
        request["data"]["data"]["page"]["cursor"] for request in transport.requests
    ]
    assert cursors == [None, "cur-2"]


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


def test_notification_read_model_matches_direct_fixture_loader(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    notification_store._invalidate_load_cache()
    fixture_path = tmp_path / "notifications.jsonl"
    shutil.copy2(FIXTURE_ROOT / "notifications" / "notifications.jsonl", fixture_path)
    monkeypatch.setattr(notification_store, "NOTIFICATIONS_FILE", str(fixture_path))
    direct = notification_store.load_notifications(include_dismissed=False)

    daemon = notification_list_from_dict(
        _notification_page([dataclasses.asdict(item) for item in direct])
    )

    assert [item.id for item in daemon.notifications] == [item.id for item in direct]


def test_bead_read_model_matches_direct_fixture_loader(tmp_path: Path) -> None:
    shutil.copytree(FIXTURE_ROOT / "beads", tmp_path / "sdd" / "beads")
    with BeadProject(tmp_path) as project:
        direct = project.list_issues()

    daemon = bead_list_from_dict(_bead_page([_issue_wire(item) for item in direct]))

    assert [item.id for item in daemon.issues] == [item.id for item in direct]


def _response(payload_type: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "request_id": "req_test",
        "snapshot_id": None,
        "payload": {"type": payload_type, "data": data},
    }


def _error_response(error: dict[str, Any]) -> dict[str, Any]:
    return _response("error", error)


def _rpc_error(code: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "code": code,
        "message": code.replace("_", " "),
        "retryable": False,
        "target": "payload",
        "details": {"capability": "notifications.read"},
        "fallback": {"available": True, "reason": code, "message": "use direct"},
    }


def _notification_page(
    notifications: list[dict[str, Any]],
    *,
    next_cursor: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "snapshot": {"schema_version": 1, "snapshot_id": "snap-notifications"},
        "page": {"schema_version": 1, "next_cursor": next_cursor},
        "notifications": notifications,
        "counts": {"total": len(notifications)},
        "bounded": {
            "schema_version": 1,
            "max_payload_bytes": 1_048_576,
            "truncated": False,
        },
    }


def _bead_page(issues: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "snapshot": {"schema_version": 1, "snapshot_id": "snap-beads"},
        "page": {"schema_version": 1, "next_cursor": None},
        "issues": issues,
        "bounded": {
            "schema_version": 1,
            "max_payload_bytes": 1_048_576,
            "truncated": False,
        },
    }


def _issue_wire(issue: Any) -> dict[str, Any]:
    data = dataclasses.asdict(issue)
    data["status"] = issue.status.value
    data["issue_type"] = issue.issue_type.value
    data["tier"] = None if issue.tier is None else issue.tier.value
    return data

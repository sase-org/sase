"""Tests for daemon-backed ACE notification provider reads."""

from __future__ import annotations

import dataclasses
from typing import Any
from unittest.mock import patch

from sase.ace.tui.actions.agents._notification_provider import notification_row_handle
from sase.daemon.client import LocalDaemonClient

from tests._notification_toasts_helpers import _FakeApp, _make


class _FakeDaemonTransport:
    def __init__(self, reads: dict[str, list[dict[str, Any]]]) -> None:
        self.reads = reads
        self.requests: list[dict[str, Any]] = []

    def request(self, envelope: dict[str, Any]) -> dict[str, Any]:
        payload = envelope["payload"]
        self.requests.append(payload)
        if payload["type"] == "capabilities":
            return _response(
                "capabilities",
                {"schema_version": 1, "capabilities": ["notifications.read"]},
            )
        if payload["type"] == "read":
            surface = payload["data"]["surface"]
            return _response(
                "read", {"surface": surface, "data": self.reads[surface].pop(0)}
            )
        raise AssertionError(f"unexpected request: {payload}")


def test_ace_notification_refresh_uses_daemon_without_jsonl_snapshot_read() -> None:
    notification = _make(action="JumpToAgent", notes=["done"])
    transport = _FakeDaemonTransport(
        {
            "notification_list": [
                _notification_page([dataclasses.asdict(notification)])
            ],
            "notification_counts": [
                {"priority": 1, "errors": 2, "rest": 3, "muted": 4}
            ],
        }
    )
    app = _FakeApp()
    app._daemon_read_client = LocalDaemonClient(transport=transport)

    with patch(
        "sase.notifications.read_notification_snapshot",
        side_effect=AssertionError("notification JSONL snapshot read"),
    ):
        app._refresh_notification_count()

    assert app._notification_provider_used_daemon is True
    assert app._notification_provider_snapshot.provider.source == "daemon"
    assert app._notification_provider_snapshot.snapshot_id == "snap-notifications"
    assert app._notification_provider_snapshot.row_handles == [
        notification_row_handle(notification)
    ]
    assert app._indicator_priority == 3
    assert app._indicator_rest == 3
    assert app._indicator_muted == 4
    assert [request["data"]["surface"] for request in transport.requests[1:]] == [
        "notification_list",
        "notification_counts",
    ]


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
        "counts": {"active": len(notifications), "unread": len(notifications)},
        "bounded": {
            "schema_version": 1,
            "max_payload_bytes": 1_048_576,
            "truncated": False,
        },
    }


def test_notification_row_handles_match_direct_and_daemon_logical_row() -> None:
    notification = _make(action="JumpToAgent", notes=["done"])

    assert (
        notification_row_handle(notification).stable_id
        == notification_row_handle(notification).stable_id
    )


def _response(payload_type: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "request_id": "req_test",
        "snapshot_id": None,
        "payload": {"type": payload_type, "data": data},
    }

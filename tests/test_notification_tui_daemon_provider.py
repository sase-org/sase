"""Tests for daemon-backed ACE notification provider reads."""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agents._notification_provider import (
    notification_row_handle,
    read_notification_counts_for_tui,
    read_notification_detail_for_tui,
    read_notification_pending_actions_for_tui,
)
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


def test_ace_notification_refresh_uses_daemon_without_jsonl_snapshot_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_ace_notification_daemon_reads(monkeypatch)
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
    assert app._notification_provider_snapshot.surface == "notification_counts"
    assert app._notification_provider_snapshot.metadata["full_reload"] is False
    assert app._notification_provider_snapshot.facets == {
        "priority": 1,
        "errors": 2,
        "rest": 3,
        "muted": 4,
    }
    assert app._indicator_priority == 3
    assert app._indicator_rest == 3
    assert app._indicator_muted == 4
    assert [request["data"]["surface"] for request in transport.requests[1:]] == [
        "notification_counts",
    ]


def test_ace_notification_modal_uses_daemon_unread_page_without_full_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_ace_notification_daemon_reads(monkeypatch)
    notification = _make(action="JumpToAgent", notes=["done"])
    transport = _FakeDaemonTransport(
        {
            "notification_list": [
                _notification_page([dataclasses.asdict(notification)])
            ],
            "notification_counts": [],
        }
    )
    app = _FakeApp()
    app._daemon_read_client = LocalDaemonClient(transport=transport)

    with patch(
        "sase.notifications.read_notification_snapshot",
        side_effect=AssertionError("notification JSONL snapshot read"),
    ):
        page = app._read_unread_notification_page_from_provider()

    assert page.notifications == [notification]
    assert page.shared_snapshot.snapshot_id == "snap-notifications"
    assert page.shared_snapshot.row_handles == [notification_row_handle(notification)]
    assert [request["data"]["surface"] for request in transport.requests[1:]] == [
        "notification_list",
    ]


def test_ace_notification_detail_and_pending_actions_use_daemon_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_ace_notification_daemon_reads(monkeypatch)
    notification = _make(id="notif-detail", action="JumpToAgent", notes=["done"])
    transport = _FakeDaemonTransport(
        {
            "notification_detail": [
                _notification_detail(dataclasses.asdict(notification))
            ],
            "notification_pending_actions": [_pending_actions_page()],
        }
    )
    client = LocalDaemonClient(transport=transport)

    detail = read_notification_detail_for_tui("notif-detail", client=client)
    pending = read_notification_pending_actions_for_tui(client=client)

    assert detail.used_daemon is True
    assert detail.value.notification == notification
    assert pending.used_daemon is True
    assert pending.value.actions == [{"prefix": "plan", "state": "pending"}]
    assert [
        request["data"]["surface"]
        for request in transport.requests
        if request["type"] == "read"
    ] == [
        "notification_detail",
        "notification_pending_actions",
    ]


def test_ace_notification_provider_falls_back_when_ace_surface_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_DAEMON_ACE_NOTIFICATIONS_READS", raising=False)
    transport = _FakeDaemonTransport(
        {"notification_counts": [{"priority": 9, "errors": 9, "rest": 9, "muted": 9}]}
    )
    direct_snapshot = SimpleNamespace(
        counts=SimpleNamespace(priority=1, errors=2, rest=3, muted=4),
        notifications=[],
        expired_ids=[],
    )

    with patch(
        "sase.notifications.read_notification_snapshot",
        return_value=direct_snapshot,
    ):
        result = read_notification_counts_for_tui(
            client=LocalDaemonClient(transport=transport)
        )

    assert result.used_daemon is False
    assert result.surface == "ace_notification_counts"
    assert result.fallback_reason == "surface_disabled"
    assert result.value.counts.priority == 1
    assert result.value.counts.errors == 2
    assert result.value.counts.rest == 3
    assert result.value.counts.muted == 4
    assert transport.requests == []


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


def _notification_detail(notification: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "snapshot": {"schema_version": 1, "snapshot_id": "snap-notifications"},
        "notification": notification,
        "bounded": {
            "schema_version": 1,
            "max_payload_bytes": 1_048_576,
            "truncated": False,
        },
    }


def _pending_actions_page() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "snapshot": {"schema_version": 1, "snapshot_id": "snap-notifications"},
        "store": {"actions": {"plan": {"prefix": "plan", "state": "pending"}}},
        "actions": [{"prefix": "plan", "state": "pending"}],
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


def _enable_ace_notification_daemon_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_DAEMON_ACE_NOTIFICATIONS_READS", "1")

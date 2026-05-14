"""Tests for read-only notification catalog helpers."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.core.time import get_timezone
from sase.daemon.client import LocalDaemonClient
from sase.notifications import daemon_reads
from sase.notifications.catalog import (
    list_notification_infos,
    notification_info_to_json,
    resolve_notification_ref,
)
from sase.notifications.models import Notification
from sase.notifications.store import append_notification


@pytest.fixture()
def temp_notifications_dir(tmp_path: Path) -> Iterator[Path]:
    notifications_dir = str(tmp_path / "notifications")
    notifications_file = str(tmp_path / "notifications" / "notifications.jsonl")
    with (
        patch("sase.notifications.store.NOTIFICATIONS_DIR", notifications_dir),
        patch("sase.notifications.store.NOTIFICATIONS_FILE", notifications_file),
    ):
        yield tmp_path


def _timestamp(minutes_ago: int) -> str:
    return (datetime.now(get_timezone()) - timedelta(minutes=minutes_ago)).isoformat()


def _make_notification(
    notification_id: str,
    *,
    minutes_ago: int = 0,
    sender: str = "test",
    notes: list[str] | None = None,
    files: list[str] | None = None,
    action: str | None = None,
    action_data: dict[str, str] | None = None,
    read: bool = False,
    dismissed: bool = False,
    silent: bool = False,
    muted: bool = False,
    snooze_until: str | None = None,
) -> Notification:
    return Notification(
        id=notification_id,
        timestamp=_timestamp(minutes_ago),
        sender=sender,
        notes=notes or [],
        files=files or [],
        action=action,
        action_data=action_data or {},
        read=read,
        dismissed=dismissed,
        silent=silent,
        muted=muted,
        snooze_until=snooze_until,
    )


def test_lists_newest_first_with_limit_and_stable_json_keys(
    temp_notifications_dir: Path,
) -> None:
    del temp_notifications_dir
    append_notification(_make_notification("old", minutes_ago=10))
    append_notification(
        _make_notification(
            "new",
            minutes_ago=1,
            sender="axe",
            notes=["1 error(s) in the last hour"],
            action="ViewErrorReport",
        )
    )

    rows = list_notification_infos(limit=1)

    assert [row.id for row in rows] == ["new"]
    payload = notification_info_to_json(rows[0])
    assert list(payload) == [
        "id",
        "timestamp",
        "age",
        "sender",
        "priority",
        "notes",
        "files",
        "action",
        "action_data",
        "read",
        "dismissed",
        "silent",
        "muted",
        "snooze_until",
    ]
    assert payload["priority"] is True


def test_resolves_exact_id_and_missing_id(temp_notifications_dir: Path) -> None:
    del temp_notifications_dir
    append_notification(_make_notification("target"))
    append_notification(_make_notification("other"))

    info = resolve_notification_ref("target")

    assert info is not None
    assert info.id == "target"
    assert resolve_notification_ref("missing") is None


def test_resolve_includes_dismissed_notifications(
    temp_notifications_dir: Path,
) -> None:
    del temp_notifications_dir
    append_notification(_make_notification("dismissed", dismissed=True))

    info = resolve_notification_ref("dismissed")

    assert info is not None
    assert info.dismissed is True


def test_sender_unread_dismissed_and_silent_filters(
    temp_notifications_dir: Path,
) -> None:
    del temp_notifications_dir
    append_notification(_make_notification("axe-unread", sender="axe"))
    append_notification(_make_notification("axe-read", sender="axe", read=True))
    append_notification(_make_notification("other", sender="sync"))
    append_notification(_make_notification("dismissed", dismissed=True))
    append_notification(_make_notification("silent", silent=True))

    assert [row.id for row in list_notification_infos(sender="axe")] == [
        "axe-read",
        "axe-unread",
    ]
    assert {row.id for row in list_notification_infos(unread=True)} == {
        "axe-unread",
        "other",
        "silent",
    }
    assert "dismissed" not in {row.id for row in list_notification_infos()}
    assert "dismissed" in {
        row.id for row in list_notification_infos(include_dismissed=True)
    }
    assert "silent" not in {
        row.id for row in list_notification_infos(include_silent=False)
    }


@pytest.mark.parametrize(
    "query",
    ["catalog-id", "worker", "digest", "ViewErrorReport", "AXE-42"],
)
def test_query_matches_catalog_fields(
    temp_notifications_dir: Path,
    query: str,
) -> None:
    del temp_notifications_dir
    append_notification(
        _make_notification(
            "catalog-id",
            sender="worker",
            notes=["digest available"],
            files=["/tmp/digest.txt"],
            action="ViewErrorReport",
            action_data={"code": "AXE-42"},
        )
    )
    append_notification(_make_notification("other"))

    assert [row.id for row in list_notification_infos(query=query)] == ["catalog-id"]


def test_projection_normalizes_home_paths_and_preserves_state_fields(
    temp_notifications_dir: Path,
) -> None:
    del temp_notifications_dir
    home_digest = str(Path.home() / ".sase" / "axe" / "digest.txt")
    snooze_until = _timestamp(-60)
    append_notification(
        _make_notification(
            "digest",
            sender="axe",
            files=[home_digest],
            action="ViewErrorReport",
            action_data={"error_report_path": home_digest},
            muted=True,
            snooze_until=snooze_until,
        )
    )

    payload = notification_info_to_json(list_notification_infos()[0])

    assert payload["files"] == ["~/.sase/axe/digest.txt"]
    assert payload["action_data"] == {"error_report_path": "~/.sase/axe/digest.txt"}
    assert payload["muted"] is True
    assert payload["snooze_until"] == snooze_until


def test_daemon_list_matches_direct_json_shape_without_jsonl_read(
    temp_notifications_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del temp_notifications_dir
    notification = _make_notification(
        "daemon-id",
        sender="axe",
        notes=["digest available"],
        action="ViewErrorReport",
        read=False,
    )
    append_notification(notification)
    direct_payload = notification_info_to_json(list_notification_infos(limit=1)[0])
    transport = _FakeDaemonTransport(
        reads={
            "notification_list": [
                _notification_page([dataclasses.asdict(notification)])
            ]
        }
    )
    monkeypatch.setattr(
        daemon_reads,
        "load_notifications",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("jsonl read")),
    )

    rows = list_notification_infos(
        limit=1,
        client=LocalDaemonClient(transport=transport),
    )

    assert [request["type"] for request in transport.requests] == [
        "capabilities",
        "read",
    ]
    assert notification_info_to_json(rows[0]) == direct_payload


def test_daemon_show_matches_direct_json_shape_without_jsonl_read(
    temp_notifications_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del temp_notifications_dir
    notification = _make_notification(
        "target",
        sender="mentor",
        notes=["review ready"],
        action="JumpToMentorReview",
    )
    append_notification(notification)
    direct = resolve_notification_ref("target")
    transport = _FakeDaemonTransport(
        reads={
            "notification_detail": [
                _notification_detail(dataclasses.asdict(notification))
            ]
        }
    )
    monkeypatch.setattr(
        daemon_reads,
        "load_notifications",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("jsonl read")),
    )

    daemon = resolve_notification_ref(
        "target",
        client=LocalDaemonClient(transport=transport),
    )

    assert direct is not None
    assert daemon is not None
    assert notification_info_to_json(daemon) == notification_info_to_json(direct)


def test_daemon_list_honors_filters_and_sends_unread_only_when_requested() -> None:
    transport = _FakeDaemonTransport(
        reads={
            "notification_list": [
                _notification_page(
                    [
                        dataclasses.asdict(
                            _make_notification("n1", sender="axe", read=False)
                        )
                    ]
                )
            ]
        }
    )

    rows = list_notification_infos(
        limit=5,
        query="digest",
        sender="axe",
        unread=True,
        include_dismissed=True,
        client=LocalDaemonClient(transport=transport),
    )

    assert [row.id for row in rows] == ["n1"]
    assert transport.requests[-1]["data"]["data"] == {
        "schema_version": 1,
        "page": {"schema_version": 1, "limit": 5, "cursor": None},
        "include_dismissed": True,
        "query": "digest",
        "sender": "axe",
        "unread": True,
    }


def test_daemon_list_without_unread_flag_sends_no_unread_filter() -> None:
    transport = _FakeDaemonTransport(
        reads={"notification_list": [_notification_page([])]}
    )

    list_notification_infos(client=LocalDaemonClient(transport=transport))

    assert transport.requests[-1]["data"]["data"]["unread"] is None


def test_daemon_counts_and_pending_actions_have_direct_fallback_shapes() -> None:
    transport = _FakeDaemonTransport(
        reads={
            "notification_counts": [
                {
                    "priority": 1,
                    "errors": 2,
                    "rest": 3,
                    "muted": 4,
                    "pending_actions": 5,
                }
            ],
            "notification_pending_actions": [
                _pending_actions(
                    [
                        {
                            "prefix": "abcd1234",
                            "notification_id": "n1",
                            "state": "available",
                        }
                    ]
                )
            ],
        }
    )
    client = LocalDaemonClient(transport=transport)

    counts = daemon_reads.read_notification_counts(client=client).value
    pending = daemon_reads.read_notification_pending_actions(client=client).value

    assert counts.counts["pending_actions"] == 5
    assert pending.actions == [
        {"prefix": "abcd1234", "notification_id": "n1", "state": "available"}
    ]


def test_invalid_jsonl_soft_errors_match_direct_fallback(
    temp_notifications_dir: Path,
) -> None:
    notifications_file = (
        temp_notifications_dir / "notifications" / "notifications.jsonl"
    )
    notifications_file.parent.mkdir(parents=True, exist_ok=True)
    valid = dataclasses.asdict(_make_notification("valid"))
    notifications_file.write_text(
        "{bad json}\n" + json.dumps(valid, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    rows = list_notification_infos(args=_NoDaemonArgs())

    assert [row.id for row in rows] == ["valid"]


class _NoDaemonArgs:
    no_daemon = True


class _FakeDaemonTransport:
    def __init__(
        self,
        *,
        reads: dict[str, list[dict[str, Any]]],
        capabilities: list[str] | None = None,
    ) -> None:
        self.reads = reads
        self.capabilities = capabilities or ["notifications.read"]
        self.requests: list[dict[str, Any]] = []

    def request(self, envelope: dict[str, Any]) -> dict[str, Any]:
        payload = envelope["payload"]
        self.requests.append(payload)
        if payload["type"] == "capabilities":
            return _response(
                "capabilities",
                {"schema_version": 1, "capabilities": self.capabilities},
            )
        if payload["type"] == "read":
            surface = payload["data"]["surface"]
            return _response(
                "read", {"surface": surface, "data": self.reads[surface].pop(0)}
            )
        raise AssertionError(f"unexpected request: {payload}")


def _response(payload_type: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "request_id": "req_test",
        "snapshot_id": None,
        "payload": {"type": payload_type, "data": data},
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


def _pending_actions(actions: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "snapshot": {"schema_version": 1, "snapshot_id": "snap-pending"},
        "store": {
            "schema_version": 1,
            "actions": {item["prefix"]: item for item in actions},
        },
        "actions": actions,
        "bounded": {
            "schema_version": 1,
            "max_payload_bytes": 1_048_576,
            "truncated": False,
        },
    }

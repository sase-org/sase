"""Tests for read-only notification catalog helpers."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.core.time import get_timezone
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
    icon: str | None = None,
    notes: list[str] | None = None,
    files: list[str] | None = None,
    tags: list[str] | None = None,
    action: str | None = None,
    action_data: dict[str, str] | None = None,
    read: bool = False,
    dismissed: bool = False,
    silent: bool = False,
    muted: bool = False,
    snooze_until: str | None = None,
    resurfaced_at: str | None = None,
) -> Notification:
    return Notification(
        id=notification_id,
        timestamp=_timestamp(minutes_ago),
        sender=sender,
        icon=icon,
        notes=notes or [],
        files=files or [],
        tags=tags or [],
        action=action,
        action_data=action_data or {},
        read=read,
        dismissed=dismissed,
        silent=silent,
        muted=muted,
        snooze_until=snooze_until,
        resurfaced_at=resurfaced_at,
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
            icon="🚨",
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
        "icon",
        "color",
        "priority",
        "notes",
        "files",
        "tags",
        "action",
        "action_data",
        "read",
        "dismissed",
        "silent",
        "muted",
        "snooze_until",
        "resurfaced_at",
    ]
    assert payload["icon"] == "🚨"
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
    ["catalog-id", "worker", "digest", "ViewErrorReport", "AXE-42", "review"],
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
            tags=["review"],
            action="ViewErrorReport",
            action_data={"code": "AXE-42"},
        )
    )
    append_notification(_make_notification("other"))

    assert [row.id for row in list_notification_infos(query=query)] == ["catalog-id"]


def test_tag_filter_normalizes_and_matches_exact_tags(
    temp_notifications_dir: Path,
) -> None:
    del temp_notifications_dir
    append_notification(_make_notification("review", tags=["done", "review"]))
    append_notification(_make_notification("done-only", tags=["done"]))
    append_notification(_make_notification("untagged"))

    assert [row.id for row in list_notification_infos(tag=" Review ")] == ["review"]
    assert [row.id for row in list_notification_infos(tag="done")] == [
        "done-only",
        "review",
    ]


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


def test_resurfaced_old_notification_sorts_as_new_activity(
    temp_notifications_dir: Path,
) -> None:
    del temp_notifications_dir
    append_notification(_make_notification("recent", minutes_ago=1))
    append_notification(
        _make_notification(
            "resurfaced",
            minutes_ago=60,
            resurfaced_at=_timestamp(0),
        )
    )

    rows = list_notification_infos(limit=1)

    assert [row.id for row in rows] == ["resurfaced"]
    assert rows[0].resurfaced_at is not None


def test_catalog_read_reconciles_due_snooze_to_current_state(
    temp_notifications_dir: Path,
) -> None:
    del temp_notifications_dir
    append_notification(
        _make_notification(
            "due",
            minutes_ago=60,
            read=True,
            muted=True,
            snooze_until=_timestamp(1),
        )
    )

    row = list_notification_infos()[0]

    assert row.id == "due"
    assert row.read is False
    assert row.muted is False
    assert row.snooze_until is None
    assert row.resurfaced_at is not None

"""Tests for the notification-store current-snapshot caching layer."""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from sase.core import notification_store_facade as facade
from sase.core.notification_store_wire import NOTIFICATION_STORE_WIRE_SCHEMA_VERSION

from tests.test_core_facade._notification_store_helpers import (
    _fake_module,
    _notification,
)


def _snapshot_payload(
    *,
    notification_id: str = "n1",
    next_snooze_deadline: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": NOTIFICATION_STORE_WIRE_SCHEMA_VERSION,
        "notifications": [
            {
                "id": notification_id,
                "timestamp": "2026-04-30T12:00:00+00:00",
                "sender": "axe",
                "notes": ["hello"],
                "files": [],
                "tags": [],
                "action": None,
                "action_data": {},
                "read": False,
                "dismissed": False,
                "silent": False,
                "muted": False,
                "snooze_until": None,
                "resurfaced_at": None,
            }
        ],
        "counts": {"priority": 1, "rest": 0, "muted": 0},
        "expired_ids": [],
        "next_snooze_deadline": next_snooze_deadline,
        "stats": {
            "total_lines": 1,
            "blank_lines": 0,
            "invalid_json_lines": 0,
            "invalid_record_lines": 0,
            "loaded_rows": 1,
            "dismissed_filtered": 0,
        },
    }


def test_unchanged_current_snapshot_does_not_reparse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "notifications.jsonl"
    path.write_text("{}\n", encoding="utf-8")
    calls: list[tuple[str, bool, bool]] = []

    def fake_read(store_path: str, include_dismissed: bool, expire: bool) -> dict:
        calls.append((store_path, include_dismissed, expire))
        return _snapshot_payload()

    _fake_module(monkeypatch, read_notifications_snapshot=fake_read)

    first = facade.read_current_notifications_snapshot(path)
    second = facade.read_current_notifications_snapshot(path)

    assert calls == [(str(path), False, True)]
    assert [row.id for row in first.notifications] == ["n1"]
    assert [row.id for row in second.notifications] == ["n1"]
    first.notifications[0].notes.append("mutated")
    third = facade.read_current_notifications_snapshot(path)
    assert third.notifications[0].notes == ["hello"]


def test_changed_store_reparses_current_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "notifications.jsonl"
    path.write_text("{}\n", encoding="utf-8")
    calls: list[str] = []

    def fake_read(store_path: str, include_dismissed: bool, expire: bool) -> dict:
        _ = (include_dismissed, expire)
        calls.append(store_path)
        return _snapshot_payload(notification_id=f"n{len(calls)}")

    _fake_module(monkeypatch, read_notifications_snapshot=fake_read)

    first = facade.read_current_notifications_snapshot(path)
    path.write_text("{}\n{}\n", encoding="utf-8")
    second = facade.read_current_notifications_snapshot(path)

    assert len(calls) == 2
    assert first.notifications[0].id == "n1"
    assert second.notifications[0].id == "n2"


@pytest.mark.parametrize("mutation", ["append", "replace"])
def test_external_write_after_snapshot_read_is_not_cached(
    mutation: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "notifications.jsonl"
    path.write_text("old\n", encoding="utf-8")
    calls: list[str] = []

    def fake_read(store_path: str, include_dismissed: bool, expire: bool) -> dict:
        _ = (include_dismissed, expire)
        calls.append(store_path)
        if len(calls) == 1:
            if mutation == "append":
                path.write_text("old\nnew\n", encoding="utf-8")
            else:
                replacement = path.with_name("notifications-replacement.jsonl")
                replacement.write_text("new\n", encoding="utf-8")
                replacement.replace(path)
            return _snapshot_payload(notification_id="old")
        return _snapshot_payload(notification_id="new")

    _fake_module(monkeypatch, read_notifications_snapshot=fake_read)

    first = facade.read_current_notifications_snapshot(path)
    second = facade.read_current_notifications_snapshot(path)
    third = facade.read_current_notifications_snapshot(path)

    assert [row.id for row in first.notifications] == ["old"]
    assert [row.id for row in second.notifications] == ["new"]
    assert [row.id for row in third.notifications] == ["new"]
    assert len(calls) == 2


def test_interleaved_readers_do_not_publish_stale_snapshot_under_new_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "notifications.jsonl"
    path.write_text("old\n", encoding="utf-8")
    first_read_changed_store = threading.Event()
    release_first_read = threading.Event()
    call_lock = threading.Lock()
    calls: list[int] = []

    def fake_read(store_path: str, include_dismissed: bool, expire: bool) -> dict:
        _ = (store_path, include_dismissed, expire)
        with call_lock:
            call_number = len(calls) + 1
            calls.append(call_number)
        if call_number == 1:
            path.write_text("old\nnew\n", encoding="utf-8")
            first_read_changed_store.set()
            assert release_first_read.wait(timeout=5)
            return _snapshot_payload(notification_id="old")
        return _snapshot_payload(notification_id="new")

    _fake_module(monkeypatch, read_notifications_snapshot=fake_read)
    first_result: dict[str, str] = {}
    first_errors: list[BaseException] = []

    def first_reader() -> None:
        try:
            snapshot = facade.read_current_notifications_snapshot(path)
        except BaseException as error:
            first_errors.append(error)
            return
        first_result["id"] = snapshot.notifications[0].id

    reader = threading.Thread(target=first_reader)
    reader.start()
    assert first_read_changed_store.wait(timeout=5)

    second = facade.read_current_notifications_snapshot(path)
    assert [row.id for row in second.notifications] == ["new"]

    release_first_read.set()
    reader.join(timeout=5)

    assert first_errors == []
    assert first_result == {"id": "old"}

    stable = facade.read_current_notifications_snapshot(path)

    assert [row.id for row in stable.notifications] == ["new"]
    assert calls == [1, 2]


def test_include_dismissed_is_part_of_snapshot_cache_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "notifications.jsonl"
    path.write_text("{}\n", encoding="utf-8")
    calls: list[bool] = []

    def fake_read(_store_path: str, include_dismissed: bool, expire: bool) -> dict:
        _ = expire
        calls.append(include_dismissed)
        suffix = "all" if include_dismissed else "active"
        return _snapshot_payload(notification_id=suffix)

    _fake_module(monkeypatch, read_notifications_snapshot=fake_read)

    active = facade.read_current_notifications_snapshot(path, include_dismissed=False)
    dismissed = facade.read_current_notifications_snapshot(path, include_dismissed=True)
    active_again = facade.read_current_notifications_snapshot(
        path, include_dismissed=False
    )

    assert calls == [False, True]
    assert active.notifications[0].id == "active"
    assert dismissed.notifications[0].id == "all"
    assert active_again.notifications[0].id == "active"


def test_local_mutation_invalidates_snapshot_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "notifications.jsonl"
    path.write_text("{}\n", encoding="utf-8")
    calls: list[int] = []

    def fake_read(_store_path: str, _include: bool, _expire: bool) -> dict:
        calls.append(1)
        return _snapshot_payload(notification_id=f"n{len(calls)}")

    def fake_append_counts(_store_path: str, _notification: dict[str, Any]) -> dict:
        return {
            "schema_version": NOTIFICATION_STORE_WIRE_SCHEMA_VERSION,
            "matched_count": 0,
            "changed_count": 0,
            "appended_count": 1,
            "rewritten": False,
            "notifications": [],
            "counts": {},
            "expired_ids": [],
            "stats": {},
        }

    _fake_module(
        monkeypatch,
        read_notifications_snapshot=fake_read,
        append_notification_counts=fake_append_counts,
    )

    first = facade.read_current_notifications_snapshot(path)
    second = facade.read_current_notifications_snapshot(path)
    facade.append_notification_counts(path, _notification("n2"))
    third = facade.read_current_notifications_snapshot(path)

    assert first.notifications[0].id == "n1"
    assert second.notifications[0].id == "n1"
    assert third.notifications[0].id == "n2"
    assert len(calls) == 2


def test_cached_current_snapshot_does_not_replay_expired_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "notifications.jsonl"
    path.write_text("{}\n", encoding="utf-8")
    calls: list[int] = []

    def fake_read(_store_path: str, _include: bool, _expire: bool) -> dict:
        calls.append(1)
        payload = _snapshot_payload()
        payload["expired_ids"] = ["n1"]
        return payload

    _fake_module(monkeypatch, read_notifications_snapshot=fake_read)

    first = facade.read_current_notifications_snapshot(path)
    second = facade.read_current_notifications_snapshot(path)

    assert len(calls) == 1
    assert first.expired_ids == ["n1"]
    assert second.expired_ids == []


def test_due_snooze_deadline_bypasses_current_snapshot_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "notifications.jsonl"
    path.write_text("{}\n", encoding="utf-8")
    calls: list[int] = []
    due = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()

    def fake_read(_store_path: str, _include: bool, _expire: bool) -> dict:
        calls.append(1)
        return _snapshot_payload(next_snooze_deadline=due)

    _fake_module(monkeypatch, read_notifications_snapshot=fake_read)

    facade.read_current_notifications_snapshot(path)
    facade.read_current_notifications_snapshot(path)

    assert len(calls) == 2


def test_future_snooze_deadline_keeps_current_snapshot_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "notifications.jsonl"
    path.write_text("{}\n", encoding="utf-8")
    calls: list[int] = []
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()

    def fake_read(_store_path: str, _include: bool, _expire: bool) -> dict:
        calls.append(1)
        return _snapshot_payload(next_snooze_deadline=future)

    _fake_module(monkeypatch, read_notifications_snapshot=fake_read)

    facade.read_current_notifications_snapshot(path)
    facade.read_current_notifications_snapshot(path)

    assert len(calls) == 1

"""Tests for the Rust notification-store facade."""

from __future__ import annotations

import shutil
import sys
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from sase.core import notification_store_facade as facade
from sase.core.notification_store_wire import (
    NOTIFICATION_STORE_WIRE_SCHEMA_VERSION,
    _NotificationCountsWire,
    NotificationAgentKeyWire,
    NotificationStateUpdateWire,
    _NotificationStoreStatsWire,
    _notification_from_dict,
    notification_store_wire_to_json_dict,
)
from sase.core.rust import RUST_EXTENSION_MODULE_NAME
from sase.core.time import get_timezone
from sase.notifications.models import Notification

FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "notifications"
    / "store_contract.jsonl"
)


def _notification(
    id: str,
    *,
    sender: str = "test",
    action: str | None = None,
    tags: list[str] | None = None,
    read: bool = False,
    muted: bool = False,
    snooze_until: str | None = None,
    resurfaced_at: str | None = None,
) -> Notification:
    return Notification(
        id=id,
        timestamp="2026-04-30T12:00:00+00:00",
        sender=sender,
        notes=["note"],
        tags=tags or [],
        action=action,
        read=read,
        muted=muted,
        snooze_until=snooze_until,
        resurfaced_at=resurfaced_at,
    )


def _fake_module(monkeypatch: pytest.MonkeyPatch, **bindings: Any) -> None:
    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    for name, binding in bindings.items():
        setattr(fake, name, binding)
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, fake)


def _skip_without_notification_bindings(
    binding_name: str = "read_notifications_snapshot",
) -> None:
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    if not hasattr(rust_module, binding_name):
        pytest.skip(f"sase_core_rs is too old (no {binding_name} binding).")


def test_read_snapshot_rehydrates_typed_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, bool, bool]] = []

    def fake_read(path: str, include_dismissed: bool, expire_due_snoozes: bool) -> dict:
        calls.append((path, include_dismissed, expire_due_snoozes))
        return {
            "schema_version": NOTIFICATION_STORE_WIRE_SCHEMA_VERSION,
            "notifications": [
                {
                    "id": "n1",
                    "timestamp": "2026-04-30T12:00:00+00:00",
                    "sender": "axe",
                    "notes": ["hello"],
                    "files": [],
                    "tags": ["done"],
                    "action": "PlanApproval",
                    "action_data": {"agent_cl_name": "cl"},
                    "read": False,
                    "dismissed": False,
                    "silent": False,
                    "muted": False,
                    "snooze_until": None,
                    "resurfaced_at": "2026-04-30T13:00:00+00:00",
                }
            ],
            "counts": {"priority": 1, "rest": 0, "muted": 0},
            "expired_ids": [],
            "next_snooze_deadline": "2026-04-30T14:00:00+00:00",
            "stats": {
                "total_lines": 1,
                "blank_lines": 0,
                "invalid_json_lines": 0,
                "invalid_record_lines": 0,
                "loaded_rows": 1,
                "dismissed_filtered": 0,
            },
        }

    _fake_module(monkeypatch, read_notifications_snapshot=fake_read)

    snapshot = facade.read_notifications_snapshot(
        "/tmp/notifications.jsonl", include_dismissed=True, expire_due_snoozes=True
    )

    assert calls == [("/tmp/notifications.jsonl", True, True)]
    assert snapshot.counts.priority == 1
    assert snapshot.notifications[0].id == "n1"
    assert snapshot.notifications[0].tags == ["done"]
    assert snapshot.notifications[0].resurfaced_at == "2026-04-30T13:00:00+00:00"
    assert snapshot.next_snooze_deadline == "2026-04-30T14:00:00+00:00"
    assert isinstance(snapshot.notifications[0], Notification)


def test_read_current_snapshot_uses_canonical_expiring_core_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, bool, bool]] = []

    def fake_read(path: str, include_dismissed: bool, expire: bool) -> dict:
        calls.append((path, include_dismissed, expire))
        return {
            "schema_version": NOTIFICATION_STORE_WIRE_SCHEMA_VERSION,
            "notifications": [],
            "counts": {},
            "expired_ids": [],
            "next_snooze_deadline": None,
            "stats": {},
        }

    _fake_module(monkeypatch, read_notifications_snapshot=fake_read)

    snapshot = facade.read_current_notifications_snapshot(
        "/tmp/notifications.jsonl", include_dismissed=True
    )

    assert calls == [("/tmp/notifications.jsonl", True, True)]
    assert snapshot.next_snooze_deadline is None


def test_missing_notification_binding_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_module(monkeypatch)

    with pytest.raises(AttributeError, match="read_notifications_snapshot"):
        facade.read_notifications_snapshot("/tmp/notifications.jsonl")


def test_schema_mismatch_fails_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_read(_path: str, _include: bool, _expire: bool) -> dict:
        return {
            "schema_version": 999,
            "notifications": [],
            "counts": {"priority": 0, "rest": 0, "muted": 0},
            "expired_ids": [],
            "stats": {},
        }

    _fake_module(monkeypatch, read_notifications_snapshot=fake_read)

    with pytest.raises(ValueError, match="notification store wire schema mismatch"):
        facade.read_notifications_snapshot("/tmp/notifications.jsonl")


def test_update_wire_serializes_tagged_shape() -> None:
    update = NotificationStateUpdateWire(kind="mark_snoozed", id="n1", until="soon")

    assert notification_store_wire_to_json_dict(update) == {
        "kind": "mark_snoozed",
        "id": "n1",
        "until": "soon",
    }


def test_update_wire_serializes_mark_many_dismissed_shape() -> None:
    update = NotificationStateUpdateWire(kind="mark_many_dismissed", ids=("n1", "n2"))

    assert notification_store_wire_to_json_dict(update) == {
        "kind": "mark_many_dismissed",
        "ids": ["n1", "n2"],
    }


def test_update_wire_serializes_bulk_mute_and_snooze_shapes() -> None:
    mute = NotificationStateUpdateWire(
        kind="mark_many_muted", ids=("n1", "n2"), muted=False
    )
    snooze = NotificationStateUpdateWire(
        kind="mark_many_snoozed", ids=("n1", "n2"), until="soon"
    )

    assert notification_store_wire_to_json_dict(mute) == {
        "kind": "mark_many_muted",
        "ids": ["n1", "n2"],
        "muted": False,
    }
    assert notification_store_wire_to_json_dict(snooze) == {
        "kind": "mark_many_snoozed",
        "ids": ["n1", "n2"],
        "until": "soon",
    }


def test_wire_helpers_rehydrate_and_serialize_agent_keys() -> None:
    n = _notification_from_dict(
        {
            "id": "n1",
            "timestamp": "2026-04-30T12:00:00+00:00",
            "sender": "test",
        }
    )
    update = NotificationStateUpdateWire(
        kind="dismiss_matching_agents",
        agents=(NotificationAgentKeyWire(cl_name="cl", raw_suffix="20260430120000"),),
    )

    assert n.id == "n1"
    assert n.tags == []
    assert _NotificationCountsWire(priority=1).priority == 1
    assert _NotificationStoreStatsWire(total_lines=3).total_lines == 3
    assert notification_store_wire_to_json_dict(update) == {
        "kind": "dismiss_matching_agents",
        "agents": [{"cl_name": "cl", "raw_suffix": "20260430120000"}],
    }


def test_apply_state_update_counts_uses_metadata_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_apply_counts(path: str, update: dict[str, Any]) -> dict:
        calls.append((path, update))
        return {
            "schema_version": NOTIFICATION_STORE_WIRE_SCHEMA_VERSION,
            "matched_count": 2,
            "changed_count": 2,
            "appended_count": 0,
            "rewritten": True,
            "notifications": [],
            "counts": {},
            "expired_ids": [],
            "stats": {},
        }

    _fake_module(monkeypatch, apply_notification_state_update_counts=fake_apply_counts)

    outcome = facade.apply_notification_state_update_counts(
        "/tmp/notifications.jsonl",
        NotificationStateUpdateWire(kind="mark_all_read"),
    )

    assert calls == [
        ("/tmp/notifications.jsonl", {"kind": "mark_all_read"}),
    ]
    assert outcome.changed_count == 2
    assert outcome.notifications == []


def test_real_extension_round_trips_store_operations(tmp_path: Path) -> None:
    _skip_without_notification_bindings()
    path = tmp_path / "notifications.jsonl"

    append = facade.append_notification(
        path, _notification("n1", sender="axe", tags=["done", "review"])
    )
    assert append.appended_count == 1
    assert append.notifications[0].id == "n1"
    assert append.notifications[0].tags == ["done", "review"]

    mark = facade.apply_notification_state_update(
        path, NotificationStateUpdateWire(kind="mark_read", id="n1")
    )
    assert mark.matched_count == 1
    assert mark.changed_count == 1
    assert mark.notifications[0].read is True

    snapshot = facade.read_notifications_snapshot(path)
    assert snapshot.counts.priority == 0
    assert snapshot.notifications[0].read is True
    assert snapshot.notifications[0].tags == ["done", "review"]

    rewrite = facade.rewrite_notifications(path, [_notification("n2")])
    assert rewrite.rewritten is True
    assert [n.id for n in rewrite.notifications] == ["n2", "n1"]


def test_real_extension_round_trips_bulk_mute_and_snooze(tmp_path: Path) -> None:
    _skip_without_notification_bindings()
    path = tmp_path / "notifications.jsonl"
    facade.rewrite_notifications(
        path, [_notification("n1"), _notification("n2"), _notification("n3")]
    )

    muted = facade.apply_notification_state_update(
        path,
        NotificationStateUpdateWire(
            kind="mark_many_muted",
            ids=("n1", "missing", "n2", "n1"),
            muted=True,
        ),
    )
    assert muted.matched_count == 2
    assert muted.changed_count == 2
    assert {n.id for n in muted.notifications if n.muted} == {"n1", "n2"}

    deadline = datetime.now(get_timezone()) + timedelta(minutes=15)
    snoozed = facade.apply_notification_state_update(
        path,
        NotificationStateUpdateWire(
            kind="mark_many_snoozed",
            ids=("n2", "n3"),
            until=deadline.isoformat(),
        ),
    )
    assert snoozed.matched_count == 2
    by_id = {n.id: n for n in snoozed.notifications}
    normalized_deadline = deadline.astimezone(UTC).isoformat()
    assert by_id["n2"].snooze_until == normalized_deadline
    assert by_id["n3"].snooze_until == normalized_deadline


def test_append_counts_uses_metadata_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_append_counts(path: str, notification: dict[str, Any]) -> dict:
        calls.append((path, notification))
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

    _fake_module(monkeypatch, append_notification_counts=fake_append_counts)

    outcome = facade.append_notification_counts(
        "/tmp/notifications.jsonl", _notification("n1", sender="axe")
    )

    assert len(calls) == 1
    assert calls[0][0] == "/tmp/notifications.jsonl"
    assert calls[0][1]["id"] == "n1"
    assert outcome.appended_count == 1
    assert outcome.notifications == []


def test_rewrite_counts_uses_metadata_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, list[dict[str, Any]]]] = []

    def fake_rewrite_counts(path: str, notifications: list[dict[str, Any]]) -> dict:
        calls.append((path, notifications))
        return {
            "schema_version": NOTIFICATION_STORE_WIRE_SCHEMA_VERSION,
            "matched_count": 2,
            "changed_count": 2,
            "appended_count": 0,
            "rewritten": True,
            "notifications": [],
            "counts": {},
            "expired_ids": [],
            "stats": {},
        }

    _fake_module(monkeypatch, rewrite_notifications_counts=fake_rewrite_counts)

    outcome = facade.rewrite_notifications_counts(
        "/tmp/notifications.jsonl",
        [_notification("n1"), _notification("n2")],
    )

    assert len(calls) == 1
    assert calls[0][0] == "/tmp/notifications.jsonl"
    assert [n["id"] for n in calls[0][1]] == ["n1", "n2"]
    assert outcome.rewritten is True
    assert outcome.matched_count == 2
    assert outcome.notifications == []


def test_real_extension_append_counts_omits_notifications(tmp_path: Path) -> None:
    _skip_without_notification_bindings("append_notification_counts")
    path = tmp_path / "notifications.jsonl"

    outcome = facade.append_notification_counts(path, _notification("n1", sender="axe"))

    assert outcome.appended_count == 1
    assert outcome.notifications == []
    assert outcome.stats.loaded_rows == 0
    snapshot = facade.read_notifications_snapshot(path)
    assert [n.id for n in snapshot.notifications] == ["n1"]


def test_real_extension_rewrite_counts_omits_notifications(tmp_path: Path) -> None:
    _skip_without_notification_bindings("rewrite_notifications_counts")
    path = tmp_path / "notifications.jsonl"
    facade.append_notification(path, _notification("n1"))

    outcome = facade.rewrite_notifications_counts(
        path, [_notification("n1", read=True), _notification("n2")]
    )

    assert outcome.rewritten is True
    assert outcome.matched_count == 2
    assert outcome.changed_count == 2
    assert outcome.notifications == []
    snapshot = facade.read_notifications_snapshot(path)
    assert {n.id for n in snapshot.notifications} == {"n1", "n2"}


def test_real_extension_counts_update_omits_notifications(tmp_path: Path) -> None:
    _skip_without_notification_bindings("apply_notification_state_update_counts")
    path = tmp_path / "notifications.jsonl"
    facade.append_notification(path, _notification("n1", sender="axe"))

    outcome = facade.apply_notification_state_update_counts(
        path, NotificationStateUpdateWire(kind="mark_all_read")
    )

    assert outcome.changed_count == 1
    assert outcome.notifications == []
    assert outcome.counts.priority == 0
    assert outcome.stats.loaded_rows == 0
    assert facade.read_notifications_snapshot(path).notifications[0].read is True


def test_real_extension_reads_phase1_contract_fixture(tmp_path: Path) -> None:
    _skip_without_notification_bindings()
    path = tmp_path / "notifications.jsonl"
    shutil.copyfile(FIXTURE_PATH, path)

    active = facade.read_notifications_snapshot(path)
    all_rows = facade.read_notifications_snapshot(path, include_dismissed=True)

    assert len(active.notifications) == 12
    assert len(all_rows.notifications) == 13
    assert active.stats.invalid_json_lines == 1
    assert active.stats.invalid_record_lines == 1
    assert active.counts.priority == 4
    assert active.counts.errors == 2
    assert active.counts.muted == 2
    valid_full = next(n for n in all_rows.notifications if n.id == "valid-full")
    assert valid_full.tags == ["done", "review"]


def test_real_extension_snapshot_can_expire_due_snoozes(tmp_path: Path) -> None:
    _skip_without_notification_bindings()
    path = tmp_path / "notifications.jsonl"
    past = (datetime.now(get_timezone()) - timedelta(minutes=1)).isoformat()
    facade.append_notification(
        path, _notification("snoozed", muted=True, snooze_until=past)
    )

    snapshot = facade.read_notifications_snapshot(path, expire_due_snoozes=True)

    assert snapshot.expired_ids == ["snoozed"]
    assert snapshot.notifications[0].muted is False
    assert snapshot.notifications[0].read is False
    assert snapshot.notifications[0].snooze_until is None
    assert snapshot.notifications[0].resurfaced_at is not None
    assert snapshot.next_snooze_deadline is None


def test_real_extension_validates_and_normalizes_snooze_updates(tmp_path: Path) -> None:
    _skip_without_notification_bindings()
    path = tmp_path / "notifications.jsonl"
    facade.rewrite_notifications(
        path, [_notification("active"), _notification("other")]
    )

    normalized = facade.apply_notification_state_update(
        path,
        NotificationStateUpdateWire(
            kind="mark_snoozed",
            id="active",
            until="2099-01-01T04:00:00-05:00",
        ),
    )
    active = next(row for row in normalized.notifications if row.id == "active")
    assert active.snooze_until == "2099-01-01T09:00:00+00:00"
    assert normalized.next_snooze_deadline == "2099-01-01T09:00:00+00:00"

    with pytest.raises(ValueError, match="timezone-aware"):
        facade.apply_notification_state_update(
            path,
            NotificationStateUpdateWire(
                kind="mark_many_snoozed",
                ids=("active", "other"),
                until="2099-01-01T09:00:00",
            ),
        )
    snapshot = facade.read_notifications_snapshot(path)
    other = next(row for row in snapshot.notifications if row.id == "other")
    assert other.snooze_until is None

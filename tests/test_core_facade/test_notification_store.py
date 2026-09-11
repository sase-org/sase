"""Tests for the Rust notification-store facade."""

from __future__ import annotations

import dataclasses
import json
import shutil
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
from tests._rust_extension_module_helpers import (
    patch_rust_extension,
)

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
    patch_rust_extension(monkeypatch, fake)


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


def test_update_wire_serializes_mark_tab_read_shape() -> None:
    update = NotificationStateUpdateWire(kind="mark_tab_read", tab_key="alpha")

    assert notification_store_wire_to_json_dict(update) == {
        "kind": "mark_tab_read",
        "tab_key": "alpha",
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
    assert n.plus_ones == []
    assert n.plus_ones_dropped == 0
    assert n.dedup_key is None
    assert n.plus_one_count == 0
    assert _NotificationCountsWire(priority=1).priority == 1
    assert _NotificationStoreStatsWire(total_lines=3).total_lines == 3
    assert notification_store_wire_to_json_dict(update) == {
        "kind": "dismiss_matching_agents",
        "agents": [{"cl_name": "cl", "raw_suffix": "20260430120000"}],
    }


def test_notification_from_dict_hydrates_plus_ones_and_omits_empty_on_write() -> None:
    hydrated = _notification_from_dict(
        {
            "id": "n1",
            "timestamp": "2026-04-30T12:00:00+00:00",
            "sender": "ci_watch",
            "plus_ones": [
                {
                    "timestamp": "2026-04-30T13:00:00+00:00",
                    "sender": "ci_watch",
                    "note": "sase-org/sase recovered",
                    "unknown": "ignored",
                }
            ],
            "plus_ones_dropped": 2,
            "dedup_key": "ci-failure/sase",
        }
    )

    assert hydrated.plus_one_count == 3
    assert hydrated.dedup_key == "ci-failure/sase"
    assert hydrated.plus_ones[0].note == "sase-org/sase recovered"
    payload = notification_store_wire_to_json_dict(hydrated)
    assert payload["plus_ones"] == [
        {
            "timestamp": "2026-04-30T13:00:00+00:00",
            "sender": "ci_watch",
            "note": "sase-org/sase recovered",
        }
    ]
    assert payload["plus_ones_dropped"] == 2
    assert payload["dedup_key"] == "ci-failure/sase"

    empty = notification_store_wire_to_json_dict(
        _notification_from_dict(
            {
                "id": "n2",
                "timestamp": "2026-04-30T12:00:00+00:00",
                "sender": "ci_watch",
            }
        )
    )
    assert "plus_ones" not in empty
    assert "plus_ones_dropped" not in empty
    assert "dedup_key" not in empty


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


def test_real_extension_mark_tab_read_scopes_to_one_tab(tmp_path: Path) -> None:
    _skip_without_notification_bindings()
    path = tmp_path / "notifications.jsonl"
    facade.rewrite_notifications(
        path,
        [
            _notification("a1", tags=["alpha"]),
            _notification("a2", tags=["alpha"]),
            _notification("b1", tags=["beta"]),
        ],
    )

    outcome = facade.apply_notification_state_update(
        path, NotificationStateUpdateWire(kind="mark_tab_read", tab_key="alpha")
    )
    assert outcome.matched_count == 2
    assert outcome.changed_count == 2

    snapshot = facade.read_notifications_snapshot(path)
    by_id = {n.id: n for n in snapshot.notifications}
    assert by_id["a1"].read is True
    assert by_id["a2"].read is True
    assert by_id["b1"].read is False

    repeat = facade.apply_notification_state_update(
        path, NotificationStateUpdateWire(kind="mark_tab_read", tab_key="alpha")
    )
    assert repeat.matched_count == 0
    assert repeat.changed_count == 0


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


def test_store_write_invalidates_snapshot_cache(tmp_path: Path) -> None:
    _skip_without_notification_bindings()
    path = tmp_path / "notifications.jsonl"
    facade.append_notification(path, _notification("n1"))
    first = facade.read_current_notifications_snapshot(path)
    assert [row.id for row in first.notifications] == ["n1"]

    facade.append_notification(path, _notification("n2"))
    second = facade.read_current_notifications_snapshot(path)
    assert {row.id for row in second.notifications} == {"n1", "n2"}


def test_compact_preserves_unread_and_actionable_notifications(tmp_path: Path) -> None:
    _skip_without_notification_bindings()
    path = tmp_path / "notifications.jsonl"
    old = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    recent = (datetime.now(UTC) - timedelta(days=3)).isoformat()
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()

    unread = _notification("unread")
    actionable = _notification("actionable", action="PlanApproval")
    recent_dismissed = dataclasses.replace(
        _notification("recent-dismissed", read=True),
        dismissed=True,
        timestamp=recent,
    )
    snoozed_dismissed = dataclasses.replace(
        _notification(
            "snoozed-dismissed",
            muted=True,
            snooze_until=future,
        ),
        dismissed=True,
        timestamp=old,
    )
    old_dismissed = [
        dataclasses.replace(
            _notification(f"old-dismissed-{index:04d}", read=True),
            dismissed=True,
            timestamp=old,
        )
        for index in range(1_001)
    ]
    rows = [unread, actionable, recent_dismissed, snoozed_dismissed, *old_dismissed]
    path.write_text(
        "".join(
            json.dumps(notification_store_wire_to_json_dict(row)) + "\n" for row in rows
        ),
        encoding="utf-8",
    )

    outcome = facade.compact_notification_store(path)

    assert outcome.archived_count == 1_001
    assert outcome.live_bytes_after < outcome.live_bytes_before
    live = facade.read_notifications_snapshot(path, include_dismissed=True)
    live_ids = {row.id for row in live.notifications}
    assert {"unread", "actionable", "recent-dismissed", "snoozed-dismissed"} <= live_ids
    assert "old-dismissed-0000" not in live_ids
    unread_row = next(row for row in live.notifications if row.id == "unread")
    actionable_row = next(row for row in live.notifications if row.id == "actionable")
    assert unread_row.read is False
    assert unread_row.dismissed is False
    assert actionable_row.action == "PlanApproval"
    archive = Path(outcome.archive_path)
    archived_ids = {
        json.loads(line)["id"]
        for line in archive.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    assert "old-dismissed-0000" in archived_ids
    assert "unread" not in archived_ids
    assert "actionable" not in archived_ids

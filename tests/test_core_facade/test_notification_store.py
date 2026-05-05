"""Tests for the Rust notification-store facade."""

from __future__ import annotations

import shutil
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from sase.core import notification_store_facade as facade
from sase.core.notification_store_wire import (
    NOTIFICATION_STORE_WIRE_SCHEMA_VERSION,
    NotificationAgentKeyWire,
    NotificationCountsWire,
    NotificationStateUpdateWire,
    NotificationStoreStatsWire,
    notification_from_dict,
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
    read: bool = False,
    muted: bool = False,
    snooze_until: str | None = None,
) -> Notification:
    return Notification(
        id=id,
        timestamp="2026-04-30T12:00:00+00:00",
        sender=sender,
        notes=["note"],
        action=action,
        read=read,
        muted=muted,
        snooze_until=snooze_until,
    )


def _fake_module(monkeypatch: pytest.MonkeyPatch, **bindings: Any) -> None:
    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    for name, binding in bindings.items():
        setattr(fake, name, binding)
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, fake)


def _skip_without_notification_bindings() -> None:
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    if not hasattr(rust_module, "read_notifications_snapshot"):
        pytest.skip("sase_core_rs is too old (no notification store bindings).")


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
                    "action": "PlanApproval",
                    "action_data": {"agent_cl_name": "cl"},
                    "read": False,
                    "dismissed": False,
                    "silent": False,
                    "muted": False,
                    "snooze_until": None,
                }
            ],
            "counts": {"priority": 1, "rest": 0, "muted": 0},
            "expired_ids": [],
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
    assert isinstance(snapshot.notifications[0], Notification)


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


def test_wire_helpers_rehydrate_and_serialize_agent_keys() -> None:
    n = notification_from_dict(
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
    assert NotificationCountsWire(priority=1).priority == 1
    assert NotificationStoreStatsWire(total_lines=3).total_lines == 3
    assert notification_store_wire_to_json_dict(update) == {
        "kind": "dismiss_matching_agents",
        "agents": [{"cl_name": "cl", "raw_suffix": "20260430120000"}],
    }


def test_real_extension_round_trips_store_operations(tmp_path: Path) -> None:
    _skip_without_notification_bindings()
    path = tmp_path / "notifications.jsonl"

    append = facade.append_notification(path, _notification("n1", sender="axe"))
    assert append.appended_count == 1
    assert append.notifications[0].id == "n1"

    mark = facade.apply_notification_state_update(
        path, NotificationStateUpdateWire(kind="mark_read", id="n1")
    )
    assert mark.matched_count == 1
    assert mark.changed_count == 1
    assert mark.notifications[0].read is True

    snapshot = facade.read_notifications_snapshot(path)
    assert snapshot.counts.priority == 0
    assert snapshot.notifications[0].read is True

    rewrite = facade.rewrite_notifications(path, [_notification("n2")])
    assert rewrite.rewritten is True
    assert [n.id for n in rewrite.notifications] == ["n2"]


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
    assert active.counts.priority == 6
    assert active.counts.muted == 2


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
    assert snapshot.notifications[0].snooze_until is None

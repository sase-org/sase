"""Tests for notification-store wire dataclass serialization/hydration."""

from __future__ import annotations

from sase.core.notification_store_wire import (
    _NotificationCountsWire,
    NotificationAgentKeyWire,
    NotificationStateUpdateWire,
    _NotificationStoreStatsWire,
    _notification_from_dict,
    notification_store_wire_to_json_dict,
)


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

"""Tests for shared notification pending-action storage."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import patch

from sase.notifications import pending_actions
from sase.notifications.models import Notification


def _notification(
    notification_id: str,
    action: str,
    action_data: dict[str, str],
    *,
    files: list[str] | None = None,
) -> Notification:
    return Notification(
        id=notification_id,
        timestamp="2026-05-06T12:00:00+00:00",
        sender="test",
        notes=["note"],
        files=files or [],
        action=action,
        action_data=action_data,
    )


def test_register_and_resolve_shared_pending_action_store(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "pending_actions" / "actions.json"
    with patch.object(pending_actions, "PENDING_ACTIONS_PATH", store_path):
        n1 = _notification("abcdef01-full", "PlanApproval", {"response_dir": "x"})
        n2 = _notification("abcdef02-full", "PlanApproval", {"response_dir": "x"})

        pending_actions.register_notification(n1, now=10.0)
        pending_actions.register_notification(n2, now=10.0)

        assert pending_actions.resolve_prefix("abcdef01").notification_id == n1.id
        assert pending_actions.resolve_prefix("abcdef").resolution == "ambiguous_prefix"


def test_pending_action_writer_reaps_only_targeted_stale_temp_siblings(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "pending_actions" / "actions.json"
    store_path.parent.mkdir()
    stale = store_path.parent / ".actions.json.old.tmp"
    fresh = store_path.parent / ".actions.json.fresh.tmp"
    unrelated = store_path.parent / ".other.json.old.tmp"
    near_match = store_path.parent / ".actions.json.tmp"
    for path in (stale, fresh, unrelated, near_match):
        path.write_text("temp", encoding="utf-8")
    old = time.time() - 25 * 60 * 60
    os.utime(stale, (old, old))
    os.utime(unrelated, (old, old))
    os.utime(near_match, (old, old))

    with patch.object(pending_actions, "PENDING_ACTIONS_PATH", store_path):
        pending_actions.register_notification(
            _notification("abcdef01-full", "PlanApproval", {"response_dir": "x"})
        )

    assert not stale.exists()
    assert fresh.exists()
    assert unrelated.exists()
    assert near_match.exists()


def test_pending_action_state_detects_external_handled_and_stale(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "pending_actions" / "actions.json"
    response_dir = tmp_path / "plan"
    response_dir.mkdir()
    (response_dir / "plan_request.json").write_text("{}", encoding="utf-8")
    notification = _notification(
        "plan-row",
        "PlanApproval",
        {"response_dir": str(response_dir)},
    )
    with patch.object(pending_actions, "PENDING_ACTIONS_PATH", store_path):
        pending_actions.register_notification(notification, now=10.0)

        assert (
            pending_actions.action_state_for_notification(notification, now=11.0)
            == "available"
        )
        assert (
            pending_actions.action_state_for_notification(
                notification,
                now=10.0 + pending_actions.STALE_THRESHOLD_SECONDS + 1,
            )
            == "stale"
        )

        (response_dir / "plan_response.json").write_text("{}", encoding="utf-8")
        assert (
            pending_actions.action_state_for_notification(
                notification,
                now=10.0 + pending_actions.STALE_THRESHOLD_SECONDS + 1,
            )
            == "already_handled"
        )


def test_launch_approval_pending_action_state(tmp_path: Path) -> None:
    store_path = tmp_path / "pending_actions" / "actions.json"
    response_dir = tmp_path / "launch"
    response_dir.mkdir()
    (response_dir / "launch_request.json").write_text("{}", encoding="utf-8")
    notification = _notification(
        "launch-row",
        "LaunchApproval",
        {"response_dir": str(response_dir), "request_id": "launch-1"},
    )
    with patch.object(pending_actions, "PENDING_ACTIONS_PATH", store_path):
        pending_actions.register_notification(notification, now=10.0)

        store = pending_actions.read_pending_action_store()
        assert store["actions"]["launch-r"]["action_kind"] == "launch_approval"
        assert (
            pending_actions.action_state_for_notification(notification, now=11.0)
            == "available"
        )

        (response_dir / "launch_response.json").write_text("{}", encoding="utf-8")
        assert (
            pending_actions.action_state_for_notification(notification, now=11.0)
            == "already_handled"
        )


def test_pending_action_state_stales_unregistered_old_notification(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "pending_actions" / "actions.json"
    response_dir = tmp_path / "plan"
    response_dir.mkdir()
    (response_dir / "plan_request.json").write_text("{}", encoding="utf-8")
    notification = Notification(
        id="old-plan-row",
        timestamp="2026-05-06T12:00:00+00:00",
        sender="test",
        notes=["note"],
        files=[],
        action="PlanApproval",
        action_data={"response_dir": str(response_dir)},
    )

    stale_now = 1_778_155_201.0  # 2026-05-07T12:00:01+00:00
    with patch.object(pending_actions, "PENDING_ACTIONS_PATH", store_path):
        assert (
            pending_actions.action_state_for_notification(notification, now=stale_now)
            == "stale"
        )


def test_legacy_telegram_pending_actions_are_compatibility_source(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "pending_actions" / "actions.json"
    legacy_path = tmp_path / "telegram" / "pending_actions.json"
    legacy_path.parent.mkdir()
    legacy_path.write_text(
        '{"abcd1234":{"notification_id":"abcd1234-full","action":"PlanApproval",'
        '"action_data":{"response_dir":"/tmp/plan"},"message_id":42,'
        '"chat_id":"chat","created_at":10.0}}',
        encoding="utf-8",
    )
    with (
        patch.object(pending_actions, "PENDING_ACTIONS_PATH", store_path),
        patch.object(
            pending_actions,
            "LEGACY_TELEGRAM_PENDING_ACTIONS_PATH",
            legacy_path,
        ),
    ):
        store = pending_actions._load_store(include_legacy=True)

    entry = store["actions"]["abcd1234"]
    assert entry["notification_id"] == "abcd1234-full"
    assert entry["transports"][0]["transport"] == "telegram_legacy"


def test_merge_transport_record_updates_existing_entry(tmp_path: Path) -> None:
    store_path = tmp_path / "pending_actions" / "actions.json"
    with patch.object(pending_actions, "PENDING_ACTIONS_PATH", store_path):
        notification = _notification(
            "abcdef01-full", "PlanApproval", {"response_dir": "x"}
        )
        pending_actions.register_notification(notification, now=10.0)

        assert pending_actions.merge_transport_record(
            notification.id,
            "telegram",
            {"chat_id": "chat", "message_id": 42},
            now=20.0,
        )

        store = pending_actions.read_pending_action_store()
        entry = store["actions"]["abcdef01"]
        telegram = next(t for t in entry["transports"] if t["transport"] == "telegram")
        assert telegram["record"] == {"chat_id": "chat", "message_id": 42}
        assert entry["updated_at_unix"] == 20.0

        # Re-merging the same transport replaces (does not duplicate) the record.
        assert pending_actions.merge_transport_record(
            notification.id, "telegram", {"chat_id": "chat", "message_id": 99}
        )
        store = pending_actions.read_pending_action_store()
        entry = store["actions"]["abcdef01"]
        telegram_records = [
            t for t in entry["transports"] if t["transport"] == "telegram"
        ]
        assert len(telegram_records) == 1
        assert telegram_records[0]["record"]["message_id"] == 99


def test_merge_transport_record_missing_entry_returns_false(tmp_path: Path) -> None:
    store_path = tmp_path / "pending_actions" / "actions.json"
    with patch.object(pending_actions, "PENDING_ACTIONS_PATH", store_path):
        assert not pending_actions.merge_transport_record(
            "nope-full", "telegram", {"chat_id": "c", "message_id": 1}
        )


def test_mark_already_handled_sets_state(tmp_path: Path) -> None:
    store_path = tmp_path / "pending_actions" / "actions.json"
    with patch.object(pending_actions, "PENDING_ACTIONS_PATH", store_path):
        notification = _notification(
            "abcdef01-full", "PlanApproval", {"response_dir": "x"}
        )
        pending_actions.register_notification(notification, now=10.0)

        assert pending_actions.mark_already_handled(
            notification.id, source="tui", action="approve", now=30.0
        )

        store = pending_actions.read_pending_action_store()
        entry = store["actions"]["abcdef01"]
        assert entry["state"] == "already_handled"
        assert entry["handled_source"] == "tui"
        assert entry["handled_action"] == "approve"
        assert entry["handled_at_unix"] == 30.0
        assert (
            pending_actions.action_state_for_notification(notification, now=31.0)
            == "already_handled"
        )

        assert not pending_actions.mark_already_handled("missing-id", source="tui")


def test_mark_plan_approval_auto_handled_matches_plan_and_identity(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "pending_actions" / "actions.json"
    plan_file = str(tmp_path / "plan.md")
    with patch.object(pending_actions, "PENDING_ACTIONS_PATH", store_path):
        target = _notification(
            "abcdef01-full",
            "PlanApproval",
            {"response_dir": "x", "agent_root_timestamp": "root-1"},
            files=[plan_file],
        )
        # Same plan file but a different agent family — must stay available.
        other_agent = _notification(
            "abcdef02-full",
            "PlanApproval",
            {"response_dir": "y", "agent_root_timestamp": "root-2"},
            files=[plan_file],
        )
        # Same agent family but a different plan — must stay available.
        other_plan = _notification(
            "abcdef03-full",
            "PlanApproval",
            {"response_dir": "z", "agent_root_timestamp": "root-1"},
            files=[str(tmp_path / "other.md")],
        )
        for n in (target, other_agent, other_plan):
            pending_actions.register_notification(n, now=10.0)
        pending_actions.merge_transport_record(
            target.id, "telegram", {"chat_id": "chat", "message_id": 7}, now=10.0
        )

        marked = pending_actions.mark_plan_approval_auto_handled(
            plan_file=plan_file,
            agent_root_timestamp="root-1",
            now=40.0,
        )

        assert marked == [target.id]
        store = pending_actions.read_pending_action_store()
        assert store["actions"]["abcdef01"]["state"] == "already_handled"
        assert store["actions"]["abcdef01"]["handled_source"] == "auto_approve"
        # The Telegram transport survives so inbound cleanup can find it.
        assert any(
            t["transport"] == "telegram"
            for t in store["actions"]["abcdef01"]["transports"]
        )
        assert store["actions"]["abcdef02"]["state"] == "available"
        assert store["actions"]["abcdef03"]["state"] == "available"


def test_mark_plan_approval_auto_handled_requires_identity(tmp_path: Path) -> None:
    store_path = tmp_path / "pending_actions" / "actions.json"
    plan_file = str(tmp_path / "plan.md")
    with patch.object(pending_actions, "PENDING_ACTIONS_PATH", store_path):
        notification = _notification(
            "abcdef01-full",
            "PlanApproval",
            {"response_dir": "x", "agent_name": "plan.agent"},
            files=[plan_file],
        )
        pending_actions.register_notification(notification, now=10.0)

        # No identity field provided → never broad-matches on plan file alone.
        assert (
            pending_actions.mark_plan_approval_auto_handled(plan_file=plan_file) == []
        )
        store = pending_actions.read_pending_action_store()
        assert store["actions"]["abcdef01"]["state"] == "available"


def test_mark_plan_approval_auto_handled_promotes_legacy_record(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "pending_actions" / "actions.json"
    legacy_path = tmp_path / "telegram" / "pending_actions.json"
    legacy_path.parent.mkdir()
    plan_file = str(tmp_path / "plan.md")
    legacy_path.write_text(
        json.dumps(
            {
                "abcd1234": {
                    "notification_id": "abcd1234-full",
                    "action": "PlanApproval",
                    "action_data": {
                        "response_dir": "/tmp/plan",
                        "agent_name": "plan.agent",
                    },
                    "plan_file": plan_file,
                    "message_id": 42,
                    "chat_id": "chat",
                    "created_at": 10.0,
                }
            }
        ),
        encoding="utf-8",
    )
    with (
        patch.object(pending_actions, "PENDING_ACTIONS_PATH", store_path),
        patch.object(
            pending_actions, "LEGACY_TELEGRAM_PENDING_ACTIONS_PATH", legacy_path
        ),
    ):
        marked = pending_actions.mark_plan_approval_auto_handled(
            plan_file=plan_file,
            agent_name="plan.agent",
            now=50.0,
        )

        assert marked == ["abcd1234-full"]
        # The matched legacy record is promoted into the shared store, handled.
        shared = pending_actions.read_pending_action_store()
        promoted = shared["actions"]["abcd1234"]
        assert promoted["state"] == "already_handled"
        record = promoted["transports"][0]["record"]
        assert record["chat_id"] == "chat"
        assert record["message_id"] == 42

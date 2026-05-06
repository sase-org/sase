"""Tests for shared notification pending-action storage."""

from __future__ import annotations

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


def test_register_resolve_and_cleanup_shared_pending_action_store(
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

        removed = pending_actions.cleanup_stale(
            now=10.0 + pending_actions.STALE_THRESHOLD_SECONDS + 1
        )
        assert removed == ["abcdef01", "abcdef02"]
        assert pending_actions.load_store()["actions"] == {}


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
        store = pending_actions.load_store(include_legacy=True)

    entry = store["actions"]["abcd1234"]
    assert entry["notification_id"] == "abcd1234-full"
    assert entry["transports"][0]["transport"] == "telegram_legacy"

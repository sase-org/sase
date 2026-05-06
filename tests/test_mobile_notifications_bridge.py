"""Tests for the mobile notification host bridge."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sase.integrations.mobile_notifications import (
    MobilePlanActionError,
    execute_mobile_plan_action,
    read_mobile_notification_snapshot,
    resolve_mobile_notification_detail,
)
from sase.notifications.models import Notification


def _snapshot(rows: list[Notification]) -> SimpleNamespace:
    return SimpleNamespace(
        notifications=rows,
        counts=SimpleNamespace(priority=1, rest=1, muted=0),
        expired_ids=["expired-row"],
    )


def _notification(
    notification_id: str,
    timestamp: str,
    *,
    action: str | None = None,
    read: bool = False,
    dismissed: bool = False,
    silent: bool = False,
    files: list[str] | None = None,
    action_data: dict[str, str] | None = None,
) -> Notification:
    return Notification(
        id=notification_id,
        timestamp=timestamp,
        sender="plan" if action == "PlanApproval" else "user-workflow",
        notes=[f"note {notification_id}"],
        files=files or [],
        action=action,
        action_data=action_data or {},
        read=read,
        dismissed=dismissed,
        silent=silent,
    )


def test_mobile_bridge_filters_orders_and_preserves_counts() -> None:
    rows = [
        _notification("old", "2026-05-06T13:00:00+00:00"),
        _notification("read", "2026-05-06T14:00:00+00:00", read=True),
        _notification("silent", "2026-05-06T15:00:00+00:00", silent=True),
        _notification(
            "plan",
            "2026-05-06T16:00:00+00:00",
            action="PlanApproval",
        ),
    ]

    with patch(
        "sase.integrations.mobile_notifications.read_notification_snapshot",
        return_value=_snapshot(rows),
    ) as read_snapshot:
        snapshot = read_mobile_notification_snapshot(unread_only=True, limit=1)

    read_snapshot.assert_called_once_with(
        include_dismissed=False,
        expire_due_snoozes=True,
    )
    assert [row.id for row in snapshot.rows] == ["plan"]
    assert snapshot.rows[0].priority is True
    assert snapshot.counts.priority == 1
    assert snapshot.expired_ids == ["expired-row"]


def test_mobile_bridge_keeps_raw_host_paths_and_safe_display_paths(
    tmp_path: Path,
) -> None:
    home_file = str(Path.home() / ".sase" / "digest.txt")
    rows = [
        _notification(
            "detail",
            "2026-05-06T13:00:00+00:00",
            action="PlanApproval",
            files=[home_file, str(tmp_path / "note.md")],
            action_data={"response_dir": home_file, "session_id": "s1"},
        )
    ]

    with patch(
        "sase.integrations.mobile_notifications.read_notification_snapshot",
        return_value=_snapshot(rows),
    ):
        detail = resolve_mobile_notification_detail("detail")

    assert detail is not None
    assert detail.display_files[0] == "~/.sase/digest.txt"
    assert detail.host_files[0] == home_file
    assert detail.display_action_data["response_dir"] == "~/.sase/digest.txt"
    assert detail.host_action_data["response_dir"] == home_file
    assert detail.host_action_data["session_id"] == "s1"
    assert detail.action_state == "available"


def test_execute_mobile_plan_action_writes_response_and_side_effects(
    tmp_path: Path,
) -> None:
    response_dir = tmp_path / "agent" / "plan_approval"
    response_dir.mkdir(parents=True)
    (response_dir / "plan_request.json").write_text("{}", encoding="utf-8")
    plan_file = tmp_path / "plan.md"
    plan_file.write_text("# Plan\n", encoding="utf-8")
    row = _notification(
        "abcdef12-plan",
        "2026-05-06T13:00:00+00:00",
        action="PlanApproval",
        files=[str(plan_file)],
        action_data={"response_dir": str(response_dir)},
    )

    with (
        patch(
            "sase.integrations.mobile_notifications.read_notification_snapshot",
            return_value=_snapshot([row]),
        ),
        patch("sase.notifications.pending_actions.resolve_prefix") as resolve,
        patch("sase.notifications.mark_dismissed") as mark_dismissed,
    ):
        resolve.return_value = SimpleNamespace(
            notification_id="abcdef12-plan",
            prefix="abcdef12",
            prefix_len=8,
            resolution="unique_prefix",
        )
        result = execute_mobile_plan_action(
            "abcdef12",
            "run",
            coder_prompt="Focus tests",
        )

    assert result.notification_id == "abcdef12-plan"
    assert result.response_json == {
        "action": "approve",
        "commit_plan": False,
        "run_coder": True,
        "coder_prompt": "Focus tests",
    }
    assert (response_dir / "plan_response.json").read_text(encoding="utf-8") == (
        "{\n"
        '  "action": "approve",\n'
        '  "commit_plan": false,\n'
        '  "run_coder": true,\n'
        '  "coder_prompt": "Focus tests"\n'
        "}\n"
    )
    mark_dismissed.assert_called_once_with("abcdef12-plan")


def test_execute_mobile_plan_action_rejects_duplicate_response(
    tmp_path: Path,
) -> None:
    response_dir = tmp_path / "agent" / "plan_approval"
    response_dir.mkdir(parents=True)
    (response_dir / "plan_request.json").write_text("{}", encoding="utf-8")
    (response_dir / "plan_response.json").write_text(
        '{"action":"approve"}', encoding="utf-8"
    )
    plan_file = tmp_path / "plan.md"
    plan_file.write_text("# Plan\n", encoding="utf-8")
    row = _notification(
        "abcdef12-plan",
        "2026-05-06T13:00:00+00:00",
        action="PlanApproval",
        files=[str(plan_file)],
        action_data={"response_dir": str(response_dir)},
    )

    with (
        patch(
            "sase.integrations.mobile_notifications.read_notification_snapshot",
            return_value=_snapshot([row]),
        ),
        patch("sase.notifications.pending_actions.resolve_prefix") as resolve,
    ):
        resolve.return_value = SimpleNamespace(
            notification_id="abcdef12-plan",
            prefix="abcdef12",
            prefix_len=8,
            resolution="unique_prefix",
        )
        try:
            execute_mobile_plan_action("abcdef12", "approve")
        except MobilePlanActionError as exc:
            assert exc.code == "conflict_already_handled"
        else:
            raise AssertionError("expected duplicate response conflict")

"""Tests for TUI notification modal response writes."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.actions.agents._notification_modal_responses import (
    write_workflow_action_response,
)
from sase.notifications.models import Notification
from sase.notifications.pending_actions import (
    read_pending_action_store,
    register_notification,
)


def _plan_notification(notification_id: str) -> Notification:
    return Notification(
        id=notification_id,
        timestamp="2026-05-06T12:00:00+00:00",
        sender="plan",
        notes=["Plan ready"],
        files=["/tmp/plan.md"],
        action="PlanApproval",
        action_data={"response_dir": "/tmp/plan"},
    )


def test_tui_plan_response_marks_shared_action_handled(tmp_path: Path) -> None:
    register_notification(_plan_notification("abcdef12-plan"), now=10.0)
    response_path = tmp_path / "plan_response.json"

    write_workflow_action_response(
        response_path,
        {"action": "reject"},
        action_kind="plan_approval",
        notification_id="abcdef12-plan",
    )

    assert response_path.exists()
    entry = read_pending_action_store()["actions"]["abcdef12"]
    assert entry["state"] == "already_handled"
    assert entry["handled_source"] == "tui"
    assert entry["handled_action"] == "reject"


def test_tui_non_plan_response_does_not_mark_handled(tmp_path: Path) -> None:
    register_notification(_plan_notification("abcdef12-plan"), now=10.0)
    response_path = tmp_path / "hitl_response.json"

    write_workflow_action_response(
        response_path,
        {"action": "accept"},
        action_kind="hitl",
        notification_id="abcdef12-plan",
    )

    entry = read_pending_action_store()["actions"]["abcdef12"]
    assert entry["state"] == "available"

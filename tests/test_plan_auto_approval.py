"""Tests for automatic plan approval behavior."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sase.llm_provider._plan_utils import (
    _POLL_INTERVAL,
    PlanApprovalResult,
    handle_plan_approval,
)
from sase.main.plan_approve_handler import (
    get_auto_plan_approval_action,
    is_auto_approve_active,
)
from sase.notification_gates.models import GateError

from tests.conftest import redirect_sase_home
from tests.plan_validation_helpers import VALID_EPIC_PLAN, VALID_TALE_PLAN


def _plan_gate_bundle(sase_home: Path, tier: str, session_id: str) -> Path:
    kind = "epic_plan" if tier == "epic" else "plan"
    bundle = sase_home / "interaction_requests" / kind / session_id
    assert bundle.is_dir()
    return bundle


def test_handle_plan_approval_auto_approve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bare auto approval uses the recommended tale extras preset."""
    sase_home = redirect_sase_home(monkeypatch, tmp_path / ".sase")
    plan = tmp_path / "plan.md"
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    with patch(
        "sase.main.plan_approve_handler.get_auto_plan_approval_action",
        return_value="approve",
    ):
        result = handle_plan_approval(str(plan), "session-123")
    _plan_gate_bundle(sase_home, "tale", "session-123")
    assert result == PlanApprovalResult(
        action="approve", plan_file=str(plan), commit_plan=True
    )


def test_handle_plan_approval_auto_epic_skips_notification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plan-specific auto-epic enters the existing epic action path."""
    plan = tmp_path / "plan.md"
    plan.write_text(VALID_EPIC_PLAN, encoding="utf-8")
    sase_home = redirect_sase_home(monkeypatch, tmp_path / ".sase")
    with (
        patch(
            "sase.main.plan_approve_handler.get_auto_plan_approval_action",
            return_value="epic",
        ),
        patch(
            "sase.plan_approval_actions.prepare_epic_launch",
            return_value=SimpleNamespace(task_id="task-auto-epic"),
        ),
    ):
        result = handle_plan_approval(str(plan), "session-123")

    _plan_gate_bundle(sase_home, "epic", "session-123")
    assert result == PlanApprovalResult(action="epic", plan_file=str(plan))
    assert result.epic_launch_owner == "host"


def test_handle_plan_approval_auto_tale_skips_notification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plan-specific auto-tale enters the auto-approval action path."""
    plan = tmp_path / "plan.md"
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    sase_home = redirect_sase_home(monkeypatch, tmp_path / ".sase")
    with patch(
        "sase.main.plan_approve_handler.get_auto_plan_approval_action",
        return_value="tale",
    ):
        result = handle_plan_approval(str(plan), "session-123")

    _plan_gate_bundle(sase_home, "tale", "session-123")
    assert result == PlanApprovalResult(
        action="approve", plan_file=str(plan), commit_plan=True
    )


def test_invalid_auto_epic_does_not_consume_pending_action(tmp_path: Path) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")

    with (
        patch(
            "sase.main.plan_approve_handler.get_auto_plan_approval_action",
            return_value="epic",
        ),
        patch(
            "sase.llm_provider._plan_utils._mark_auto_approved_plan_handled"
        ) as mark_handled,
        pytest.raises(GateError, match="conflicts with the authored tale plan tier"),
    ):
        handle_plan_approval(str(plan), "session-123", agent_name="planner")

    mark_handled.assert_not_called()


@pytest.mark.parametrize("auto_action", ["approve", "tale", "epic"])
def test_handle_plan_approval_rechecks_auto_approve_while_waiting(
    auto_action: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pending plan unblocks when auto-approve is enabled after notification."""
    from sase.notifications import load_notifications, pending_actions

    plan_file = str(tmp_path / "plan.md")
    tier = "epic" if auto_action == "epic" else "tale"
    Path(plan_file).write_text(VALID_EPIC_PLAN if tier == "epic" else VALID_TALE_PLAN)
    session_id = f"waiting-auto-{auto_action}"
    sase_home = redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.setenv("SASE_AGENT_ROOT_TIMESTAMP", "root-1")

    with (
        patch(
            "sase.main.plan_approve_handler.get_auto_plan_approval_action",
            side_effect=[None, None, auto_action],
        ) as get_auto_action,
        patch("sase.notification_gates.poller.time.sleep") as sleep,
        patch("sase.main.plan_approve_handler.send_desktop_notification"),
        patch("sase.main.plan_approve_handler.ring_tmux_bell"),
        patch("sase.main.plan_approve_handler.get_tmux_prefix", return_value=""),
        patch(
            "sase.plan_approval_actions.prepare_epic_launch",
            return_value=SimpleNamespace(task_id="task-waiting-auto"),
        ),
    ):
        result = handle_plan_approval(
            plan_file,
            session_id,
            agent_name="planner.agent",
        )

    response_dir = _plan_gate_bundle(sase_home, tier, session_id)
    assert result == PlanApprovalResult(
        action="epic" if auto_action == "epic" else "approve",
        plan_file=plan_file,
        commit_plan=True,
    )
    assert get_auto_action.call_count == 3
    if auto_action == "epic":
        assert result.epic_launch_owner == "host"
    sleep.assert_any_call(_POLL_INTERVAL)

    assert (response_dir / "response.json").exists()
    assert (response_dir / "request.json").exists()

    store = pending_actions.read_pending_action_store()
    [entry] = store["actions"].values()
    assert entry["state"] == "already_handled"
    assert entry["handled_source"] == "auto_approve"
    assert entry["handled_action"] == ("epic" if auto_action == "epic" else "approve")

    notifications = load_notifications(include_dismissed=True)
    assert len(notifications) == 1
    assert notifications[0].dismissed is True
    assert load_notifications() == []


def test_handle_plan_approval_killed_check_wins_over_waiting_auto_approve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A kill during the wait returns None without consuming a later auto action."""
    from sase.notifications import load_notifications, pending_actions

    plan_file = str(tmp_path / "plan.md")
    Path(plan_file).write_text(VALID_TALE_PLAN)
    session_id = "waiting-auto-killed"
    sase_home = redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.setenv("SASE_AGENT_ROOT_TIMESTAMP", "root-1")

    with (
        patch(
            "sase.main.plan_approve_handler.get_auto_plan_approval_action",
            side_effect=[None, "approve"],
        ) as get_auto_action,
        patch("sase.notification_gates.poller.time.sleep") as sleep,
        patch("sase.main.plan_approve_handler.send_desktop_notification"),
        patch("sase.main.plan_approve_handler.ring_tmux_bell"),
        patch("sase.main.plan_approve_handler.get_tmux_prefix", return_value=""),
    ):
        result = handle_plan_approval(
            plan_file,
            session_id,
            killed_check=lambda: True,
            agent_name="planner.agent",
        )

    assert result is None
    assert get_auto_action.call_count == 1
    sleep.assert_not_called()

    response_dir = _plan_gate_bundle(sase_home, "tale", session_id)
    assert (response_dir / "request.json").exists()
    assert not (response_dir / "response.json").exists()

    store = pending_actions.read_pending_action_store()
    [entry] = store["actions"].values()
    assert entry["state"] == "already_handled"
    assert entry["handled_source"] == "requester"

    notifications = load_notifications(include_dismissed=True)
    assert len(notifications) == 1
    assert notifications[0].dismissed is True


def test_handle_plan_approval_auto_marks_stale_telegram_action_handled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Auto-approval dismisses a stale Telegram plan keyboard via shared state.

    A prior run left a registered PlanApproval action with a Telegram transport
    record. When the same plan/agent is auto-approved (no notification, no
    response file), the shared action must flip to ``already_handled`` so the
    Telegram inbound chop removes the inline keyboard.
    """
    from sase.notifications import pending_actions
    from sase.notifications.models import Notification

    store_path = tmp_path / "pending_actions" / "actions.json"
    plan_file = str(tmp_path / "plan.md")
    Path(plan_file).write_text(VALID_TALE_PLAN, encoding="utf-8")
    sase_home = redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.setattr(pending_actions, "PENDING_ACTIONS_PATH", store_path)
    monkeypatch.setenv("SASE_AGENT_ROOT_TIMESTAMP", "root-1")

    stale = Notification(
        id="abcdef01-full",
        timestamp="2026-05-06T12:00:00+00:00",
        sender="plan",
        notes=["Plan ready"],
        files=[plan_file],
        action="PlanApproval",
        action_data={"response_dir": "x", "agent_root_timestamp": "root-1"},
    )
    pending_actions.register_notification(stale, now=10.0)
    pending_actions.merge_transport_record(
        stale.id, "telegram", {"chat_id": "chat", "message_id": 7}, now=10.0
    )

    with patch(
        "sase.main.plan_approve_handler.get_auto_plan_approval_action",
        return_value="approve",
    ):
        result = handle_plan_approval(plan_file, "session-xyz", agent_name="plan.agent")

    _plan_gate_bundle(sase_home, "tale", "session-xyz")
    assert result == PlanApprovalResult(
        action="approve", plan_file=plan_file, commit_plan=True
    )
    store = pending_actions.read_pending_action_store()
    assert store["actions"]["abcdef01"]["state"] == "already_handled"
    assert store["actions"]["abcdef01"]["handled_action"] == "approve"


def test_auto_plan_action_reads_epic_from_agent_meta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        '{"auto_approve_plan_action": "epic", "approve": true}'
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))

    assert get_auto_plan_approval_action() == "epic"
    assert is_auto_approve_active() is True


def test_auto_plan_action_reads_tale_from_agent_meta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text('{"auto_approve_plan_action": "tale"}')
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))

    assert get_auto_plan_approval_action() == "tale"


def test_normalize_plan_action_recognizes_tale() -> None:
    """_normalize_plan_action accepts tale alongside approve and epic."""
    from sase.main.plan_approve_handler import _normalize_plan_action

    assert _normalize_plan_action("tale") == "tale"
    assert _normalize_plan_action("  TALE  ") == "tale"
    assert _normalize_plan_action("epic") == "epic"
    assert _normalize_plan_action("approve") == "approve"
    assert _normalize_plan_action("bogus") is None
    assert _normalize_plan_action(None) is None

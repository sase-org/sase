"""Table-driven routing coverage for the shared notification dispatcher."""

from __future__ import annotations

from typing import Any

import pytest

from sase.ace.tui.actions.agents._notification_dispatch import open_notification_action
from sase.notifications import Notification


def _notification(action: str | None) -> Notification:
    return Notification(
        id=f"n-{action or 'none'}",
        timestamp="2026-09-18T12:00:00+00:00",
        sender="test",
        action=action,
        action_data={},
    )


class _DispatchApp:
    def __init__(self) -> None:
        self.pending_reads = 0
        self.notifies: list[tuple[str, Any]] = []

    def _read_notification_pending_actions_from_provider(self) -> object:
        self.pending_reads += 1
        return object()

    def notify(self, message: str, severity: str | None = None) -> None:
        self.notifies.append((message, severity))


_ROUTED_ACTIONS: list[tuple[str, str, bool]] = [
    # (action, handler attribute, expects privileged pending-actions read)
    ("JumpToPatch", "handle_jump_to_patch", False),
    ("JumpToMentorReview", "handle_jump_to_mentor_review", False),
    ("JumpToAgent", "handle_jump_to_agent", False),
    ("Tmux", "handle_tmux", False),
    ("HITL", "handle_hitl", True),
    ("PlanApproval", "handle_plan_approval", True),
    ("EpicApproval", "handle_plan_approval", True),
    ("UserQuestion", "handle_user_question", True),
    ("LaunchApproval", "handle_launch_approval", True),
    ("RemoteAttention", "handle_remote_attention_notification", False),
    ("SudoRequest", "handle_sudo_request", True),
    ("TaskTriage", "handle_custom_gate", True),
    ("BeadSnooze", "handle_custom_gate", True),
    ("FlagTriage", "handle_custom_gate", True),
    ("BeadStaleCleanup", "handle_custom_gate", True),
    ("PluginsRequired", "handle_custom_gate", True),
    ("CustomGate", "handle_custom_gate", True),
    ("ViewErrorReport", "handle_view_error_report", False),
    ("GateExecutionFailed", "handle_gate_execution_failed", False),
    ("ViewReport", "handle_view_report", False),
    ("OpenLaunchControl", "handle_open_launch_control", False),
]

_HANDLER_ATTRS = sorted({handler for _, handler, _ in _ROUTED_ACTIONS})


@pytest.mark.parametrize(
    ("action", "handler_name", "expect_pending_read"), _ROUTED_ACTIONS
)
def test_every_action_routes_to_its_handler(
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    handler_name: str,
    expect_pending_read: bool,
) -> None:
    calls: dict[str, list[str]] = {name: [] for name in _HANDLER_ATTRS}
    for name in _HANDLER_ATTRS:
        monkeypatch.setattr(
            f"sase.ace.tui.actions.agents._notification_actions.{name}",
            lambda app, notification, _name=name: calls[_name].append(notification.id),
        )
    app = _DispatchApp()
    notification = _notification(action)

    assert open_notification_action(app, notification) is True

    assert calls[handler_name] == [notification.id]
    for name, seen in calls.items():
        if name != handler_name:
            assert seen == []
    assert app.pending_reads == (1 if expect_pending_read else 0)
    assert app.notifies == []


def test_sudo_request_wins_over_generic_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SudoRequest has a generic-form adapter but keeps its own handler."""
    from sase.notification_gates.registry import adapter_for_action

    assert adapter_for_action("SudoRequest") is not None
    assert adapter_for_action("SudoRequest").generic_form is True  # type: ignore[union-attr]

    seen: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_actions.handle_sudo_request",
        lambda app, notification: seen.append("sudo"),
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_actions.handle_custom_gate",
        lambda app, notification: seen.append("custom"),
    )

    assert (
        open_notification_action(_DispatchApp(), _notification("SudoRequest")) is True
    )
    assert seen == ["sudo"]


@pytest.mark.parametrize("action", [None, "", "   "])
def test_empty_action_dispatches_nothing(action: str | None) -> None:
    app = _DispatchApp()
    assert open_notification_action(app, _notification(action)) is False
    assert app.pending_reads == 0
    assert app.notifies == []


def test_unsupported_action_warns() -> None:
    app = _DispatchApp()
    assert open_notification_action(app, _notification("BogusAction")) is True
    assert app.notifies == [("Unsupported notification action: BogusAction", "warning")]

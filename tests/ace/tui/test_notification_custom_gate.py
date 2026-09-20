"""Notification action-router dispatch coverage for neutral gates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui.actions.agents._notification_handlers import handle_view_error_report
from sase.ace.tui.actions.agents._notification_provider_direct import (
    direct_unread_notification_page,
)
from sase.feature_flags import override_flags
from sase.notification_gates.failure_notifications import GATE_EXECUTION_FAILED_ACTION
from sase.notification_gates.service import create_gate
from sase.bead.task_gate import create_task_triage_gate
from sase.notifications.models import Notification
from sase.notifications.store import append_notification, load_notifications
from sase.sudo.gate import build_sudo_gate_request

from ._notification_custom_gate_helpers import (
    _NotificationFlowApp,
    _spec,
    _sudo_request,
    gate_home_fixture,
)


def test_notification_flow_dispatches_custom_gate(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    create_gate(_spec())
    notification = load_notifications()[0]
    app = _NotificationFlowApp(notification)
    dispatched: list[Any] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_actions.handle_custom_gate",
        lambda _app, selected: dispatched.append(selected),
    )

    app._show_notification_modal()

    assert dispatched == [notification]
    assert app.pending_reads == 1
    assert app.refresh_count == 1


def test_notification_flow_dispatches_sudo_before_generic_gate(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    with override_flags(agent_sudo_requests=True):
        create_gate(build_sudo_gate_request(_sudo_request()))
    notification = load_notifications()[0]
    app = _NotificationFlowApp(notification)
    sudo_dispatched: list[Any] = []
    custom_dispatched: list[Any] = []
    marked_read: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_actions.handle_sudo_request",
        lambda _app, selected: sudo_dispatched.append(selected),
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_actions.handle_custom_gate",
        lambda _app, selected: custom_dispatched.append(selected),
    )
    monkeypatch.setattr(
        "sase.notifications.mark_read",
        lambda notification_id: marked_read.append(notification_id),
    )

    app._show_notification_modal()

    assert sudo_dispatched == [notification]
    assert custom_dispatched == []
    assert marked_read == []
    assert app.pending_reads == 1
    assert app.refresh_count == 1


def test_notification_flow_dispatches_task_triage_without_marking_read(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    create_task_triage_gate(
        request_id="task-triage-ace-dispatch",
        bead_id="sase-task.1",
        project="sase",
        title="Review follow-up",
    )
    notification = load_notifications()[0]
    app = _NotificationFlowApp(notification)
    dispatched: list[Any] = []
    marked_read: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_actions.handle_custom_gate",
        lambda _app, selected: dispatched.append(selected),
    )
    monkeypatch.setattr(
        "sase.notifications.mark_read",
        lambda notification_id: marked_read.append(notification_id),
    )

    app._show_notification_modal()

    assert dispatched == [notification]
    assert marked_read == []
    assert app.pending_reads == 1
    assert app.refresh_count == 1


def test_notification_flow_warns_for_unknown_action(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    create_gate(_spec())
    notification = load_notifications()[0]
    notification.action = "FutureGate"
    app = _NotificationFlowApp(notification)
    marked_read: list[str] = []
    monkeypatch.setattr(
        "sase.notifications.mark_read",
        lambda notification_id: marked_read.append(notification_id),
    )

    app._show_notification_modal()

    assert marked_read == [notification.id]
    assert app.notices == [("Unsupported notification action: FutureGate", "warning")]


def test_notification_flow_dispatches_view_report(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    create_gate(_spec())
    notification = load_notifications()[0]
    notification.action = "ViewReport"
    notification.action_data = {
        "report": '{"title":"Report","blocks":[]}',
    }
    app = _NotificationFlowApp(notification)
    dispatched: list[Any] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_actions.handle_view_report",
        lambda _app, selected: dispatched.append(selected),
    )

    app._show_notification_modal()

    assert dispatched == [notification]
    assert app.pending_reads == 0
    assert app.refresh_count == 1


def test_notification_flow_dispatches_open_launch_control(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    create_gate(_spec())
    notification = load_notifications()[0]
    notification.action = "OpenLaunchControl"
    notification.action_data = {"provider": "claude"}
    app = _NotificationFlowApp(notification)
    dispatched: list[Any] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_actions.handle_open_launch_control",
        lambda _app, selected: dispatched.append(selected),
    )

    app._show_notification_modal()

    assert dispatched == [notification]
    assert app.pending_reads == 0
    assert app.refresh_count == 1
    assert app.notices == []


def test_notification_flow_dispatches_gate_execution_failed_to_recovery(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    create_gate(_spec())
    notification = load_notifications()[0]
    notification.action = GATE_EXECUTION_FAILED_ACTION
    notification.action_data = {"message": "redacted failure"}
    app = _NotificationFlowApp(notification)
    dispatched: list[Any] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_actions.handle_gate_execution_failed",
        lambda _app, selected: dispatched.append(selected),
    )

    app._show_notification_modal()

    assert dispatched == [notification]
    assert app.notices == []
    assert app.refresh_count == 1


def test_gate_execution_failed_report_action_has_actionable_missing_report_fallback() -> (
    None
):
    notification = Notification(
        id="failed-gate",
        timestamp="2026-09-18T00:00:00+00:00",
        sender="gate",
        action=GATE_EXECUTION_FAILED_ACTION,
        action_data={
            "message": "command failed for option accept",
            "resume_command": "sase gate answer --kind hitl --id demo --option accept --resume",
            "cancel_command": "sase gate cancel --kind hitl --id demo",
        },
    )

    class _App:
        def __init__(self) -> None:
            self.notices: list[tuple[str, str]] = []

        def notify(self, message: str, *, severity: str = "information") -> None:
            self.notices.append((message, severity))

    app = _App()

    assert handle_view_error_report(app, notification) is False
    assert app.notices == [
        (
            "Gate execution failed: command failed for option accept. "
            "No error report is available. Recovery: "
            "sase gate answer --kind hitl --id demo --option accept --resume; "
            "sase gate cancel --kind hitl --id demo",
            "warning",
        )
    ]


@pytest.mark.parametrize("action", [None, "", "   "])
def test_notification_flow_silently_marks_actionless_notification_read(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    action: str | None,
) -> None:
    del gate_home
    create_gate(_spec())
    notification = load_notifications()[0]
    notification.action = action
    app = _NotificationFlowApp(notification)
    marked_read: list[str] = []
    monkeypatch.setattr(
        "sase.notifications.mark_read",
        lambda notification_id: marked_read.append(notification_id),
    )

    app._show_notification_modal()

    assert marked_read == [notification.id]
    assert app.notices == []
    assert app.refresh_count == 1


def test_unread_page_repairs_terminal_gate_notification(gate_home: Path) -> None:
    del gate_home
    created = create_gate(_spec())
    created.response_path.write_text("{}\n", encoding="utf-8")

    page = direct_unread_notification_page(include_dismissed=False, limit=50)

    assert page.notifications == []
    [notification] = load_notifications(include_dismissed=True)
    assert notification.id == created.notification_id
    assert notification.dismissed is True


def test_unread_page_keeps_unanswered_gate_notification(gate_home: Path) -> None:
    del gate_home
    created = create_gate(_spec())

    page = direct_unread_notification_page(include_dismissed=False, limit=50)

    assert [notification.id for notification in page.notifications] == [
        created.notification_id
    ]
    [notification] = load_notifications(include_dismissed=True)
    assert notification.dismissed is False


def test_unread_page_keeps_live_gate_behind_large_backlog(gate_home: Path) -> None:
    del gate_home
    created = create_gate(_spec())
    for index in range(120):
        append_notification(
            Notification(
                id=f"newer-{index}",
                timestamp=(f"2026-09-18T12:{index // 60:02d}:{index % 60:02d}+00:00"),
                sender="test",
                tags=["done"],
            )
        )

    page = direct_unread_notification_page(include_dismissed=False)

    assert created.notification_id in [
        notification.id for notification in page.notifications
    ]

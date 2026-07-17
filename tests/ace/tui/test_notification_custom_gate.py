"""ACE loading and tracked execution coverage for neutral gates."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.actions.agents._notification_custom_gate import (
    _load_custom_gate_modal_data,
)
from sase.ace.tui.actions.agents._notification_gate_execution import (
    GateSubmission,
    _execute_gate_submission,
    submit_gate_execution_task,
)
from sase.ace.tui.actions.agents._notification_hitl_modal import (
    _load_neutral_hitl_data,
    _neutral_hitl_choice_id,
)
from sase.ace.tui.actions.agents._notification_modal_flow import (
    AgentNotificationModalMixin,
)
from sase.notification_gates.service import create_gate
from sase.notifications import pending_actions
from sase.notifications.store import load_notifications
from sase.xprompt import HITLResult


@pytest.fixture()
def gate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from sase.notification_gates import paths
    from sase.notifications import store

    monkeypatch.setattr(paths, "INTERACTION_REQUESTS_DIR", tmp_path / "requests")
    monkeypatch.setattr(store, "NOTIFICATIONS_DIR", str(tmp_path / "notifications"))
    monkeypatch.setattr(
        store,
        "NOTIFICATIONS_FILE",
        str(tmp_path / "notifications" / "notifications.jsonl"),
    )
    monkeypatch.setattr(
        pending_actions, "PENDING_ACTIONS_PATH", tmp_path / "pending.json"
    )
    monkeypatch.setattr(
        pending_actions,
        "LEGACY_TELEGRAM_PENDING_ACTIONS_PATH",
        tmp_path / "legacy.json",
    )
    store._LOAD_CACHE.clear()
    return tmp_path


def _spec(*, kind: str = "custom") -> dict[str, object]:
    return {
        "schema_version": 1,
        "request_id": f"{kind}-ace",
        "kind": kind,
        "producer": {"agent": "test"},
        "payload": {
            "title": "Review guarded work",
            "step_name": "guarded work",
            "output": {"command": "safe-command"},
        },
        "presentation": {
            "sender": "safety-agent",
            "icon": "🛡️",
            "notes": ["Confirm the guarded command."],
            "preview": "preview.md",
        },
        "choices": [
            {
                "id": "approve",
                "label": "Approve",
                "icon": "✅",
                "feedback": "optional" if kind == "custom" else "disabled",
                "command": {"argv": ["commands/approve"]},
                "input_schema": {"type": "object"},
                "result_schema": {"type": "object"},
                "extras": (
                    [
                        {
                            "id": "audit",
                            "label": "Write audit record",
                            "icon": "📝",
                            "default_selected": True,
                            "command": {"argv": ["commands/audit"]},
                        }
                    ]
                    if kind == "custom"
                    else []
                ),
            }
        ],
        "resources": [
            {
                "path": "commands/approve",
                "role": "command",
                "content": (
                    "#!/usr/bin/env python3\n"
                    "import json, sys\n"
                    "value = json.load(sys.stdin)\n"
                    "print(json.dumps({'approved': True, 'input': value}))\n"
                ),
            },
            {
                "path": "commands/audit",
                "role": "command",
                "content": "#!/bin/sh\nprintf '{\"audited\": true}\\n'\n",
            },
            {
                "path": "preview.md",
                "role": "preview",
                "content": "# Guarded work\n\nReview before proceeding.\n",
            },
        ],
    }


class _TaskInfo:
    def __init__(self) -> None:
        self.running: set[Any] = set()

    def register_process(self, process: Any) -> None:
        self.running.add(process)

    def unregister_process(self, process: Any) -> None:
        self.running.discard(process)


class _Reporter:
    def __init__(self) -> None:
        self.task_info = _TaskInfo()
        self.phases: list[str] = []
        self.lines: list[tuple[str, str]] = []
        self.commands: list[tuple[str, ...]] = []

    def phase(self, value: str) -> None:
        self.phases.append(value)

    def section(self, value: str) -> None:
        self.lines.append(("header", value))

    def set_command(self, argv: tuple[str, ...]) -> None:
        self.commands.append(argv)

    def log(self, value: str, *, stream: str = "stdout") -> None:
        self.lines.append((stream, value))


class _TrackedSubmissionApp:
    def __init__(self) -> None:
        self.reporter = _Reporter()
        self.notifications: list[tuple[str, str]] = []
        self.refresh_count = 0
        self.task_types: list[str] = []

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def _refresh_notification_count(self) -> None:
        self.refresh_count += 1

    def _submit_tracked_task(self, *args: Any, **kwargs: Any) -> object:
        self.task_types.append(str(args[0]))
        completion = args[3](self.reporter)
        kwargs["on_complete"](completion)
        return SimpleNamespace(task_id="gate-task")


class _NotificationFlowApp(AgentNotificationModalMixin):
    def __init__(self, notification: Any) -> None:
        self.notification = notification
        self.refresh_count = 0
        self.pending_reads = 0
        self.notices: list[tuple[str, str]] = []

    def _read_unread_notification_page_from_provider(self) -> object:
        return SimpleNamespace(notifications=(self.notification,))

    def _read_notification_detail_from_provider(self, _notification_id: str) -> object:
        return SimpleNamespace(notification=self.notification)

    def _read_notification_pending_actions_from_provider(self) -> object:
        self.pending_reads += 1
        return object()

    def _refresh_notification_count(self) -> None:
        self.refresh_count += 1

    def push_screen(self, _screen: object, callback: Any) -> None:
        callback(self.notification)

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notices.append((message, severity))


def test_custom_gate_loader_projects_icons_preview_and_defaults(
    gate_home: Path,
) -> None:
    del gate_home
    create_gate(_spec())
    notification = load_notifications()[0]

    data = _load_custom_gate_modal_data(notification)

    assert data.icon == "🛡️"
    assert data.sender == "safety-agent"
    assert data.preview_name == "preview.md"
    assert data.preview_text is not None and "Guarded work" in data.preview_text
    assert data.choices[0].icon == "✅"
    assert data.choices[0].extras[0].default_selected is True


def test_tracked_executor_reports_terminal_and_extra_commands_live(
    gate_home: Path,
) -> None:
    del gate_home
    created = create_gate(_spec())
    reporter = _Reporter()

    outcome = _execute_gate_submission(
        created.bundle_path,
        GateSubmission(
            choice_id="approve",
            selected_extra_ids=("audit",),
            feedback="Reviewed",
            input_data={},
        ),
        reporter=reporter,  # type: ignore[arg-type]
    )

    assert outcome.success is True
    assert reporter.phases == [
        "Running choice: Approve",
        "Running add-on: Write audit record",
    ]
    assert reporter.task_info.running == set()
    assert any('"approved": true' in line for _stream, line in reporter.lines)
    assert any('"audited": true' in line for _stream, line in reporter.lines)
    assert (created.bundle_path / "response.json").is_file()


def test_custom_gate_submission_uses_tracked_task_toast_and_refresh(
    gate_home: Path,
) -> None:
    del gate_home
    create_gate(_spec())
    notification = load_notifications()[0]
    app = _TrackedSubmissionApp()

    submitted = submit_gate_execution_task(
        app,
        notification,
        GateSubmission(choice_id="approve", feedback="Reviewed", input_data={}),
    )

    assert submitted is True
    assert app.task_types == ["notification-gate"]
    assert app.notifications == [("Gate answered with approve", "information")]
    assert app.refresh_count == 1
    assert any('"approved": true' in line for _stream, line in app.reporter.lines)


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


def test_neutral_hitl_loader_and_accept_alias_use_gate_choice(gate_home: Path) -> None:
    del gate_home
    create_gate(_spec(kind="hitl"))
    notification = load_notifications()[0]

    data = _load_neutral_hitl_data(notification)

    assert data.input_data.step_name == "guarded work"
    assert data.choice_ids == ("approve",)
    assert (
        _neutral_hitl_choice_id(
            HITLResult(action="accept", approved=True), data.choice_ids
        )
        == "approve"
    )

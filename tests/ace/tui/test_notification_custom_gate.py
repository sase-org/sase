"""ACE loading and tracked execution coverage for neutral gates."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from sase.ace.tui.actions.agents._notification_custom_gate import (
    _load_custom_gate_modal_data,
    handle_custom_gate,
)
from sase.ace.tui.actions.agents._notification_gate_execution import (
    GateSubmission,
    submit_gate_execution_task,
)
from sase.ace.tui.modals import CustomGateModalResult
from sase.ace.tui.actions.agents._notification_hitl_modal import (
    _load_neutral_hitl_data,
    _neutral_hitl_choice_id,
)
from sase.ace.tui.actions.agents._notification_modal_flow import (
    AgentNotificationModalMixin,
)
from sase.ace.tui.actions.agents._notification_provider_direct import (
    direct_unread_notification_page,
)
from sase.ace.tui.modals.notification_modal_constants import (
    ACTION_BADGES,
    notification_icon,
)
from sase.notification_gates.presentation import GateChip
from sase.notification_gates.service import create_gate
from sase.ops.names import GATE_ANSWER
from sase.bead.task_gate import create_task_triage_gate
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
    singleton_id = "accept" if kind == "hitl" else "approve"
    return {
        "schema_version": 3,
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
            "title": "Review guarded work",
            "notes": ["Confirm the guarded command."],
            "preview": "preview.md",
        },
        "query": "(approve AND audit)" if kind == "custom" else singleton_id,
        "primary_branch": (
            ["approve", "audit"] if kind == "custom" else [singleton_id]
        ),
        "options": [
            {
                "id": singleton_id,
                "label": singleton_id.title(),
                "icon": "✅",
                "feedback": "optional" if kind == "custom" else "disabled",
                "command": {"argv": [f"commands/{singleton_id}"]},
                "input_schema": {"type": "object"},
                "result_schema": {"type": "object"},
            },
            *(
                [
                    {
                        "id": "audit",
                        "label": "Write audit record",
                        "icon": "📝",
                        "default_selected": True,
                        "feedback": "disabled",
                        "command": {"argv": ["commands/audit"]},
                        "input_schema": {"type": "object"},
                        "result_schema": {"type": "object"},
                    }
                ]
                if kind == "custom"
                else []
            ),
        ],
        "groups": (
            [{"options": ["approve", "audit"], "label": "Approve", "icon": "✅"}]
            if kind == "custom"
            else []
        ),
        "resources": [
            {
                "path": f"commands/{singleton_id}",
                "role": "command",
                "content": (
                    "#!/usr/bin/env python3\n"
                    "import json, sys\n"
                    "value = json.load(sys.stdin)\n"
                    "print(json.dumps({'approved': True, 'input': value}))\n"
                ),
            },
            *(
                [
                    {
                        "path": "commands/audit",
                        "role": "command",
                        "content": "#!/bin/sh\nprintf '{\"audited\": true}\\n'\n",
                    }
                ]
                if kind == "custom"
                else []
            ),
            {
                "path": "preview.md",
                "role": "preview",
                "content": "# Guarded work\n\nReview before proceeding.\n",
            },
        ],
    }


class _TrackedSubmissionApp:
    def __init__(self) -> None:
        self.notifications: list[tuple[str, str]] = []
        self.refresh_count = 0
        self.submitted: list[tuple[tuple[object, ...], dict[str, Any]]] = []

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def _refresh_notification_count(self) -> None:
        self.refresh_count += 1

    def _submit_durable_proc(self, *args: object, **kwargs: Any) -> object:
        self.submitted.append((args, kwargs))
        completion = SimpleNamespace(
            success=True,
            message="Gate answered with approve",
            payload={"selected_option_ids": ["approve"]},
        )
        kwargs["on_complete"](completion)
        return SimpleNamespace(proc_id="gate-task")


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
    assert data.title == "Custom Gate"
    assert data.origin_agent is None
    assert data.chip is None
    assert data.sender == "safety-agent"
    assert data.preview_name == "preview.md"
    assert data.preview_text is not None and "Guarded work" in data.preview_text
    assert data.gate.options[0].icon == "✅"
    assert data.gate.options[1].default_selected is True
    assert data.gate.branches == (("approve", "audit"),)


def test_custom_gate_loader_carries_declared_chip(
    gate_home: Path,
) -> None:
    del gate_home
    spec = _spec()
    presentation = cast(dict[str, object], spec["presentation"])
    spec["presentation"] = {
        **presentation,
        "chip": {"glyph": "≈", "label": "flake", "color": "#AF87FF"},
    }
    create_gate(spec)
    notification = load_notifications()[0]

    data = _load_custom_gate_modal_data(notification)

    assert data.chip == GateChip("≈", "flake", "#AF87FF")


def test_custom_gate_loader_carries_declared_origin_agent(
    gate_home: Path,
) -> None:
    del gate_home
    spec = _spec()
    presentation = cast(dict[str, object], spec["presentation"])
    spec["presentation"] = {**presentation, "origin_agent": "claude_coder"}
    create_gate(spec)
    notification = load_notifications()[0]

    data = _load_custom_gate_modal_data(notification)

    assert data.origin_agent == "claude_coder"


def test_task_triage_loader_uses_generic_branch_modal_data(
    gate_home: Path,
) -> None:
    del gate_home
    create_task_triage_gate(
        request_id="task-triage-ace-loader",
        bead_id="sase-task.1",
        project="sase",
        title="Review follow-up",
        description="Preserve the compatibility path.",
        notes="Raised by the land agent.",
    )
    notification = load_notifications()[0]

    data = _load_custom_gate_modal_data(notification)

    assert data.icon == "✦"
    assert data.title == "Task Triage"
    assert data.sender == "bead"
    assert data.preview_name == "task.md"
    assert data.preview_text is not None
    assert "Preserve the compatibility path." in data.preview_text
    assert data.gate.branches == (("launch",), ("close",), ("snooze",))
    assert data.gate.primary_branch == ("launch",)
    assert [option.feedback for option in data.gate.options] == [
        "optional",
        "required",
        "optional",
    ]
    # Snooze collects its wake time as a declared input, which the generic
    # branch controls render with no per-kind code.
    assert [[field.id for field in option.inputs] for option in data.gate.options] == [
        [],
        [],
        ["duration"],
    ]
    [duration_field] = data.gate.options[2].inputs
    assert duration_field.label == "Wake time"
    assert duration_field.type.value == "line"
    assert duration_field.required is True
    assert ACTION_BADGES["TaskTriage"] == "[task]"
    assert notification_icon("TaskTriage", None) == "✦"
    assert ACTION_BADGES["OpenLaunchControl"] == "[models]"
    assert notification_icon("OpenLaunchControl", None) == "🎛️"


def test_task_triage_opening_reuses_pump_free_generic_gate_path(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    create_task_triage_gate(
        request_id="task-triage-ace-off-pump",
        bead_id="sase-task.1",
        project="sase",
        title="Review follow-up",
    )
    notification = load_notifications()[0]
    app = SimpleNamespace(notify=lambda *_args, **_kwargs: None)
    captured: dict[str, Any] = {}

    def spawn(
        owner: object,
        coroutine: Any,
        *,
        name: str,
        registry_attr: str,
    ) -> object:
        captured.update(
            owner=owner,
            name=name,
            registry_attr=registry_attr,
        )
        coroutine.close()
        return object()

    monkeypatch.setattr(
        "sase.ace.tui.util.pump_tasks.spawn_pump_free_task",
        spawn,
    )

    assert handle_custom_gate(app, notification) is True
    assert captured == {
        "owner": app,
        "name": f"custom-gate-open:{notification.id}",
        "registry_attr": "_custom_gate_open_tasks",
    }


def test_custom_gate_submission_uses_durable_task_toast_and_refresh(
    gate_home: Path,
) -> None:
    del gate_home
    create_gate(_spec())
    notification = load_notifications()[0]
    app = _TrackedSubmissionApp()

    submitted = submit_gate_execution_task(
        app,
        notification,
        GateSubmission(
            selected_option_ids=("approve",),
            feedback="Reviewed",
            input_data={},
        ),
    )

    assert submitted is True
    [(args, kwargs)] = app.submitted
    assert args == (
        [
            "sase",
            "gate",
            "answer",
            "--id",
            notification.action_data["request_id"],
            "--kind",
            notification.action_data["request_kind"],
            "--json",
        ],
    )
    assert kwargs["operation"] == GATE_ANSWER
    request = kwargs["request"]
    assert isinstance(request, dict)
    assert request["option_ids"] == ["approve"]
    assert request["feedback"] == "Reviewed"
    assert request["input_data"] == {}
    assert app.notifications == [("Gate answered with approve", "information")]
    assert app.refresh_count == 1


async def test_custom_gate_dismissal_forwards_collected_option_inputs(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    create_gate(_spec())
    notification = load_notifications()[0]
    captured: dict[str, Any] = {}

    def fake_submit(_app: Any, _notification: Any, submission: GateSubmission) -> bool:
        captured["submission"] = submission
        return True

    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_gate_execution."
        "submit_gate_execution_task",
        fake_submit,
    )

    class _App:
        def push_screen(self, _screen: object, callback: Any) -> None:
            callback(
                CustomGateModalResult(
                    selected_option_ids=("approve", "audit"),
                    feedback=None,
                    option_inputs={"approve": {"ticket": "OPS-1"}, "audit": {}},
                )
            )

        def notify(self, *_args: object, **_kwargs: object) -> None:
            pass

    app = _App()
    assert handle_custom_gate(app, notification) is True
    [task] = app._custom_gate_open_tasks
    await task

    submission = captured["submission"]
    assert submission.option_inputs == {
        "approve": {"ticket": "OPS-1"},
        "audit": {},
    }


async def test_custom_gate_dismissal_sends_no_option_inputs_when_none_collected(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    create_gate(_spec())
    notification = load_notifications()[0]
    captured: dict[str, Any] = {}

    def fake_submit(_app: Any, _notification: Any, submission: GateSubmission) -> bool:
        captured["submission"] = submission
        return True

    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_gate_execution."
        "submit_gate_execution_task",
        fake_submit,
    )

    class _App:
        def push_screen(self, _screen: object, callback: Any) -> None:
            callback(
                CustomGateModalResult(
                    selected_option_ids=("approve", "audit"),
                    feedback=None,
                )
            )

        def notify(self, *_args: object, **_kwargs: object) -> None:
            pass

    app = _App()
    assert handle_custom_gate(app, notification) is True
    [task] = app._custom_gate_open_tasks
    await task

    assert captured["submission"].option_inputs is None


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


def test_neutral_hitl_loader_and_accept_alias_use_gate_choice(gate_home: Path) -> None:
    del gate_home
    create_gate(_spec(kind="hitl"))
    notification = load_notifications()[0]

    data = _load_neutral_hitl_data(notification)

    assert data.input_data.step_name == "guarded work"
    assert data.choice_ids == ("accept",)
    assert (
        _neutral_hitl_choice_id(
            HITLResult(action="accept", approved=True), data.choice_ids
        )
        == "accept"
    )

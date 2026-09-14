"""Custom gate opening, submission, and dismissal execution coverage."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.actions.agents._notification_custom_gate import handle_custom_gate
from sase.ace.tui.actions.agents._notification_gate_execution import (
    GateSubmission,
    submit_gate_execution_task,
)
from sase.ace.tui.modals import CustomGateModalResult
from sase.notification_gates.service import create_gate
from sase.ops.names import GATE_ANSWER
from sase.bead.task_gate import create_task_triage_gate
from sase.notifications.store import load_notifications

from ._notification_custom_gate_helpers import (
    _TrackedSubmissionApp,
    _spec,
    gate_home_fixture,
)


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
            "--no-detach",
            "--json",
        ],
    )
    assert kwargs["operation"] == GATE_ANSWER
    request = kwargs["request"]
    assert isinstance(request, dict)
    assert request["option_ids"] == ["approve"]
    assert request["feedback"] == "Reviewed"
    assert request["input_data"] == {}
    assert request["source"] == "tui"
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

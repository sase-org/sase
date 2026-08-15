"""ACE never guesses how to finish a partly executed AND branch.

The executor refuses a bare resubmission with ``partial_attempt``; what is
asserted here is that ACE turns that refusal into an explicit reviewer choice
and resubmits with exactly the retry the reviewer picked.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from textual.app import App
from textual.widgets import Static

from sase.ace.tui.actions.agents._notification_gate_execution import (
    GateSubmission,
    _PartialAttempt,
    submit_gate_execution_task,
)
from sase.ace.tui.modals.gate_retry_modal import GateRetryModal


class _TestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False


class _RecordingApp:
    """Capture what the retry flow pushed and what it notified."""

    def __init__(self) -> None:
        self.pushed: list[tuple[object, Any]] = []
        self.notifications: list[tuple[str, str]] = []
        self.refreshes = 0
        self.completions: list[object] = []
        self.submitted: list[tuple[tuple[object, ...], dict[str, Any]]] = []

    def push_screen(self, screen: object, callback: Any = None) -> None:
        self.pushed.append((screen, callback))

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def _refresh_notification_count(self) -> None:
        self.refreshes += 1

    def _submit_durable_proc(self, *args: object, **kwargs: Any) -> object:
        self.submitted.append((args, kwargs))
        if self.completions:
            on_complete = kwargs["on_complete"]
            assert callable(on_complete)
            on_complete(self.completions.pop(0))
        return SimpleNamespace(proc_id=f"gate-{len(self.submitted)}")


def _notification() -> Any:
    return SimpleNamespace(
        id="notification-1",
        action_data={
            "bundle_path": "/tmp/gate-bundle",
            "request_id": "request-1",
            "request_kind": "custom",
        },
    )


def _partial() -> _PartialAttempt:
    return _PartialAttempt(
        attempt_id="attempt-1",
        completed_option_ids=("approve",),
        failed_option_ids=("commit",),
    )


def _partial_completion(message: str = "gate attempt is incomplete") -> object:
    return SimpleNamespace(
        success=False,
        message=message,
        payload={"code": "partial_attempt"},
    )


def test_partial_attempt_asks_instead_of_notifying(monkeypatch: Any) -> None:
    app = _RecordingApp()
    app.completions.append(_partial_completion())
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_gate_execution"
        "._describe_partial_attempt",
        lambda _bundle_path: _partial(),
    )

    submit_gate_execution_task(
        app, _notification(), GateSubmission(("approve", "commit"))
    )

    [(screen, _callback)] = app.pushed
    assert isinstance(screen, GateRetryModal)
    assert app.notifications == []


def test_choosing_resume_resubmits_with_that_retry(monkeypatch: Any) -> None:
    app = _RecordingApp()
    app.completions.append(_partial_completion())
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_gate_execution"
        "._describe_partial_attempt",
        lambda _bundle_path: _partial(),
    )

    submit_gate_execution_task(
        app, _notification(), GateSubmission(("approve", "commit"))
    )
    [(_screen, callback)] = app.pushed
    callback("resume")

    assert len(app.submitted) == 2
    retry_request = app.submitted[1][1]["request"]
    assert retry_request["retry"] == "resume"
    assert retry_request["option_ids"] == ["approve", "commit"]


def test_declining_the_choice_leaves_the_gate_alone(monkeypatch: Any) -> None:
    app = _RecordingApp()
    app.completions.append(_partial_completion())
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_gate_execution"
        "._describe_partial_attempt",
        lambda _bundle_path: _partial(),
    )

    submit_gate_execution_task(
        app, _notification(), GateSubmission(("approve", "commit"))
    )
    [(_screen, callback)] = app.pushed
    callback(None)

    assert len(app.submitted) == 1
    assert app.notifications and "incomplete" in app.notifications[0][0]


def test_a_retried_submission_reports_its_failure_rather_than_asking_again() -> None:
    app = _RecordingApp()
    app.completions.append(_partial_completion())

    submit_gate_execution_task(
        app,
        _notification(),
        GateSubmission(("approve", "commit"), retry="resume"),
    )

    assert app.pushed == []
    assert app.notifications == [("gate attempt is incomplete", "error")]


async def test_retry_modal_reports_both_option_sets_and_returns_a_choice() -> None:
    results: list[object] = []
    modal = GateRetryModal(
        completed_option_ids=("approve",), failed_option_ids=("commit",)
    )

    async with _TestApp().run_test(size=(90, 24)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        summary = modal.query_one("#gate-retry-summary", Static).render().plain
        assert "approve" in summary
        assert "commit" in summary
        await pilot.press("R")
        await pilot.pause()

    assert results == ["restart"]

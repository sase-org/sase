"""Tracked shared-executor submission for neutral notification gates."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from sase.notifications import Notification

    from ...task_subprocess import TaskReporter


_GateTaskSeverity = Literal["warning", "error"]


@dataclass(frozen=True)
class GateSubmission:
    """Surface-neutral input for one gate executor call."""

    selected_option_ids: tuple[str, ...]
    feedback: str | None = None
    input_data: object | None = None


@dataclass(frozen=True)
class _GateTaskOutcome:
    message: str
    success: bool
    severity: _GateTaskSeverity | None = None


def submit_gate_execution_task(
    app: object,
    notification: Notification,
    submission: GateSubmission,
) -> bool:
    """Execute a neutral gate through ACE's tracked background task queue."""
    bundle_value = notification.action_data.get("bundle_path")
    if not bundle_value:
        app.notify("No neutral gate bundle in notification", severity="error")  # type: ignore[attr-defined]
        return False
    submit = getattr(app, "_submit_tracked_task", None)
    if not callable(submit):
        app.notify("Tracked gate execution is unavailable", severity="error")  # type: ignore[attr-defined]
        return False

    from ...actions.task_actions import TrackedTaskResult

    request_id = str(notification.action_data.get("request_id") or notification.id)
    bundle_path = Path(bundle_value)

    def work(reporter: TaskReporter) -> TrackedTaskResult[_GateTaskOutcome]:
        outcome = _execute_gate_submission(
            bundle_path,
            submission,
            reporter=reporter,
        )
        return TrackedTaskResult(
            success=outcome.success,
            message=outcome.message,
            payload=outcome,
            error=None if outcome.success else outcome.message,
        )

    def on_complete(completion: object) -> None:
        outcome = getattr(completion, "payload", None)
        if isinstance(outcome, _GateTaskOutcome):
            _finish_gate_task(app, outcome)
            return
        if not bool(getattr(completion, "success", False)):
            app.notify(  # type: ignore[attr-defined]
                str(getattr(completion, "message", "Gate execution failed")),
                severity="error",
            )
        _refresh_notifications(app)

    task = submit(
        "notification-gate",
        f"gate {request_id}",
        str(bundle_path),
        work,
        display_name=f"Gate response: {', '.join(submission.selected_option_ids)}",
        dedup_key=f"notification-gate:{notification.id}",
        duplicate_message="This gate response is already being processed",
        on_complete=on_complete,
        reload_on_complete=False,
        notify_on_complete=False,
    )
    return task is not None


def _execute_gate_submission(
    bundle_path: Path,
    submission: GateSubmission,
    *,
    reporter: TaskReporter,
) -> _GateTaskOutcome:
    from sase.notification_gates.executor import execute_gate_selection
    from sase.notification_gates.models import GateError

    def command_start(
        command_kind: str,
        command_id: str,
        label: str,
        argv: tuple[str, ...],
    ) -> None:
        del command_kind
        reporter.phase(f"Running option: {label}")
        reporter.section(f"Option {command_id}")
        reporter.set_command(argv)

    def output_line(
        _command_kind: str,
        _command_id: str,
        stream: str,
        line: str,
    ) -> None:
        reporter.log(line, stream="stderr" if stream == "stderr" else "stdout")

    def process_state(process: Any, running: bool) -> None:
        if running:
            reporter.task_info.register_process(process)
        else:
            reporter.task_info.unregister_process(process)

    try:
        result = execute_gate_selection(
            bundle_path,
            submission.selected_option_ids,
            submission.input_data,
            feedback=submission.feedback,
            source="tui",
            on_command_start=command_start,
            on_output_line=output_line,
            on_process_state=process_state,
        )
    except GateError as exc:
        return _GateTaskOutcome(str(exc), False, "error")
    except Exception as exc:
        return _GateTaskOutcome(str(exc), False, "error")

    if result.already_completed:
        return _GateTaskOutcome("Gate was already answered", True, "warning")
    return _GateTaskOutcome(
        f"Gate answered with {', '.join(submission.selected_option_ids)}",
        True,
    )


def _finish_gate_task(app: object, outcome: _GateTaskOutcome) -> None:
    if outcome.severity is None:
        app.notify(outcome.message)  # type: ignore[attr-defined]
    else:
        app.notify(outcome.message, severity=outcome.severity)  # type: ignore[attr-defined]
    _refresh_notifications(app)


def _refresh_notifications(app: object) -> None:
    refresh = getattr(app, "_refresh_notification_count", None)
    if callable(refresh):
        refresh()


__all__ = ["GateSubmission", "submit_gate_execution_task"]

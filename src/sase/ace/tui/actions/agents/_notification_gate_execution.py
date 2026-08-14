"""Tracked shared-executor submission for neutral notification gates."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from sase.notifications import Notification

    from ...proc_subprocess import ProcReporter


_GateTaskSeverity = Literal["warning", "error"]


@dataclass(frozen=True)
class GateSubmission:
    """Surface-neutral input for one gate executor call."""

    selected_option_ids: tuple[str, ...]
    feedback: str | None = None
    input_data: object | None = None
    retry: Literal["resume", "restart"] | None = None
    option_inputs: Mapping[str, object] | None = None


@dataclass(frozen=True)
class _PartialAttempt:
    """A branch this gate already ran partway through, awaiting a retry choice."""

    attempt_id: str
    completed_option_ids: tuple[str, ...]
    failed_option_ids: tuple[str, ...]


@dataclass(frozen=True)
class _GateTaskOutcome:
    message: str
    success: bool
    severity: _GateTaskSeverity | None = None
    partial_attempt: _PartialAttempt | None = None


def submit_gate_execution_task(
    app: object,
    notification: Notification,
    submission: GateSubmission,
) -> bool:
    """Execute a neutral gate through ACE's tracked proc queue."""
    bundle_value = notification.action_data.get("bundle_path")
    if not bundle_value:
        app.notify("No neutral gate bundle in notification", severity="error")  # type: ignore[attr-defined]
        return False
    submit = getattr(app, "_submit_tracked_proc", None)
    if not callable(submit):
        app.notify("Tracked gate execution is unavailable", severity="error")  # type: ignore[attr-defined]
        return False

    from ...actions.proc_actions import TrackedProcResult

    request_id = str(notification.action_data.get("request_id") or notification.id)
    bundle_path = Path(bundle_value)

    def work(reporter: ProcReporter) -> TrackedProcResult[_GateTaskOutcome]:
        outcome = _execute_gate_submission(
            bundle_path,
            submission,
            reporter=reporter,
        )
        return TrackedProcResult(
            success=outcome.success,
            message=outcome.message,
            payload=outcome,
            error=None if outcome.success else outcome.message,
        )

    def on_complete(completion: object) -> None:
        outcome = getattr(completion, "payload", None)
        if isinstance(outcome, _GateTaskOutcome):
            _finish_gate_task(app, notification, submission, outcome)
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
    reporter: ProcReporter,
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
            reporter.proc_info.register_process(process)
        else:
            reporter.proc_info.unregister_process(process)

    try:
        result = execute_gate_selection(
            bundle_path,
            submission.selected_option_ids,
            submission.input_data,
            feedback=submission.feedback,
            source="tui",
            retry=submission.retry,
            option_inputs=submission.option_inputs,
            on_command_start=command_start,
            on_output_line=output_line,
            on_process_state=process_state,
        )
    except GateError as exc:
        if exc.code == "partial_attempt":
            return _GateTaskOutcome(
                str(exc),
                False,
                "warning",
                partial_attempt=_describe_partial_attempt(bundle_path),
            )
        return _GateTaskOutcome(str(exc), False, "error")
    except Exception as exc:
        return _GateTaskOutcome(str(exc), False, "error")

    if result.already_completed:
        return _GateTaskOutcome("Gate was already answered", True, "warning")
    return _GateTaskOutcome(
        f"Gate answered with {', '.join(submission.selected_option_ids)}",
        True,
    )


def _describe_partial_attempt(bundle_path: Path) -> _PartialAttempt | None:
    """Read which options a rejected resubmission already ran, for the retry choice."""
    from sase.notification_gates.journal import incomplete_attempt

    try:
        pending = incomplete_attempt(bundle_path)
    except Exception:
        return None
    if pending is None:
        return None
    return _PartialAttempt(
        attempt_id=pending.attempt_id,
        completed_option_ids=pending.completed_option_ids,
        failed_option_ids=pending.failed_option_ids,
    )


def _finish_gate_task(
    app: object,
    notification: Notification,
    submission: GateSubmission,
    outcome: _GateTaskOutcome,
) -> None:
    if outcome.partial_attempt is not None and submission.retry is None:
        _ask_retry_choice(app, notification, submission, outcome.partial_attempt)
        return
    if outcome.severity is None:
        app.notify(outcome.message)  # type: ignore[attr-defined]
    else:
        app.notify(outcome.message, severity=outcome.severity)  # type: ignore[attr-defined]
    _refresh_notifications(app)


def _ask_retry_choice(
    app: object,
    notification: Notification,
    submission: GateSubmission,
    partial: _PartialAttempt,
) -> None:
    """Let the reviewer choose how to finish a partly executed branch."""
    from dataclasses import replace

    from ...modals.gate_retry_modal import GateRetryModal

    def on_choice(choice: object) -> None:
        if choice not in {"resume", "restart"}:
            app.notify(_incomplete_attempt_message(partial), severity="warning")  # type: ignore[attr-defined]
            _refresh_notifications(app)
            return
        submit_gate_execution_task(app, notification, replace(submission, retry=choice))

    app.push_screen(  # type: ignore[attr-defined]
        GateRetryModal(
            completed_option_ids=partial.completed_option_ids,
            failed_option_ids=partial.failed_option_ids,
        ),
        on_choice,
    )


def _incomplete_attempt_message(partial: _PartialAttempt) -> str:
    """Describe an attempt the reviewer declined to finish."""
    return (
        f"Gate attempt {partial.attempt_id} is still incomplete; "
        "answer it again to resume or restart"
    )


def _refresh_notifications(app: object) -> None:
    refresh = getattr(app, "_refresh_notification_count", None)
    if callable(refresh):
        refresh()


__all__ = ["GateSubmission", "submit_gate_execution_task"]

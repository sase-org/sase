"""Tracked shared-executor submission for neutral notification gates."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from sase.ace.tui.actions._durable_ops import (
    durable_fingerprint,
    durable_request_payload,
    sase_argv,
)
from sase.ops.names import GATE_ANSWER

if TYPE_CHECKING:
    from sase.notifications import Notification


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


def submit_gate_execution_task(
    app: object,
    notification: Notification,
    submission: GateSubmission,
) -> bool:
    """Execute a neutral gate through ACE's durable proc queue."""
    bundle_value = notification.action_data.get("bundle_path")
    if not bundle_value:
        app.notify("No neutral gate bundle in notification", severity="error")  # type: ignore[attr-defined]
        return False
    submit = getattr(app, "_submit_durable_proc", None)
    if not callable(submit):
        app.notify("Durable gate execution is unavailable", severity="error")  # type: ignore[attr-defined]
        return False

    request_id = str(notification.action_data.get("request_id") or notification.id)
    request_kind = str(notification.action_data.get("request_kind") or "custom")
    bundle_path = Path(bundle_value)

    def on_complete(completion: object) -> None:
        success = bool(getattr(completion, "success", False))
        payload = getattr(completion, "payload", None)
        if (
            not success
            and isinstance(payload, dict)
            and payload.get("code") == "partial_attempt"
            and submission.retry is None
        ):
            offer_partial_attempt_retry(
                app,
                notification,
                submission,
                bundle_path,
                on_unavailable=lambda: _report_completion(app, completion),
            )
            return
        _report_completion(app, completion)

    task = submit(
        sase_argv(
            "gate",
            "answer",
            "--id",
            request_id,
            "--kind",
            request_kind,
            "--no-detach",
            "--json",
        ),
        operation=GATE_ANSWER,
        request=durable_request_payload(
            feedback=submission.feedback,
            input_data=submission.input_data,
            option_ids=list(submission.selected_option_ids),
            option_inputs=(
                None
                if submission.option_inputs is None
                else dict(submission.option_inputs)
            ),
            retry=submission.retry,
            source="tui",
        ),
        request_fingerprint=durable_fingerprint(
            GATE_ANSWER,
            request_kind,
            request_id,
            ",".join(submission.selected_option_ids),
            submission.retry or "",
            "tui",
        ),
        concurrency_keys=(f"notification-gate:{notification.id}",),
        label=f"Gate response: {', '.join(submission.selected_option_ids)}",
        display_name=f"Gate response: {', '.join(submission.selected_option_ids)}",
        cl_name=f"gate {request_id}",
        project_file=str(bundle_path),
        on_complete=on_complete,
        reload_on_complete=False,
        notify_on_complete=False,
    )
    if task is not None:
        from ._notification_utils import schedule_gate_decision_receipt_refresh

        schedule_gate_decision_receipt_refresh(
            app,
            notification=notification,
            bundle_path=bundle_path,
        )
    return task is not None


def _report_completion(app: object, completion: object) -> None:
    if getattr(completion, "success", False):
        app.notify(str(getattr(completion, "message", "Gate answered")))  # type: ignore[attr-defined]
    else:
        app.notify(  # type: ignore[attr-defined]
            str(getattr(completion, "message", "Gate execution failed")),
            severity="error",
        )
    _refresh_notifications(app)


def offer_partial_attempt_retry(
    app: object,
    notification: Notification,
    submission: GateSubmission,
    bundle_path: Path,
    *,
    on_unavailable: Callable[[], None],
) -> None:
    """Ask resume-or-restart after a ``partial_attempt`` refusal.

    The journal read happens off the event loop. ``on_unavailable`` runs when
    no incomplete attempt can be described (nothing to choose between).
    """
    from ._notification_off_loop import run_off_loop

    def on_done(partial: _PartialAttempt | None) -> None:
        if partial is None:
            on_unavailable()
            return
        _ask_retry_choice(app, notification, submission, partial)

    run_off_loop(
        app,
        lambda: describe_partial_attempt(bundle_path),
        on_done,
        name=f"gate-partial-attempt:{notification.id}",
    )


def describe_partial_attempt(bundle_path: Path) -> _PartialAttempt | None:
    """Read which options a rejected resubmission already ran, for the retry choice."""
    from sase.notification_gates.journal import incomplete_attempt

    try:
        # Only reached after ``execute_gate_selection`` raised
        # ``partial_attempt``, which happens before ``response.json`` exists.
        pending = incomplete_attempt(bundle_path, response_exists=False)
    except Exception:
        return None
    if pending is None:
        return None
    return _PartialAttempt(
        attempt_id=pending.attempt_id,
        completed_option_ids=pending.completed_option_ids,
        failed_option_ids=pending.failed_option_ids,
    )


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
        retry = cast(Literal["resume", "restart"], choice)
        submit_gate_execution_task(app, notification, replace(submission, retry=retry))

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
        f"Gate attempt {partial.attempt_id} is still incomplete; open its "
        "gate-failure notification or run `sase gate answer --resume` "
        "(or `--restart`) to finish it"
    )


def _refresh_notifications(app: object) -> None:
    schedule_refresh = getattr(app, "_schedule_notification_snapshot_refresh", None)
    if callable(schedule_refresh):
        schedule_refresh()
        return
    refresh = getattr(app, "_refresh_notification_count", None)
    if callable(refresh):
        refresh()


__all__ = [
    "GateSubmission",
    "offer_partial_attempt_retry",
    "submit_gate_execution_task",
]

"""Resume, restart, and cancel actions for a failed gate execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ._notification_gate_execution import (
    GateSubmission,
    describe_partial_attempt,
    submit_gate_execution_task,
)
from ._notification_off_loop import run_off_loop

if TYPE_CHECKING:
    from sase.notifications import Notification


@dataclass(frozen=True)
class _RecoveryContext:
    selected_option_ids: tuple[str, ...]
    completed_option_ids: tuple[str, ...]
    failed_option_ids: tuple[str, ...]


def handle_gate_execution_failed(app: object, notification: Notification) -> bool:
    """Offer resume, restart, and cancel for a failed gate execution.

    Works from the failure notification alone, so it stays available after the
    original review notification was dismissed. All bundle and journal reads run
    off the event loop.
    """
    bundle_value = notification.action_data.get("bundle_path")
    if not bundle_value:
        return _open_report(app, notification)
    bundle_path = Path(str(bundle_value))

    def load() -> _RecoveryContext:
        from sase.notification_gates.failure_notifications import (
            gate_failure_selected_option_ids,
        )

        selected = gate_failure_selected_option_ids(
            bundle_path, notification.action_data
        )
        partial = describe_partial_attempt(bundle_path)
        return _RecoveryContext(
            selected_option_ids=selected,
            completed_option_ids=partial.completed_option_ids if partial else (),
            failed_option_ids=(partial.failed_option_ids if partial else ()),
        )

    def on_loaded(context: _RecoveryContext) -> None:
        _ask_recovery_choice(app, notification, bundle_path, context)

    run_off_loop(
        app,
        load,
        on_loaded,
        name=f"gate-failure-recovery:{notification.id}",
    )
    return True


def _recovery_actions(notification: Notification) -> frozenset[str]:
    raw = str(notification.action_data.get("recovery_actions") or "")
    return frozenset(part for part in raw.split(",") if part)


def _ask_recovery_choice(
    app: object,
    notification: Notification,
    bundle_path: Path,
    context: _RecoveryContext,
) -> None:
    from ...modals.gate_retry_modal import GateRetryModal

    actions = _recovery_actions(notification)
    can_resume = "resume" in actions and bool(context.selected_option_ids)
    allow_restart = "restart" in actions and bool(context.selected_option_ids)
    allow_cancel = "cancel" in actions

    def on_choice(choice: object) -> None:
        if choice == "report":
            _open_report(app, notification)
        elif choice == "cancel":
            _cancel_gate(app, notification, bundle_path)
        elif choice in {"resume", "restart"} and context.selected_option_ids:
            submit_gate_execution_task(
                app,
                notification,
                GateSubmission(
                    context.selected_option_ids,
                    retry="resume" if choice == "resume" else "restart",
                ),
            )

    if not (can_resume or allow_restart or allow_cancel):
        _open_report(app, notification)
        return
    app.push_screen(  # type: ignore[attr-defined]
        GateRetryModal(
            completed_option_ids=context.completed_option_ids,
            failed_option_ids=context.failed_option_ids,
            title=f"Gate execution failed: {notification.action_data.get('stage', '')}",
            allow_restart=allow_restart,
            allow_cancel=allow_cancel,
            allow_report=True,
        ),
        on_choice,
    )


def _open_report(app: object, notification: Notification) -> bool:
    from ._notification_handlers import handle_view_error_report

    return handle_view_error_report(app, notification)


def _cancel_gate(app: object, notification: Notification, bundle_path: Path) -> None:
    def work() -> str | None:
        from sase.notification_gates.executor_cancellation import cancel_gate
        from sase.notification_gates.models import GateError

        try:
            cancel_gate(bundle_path, reason="user_cancelled", source="tui")
        except GateError as exc:
            return str(exc)
        except Exception as exc:  # noqa: BLE001 - surfaced as a toast
            return str(exc)
        return None

    def on_done(error: str | None) -> None:
        if error is None:
            app.notify("Gate cancelled")  # type: ignore[attr-defined]
        else:
            app.notify(f"Gate cancel failed: {error}", severity="error")  # type: ignore[attr-defined]
        schedule = getattr(app, "_schedule_notification_snapshot_refresh", None)
        if callable(schedule):
            schedule()

    run_off_loop(app, work, on_done, name=f"gate-failure-cancel:{notification.id}")


__all__ = ["handle_gate_execution_failed"]

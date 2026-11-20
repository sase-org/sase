"""TUI handler for the wait_checks root-blocker expire action."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sase.agent.expire_blocked_waiters import (
    EXPIRE_WAITERS_ACTION,
    ExpireBlockedWaitersResult,
    WaiterExpireResult,
    expire_blocked_waiters,
    expire_blocked_waiters_summary,
)
from sase.scripts._chop_wait_checks_root_notice import waiters_from_root_notice

if TYPE_CHECKING:
    from sase.notifications import Notification

log = logging.getLogger(__name__)


def handle_expire_waiters(app: Any, notification: Notification) -> bool:
    """Confirm, then expire every waiter the root-blocker notice names.

    Cancelling the confirmation leaves waiters and the notice unchanged.
    The kill/marker work runs off the UI thread.
    """
    from sase.ace.tui.modals.confirm_action_modal import ConfirmActionModal
    from sase.ace.tui.modals.confirm_dialog import ConfirmKind

    waiters = waiters_from_root_notice(notification)
    count = len(waiters)
    blocker = (
        notification.action_data.get("blocker_name")
        or notification.action_data.get("blocker_dependency")
        or "the failed blocker"
    )
    waiter_word = "waiter" if count == 1 else "waiters"
    message = (
        f"Expire {count} {waiter_word} blocked on {blocker}? "
        "They will be stopped without launching."
    )

    def _on_answer(confirmed: bool | None) -> None:
        if not confirmed:
            return
        _run_expire_blocked_waiters(app, notification)

    app.push_screen(
        ConfirmActionModal(
            "Expire blocked waiters",
            message,
            kind=ConfirmKind.DANGER,
            confirm_label="Expire",
            cancel_label="Keep waiting",
            default="cancel",
        ),
        _on_answer,
    )
    return True


def _run_expire_blocked_waiters(app: Any, notification: Notification) -> None:
    """Expire named waiters off the UI thread, then apply toasts on it."""

    def work() -> None:
        result = expire_blocked_waiters(notification)

        def apply() -> None:
            _apply_expire_result(app, result)

        call_from_thread = getattr(app, "call_from_thread", None)
        if callable(call_from_thread):
            try:
                call_from_thread(apply)
                return
            except Exception:
                log.debug("Failed to schedule expire-waiters UI update", exc_info=True)
        apply()

    run_worker = getattr(app, "run_worker", None)
    if callable(run_worker):
        try:
            run_worker(work, thread=True)
            return
        except Exception:
            log.debug("Falling back to synchronous expire-waiters work", exc_info=True)
    work()


def _failed_waiter_names(results: tuple[WaiterExpireResult, ...]) -> str:
    return ", ".join(item.name for item in results if item.status == "failed")


def _apply_expire_result(app: Any, result: ExpireBlockedWaitersResult) -> None:
    summary = expire_blocked_waiters_summary(result)
    failed_names = _failed_waiter_names(result.results)
    if failed_names:
        summary = f"{summary}: {failed_names}"
    severity = "error" if result.failed_count else "information"
    app.notify(summary, severity=severity)
    refresh = getattr(app, "_schedule_agents_async_refresh", None)
    if callable(refresh):
        refresh(source="expire-blocked-waiters")
    count_refresh = getattr(app, "_refresh_notification_count", None)
    if callable(count_refresh):
        count_refresh()


__all__ = ["EXPIRE_WAITERS_ACTION", "handle_expire_waiters"]

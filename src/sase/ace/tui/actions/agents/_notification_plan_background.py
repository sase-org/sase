"""Background archival and UI follow-up helpers for plan approvals."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from sase.notifications import Notification

    from ...modals import PlanApprovalResult


log = logging.getLogger(__name__)


def _plan_tier_for_action(action: str) -> Literal["tale", "epic"]:
    return "epic" if action == "epic" else "tale"


def archive_plan_for_approval(
    notification: Notification, action: str = "approve"
) -> str | None:
    """Best-effort copy of an approved plan into the workspace plan archive."""
    if not notification.files:
        return None

    src_plan = Path(notification.files[0])
    try:
        from sase._plan_archive_approval import archive_approved_plan

        return archive_approved_plan(
            notification.action_data,
            src_plan,
            tier=_plan_tier_for_action(action),
            push_after_commit="async",
        )
    except Exception as error:
        from sase._plan_archive_approval import report_plan_archive_failure

        report_plan_archive_failure(src_plan, notification.action_data, error)
        return None


def add_saved_plan_to_response(plan_response_path: Path, saved_plan_path: str) -> None:
    """Add the archived path to the response file after the fast write."""
    try:
        with open(plan_response_path, encoding="utf-8") as f:
            response_data = json.load(f)
        if not isinstance(response_data, dict):
            return
        response_data["saved_plan_path"] = saved_plan_path
        with open(plan_response_path, "w", encoding="utf-8") as f:
            json.dump(response_data, f, indent=2)
    except Exception:
        log.debug("Failed to update plan response with saved plan path", exc_info=True)


def call_on_app_thread(app: object, callback: object) -> None:
    """Invoke a UI callback from worker threads when Textual support exists."""
    call_from_thread = getattr(app, "call_from_thread", None)
    if callable(call_from_thread):
        try:
            call_from_thread(callback)
            return
        except Exception:
            log.debug("Failed to schedule app-thread callback", exc_info=True)
    if callable(callback):
        callback()


def finish_plan_approval_background_work(
    app: object,
    result: PlanApprovalResult,
    saved_plan_path: str | None,
) -> None:
    """Apply UI-only follow-up after background approval work completes."""
    if (
        result.action == "approve"
        and not result.run_coder
        and result.commit_plan
        and saved_plan_path is not None
    ):
        from sase.ace.tui.actions.clipboard import schedule_copy_delivery

        short_path = saved_plan_path.replace(str(Path.home()), "~")
        schedule_copy_delivery(
            app,
            short_path,
            copied_label=f"committed plan path ({short_path})",
            task_name="sase-copy-committed-plan-path",
        )
        app.notify("Plan committed")  # type: ignore[attr-defined]

    refresh_count = getattr(app, "_refresh_notification_count", None)
    if callable(refresh_count):
        refresh_count()

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
    import os

    project_dir = notification.action_data.get("project_dir")
    if not project_dir or not notification.files:
        return None

    try:
        from sase.plan_approval_actions import resolve_plan_agent_artifacts_dir
        from sase.running_field import get_workspace_directory
        from sase.sdd.files import (
            commit_sdd_store_files,
            ensure_bare_git_sdd_initialized,
        )
        from sase.sdd.plan_archive import archive_plan_file
        from sase.sdd.store import materialize_sdd_store

        project_basename = os.path.basename(str(project_dir))
        workspace_dir = get_workspace_directory(project_basename, 1)
        sdd_store = materialize_sdd_store(workspace_dir, 1)
        if sdd_store.is_in_tree:
            ensure_bare_git_sdd_initialized(
                workspace_dir,
                commit=True,
                push=False,
            )
        src_plan = Path(notification.files[0])
        tier = _plan_tier_for_action(action)
        archived = archive_plan_file(
            src_plan,
            sdd_store,
            tier=tier,
            preserve_existing=False,
        )
        if not sdd_store.is_in_tree:
            artifacts_dir = resolve_plan_agent_artifacts_dir(notification.action_data)
            commit_sdd_store_files(
                sdd_store,
                f"Archive approved plan {src_plan.stem}",
                paths=[archived.path],
                push_after_commit="async",
                artifacts_dir=artifacts_dir,
            )
        return str(archived.path)
    except Exception:
        log.debug("Failed to archive approved plan", exc_info=True)
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

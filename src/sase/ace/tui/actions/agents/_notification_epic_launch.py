"""Compatibility bridge from TUI plan approvals to detached epic launches."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sase.bead.epic_launch import (
    resolve_epic_launch_cwd,
    submit_epic_launch_task as submit_detached_epic_launch_task,
)

if TYPE_CHECKING:
    from sase.notifications import Notification


log = logging.getLogger(__name__)


def submit_epic_launch_task(
    app: object,
    notification: Notification,
    *,
    plan_file: str,
    phase_count: int,
) -> bool:
    """Submit the notification's epic as one shared detached task."""
    del app, phase_count
    project_dir = notification.action_data.get("project_dir")
    agent_project_file = notification.action_data.get("agent_project_file")
    if not project_dir and not agent_project_file:
        return False

    try:
        cwd = resolve_epic_launch_cwd(
            project_dir,
            agent_project_file=agent_project_file,
        )
        from sase.plan_approval_actions import resolve_plan_agent_artifacts_dir

        submit_detached_epic_launch_task(
            plan_file,
            cwd=cwd,
            artifacts_dir=resolve_plan_agent_artifacts_dir(notification.action_data),
            cl_name=notification.action_data.get("agent_cl_name"),
            origin="ace",
        )
    except Exception:
        log.warning("Could not submit detached epic launch", exc_info=True)
        return False
    return True


__all__ = ["submit_epic_launch_task"]

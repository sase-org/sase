"""Shared utilities for agent killing and dismissal."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models import Agent


def delete_agent_artifacts(artifacts_dir: str | None) -> None:
    """Delete artifact files that cause an agent to be loaded.

    Removes workflow_state.json, done.json, and prompt_step_*.json files
    from the artifacts directory so the agent won't be reloaded on restart.

    Args:
        artifacts_dir: Path to the agent's artifacts directory, or None.
    """
    if not artifacts_dir:
        return
    from sase.core.agent_cleanup_execution import try_delete_agent_artifacts

    if try_delete_agent_artifacts(artifacts_dir):
        return

    from pathlib import Path

    artifacts_path = Path(artifacts_dir)
    if not artifacts_path.is_dir():
        return

    # Delete files that the loaders scan for
    for pattern in ("workflow_state.json", "done.json", "prompt_step_*.json"):
        for f in artifacts_path.glob(pattern):
            try:
                f.unlink()
            except OSError:
                pass


def dismiss_notifications_for_agents(agents: Iterable[Agent]) -> int:
    """Dismiss notifications that reference any of the given agents.

    Returns the number of notifications newly marked dismissed. The notification
    file is loaded and rewritten at most once.
    """
    from sase.notifications import load_notifications
    from sase.notifications.store import rewrite_notifications

    agent_keys = {(a.cl_name, a.raw_suffix) for a in agents}
    if not agent_keys:
        return 0

    all_notifications = load_notifications(include_dismissed=True)
    dismissed_count = 0
    for n in all_notifications:
        if n.dismissed:
            continue
        if n.action == "JumpToAgent":
            cl_name = n.action_data.get("cl_name")
            raw_suffix = n.action_data.get("raw_suffix")
            if raw_suffix is None:
                match = any(agent_cl == cl_name for agent_cl, _ in agent_keys)
            else:
                match = (cl_name, raw_suffix) in agent_keys
            if match:
                n.dismissed = True
                dismissed_count += 1
        elif n.action in ("PlanApproval", "UserQuestion"):
            cl_name = n.action_data.get("agent_cl_name")
            timestamp = n.action_data.get("agent_timestamp")
            if timestamp is None:
                match = any(agent_cl == cl_name for agent_cl, _ in agent_keys)
            else:
                from ...models._timestamps import normalize_to_14_digit

                match = (cl_name, normalize_to_14_digit(timestamp)) in agent_keys
            if match:
                n.dismissed = True
                dismissed_count += 1

    if dismissed_count:
        rewrite_notifications(all_notifications)
    return dismissed_count


def find_workflow_workspace_from_running_field(
    project_file: str,
    workflow_name: str,
    cl_name: str | None = None,
) -> int | None:
    """Find workspace_num for a workflow from the RUNNING field.

    Args:
        project_file: Path to the project file.
        workflow_name: The workflow name (without "workflow()" wrapper).
        cl_name: Optional CL name for more specific matching.

    Returns:
        The workspace_num if found, None otherwise.
    """
    from sase.running_field import get_claimed_workspaces

    claims = get_claimed_workspaces(project_file)
    expected_workflow = f"workflow({workflow_name})"

    for claim in claims:
        if claim.workflow == expected_workflow:
            if cl_name is not None and claim.cl_name != cl_name:
                continue
            return claim.workspace_num

    return None

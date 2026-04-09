"""Shared utilities for agent killing and dismissal."""

from __future__ import annotations

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
    from pathlib import Path

    if not artifacts_dir:
        return

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


def dismiss_notifications_for_agent(agent: Agent) -> None:
    """Dismiss notifications that reference the given agent.

    Handles JumpToAgent (cl_name/raw_suffix), PlanApproval and UserQuestion
    (agent_cl_name/agent_timestamp) notification types.
    """
    from sase.notifications import load_notifications, mark_dismissed

    for n in load_notifications():
        if n.action == "JumpToAgent":
            if n.action_data.get("cl_name") != agent.cl_name:
                continue
            n_raw_suffix = n.action_data.get("raw_suffix")
            if n_raw_suffix is not None and n_raw_suffix != agent.raw_suffix:
                continue
            mark_dismissed(n.id)
        elif n.action in ("PlanApproval", "UserQuestion"):
            if n.action_data.get("agent_cl_name") != agent.cl_name:
                continue
            n_timestamp = n.action_data.get("agent_timestamp")
            if n_timestamp is not None:
                from ...models._timestamps import normalize_to_14_digit

                if normalize_to_14_digit(n_timestamp) != agent.raw_suffix:
                    continue
            mark_dismissed(n.id)


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

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
    store is updated atomically by the Rust-backed notification API.
    """
    from sase.notifications import dismiss_notifications_matching_agents

    return dismiss_notifications_matching_agents(
        [{"cl_name": agent.cl_name, "raw_suffix": agent.raw_suffix} for agent in agents]
    )


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

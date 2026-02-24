"""VCS diff fetching for the file panel."""

from pathlib import Path

from sase.running_field import get_workspace_directory
from sase.vcs_provider import VCSProviderNotFoundError, get_vcs_provider

from ...models.agent import Agent


def get_agent_diff(agent: Agent) -> str | None:
    """Get diff output for an agent.

    For RUNNING type agents, use workspace_num to find directory.
    For other agents, try to determine workspace from project file.

    Args:
        agent: The agent to get diff for.

    Returns:
        Diff output string, or None if unavailable.
    """
    try:
        # Get project basename from file path
        project_basename = Path(agent.project_file).stem

        if agent.workspace_num:
            workspace_dir = get_workspace_directory(
                project_basename, agent.workspace_num
            )
        else:
            # Use primary workspace for other agent types
            # Loop agents use workspaces 100+, but we show diff from main
            workspace_dir = get_workspace_directory(project_basename, 1)

        try:
            provider = get_vcs_provider(workspace_dir)
        except VCSProviderNotFoundError:
            return None

        _, diff_text = provider.diff_with_untracked(workspace_dir, timeout=10)
        if diff_text:
            return diff_text
        if agent.status in ("DONE", "FAILED"):
            _, committed = provider.committed_diff(workspace_dir, timeout=10)
            return committed
        return None

    except RuntimeError:
        # get_workspace_directory command failed
        return None
    except Exception:
        return None

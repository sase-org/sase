"""VCS diff fetching for the file panel."""

from pathlib import Path

from sase.running_field import get_workspace_directory
from sase.vcs_provider import VCSProviderNotFoundError, get_vcs_provider

from ...models.agent import Agent


def get_agent_diff(agent: Agent) -> str | None:
    """Get diff output for an agent.

    For completed agents with a diff_path, read the pre-computed diff file.
    For RUNNING agents, use workspace_num to find directory and run live diff.

    Args:
        agent: The agent to get diff for.

    Returns:
        Diff output string, or None if unavailable.
    """
    # Prefer the pre-computed diff file (e.g. from the gh workflow's diff
    # step).  This is authoritative — the workspace may have been released
    # and reused by the time we display the diff.
    if agent.diff_path:
        try:
            text = Path(agent.diff_path).read_text()
            return text if text.strip() else None
        except OSError:
            pass

    # For completed agents, the diff_path is the only reliable source.
    # The workspace may have been released and reused by another agent,
    # so falling back to `git diff HEAD~1..HEAD` would show an unrelated
    # commit's diff.
    if agent.status in ("DONE", "FAILED"):
        return None

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
        return diff_text if diff_text else None

    except RuntimeError:
        # get_workspace_directory command failed
        return None
    except Exception:
        return None

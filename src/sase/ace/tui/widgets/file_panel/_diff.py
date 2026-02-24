"""VCS diff fetching for the file panel."""

import subprocess
from pathlib import Path

from sase.running_field import get_workspace_directory
from sase.vcs_provider import detect_vcs_family

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

        # Detect VCS type from workspace directory; fall back to "hg"
        # when detection returns None (e.g. CITC/fig workspaces that
        # lack a physical .hg directory).
        vcs_type = detect_vcs_family(workspace_dir) or "hg"
        if vcs_type == "git":
            from sase.git_utils import git_committed_diff, git_diff_with_untracked

            git_diff = git_diff_with_untracked(workspace_dir, timeout=10)
            if git_diff:
                return git_diff
            # For completed agents, fall back to the last committed diff
            if agent.status in ("DONE", "FAILED"):
                return git_committed_diff(workspace_dir, timeout=10)
            return None
        elif vcs_type == "hg":
            diff_cmd = ["hg", "diff"]
        else:
            return None

        result = subprocess.run(
            diff_cmd,
            cwd=workspace_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
        return None

    except subprocess.TimeoutExpired:
        return None
    except subprocess.CalledProcessError:
        return None
    except RuntimeError:
        # get_workspace_directory command failed
        return None
    except Exception:
        return None

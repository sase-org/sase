"""VCS diff fetching for the file panel."""

import os
import subprocess
from pathlib import Path

from sase.workspace_utils import detect_vcs_type_for_project
from sase.running_field import get_workspace_directory

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

        # Detect VCS type from project config rather than filesystem
        # detection.  CITC/fig hg workspaces may lack a physical .hg
        # directory, so detect_vcs() (which walks the directory tree
        # looking for .hg/.git) can return None even though hg commands
        # work fine.  detect_vcs_type_for_project() uses the .gp file
        # configuration (WORKSPACE_DIR + .git check) which is reliable
        # for both git and hg projects.
        vcs_type = detect_vcs_type_for_project(os.path.expanduser(agent.project_file))
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
        # sase_hg_get_workspace command failed
        return None
    except Exception:
        return None

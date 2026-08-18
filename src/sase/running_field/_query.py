"""Read access to the workspace claims recorded in the RUNNING field."""

import os

from sase.core.agent_launch_claims import list_workspace_claims_from_content
from sase.running_field._model import WorkspaceClaim


def get_claimed_workspaces(project_file: str) -> list[WorkspaceClaim]:
    """Get all workspace claims from a ProjectSpec file.

    Args:
        project_file: Path to the ProjectSpec file

    Returns:
        List of WorkspaceClaim objects representing active claims
    """
    if not os.path.exists(project_file):
        return []

    try:
        with open(project_file, encoding="utf-8") as f:
            return list_workspace_claims_from_content(f.read())
    except Exception:
        return []

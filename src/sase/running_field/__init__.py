"""RUNNING field management for tracking active workflows and workspace claims.

The RUNNING field in ProjectSpec files tracks which workspace directories
are currently in use by sase workflows. Format:

RUNNING:
  #1 | 12345 | crs | my_feature
  #3 | 67890 | crs | other_feature

Where:
- #N is the workspace number (1 = main workspace, 2+ = workspace shares)
- PID is the process ID of the running agent (required - every entry must have a PID)
- WORKFLOW is the name of the running workflow (e.g., crs, crs, run, rerun)
- CL_NAME is the ChangeSpec name being worked on (optional, can be empty)
"""

from sase.running_field._model import WorkspaceClaim
from sase.running_field._operations import (
    claim_next_axe_workspace,
    claim_workspace,
    get_claimed_workspaces,
    release_workspace,
    update_running_field_cl_name,
)
from sase.running_field._workspace import (
    get_first_available_axe_workspace,
    get_first_available_workspace,
    get_workspace_directory,
    get_workspace_directory_for_num,
)

__all__ = [
    "WorkspaceClaim",
    "claim_next_axe_workspace",
    "claim_workspace",
    "get_claimed_workspaces",
    "get_first_available_axe_workspace",
    "get_first_available_workspace",
    "get_workspace_directory",
    "get_workspace_directory_for_num",
    "release_workspace",
    "update_running_field_cl_name",
]

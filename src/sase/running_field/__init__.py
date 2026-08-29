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
- CL_NAME is the Patch name being worked on (optional, can be empty)

Two WORKFLOW label forms are reserved wrappers around an inner identity:
``workflow(<name>)`` marks an xprompt workflow claim, and ``lease(<workflow>)``
marks a machine-owned operational workspace lease that is not an agent run.
"""

from sase.running_field._claim import (
    claim_next_axe_workspace,
    claim_workspace,
)
from sase.running_field._claim_labels import (
    OPERATIONAL_LEASE_CLAIM_PREFIX,
    is_operational_lease_claim_workflow,
    operational_lease_claim_workflow,
)
from sase.running_field._hold import hold_workspace_claim
from sase.running_field._model import (
    ClaimResult,
    WorkspaceClaim,
    WorkspaceClaimError,
)
from sase.running_field._query import get_claimed_workspaces
from sase.running_field._release import release_workspace
from sase.running_field._rename import update_running_field_cl_name
from sase.running_field._transfer import transfer_workspace_claim
from sase.running_field._workspace import (
    claim_next_axe_workspace_dir,
    find_runner_numbered_workspace,
    get_first_available_axe_workspace,
    get_first_available_workspace,
    get_workspace_directory,
    get_workspace_directory_for_num,
    runner_has_placeholder_workspace,
)

__all__ = [
    "OPERATIONAL_LEASE_CLAIM_PREFIX",
    "ClaimResult",
    "WorkspaceClaim",
    "WorkspaceClaimError",
    "claim_next_axe_workspace",
    "claim_next_axe_workspace_dir",
    "claim_workspace",
    "find_runner_numbered_workspace",
    "get_claimed_workspaces",
    "get_first_available_axe_workspace",
    "get_first_available_workspace",
    "get_workspace_directory",
    "get_workspace_directory_for_num",
    "hold_workspace_claim",
    "is_operational_lease_claim_workflow",
    "operational_lease_claim_workflow",
    "release_workspace",
    "runner_has_placeholder_workspace",
    "transfer_workspace_claim",
    "update_running_field_cl_name",
]

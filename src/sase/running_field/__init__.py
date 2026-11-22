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
``workflow(<name>)`` marks a macro workflow claim, and ``lease(<workflow>)``
marks a machine-owned operational workspace lease that is not an agent run.

Package-level names resolve lazily, so that importing a leaf submodule such as
``sase.running_field._model`` does not pull in the claim/release graph. This also
prevents the cycle with ``sase.core.agent_launch_claims``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase._lazy_exports import lazy_dir, lazy_getattr

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "OPERATIONAL_LEASE_CLAIM_PREFIX": (
        "sase.running_field._claim_labels",
        "OPERATIONAL_LEASE_CLAIM_PREFIX",
    ),
    "ClaimResult": ("sase.running_field._model", "ClaimResult"),
    "WorkspaceClaim": ("sase.running_field._model", "WorkspaceClaim"),
    "WorkspaceClaimError": ("sase.running_field._model", "WorkspaceClaimError"),
    "claim_next_axe_workspace": (
        "sase.running_field._claim",
        "claim_next_axe_workspace",
    ),
    "claim_next_axe_workspace_dir": (
        "sase.running_field._workspace",
        "claim_next_axe_workspace_dir",
    ),
    "claim_workspace": ("sase.running_field._claim", "claim_workspace"),
    "describe_workspace_occupant": (
        "sase.running_field._occupant",
        "describe_workspace_occupant",
    ),
    "find_runner_numbered_workspace": (
        "sase.running_field._workspace",
        "find_runner_numbered_workspace",
    ),
    "format_workspace_occupant": (
        "sase.running_field._occupant",
        "format_workspace_occupant",
    ),
    "get_claimed_workspaces": (
        "sase.running_field._query",
        "get_claimed_workspaces",
    ),
    "get_first_available_axe_workspace": (
        "sase.running_field._workspace",
        "get_first_available_axe_workspace",
    ),
    "get_first_available_workspace": (
        "sase.running_field._workspace",
        "get_first_available_workspace",
    ),
    "get_workspace_directory": (
        "sase.running_field._workspace",
        "get_workspace_directory",
    ),
    "get_workspace_directory_for_num": (
        "sase.running_field._workspace",
        "get_workspace_directory_for_num",
    ),
    "hold_workspace_claim": ("sase.running_field._hold", "hold_workspace_claim"),
    "is_operational_lease_claim_workflow": (
        "sase.running_field._claim_labels",
        "is_operational_lease_claim_workflow",
    ),
    "operational_lease_claim_workflow": (
        "sase.running_field._claim_labels",
        "operational_lease_claim_workflow",
    ),
    "pid_is_alive": ("sase.running_field._occupant", "pid_is_alive"),
    "release_workspace": ("sase.running_field._release", "release_workspace"),
    "runner_has_placeholder_workspace": (
        "sase.running_field._workspace",
        "runner_has_placeholder_workspace",
    ),
    "transfer_workspace_claim": (
        "sase.running_field._transfer",
        "transfer_workspace_claim",
    ),
    "update_running_field_cl_name": (
        "sase.running_field._rename",
        "update_running_field_cl_name",
    ),
}

if TYPE_CHECKING:
    from ._claim import (
        claim_next_axe_workspace,
        claim_workspace,
    )
    from ._claim_labels import (
        OPERATIONAL_LEASE_CLAIM_PREFIX,
        is_operational_lease_claim_workflow,
        operational_lease_claim_workflow,
    )
    from ._hold import hold_workspace_claim
    from ._model import (
        ClaimResult,
        WorkspaceClaim,
        WorkspaceClaimError,
    )
    from ._occupant import (
        describe_workspace_occupant,
        format_workspace_occupant,
        pid_is_alive,
    )
    from ._query import get_claimed_workspaces
    from ._release import release_workspace
    from ._rename import update_running_field_cl_name
    from ._transfer import transfer_workspace_claim
    from ._workspace import (
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
    "describe_workspace_occupant",
    "format_workspace_occupant",
    "pid_is_alive",
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


def __getattr__(name: str) -> object:
    return lazy_getattr(__name__, globals(), _LAZY_EXPORTS, name)


def __dir__() -> list[str]:
    return lazy_dir(globals(), _LAZY_EXPORTS)


# Symvision cannot see Python's package-level lazy hook lookup.
_PACKAGE_GETATTR = __getattr__
_PACKAGE_DIR = __dir__

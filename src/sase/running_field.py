"""
RUNNING field management for tracking active workflows and workspace claims.

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

import os
import re
from dataclasses import dataclass

from sase.spec_writer.client import make_request, submit_spec_write_and_wait
from sase.spec_writer.models import OperationType


@dataclass
class WorkspaceClaim:
    """Represents a single workspace claim in the RUNNING field."""

    workspace_num: int
    workflow: str
    cl_name: str | None
    pid: int
    artifacts_timestamp: str | None = None
    pinned: bool = False

    def to_line(self) -> str:
        """Convert to RUNNING field line format.

        Format: #N | PID | WORKFLOW | CL_NAME | TIMESTAMP
        PID is second to make it easily visible for process management.

        Raises:
            ValueError: If pid is not set (every RUNNING entry must have a PID).
        """
        cl_part = self.cl_name or ""
        ts_part = f" | {self.artifacts_timestamp}" if self.artifacts_timestamp else ""
        pin_part = " | PINNED" if self.pinned else ""
        return f"  #{self.workspace_num} | {self.pid} | {self.workflow} | {cl_part}{ts_part}{pin_part}"

    @staticmethod
    def from_line(line: str) -> "WorkspaceClaim | None":
        """Parse a RUNNING field line into a WorkspaceClaim.

        Format (PID second, required):
        - #<N> | <PID> | <WORKFLOW> | <CL_NAME>
        - #<N> | <PID> | <WORKFLOW> | <CL_NAME> | <TIMESTAMP>

        Note: Returns None for entries without a PID (PID is required).
        """
        match = re.match(
            r"^\s*#(\d+)\s*\|\s*(\d+)\s*\|\s*(\S+)\s*\|\s*([^|]*?)"
            r"(?:\s*\|\s*(\d{6}_\d{6}|\d{14}))?(?:\s*\|\s*([^|]+))?$",
            line,
        )
        if match:
            workspace_num = int(match.group(1))
            pid = int(match.group(2))
            workflow = match.group(3)
            cl_name = match.group(4).strip() or None
            artifacts_timestamp = match.group(5) if match.group(5) else None
            pinned = match.group(6) is not None and match.group(6).strip() == "PINNED"
            return WorkspaceClaim(
                workspace_num=workspace_num,
                workflow=workflow,
                cl_name=cl_name,
                pid=pid,
                artifacts_timestamp=artifacts_timestamp,
                pinned=pinned,
            )

        return None


def normalize_running_field_spacing(content: str) -> str:
    """Normalize blank lines around the RUNNING field.

    Ensures exactly two blank lines between:
    - The last RUNNING entry and the first ChangeSpec (NAME field)
    - If there's no RUNNING field, clean up any orphaned blank lines at the start

    Args:
        content: The file content as a string.

    Returns:
        The content with normalized spacing.
    """
    lines = content.split("\n")
    result_lines: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Check if this is the RUNNING field
        if line.startswith("RUNNING:"):
            result_lines.append(line)
            i += 1

            # Collect all RUNNING entries (2-space indented lines starting with #)
            while i < len(lines):
                entry_line = lines[i]
                if entry_line.startswith("  ") and entry_line.strip().startswith("#"):
                    result_lines.append(entry_line)
                    i += 1
                else:
                    break

            # Skip all blank lines after RUNNING entries
            while i < len(lines) and lines[i].strip() == "":
                i += 1

            # Add exactly two blank lines before the next content (NAME field)
            if i < len(lines):
                result_lines.append("")
                result_lines.append("")
        else:
            result_lines.append(line)
            i += 1

    return "\n".join(result_lines)


def clean_orphaned_blank_lines(content: str) -> str:
    """Clean up orphaned consecutive blank lines in the file.

    This is used after removing the RUNNING field entirely to clean up
    any extra blank lines that were left behind.

    Args:
        content: The file content as a string.

    Returns:
        The content with consecutive blank lines reduced to at most two.
        Two blank lines are preserved because they serve as boundaries
        between ChangeSpecs.
    """
    lines = content.split("\n")
    result_lines: list[str] = []
    consecutive_blank_count = 0

    for line in lines:
        is_blank = line.strip() == ""

        if is_blank:
            consecutive_blank_count += 1
            # Allow at most 2 consecutive blank lines (ChangeSpec boundary)
            if consecutive_blank_count > 2:
                continue
        else:
            consecutive_blank_count = 0

        result_lines.append(line)

    return "\n".join(result_lines)


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
            lines = f.readlines()
    except Exception:
        return []

    claims: list[WorkspaceClaim] = []
    in_running_field = False

    for line in lines:
        if line.startswith("RUNNING:"):
            in_running_field = True
            continue

        if in_running_field:
            # Check if this is a continuation line (starts with 2 spaces)
            if line.startswith("  ") and line.strip().startswith("#") is not False:
                claim = WorkspaceClaim.from_line(line)
                if claim:
                    claims.append(claim)
            else:
                # End of RUNNING field
                break

    return claims


def claim_workspace(
    project_file: str,
    workspace_num: int,
    workflow: str,
    pid: int,
    cl_name: str | None = None,
    artifacts_timestamp: str | None = None,
    pinned: bool = False,
) -> bool:
    """Claim a workspace by adding it to the RUNNING field.

    Acquires a lock for the entire read-modify-write cycle.

    Args:
        project_file: Path to the ProjectSpec file
        workspace_num: Workspace number to claim (1 = main, 2+ = shares)
        workflow: Name of the workflow claiming the workspace
        pid: Process ID of the claiming process (required)
        cl_name: Optional ChangeSpec name being worked on
        artifacts_timestamp: Optional timestamp of the artifacts directory (YYYYmmddHHMMSS)
        pinned: If True, the claim is pinned and won't be cleaned up as stale

    Returns:
        True if claim was successful, False otherwise
    """
    params: dict = {
        "workspace_num": workspace_num,
        "workflow": workflow,
        "pid": pid,
    }
    if cl_name is not None:
        params["cl_name"] = cl_name
    if artifacts_timestamp is not None:
        params["artifacts_timestamp"] = artifacts_timestamp
    if pinned:
        params["pinned"] = pinned

    if not os.path.exists(project_file):
        return False

    try:
        request = make_request(project_file, OperationType.CLAIM_WORKSPACE, params)
        response = submit_spec_write_and_wait(request, timeout=10.0)
        return response.success
    except Exception:
        return False


def release_workspace(
    project_file: str,
    workspace_num: int,
    workflow: str | None = None,
    cl_name: str | None = None,
) -> bool:
    """Release a workspace by removing it from the RUNNING field.

    Acquires a lock for the entire read-modify-write cycle.

    Args:
        project_file: Path to the ProjectSpec file
        workspace_num: Workspace number to release
        workflow: Optional workflow name to match (for more specific release)
        cl_name: Optional ChangeSpec name to match (for more specific release)

    Returns:
        True if release was successful, False otherwise
    """
    if not os.path.exists(project_file):
        return False

    params: dict = {"workspace_num": workspace_num}
    if workflow is not None:
        params["workflow"] = workflow
    if cl_name is not None:
        params["cl_name"] = cl_name

    try:
        request = make_request(project_file, OperationType.RELEASE_WORKSPACE, params)
        response = submit_spec_write_and_wait(request, timeout=10.0)
        return response.success
    except Exception:
        return False


def update_running_field_cl_name(
    project_file: str,
    old_cl_name: str,
    new_cl_name: str,
) -> bool:
    """Update the cl_name in RUNNING field entries.

    This is used when a ChangeSpec is renamed (e.g., during restore) to
    ensure the RUNNING field entries reference the new name.
    Acquires a lock for the entire read-modify-write cycle.

    Args:
        project_file: Path to the ProjectSpec file
        old_cl_name: The old ChangeSpec name to replace
        new_cl_name: The new ChangeSpec name

    Returns:
        True if update was successful, False otherwise
    """
    if not os.path.exists(project_file):
        return False

    try:
        request = make_request(
            project_file,
            OperationType.UPDATE_RUNNING_CL_NAME,
            {"old_cl_name": old_cl_name, "new_cl_name": new_cl_name},
        )
        response = submit_spec_write_and_wait(request, timeout=10.0)
        return response.success
    except Exception:
        return False


def get_first_available_workspace(project_file: str, max_workspaces: int = 99) -> int:
    """Find the first available (unclaimed) workspace number.

    Args:
        project_file: Path to the ProjectSpec file
        max_workspaces: Maximum workspace number to check (1-99)

    Returns:
        First available workspace number (1 = main, 2+ = shares)
    """
    claims = get_claimed_workspaces(project_file)
    claimed_nums = {claim.workspace_num for claim in claims}

    # Find first unclaimed workspace number
    for n in range(1, max_workspaces + 1):
        if n not in claimed_nums:
            return n

    # All workspaces claimed - return 1 as fallback
    return 1


def get_first_available_axe_workspace(
    project_file: str, min_workspace: int = 100, max_workspace: int = 199
) -> int:
    """Find the first available (unclaimed) workspace number for axe hooks.

    Axe hooks use workspace numbers >= 100 to avoid conflicts with regular
    workflows that use workspaces 1-99.

    Args:
        project_file: Path to the ProjectSpec file
        min_workspace: Minimum workspace number to consider (default: 100)
        max_workspace: Maximum workspace number to consider (default: 199)

    Returns:
        First available workspace number in the axe range (100-199)
    """
    claims = get_claimed_workspaces(project_file)
    claimed_nums = {claim.workspace_num for claim in claims}

    # Find first unclaimed workspace number in axe range
    for n in range(min_workspace, max_workspace + 1):
        if n not in claimed_nums:
            return n

    # All axe workspaces claimed - return min_workspace as fallback
    return min_workspace


def get_workspace_directory_for_num(
    workspace_num: int, project_basename: str, *, clean: bool = True
) -> tuple[str, str | None]:
    """Get the workspace directory path for a given workspace number.

    Calls sase_hg_get_workspace to get the directory path, which will create
    workspace shares if they don't exist.

    For non-main workspaces (workspace_num > 1), automatically cleans the
    workspace to revert any uncommitted changes before returning.  This
    prevents ``checkout`` / ``hg update`` failures caused by leftover dirty
    state from a previous run.

    Args:
        workspace_num: Workspace number (1 = main, 2+ = shares)
        project_basename: Project name
        clean: If True (default), clean non-main workspaces before returning.

    Returns:
        Tuple of (workspace_directory, workspace_suffix)
        - workspace_directory: Full path to workspace directory
        - workspace_suffix: Suffix like "fig_3" or None for main workspace

    Raises:
        RuntimeError: If sase_hg_get_workspace command fails
    """
    workspace_dir = get_workspace_directory(project_basename, workspace_num)

    if workspace_num == 1:
        return (workspace_dir, None)

    # Clean non-main workspaces to avoid checkout conflicts from leftover
    # dirty state.
    if clean:
        from sase.commit_utils import clean_workspace

        clean_workspace(workspace_dir)

    workspace_suffix = f"{project_basename}_{workspace_num}"
    return (workspace_dir, workspace_suffix)


def get_workspace_directory(project: str, workspace_num: int = 1) -> str:
    """Get the workspace directory path for a project.

    Delegates to workspace provider plugins via the
    ``ws_get_workspace_directory`` hook.

    Args:
        project: Project name (e.g., "foobar")
        workspace_num: Workspace number (1 = main, 2+ = shares)

    Returns:
        Full path to workspace directory

    Raises:
        RuntimeError: If workspace resolution fails
    """
    from sase.workspace_provider import (
        detect_workflow_type,
        get_workspace_directory as ws_get_workspace_directory,
    )
    from sase.workspace_utils import parse_workspace_dir
    from sase.workflow_utils import get_project_file_path

    project_file = get_project_file_path(project)
    try:
        workflow_type = detect_workflow_type(project_file)
    except ValueError as e:
        raise RuntimeError(str(e)) from e
    workspace_dir = parse_workspace_dir(project_file) or ""
    return ws_get_workspace_directory(
        workflow_type, workspace_num, project, workspace_dir
    )

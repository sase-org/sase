"""RUNNING field CRUD operations for tracking active workflows."""

import os
import time

from sase.ace.changespec import changespec_lock, write_changespec_atomic
from sase.running_field._formatting import (
    clean_orphaned_blank_lines,
    normalize_running_field_spacing,
)
from sase.running_field._model import WorkspaceClaim
from sase.telemetry.metrics import (
    WORKSPACE_ACQUISITIONS,
    WORKSPACE_ACTIVE,
    WORKSPACE_RELEASES,
)


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
    max_retries = 2
    for attempt in range(1 + max_retries):
        if not os.path.exists(project_file):
            if attempt < max_retries:
                time.sleep(0.5)
                continue
            return False

        try:
            with changespec_lock(project_file):
                with open(project_file, encoding="utf-8") as f:
                    content = f.read()
                    lines = content.split("\n")

                new_claim = WorkspaceClaim(
                    workspace_num=workspace_num,
                    workflow=workflow,
                    cl_name=cl_name,
                    pid=pid,
                    artifacts_timestamp=artifacts_timestamp,
                    pinned=pinned,
                )

                # Find RUNNING field
                running_field_idx = -1
                running_end_idx = -1

                for i, line in enumerate(lines):
                    if line.startswith("RUNNING:"):
                        running_field_idx = i
                        # Find end of RUNNING field
                        for j in range(i + 1, len(lines)):
                            if lines[j].startswith("  ") and (
                                lines[j].strip().startswith("#")
                                or lines[j].strip().startswith("|")
                            ):
                                running_end_idx = j
                            else:
                                if running_end_idx == -1:
                                    running_end_idx = i
                                break
                        else:
                            if running_end_idx == -1:
                                running_end_idx = i
                        break

                if running_field_idx >= 0:
                    # Reject duplicate workspace numbers (TOCTOU race guard).
                    # Two processes can call get_first_available_axe_workspace()
                    # concurrently and both get the same number before either
                    # claims it.  By checking under the lock we prevent the
                    # second process from silently double-claiming.
                    if workspace_num != 0:
                        for k in range(running_field_idx + 1, running_end_idx + 1):
                            existing = WorkspaceClaim.from_line(lines[k])
                            if (
                                existing is not None
                                and existing.workspace_num == workspace_num
                            ):
                                return False

                    # RUNNING field exists - add new claim
                    # Insert after the last continuation line
                    insert_idx = running_end_idx + 1
                    lines.insert(insert_idx, new_claim.to_line())
                else:
                    # RUNNING field doesn't exist - create it at the beginning
                    lines.insert(0, f"RUNNING:\n{new_claim.to_line()}\n")

                # Normalize blank lines around RUNNING field
                result_content = "\n".join(lines)
                result_content = normalize_running_field_spacing(result_content)

                # Write atomically
                cl_part = f" for {cl_name}" if cl_name else ""
                write_changespec_atomic(
                    project_file,
                    result_content,
                    f"Claim workspace #{workspace_num} ({workflow}){cl_part}",
                )
                project = os.path.splitext(os.path.basename(project_file))[0]
                WORKSPACE_ACQUISITIONS.labels(project=project).inc()
                WORKSPACE_ACTIVE.labels(project=project).inc()
                return True
        except Exception:
            if attempt < max_retries:
                time.sleep(0.5)
                continue
            return False

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

    try:
        with changespec_lock(project_file):
            with open(project_file, encoding="utf-8") as f:
                content = f.read()

            from sase.core.agent_cleanup_execution import (
                try_release_workspace_from_content,
            )

            rust_result = try_release_workspace_from_content(
                content, workspace_num, workflow, cl_name
            )
            if rust_result is not None:
                result_content = str(rust_result["content"])
            else:
                lines = content.split("\n")
                new_lines: list[str] = []
                in_running_field = False
                running_field_idx = -1
                has_remaining_claims = False

                for line in lines:
                    if line.startswith("RUNNING:"):
                        in_running_field = True
                        running_field_idx = len(new_lines)
                        new_lines.append(line)
                        continue

                    if in_running_field and line.startswith("  "):
                        claim = WorkspaceClaim.from_line(line)
                        if claim:
                            # Check if this is the claim to remove
                            should_remove = claim.workspace_num == workspace_num
                            if workflow and claim.workflow != workflow:
                                should_remove = False
                            if cl_name and claim.cl_name != cl_name:
                                should_remove = False

                            if should_remove:
                                # Skip this line (remove the claim)
                                continue
                            else:
                                has_remaining_claims = True
                    else:
                        in_running_field = False

                    new_lines.append(line)

                # If RUNNING field is now empty, remove it entirely
                if running_field_idx >= 0 and not has_remaining_claims:
                    # Remove the RUNNING: line
                    del new_lines[running_field_idx]

                # Normalize blank lines (clean up extra blanks after RUNNING field or where it was)
                result_content = "\n".join(new_lines)
                if has_remaining_claims:
                    # Normalize spacing around remaining RUNNING field
                    result_content = normalize_running_field_spacing(result_content)
                else:
                    # Clean up orphaned blank lines where RUNNING field was removed
                    result_content = clean_orphaned_blank_lines(result_content)

            # Write atomically
            write_changespec_atomic(
                project_file,
                result_content,
                f"Release workspace #{workspace_num}",
            )
            project = os.path.splitext(os.path.basename(project_file))[0]
            WORKSPACE_RELEASES.labels(project=project).inc()
            WORKSPACE_ACTIVE.labels(project=project).dec()
            return True
    except Exception:
        return False


def transfer_workspace_claim(
    project_file: str,
    workspace_num: int,
    *,
    from_pid: int,
    to_pid: int,
    new_workflow: str,
    new_artifacts_timestamp: str | None,
    cl_name: str | None = None,
) -> bool:
    """Atomically transfer ownership of an existing workspace claim to a new PID.

    Used by the spawn-on-retry flow to hand a workspace claim from a failing
    parent agent to a fresh detached child without freeing the slot for
    other agents in between.  Updates the claim row in place under the
    ProjectSpec lock — the workspace slot stays continuously claimed.

    Returns True iff the matching claim row was found and updated.
    """
    if not os.path.exists(project_file):
        return False

    try:
        with changespec_lock(project_file):
            with open(project_file, encoding="utf-8") as f:
                content = f.read()
                lines = content.split("\n")

            new_lines: list[str] = []
            in_running_field = False
            updated = False

            for line in lines:
                if line.startswith("RUNNING:"):
                    in_running_field = True
                    new_lines.append(line)
                    continue

                if in_running_field and line.startswith("  "):
                    claim = WorkspaceClaim.from_line(line)
                    if (
                        claim
                        and not updated
                        and claim.workspace_num == workspace_num
                        and claim.pid == from_pid
                        and (cl_name is None or claim.cl_name == cl_name)
                    ):
                        replacement = WorkspaceClaim(
                            workspace_num=claim.workspace_num,
                            workflow=new_workflow,
                            cl_name=claim.cl_name,
                            pid=to_pid,
                            artifacts_timestamp=new_artifacts_timestamp
                            or claim.artifacts_timestamp,
                            pinned=claim.pinned,
                        )
                        new_lines.append(replacement.to_line())
                        updated = True
                        continue
                else:
                    in_running_field = False

                new_lines.append(line)

            if not updated:
                return False

            write_changespec_atomic(
                project_file,
                "\n".join(new_lines),
                f"Transfer workspace #{workspace_num} from pid {from_pid} to {to_pid}",
            )
            return True
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
        with changespec_lock(project_file):
            with open(project_file, encoding="utf-8") as f:
                content = f.read()
                lines = content.split("\n")

            new_lines: list[str] = []
            in_running_field = False
            updated = False

            for line in lines:
                if line.startswith("RUNNING:"):
                    in_running_field = True
                    new_lines.append(line)
                    continue

                if in_running_field and line.startswith("  "):
                    claim = WorkspaceClaim.from_line(line)
                    if claim and claim.cl_name == old_cl_name:
                        # Update the cl_name, preserving other fields
                        updated_claim = WorkspaceClaim(
                            workspace_num=claim.workspace_num,
                            workflow=claim.workflow,
                            cl_name=new_cl_name,
                            pid=claim.pid,
                            artifacts_timestamp=claim.artifacts_timestamp,
                            pinned=claim.pinned,
                        )
                        new_lines.append(updated_claim.to_line())
                        updated = True
                        continue
                else:
                    in_running_field = False

                new_lines.append(line)

            if not updated:
                # No changes needed
                return True

            # Write atomically
            write_changespec_atomic(
                project_file,
                "\n".join(new_lines),
                f"Rename {old_cl_name} to {new_cl_name} in RUNNING field",
            )
            return True
    except Exception:
        return False


def claim_next_axe_workspace(
    project_file: str,
    workflow: str,
    pid: int,
    cl_name: str | None = None,
    artifacts_timestamp: str | None = None,
    pinned: bool = False,
    min_workspace: int = 100,
    max_workspace: int = 199,
) -> int:
    """Atomically find and claim the next available axe workspace.

    Combines ``get_first_available_axe_workspace`` and ``claim_workspace``
    into a single operation to eliminate the TOCTOU race window between
    reading the available workspace number and claiming it.

    Args:
        project_file: Path to the ProjectSpec file.
        workflow: Name of the workflow claiming the workspace.
        pid: Process ID of the claiming process.
        cl_name: Optional ChangeSpec name being worked on.
        artifacts_timestamp: Optional timestamp of the artifacts directory.
        pinned: If True, the claim is pinned and won't be cleaned up as stale.
        min_workspace: Minimum workspace number to consider (default: 100).
        max_workspace: Maximum workspace number to consider (default: 199).

    Returns:
        The claimed workspace number.

    Raises:
        RuntimeError: If no workspace could be claimed.
    """
    max_retries = 2
    for attempt in range(1 + max_retries):
        if not os.path.exists(project_file):
            if attempt < max_retries:
                time.sleep(0.5)
                continue
            raise RuntimeError(f"Project file does not exist: {project_file}")

        try:
            with changespec_lock(project_file):
                with open(project_file, encoding="utf-8") as f:
                    content = f.read()
                    lines = content.split("\n")

                # Find RUNNING field and existing claims
                running_field_idx = -1
                running_end_idx = -1
                claimed_nums: set[int] = set()

                for i, line in enumerate(lines):
                    if line.startswith("RUNNING:"):
                        running_field_idx = i
                        for j in range(i + 1, len(lines)):
                            if lines[j].startswith("  ") and (
                                lines[j].strip().startswith("#")
                                or lines[j].strip().startswith("|")
                            ):
                                running_end_idx = j
                                existing = WorkspaceClaim.from_line(lines[j])
                                if existing is not None:
                                    claimed_nums.add(existing.workspace_num)
                            else:
                                if running_end_idx == -1:
                                    running_end_idx = i
                                break
                        else:
                            if running_end_idx == -1:
                                running_end_idx = i
                        break

                # Find first available workspace number
                workspace_num: int | None = None
                for n in range(min_workspace, max_workspace + 1):
                    if n not in claimed_nums:
                        workspace_num = n
                        break

                if workspace_num is None:
                    raise RuntimeError(
                        f"All axe workspaces ({min_workspace}-{max_workspace}) "
                        f"are claimed in {project_file}"
                    )

                new_claim = WorkspaceClaim(
                    workspace_num=workspace_num,
                    workflow=workflow,
                    cl_name=cl_name,
                    pid=pid,
                    artifacts_timestamp=artifacts_timestamp,
                    pinned=pinned,
                )

                if running_field_idx >= 0:
                    insert_idx = running_end_idx + 1
                    lines.insert(insert_idx, new_claim.to_line())
                else:
                    lines.insert(0, f"RUNNING:\n{new_claim.to_line()}\n")

                result_content = "\n".join(lines)
                result_content = normalize_running_field_spacing(result_content)

                cl_part = f" for {cl_name}" if cl_name else ""
                write_changespec_atomic(
                    project_file,
                    result_content,
                    f"Claim workspace #{workspace_num} ({workflow}){cl_part}",
                )
                project = os.path.splitext(os.path.basename(project_file))[0]
                WORKSPACE_ACQUISITIONS.labels(project=project).inc()
                WORKSPACE_ACTIVE.labels(project=project).inc()
                return workspace_num
        except RuntimeError:
            raise
        except Exception as exc:
            if attempt < max_retries:
                time.sleep(0.5)
                continue
            raise RuntimeError(
                f"Failed to claim axe workspace in {project_file} "
                f"after {1 + max_retries} attempts"
            ) from exc

    raise RuntimeError(
        f"Failed to claim axe workspace in {project_file} "
        f"after {1 + max_retries} attempts"
    )

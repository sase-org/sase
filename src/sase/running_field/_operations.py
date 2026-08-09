"""RUNNING field CRUD operations for tracking active workflows."""

import os
import time
from pathlib import Path

from sase.ace.patch import changespec_lock, write_changespec_atomic
from sase.core.agent_launch_claims import (
    allocate_and_claim_workspace_from_content,
    list_workspace_claims_from_content,
    plan_claim_workspace_from_content,
    plan_transfer_workspace_claim_from_content,
)
from sase.core.agent_launch_wire import WorkspaceClaimRequestWire
from sase.core.project_lifecycle_facade import read_project_lifecycle_from_content
from sase.core.project_lifecycle_wire import is_disabled_project_lifecycle_state
from sase.running_field._formatting import (
    clean_orphaned_blank_lines,
    normalize_running_field_spacing,
)
from sase.running_field._model import (
    ClaimResult,
    WorkspaceClaim,
    WorkspaceClaimError,
)
from sase.telemetry.metrics import WORKSPACE_ACTIVE


def _project_name_from_file(project_file: str) -> str:
    path = Path(project_file)
    if path.name.endswith("-archive.sase"):
        return path.name.removesuffix("-archive.sase")
    if path.name.endswith("-archive.gp"):
        return path.name.removesuffix("-archive.gp")
    return path.stem


def _disabled_project_claim_error(project_file: str, state: str) -> str:
    project = _project_name_from_file(project_file)
    return (
        f"project '{project}' is {state}; run 'sase project enable {project}' "
        "before launching work"
    )


def _new_work_lifecycle_error(project_file: str, content: str) -> str | None:
    lifecycle = read_project_lifecycle_from_content(content)
    if is_disabled_project_lifecycle_state(lifecycle.state):
        return _disabled_project_claim_error(project_file, lifecycle.state)
    return None


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


def claim_workspace(
    project_file: str,
    workspace_num: int,
    workflow: str,
    pid: int,
    cl_name: str | None = None,
    artifacts_timestamp: str | None = None,
    pinned: bool = False,
) -> ClaimResult:
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
        ClaimResult.  ``success`` is True on a successful claim.  On failure
        ``error`` carries a human-readable reason: the Rust outcome's
        ``error`` field for Rust-rejected claims, or ``repr(exc)`` for
        Python-side failures (transient IO errors after the retry budget,
        a missing project file, etc.).
    """
    max_retries = 2
    last_error: str | None = None
    for attempt in range(1 + max_retries):
        if not os.path.exists(project_file):
            last_error = f"project file does not exist: {project_file}"
            if attempt < max_retries:
                time.sleep(0.5)
                continue
            return ClaimResult(success=False, error=last_error)

        try:
            with changespec_lock(project_file):
                with open(project_file, encoding="utf-8") as f:
                    content = f.read()

                lifecycle_error = _new_work_lifecycle_error(project_file, content)
                if lifecycle_error is not None:
                    return ClaimResult(success=False, error=lifecycle_error)

                plan = plan_claim_workspace_from_content(
                    content,
                    WorkspaceClaimRequestWire(
                        project_file=project_file,
                        workspace_num=workspace_num,
                        workflow_name=workflow,
                        pid=pid,
                        cl_name=cl_name or "",
                        artifacts_timestamp=artifacts_timestamp or "",
                        pinned=pinned,
                    ),
                )
                outcome = dict(plan["outcome"])
                if not bool(outcome["success"]):
                    reason = outcome.get("error") or (
                        f"workspace #{workspace_num} claim rejected by core"
                    )
                    return ClaimResult(success=False, error=str(reason))

                cl_part = f" for {cl_name}" if cl_name else ""
                write_changespec_atomic(
                    project_file,
                    str(plan["content"]),
                    f"Claim workspace #{workspace_num} ({workflow}){cl_part}",
                )
                project = os.path.splitext(os.path.basename(project_file))[0]
                WORKSPACE_ACTIVE.labels(project=project).inc()
                return ClaimResult(success=True)
        except (OSError, BlockingIOError) as exc:
            last_error = repr(exc)
            if attempt < max_retries:
                time.sleep(0.5)
                continue
            return ClaimResult(success=False, error=last_error)

    return ClaimResult(
        success=False, error=last_error or "claim retry budget exhausted"
    )


def release_workspace(
    project_file: str,
    workspace_num: int,
    workflow: str | None = None,
    cl_name: str | None = None,
) -> ClaimResult:
    """Release a workspace by removing it from the RUNNING field.

    Acquires a lock for the entire read-modify-write cycle.

    Args:
        project_file: Path to the ProjectSpec file
        workspace_num: Workspace number to release
        workflow: Optional workflow name to match (for more specific release)
        cl_name: Optional ChangeSpec name to match (for more specific release)

    Returns:
        ClaimResult.  ``success`` is True on a successful release; on
        failure ``error`` carries the reason (missing project file or a
        captured exception's ``repr``).
    """
    if not os.path.exists(project_file):
        return ClaimResult(
            success=False,
            error=f"project file does not exist: {project_file}",
        )

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
            WORKSPACE_ACTIVE.labels(project=project).dec()
            return ClaimResult(success=True)
    except (OSError, BlockingIOError) as exc:
        return ClaimResult(success=False, error=repr(exc))


def hold_workspace_claim(
    project_file: str,
    workspace_num: int,
    workflow: str,
    cl_name: str,
    artifacts_timestamp: str,
) -> ClaimResult:
    """Atomically pin the existing workspace claim for a failed agent run.

    The claim is removed and re-added in memory under one ProjectSpec lock so
    readers can never observe the workspace as available.  Existing claim
    ownership metadata, including the PID, is preserved.
    """
    if not os.path.exists(project_file):
        return ClaimResult(
            success=False,
            error=f"project file does not exist: {project_file}",
        )

    try:
        with changespec_lock(project_file):
            with open(project_file, encoding="utf-8") as f:
                content = f.read()

            claim = next(
                (
                    item
                    for item in list_workspace_claims_from_content(content)
                    if item.workspace_num == workspace_num
                    and item.workflow == workflow
                    and item.cl_name == cl_name
                    and item.artifacts_timestamp == artifacts_timestamp
                ),
                None,
            )
            if claim is None:
                return ClaimResult(
                    success=False,
                    error=(
                        f"workspace #{workspace_num} claim for {workflow}/{cl_name} "
                        f"at {artifacts_timestamp} was not found"
                    ),
                )
            if claim.pinned:
                return ClaimResult(success=True)

            from sase.core.agent_cleanup_execution import (
                try_release_workspace_from_content,
            )

            released = try_release_workspace_from_content(
                content,
                workspace_num,
                workflow,
                cl_name,
            )
            if released is None or not bool(released.get("removed")):
                return ClaimResult(
                    success=False,
                    error=f"workspace #{workspace_num} claim could not be held",
                )

            plan = plan_claim_workspace_from_content(
                str(released["content"]),
                WorkspaceClaimRequestWire(
                    project_file=project_file,
                    workspace_num=workspace_num,
                    workflow_name=claim.workflow,
                    pid=claim.pid,
                    cl_name=claim.cl_name or "",
                    artifacts_timestamp=claim.artifacts_timestamp or "",
                    pinned=True,
                ),
            )
            outcome = dict(plan["outcome"])
            if not bool(outcome["success"]):
                reason = outcome.get("error") or (
                    f"workspace #{workspace_num} hold rejected by core"
                )
                return ClaimResult(success=False, error=str(reason))

            write_changespec_atomic(
                project_file,
                str(plan["content"]),
                f"Hold workspace #{workspace_num} for failed agent run",
            )
            return ClaimResult(success=True)
    except (OSError, BlockingIOError) as exc:
        return ClaimResult(success=False, error=repr(exc))


def transfer_workspace_claim(
    project_file: str,
    workspace_num: int,
    *,
    from_pid: int,
    to_pid: int,
    new_workflow: str,
    new_artifacts_timestamp: str | None,
    cl_name: str | None = None,
) -> ClaimResult:
    """Atomically transfer ownership of an existing workspace claim to a new PID.

    Used by the spawn-on-retry flow to hand a workspace claim from a failing
    parent agent to a fresh detached child without freeing the slot for
    other agents in between.  Updates the claim row in place under the
    ProjectSpec lock — the workspace slot stays continuously claimed.

    Returns:
        ClaimResult.  ``success`` is True iff the matching claim row was
        found and updated; ``error`` carries the Rust outcome reason on
        rejection or ``repr(exc)`` on a Python-side failure.
    """
    if not os.path.exists(project_file):
        return ClaimResult(
            success=False,
            error=f"project file does not exist: {project_file}",
        )

    try:
        with changespec_lock(project_file):
            with open(project_file, encoding="utf-8") as f:
                content = f.read()

            plan = plan_transfer_workspace_claim_from_content(
                content,
                WorkspaceClaimRequestWire(
                    project_file=project_file,
                    workspace_num=workspace_num,
                    workflow_name=new_workflow,
                    pid=to_pid,
                    cl_name=cl_name or "",
                    artifacts_timestamp=new_artifacts_timestamp or "",
                    transfer_from_pid=from_pid,
                ),
            )
            outcome = dict(plan["outcome"])
            if not bool(outcome["success"]):
                reason = outcome.get("error") or (
                    f"transfer of workspace #{workspace_num} from pid {from_pid} "
                    "rejected by core"
                )
                return ClaimResult(success=False, error=str(reason))

            write_changespec_atomic(
                project_file,
                str(plan["content"]),
                f"Transfer workspace #{workspace_num} from pid {from_pid} to {to_pid}",
            )
            return ClaimResult(success=True)
    except (OSError, BlockingIOError) as exc:
        return ClaimResult(success=False, error=repr(exc))


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
    min_workspace: int | None = None,
    max_workspace: int | None = None,
) -> int:
    """Atomically find and claim the next available axe workspace.

    Combines ``get_first_available_axe_workspace`` and ``claim_workspace``
    into a single operation to eliminate the TOCTOU race window between
    reading the available workspace number and claiming it.

    Claim-backed workspaces share the unified pool with workflow shares;
    the default range is ``10-999`` (``#0`` is the primary checkout /
    deferred placeholder and ``#1``-``#9`` are reserved).  Explicit
    ``min_workspace`` / ``max_workspace`` arguments override the default
    for tests and advanced callers.

    Args:
        project_file: Path to the ProjectSpec file.
        workflow: Name of the workflow claiming the workspace.
        pid: Process ID of the claiming process.
        cl_name: Optional ChangeSpec name being worked on.
        artifacts_timestamp: Optional timestamp of the artifacts directory.
        pinned: If True, the claim is pinned and won't be cleaned up as stale.
        min_workspace: Minimum workspace number to consider (default: 10).
        max_workspace: Maximum workspace number to consider (default: 999).

    Returns:
        The claimed workspace number.

    Raises:
        WorkspaceClaimError: If no workspace could be claimed.  The message
            includes the Rust outcome's ``error`` field when present so
            callers / digests can see why.
    """
    from sase.running_field._workspace import (
        UNIFIED_MAX_WORKSPACE,
        UNIFIED_MIN_WORKSPACE,
    )

    if min_workspace is None:
        min_workspace = UNIFIED_MIN_WORKSPACE
    if max_workspace is None:
        max_workspace = UNIFIED_MAX_WORKSPACE

    max_retries = 2
    for attempt in range(1 + max_retries):
        if not os.path.exists(project_file):
            if attempt < max_retries:
                time.sleep(0.5)
                continue
            raise WorkspaceClaimError(f"Project file does not exist: {project_file}")

        try:
            with changespec_lock(project_file):
                with open(project_file, encoding="utf-8") as f:
                    content = f.read()

                lifecycle_error = _new_work_lifecycle_error(project_file, content)
                if lifecycle_error is not None:
                    raise WorkspaceClaimError(lifecycle_error)

                plan = allocate_and_claim_workspace_from_content(
                    content,
                    min_workspace,
                    max_workspace,
                    WorkspaceClaimRequestWire(
                        project_file=project_file,
                        workspace_num=0,
                        workflow_name=workflow,
                        pid=pid,
                        cl_name=cl_name or "",
                        artifacts_timestamp=artifacts_timestamp or "",
                        pinned=pinned,
                    ),
                )
                outcome = dict(plan["outcome"])
                if not bool(outcome["success"]):
                    error = outcome.get("error")
                    if error:
                        raise WorkspaceClaimError(f"{error} in {project_file}")
                    raise WorkspaceClaimError(
                        f"All axe workspaces ({min_workspace}-{max_workspace}) "
                        f"are claimed in {project_file}"
                    )
                workspace_num = int(outcome["workspace_num"])

                cl_part = f" for {cl_name}" if cl_name else ""
                write_changespec_atomic(
                    project_file,
                    str(plan["content"]),
                    f"Claim workspace #{workspace_num} ({workflow}){cl_part}",
                )
                project = os.path.splitext(os.path.basename(project_file))[0]
                WORKSPACE_ACTIVE.labels(project=project).inc()
                return workspace_num
        except WorkspaceClaimError:
            raise
        except (OSError, BlockingIOError) as exc:
            if attempt < max_retries:
                time.sleep(0.5)
                continue
            raise WorkspaceClaimError(
                f"Failed to claim axe workspace in {project_file} "
                f"after {1 + max_retries} attempts: {exc!r}"
            ) from exc

    raise WorkspaceClaimError(
        f"Failed to claim axe workspace in {project_file} "
        f"after {1 + max_retries} attempts"
    )

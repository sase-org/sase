"""Claiming workspaces in the RUNNING field."""

import os
import time
from pathlib import Path

from sase.ace.patch import patch_lock, write_patch_atomic
from sase.core.agent_launch_claims import (
    allocate_and_claim_workspace_from_content,
    plan_claim_workspace_from_content,
)
from sase.core.agent_launch_wire import WorkspaceClaimRequestWire
from sase.core.project_lifecycle_facade import read_project_lifecycle_from_content
from sase.core.project_lifecycle_wire import is_disabled_project_lifecycle_state
from sase.logs.workspace_claim_ledger import record_running_field_mutation
from sase.running_field._model import (
    ClaimResult,
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


def claim_workspace(
    project_file: str,
    workspace_num: int,
    workflow: str,
    pid: int,
    cl_name: str | None = None,
    artifacts_timestamp: str | None = None,
    pinned: bool = False,
    caller_tag: str | None = None,
) -> ClaimResult:
    """Claim a workspace by adding it to the RUNNING field.

    Acquires a lock for the entire read-modify-write cycle.

    Args:
        project_file: Path to the ProjectSpec file
        workspace_num: Workspace number to claim (1 = main, 2+ = shares)
        workflow: Name of the workflow claiming the workspace
        pid: Process ID of the claiming process (required)
        cl_name: Optional Patch name being worked on
        artifacts_timestamp: Optional timestamp of the artifacts directory (YYYYmmddHHMMSS)
        pinned: If True, the claim is pinned and won't be cleaned up as stale
        caller_tag: Optional short tag naming the calling code path, recorded
            in the workspace-claim mutation ledger.

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
            with patch_lock(project_file):
                with open(project_file, encoding="utf-8") as f:
                    content = f.read()

                lifecycle_error = _new_work_lifecycle_error(project_file, content)
                if lifecycle_error is not None:
                    record_running_field_mutation(
                        operation="claim",
                        project_file=project_file,
                        workspace_num=workspace_num,
                        success=False,
                        before_content=content,
                        workflow=workflow,
                        cl_name=cl_name,
                        artifacts_timestamp=artifacts_timestamp,
                        claim_pid=pid,
                        error=lifecycle_error,
                        caller_tag=caller_tag,
                    )
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
                    record_running_field_mutation(
                        operation="claim",
                        project_file=project_file,
                        workspace_num=workspace_num,
                        success=False,
                        before_content=content,
                        workflow=workflow,
                        cl_name=cl_name,
                        artifacts_timestamp=artifacts_timestamp,
                        claim_pid=pid,
                        error=str(reason),
                        caller_tag=caller_tag,
                    )
                    return ClaimResult(success=False, error=str(reason))

                cl_part = f" for {cl_name}" if cl_name else ""
                new_content = str(plan["content"])
                write_patch_atomic(
                    project_file,
                    new_content,
                    f"Claim workspace #{workspace_num} ({workflow}){cl_part}",
                )
                record_running_field_mutation(
                    operation="claim",
                    project_file=project_file,
                    workspace_num=workspace_num,
                    success=True,
                    before_content=content,
                    after_content=new_content,
                    workflow=workflow,
                    cl_name=cl_name,
                    artifacts_timestamp=artifacts_timestamp,
                    claim_pid=pid,
                    caller_tag=caller_tag,
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


def claim_next_axe_workspace(
    project_file: str,
    workflow: str,
    pid: int,
    cl_name: str | None = None,
    artifacts_timestamp: str | None = None,
    pinned: bool = False,
    min_workspace: int | None = None,
    max_workspace: int | None = None,
    caller_tag: str | None = None,
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
        cl_name: Optional Patch name being worked on.
        artifacts_timestamp: Optional timestamp of the artifacts directory.
        pinned: If True, the claim is pinned and won't be cleaned up as stale.
        min_workspace: Minimum workspace number to consider (default: 10).
        max_workspace: Maximum workspace number to consider (default: 999).
        caller_tag: Optional short tag naming the calling code path, recorded
            in the workspace-claim mutation ledger.

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
            with patch_lock(project_file):
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
                    message = error or (
                        f"All axe workspaces ({min_workspace}-{max_workspace}) "
                        f"are claimed in {project_file}"
                    )
                    record_running_field_mutation(
                        operation="claim_next_axe",
                        project_file=project_file,
                        workspace_num=None,
                        success=False,
                        before_content=content,
                        workflow=workflow,
                        cl_name=cl_name,
                        artifacts_timestamp=artifacts_timestamp,
                        claim_pid=pid,
                        error=str(message),
                        caller_tag=caller_tag,
                    )
                    if error:
                        raise WorkspaceClaimError(f"{error} in {project_file}")
                    raise WorkspaceClaimError(message)
                workspace_num = int(outcome["workspace_num"])

                cl_part = f" for {cl_name}" if cl_name else ""
                new_content = str(plan["content"])
                write_patch_atomic(
                    project_file,
                    new_content,
                    f"Claim workspace #{workspace_num} ({workflow}){cl_part}",
                )
                record_running_field_mutation(
                    operation="claim_next_axe",
                    project_file=project_file,
                    workspace_num=workspace_num,
                    success=True,
                    before_content=content,
                    after_content=new_content,
                    workflow=workflow,
                    cl_name=cl_name,
                    artifacts_timestamp=artifacts_timestamp,
                    claim_pid=pid,
                    caller_tag=caller_tag,
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

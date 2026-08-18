"""Pinning an existing workspace claim so a failed run keeps its workspace."""

import os

from sase.ace.patch import patch_lock, write_patch_atomic
from sase.core.agent_launch_claims import (
    list_workspace_claims_from_content,
    plan_claim_workspace_from_content,
)
from sase.core.agent_launch_wire import WorkspaceClaimRequestWire
from sase.logs.workspace_claim_ledger import record_running_field_mutation
from sase.running_field._model import ClaimResult


def hold_workspace_claim(
    project_file: str,
    workspace_num: int,
    workflow: str,
    cl_name: str,
    artifacts_timestamp: str,
    caller_tag: str | None = None,
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
        with patch_lock(project_file):
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
                error = (
                    f"workspace #{workspace_num} claim for {workflow}/{cl_name} "
                    f"at {artifacts_timestamp} was not found"
                )
                record_running_field_mutation(
                    operation="hold",
                    project_file=project_file,
                    workspace_num=workspace_num,
                    success=False,
                    before_content=content,
                    workflow=workflow,
                    cl_name=cl_name,
                    artifacts_timestamp=artifacts_timestamp,
                    error=error,
                    caller_tag=caller_tag,
                )
                return ClaimResult(success=False, error=error)
            if claim.pinned:
                record_running_field_mutation(
                    operation="hold",
                    project_file=project_file,
                    workspace_num=workspace_num,
                    success=True,
                    before_content=content,
                    workflow=workflow,
                    cl_name=cl_name,
                    artifacts_timestamp=artifacts_timestamp,
                    claim_pid=claim.pid,
                    error="already pinned (no-op)",
                    caller_tag=caller_tag,
                )
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
                error = f"workspace #{workspace_num} claim could not be held"
                record_running_field_mutation(
                    operation="hold",
                    project_file=project_file,
                    workspace_num=workspace_num,
                    success=False,
                    before_content=content,
                    workflow=workflow,
                    cl_name=cl_name,
                    artifacts_timestamp=artifacts_timestamp,
                    claim_pid=claim.pid,
                    error=error,
                    caller_tag=caller_tag,
                )
                return ClaimResult(success=False, error=error)

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
                record_running_field_mutation(
                    operation="hold",
                    project_file=project_file,
                    workspace_num=workspace_num,
                    success=False,
                    before_content=content,
                    workflow=workflow,
                    cl_name=cl_name,
                    artifacts_timestamp=artifacts_timestamp,
                    claim_pid=claim.pid,
                    error=str(reason),
                    caller_tag=caller_tag,
                )
                return ClaimResult(success=False, error=str(reason))

            new_content = str(plan["content"])
            write_patch_atomic(
                project_file,
                new_content,
                f"Hold workspace #{workspace_num} for failed agent run",
            )
            record_running_field_mutation(
                operation="hold",
                project_file=project_file,
                workspace_num=workspace_num,
                success=True,
                before_content=content,
                after_content=new_content,
                workflow=workflow,
                cl_name=cl_name,
                artifacts_timestamp=artifacts_timestamp,
                claim_pid=claim.pid,
                caller_tag=caller_tag,
            )
            return ClaimResult(success=True)
    except (OSError, BlockingIOError) as exc:
        return ClaimResult(success=False, error=repr(exc))

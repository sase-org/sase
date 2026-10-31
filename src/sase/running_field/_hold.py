"""Pinning an existing workspace claim so a failed run keeps its workspace."""

import os

from sase.ace.patch import patch_lock, write_patch_atomic
from sase.core.agent_launch_claims import plan_pin_workspace_claim_from_content
from sase.logs.workspace_claim_ledger import record_running_field_mutation
from sase.running_field._model import ClaimResult


def hold_workspace_claim(
    project_file: str,
    workspace_num: int,
    workflow: str,
    cl_name: str,
    artifacts_timestamp: str,
    caller_tag: str | None = None,
    *,
    expected_pid: int | None = None,
) -> ClaimResult:
    """Atomically pin the existing workspace claim for a failed agent run.

    The matching RUNNING row is rewritten in place under one ProjectSpec lock
    so readers can never observe the workspace as available. Existing claim
    ownership metadata, including the PID, is preserved. When ``expected_pid``
    is set, a mismatched or replaced claim is a no-op.
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

            owner: dict[str, object] = {
                "workspace_num": workspace_num,
                "workflow": workflow,
                "cl_name": cl_name or "",
                "artifacts_timestamp": artifacts_timestamp or "",
            }
            if expected_pid is not None:
                owner["pid"] = expected_pid
            plan = plan_pin_workspace_claim_from_content(content, owner)
            outcome = dict(plan["outcome"])
            claim_pid = outcome.get("pid")
            claim_pid_int = int(claim_pid) if isinstance(claim_pid, int) else None
            if not bool(outcome["success"]):
                reason = outcome.get("error") or (
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
                    claim_pid=claim_pid_int,
                    error=str(reason),
                    caller_tag=caller_tag,
                )
                return ClaimResult(success=False, error=str(reason))
            if not bool(plan.get("changed")):
                record_running_field_mutation(
                    operation="hold",
                    project_file=project_file,
                    workspace_num=workspace_num,
                    success=True,
                    before_content=content,
                    workflow=workflow,
                    cl_name=cl_name,
                    artifacts_timestamp=artifacts_timestamp,
                    claim_pid=claim_pid_int,
                    error="already pinned (no-op)",
                    caller_tag=caller_tag,
                )
                return ClaimResult(success=True)

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
                claim_pid=claim_pid_int,
                caller_tag=caller_tag,
            )
            return ClaimResult(success=True)
    except (OSError, BlockingIOError) as exc:
        return ClaimResult(success=False, error=repr(exc))

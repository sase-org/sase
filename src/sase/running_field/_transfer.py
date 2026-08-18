"""Transferring ownership of an existing workspace claim to a new PID."""

import os

from sase.ace.patch import patch_lock, write_patch_atomic
from sase.core.agent_launch_claims import plan_transfer_workspace_claim_from_content
from sase.core.agent_launch_wire import WorkspaceClaimRequestWire
from sase.logs.workspace_claim_ledger import record_running_field_mutation
from sase.running_field._model import ClaimResult


def transfer_workspace_claim(
    project_file: str,
    workspace_num: int,
    *,
    from_pid: int,
    to_pid: int,
    new_workflow: str,
    new_artifacts_timestamp: str | None,
    cl_name: str | None = None,
    caller_tag: str | None = None,
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
        with patch_lock(project_file):
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
                record_running_field_mutation(
                    operation="transfer",
                    project_file=project_file,
                    workspace_num=workspace_num,
                    success=False,
                    before_content=content,
                    workflow=new_workflow,
                    cl_name=cl_name,
                    artifacts_timestamp=new_artifacts_timestamp,
                    claim_pid=to_pid,
                    error=str(reason),
                    caller_tag=caller_tag,
                )
                return ClaimResult(success=False, error=str(reason))

            new_content = str(plan["content"])
            write_patch_atomic(
                project_file,
                new_content,
                f"Transfer workspace #{workspace_num} from pid {from_pid} to {to_pid}",
            )
            record_running_field_mutation(
                operation="transfer",
                project_file=project_file,
                workspace_num=workspace_num,
                success=True,
                before_content=content,
                after_content=new_content,
                workflow=new_workflow,
                cl_name=cl_name,
                artifacts_timestamp=new_artifacts_timestamp,
                claim_pid=to_pid,
                caller_tag=caller_tag,
            )
            return ClaimResult(success=True)
    except (OSError, BlockingIOError) as exc:
        return ClaimResult(success=False, error=repr(exc))

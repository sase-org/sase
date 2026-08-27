"""RUNNING-field claim moves made for a pending gate shell."""

from __future__ import annotations

from dataclasses import dataclass

from sase.gate_shell.claims import GATE_WORKSPACE_CLAIM_WORKFLOW
from sase.running_field import (
    ClaimResult,
    WorkspaceClaim,
    claim_workspace,
    get_claimed_workspaces,
    release_workspace,
    transfer_workspace_claim,
)


@dataclass(frozen=True)
class GateClaimMove:
    """Outcome of moving or releasing the creator's workspace claim."""

    result: ClaimResult
    creator_claim: WorkspaceClaim | None
    gate_pid: int | None
    workspace_policy: str


def move_gate_shell_claim(
    project_file: str,
    workspace_num: int | None,
    *,
    creator_pid: int | None,
    artifacts_timestamp: str,
    cl_name: str | None,
    workspace_policy: str,
) -> GateClaimMove:
    """Move or release the creator claim for a pending gate shell."""
    if workspace_num in (None, 0) or creator_pid is None:
        return GateClaimMove(
            result=ClaimResult(True),
            creator_claim=None,
            gate_pid=None,
            workspace_policy=workspace_policy,
        )
    creator_claim = _find_claim(
        project_file,
        workspace_num=int(workspace_num),
        pid=creator_pid,
    )
    if creator_claim is None:
        return GateClaimMove(
            result=ClaimResult(True),
            creator_claim=None,
            gate_pid=None,
            workspace_policy=workspace_policy,
        )
    if workspace_policy == "release":
        result = release_workspace(
            project_file,
            int(workspace_num),
            creator_claim.workflow,
            creator_claim.cl_name,
            caller_tag="gate-shell-create",
        )
        return GateClaimMove(
            result=result,
            creator_claim=creator_claim,
            gate_pid=None,
            workspace_policy=workspace_policy,
        )

    result = transfer_workspace_claim(
        project_file,
        int(workspace_num),
        from_pid=creator_pid,
        to_pid=creator_pid,
        new_workflow=GATE_WORKSPACE_CLAIM_WORKFLOW,
        new_artifacts_timestamp=artifacts_timestamp,
        cl_name=cl_name,
        caller_tag="gate-shell-create",
    )
    return GateClaimMove(
        result=result,
        creator_claim=creator_claim,
        gate_pid=creator_pid,
        workspace_policy=workspace_policy,
    )


def restore_gate_shell_claim(
    project_file: str,
    *,
    move: GateClaimMove,
    cl_name: str | None,
) -> None:
    """Restore the creator's exact original claim after a failed handoff."""
    claim = move.creator_claim
    if claim is None:
        return
    if move.workspace_policy == "release":
        claim_workspace(
            project_file,
            claim.workspace_num,
            claim.workflow,
            claim.pid,
            claim.cl_name,
            artifacts_timestamp=claim.artifacts_timestamp,
            pinned=claim.pinned,
            caller_tag="gate-shell-restore",
        )
        return
    if move.gate_pid is None:
        return
    transfer_workspace_claim(
        project_file,
        claim.workspace_num,
        from_pid=move.gate_pid,
        to_pid=claim.pid,
        new_workflow=claim.workflow,
        new_artifacts_timestamp=claim.artifacts_timestamp,
        cl_name=cl_name,
        caller_tag="gate-shell-restore",
    )


def release_gate_shell_claim(
    meta: dict[str, object],
    project_name: str | None,
) -> str | None:
    """Release this gate shell's workspace claim, if it can be resolved.

    A ``workspace: "release"`` gate shell never held a claim -- it was
    released back to the free pool at creation time (``move_gate_shell_claim``)
    -- so releasing it again here would tear down whatever unrelated claim
    another agent has since taken on that workspace number.
    """
    if meta.get("gate_workspace_policy") == "release":
        return None
    workspace_num = meta.get("workspace_num")
    cl_name = meta.get("cl_name")
    if project_name:
        if isinstance(workspace_num, bool) or not isinstance(workspace_num, int | str):
            return None
        from sase.workflows.utils import get_project_file_path

        result = release_workspace(
            get_project_file_path(project_name),
            int(workspace_num),
            GATE_WORKSPACE_CLAIM_WORKFLOW,
            cl_name=str(cl_name) if isinstance(cl_name, str) else None,
            caller_tag="gate-shell-settle",
        )
        if not result.success:
            return result.error or "workspace release failed"
    return None


def _find_claim(
    project_file: str,
    *,
    workspace_num: int,
    pid: int,
) -> WorkspaceClaim | None:
    return next(
        (
            claim
            for claim in get_claimed_workspaces(project_file)
            if claim.workspace_num == workspace_num and claim.pid == pid
        ),
        None,
    )


__all__ = [
    "GateClaimMove",
    "move_gate_shell_claim",
    "release_gate_shell_claim",
    "restore_gate_shell_claim",
]

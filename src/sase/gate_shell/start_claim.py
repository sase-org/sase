"""RUNNING-field claim moves made for a pending gate shell."""

from __future__ import annotations

from dataclasses import dataclass

from sase.ace.hooks.processes import is_process_running
from sase.gate_shell.claims import GATE_WORKSPACE_CLAIM_WORKFLOW
from sase.gate_shell.log import append_gate_shell_log_text
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
    if workspace_num is None or workspace_num == 0 or creator_pid is None:
        return GateClaimMove(
            result=ClaimResult(True),
            creator_claim=None,
            gate_pid=None,
            workspace_policy=workspace_policy,
        )
    workspace_id = workspace_num
    creator_claim = _find_claim(
        project_file,
        workspace_num=workspace_id,
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
            workspace_id,
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
        workspace_id,
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
    caller_tag: str = "gate-shell-restore",
) -> ClaimResult | None:
    """Restore the creator's exact original claim after a failed handoff."""
    claim = move.creator_claim
    if claim is None:
        return None
    if move.workspace_policy == "release":
        return claim_workspace(
            project_file,
            claim.workspace_num,
            claim.workflow,
            claim.pid,
            claim.cl_name,
            artifacts_timestamp=claim.artifacts_timestamp,
            pinned=claim.pinned,
            caller_tag=caller_tag,
        )
    if move.gate_pid is None:
        return None
    return transfer_workspace_claim(
        project_file,
        claim.workspace_num,
        from_pid=move.gate_pid,
        to_pid=claim.pid,
        new_workflow=claim.workflow,
        new_artifacts_timestamp=claim.artifacts_timestamp,
        cl_name=cl_name,
        caller_tag=caller_tag,
    )


def release_gate_shell_claim(
    meta: dict[str, object],
    project_name: str | None,
    *,
    artifacts_dir: str | None = None,
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

        workspace_id = int(workspace_num)
        project_file = get_project_file_path(project_name)
        restored, restore_error = _restore_live_creator_claim(
            project_file,
            meta,
            workspace_num=workspace_id,
            artifacts_dir=artifacts_dir,
        )
        if restored:
            return restore_error
        result = release_workspace(
            project_file,
            workspace_id,
            GATE_WORKSPACE_CLAIM_WORKFLOW,
            cl_name=str(cl_name) if isinstance(cl_name, str) else None,
            caller_tag="gate-shell-settle",
        )
        if not result.success:
            return result.error or "workspace release failed"
    return None


def _restore_live_creator_claim(
    project_file: str,
    meta: dict[str, object],
    *,
    workspace_num: int,
    artifacts_dir: str | None,
) -> tuple[bool, str | None]:
    creator_claim = _recorded_creator_claim(meta, workspace_num)
    if creator_claim is None or not _creator_pid_is_live(creator_claim.pid):
        return False, None

    move = GateClaimMove(
        result=ClaimResult(True),
        creator_claim=creator_claim,
        gate_pid=creator_claim.pid,
        workspace_policy="inherit",
    )
    result = restore_gate_shell_claim(
        project_file,
        move=move,
        cl_name=creator_claim.cl_name,
        caller_tag="gate-shell-settle-restore",
    )
    _append_live_creator_restore_log(artifacts_dir, creator_claim, result)
    if result is not None and not result.success:
        return True, result.error or "workspace claim restore failed"
    return True, None


def _recorded_creator_claim(
    meta: dict[str, object],
    workspace_num: int,
) -> WorkspaceClaim | None:
    pid = _optional_int(meta.get("gate_creator_claim_pid"))
    workflow = _optional_str(meta.get("gate_creator_claim_workflow"))
    if pid is None or workflow is None:
        return None
    return WorkspaceClaim(
        workspace_num=workspace_num,
        workflow=workflow,
        cl_name=_creator_claim_cl_name(meta),
        pid=pid,
        artifacts_timestamp=_optional_str(
            meta.get("gate_creator_claim_artifacts_timestamp")
        ),
        pinned=meta.get("gate_creator_claim_pinned") is True,
    )


def _creator_claim_cl_name(meta: dict[str, object]) -> str | None:
    if "gate_creator_claim_cl_name" in meta:
        return _optional_str(meta.get("gate_creator_claim_cl_name"))
    return _optional_str(meta.get("cl_name"))


def _creator_pid_is_live(pid: int) -> bool:
    try:
        return is_process_running(pid)
    except (OSError, RuntimeError, ValueError):
        return False


def _append_live_creator_restore_log(
    artifacts_dir: str | None,
    claim: WorkspaceClaim,
    result: ClaimResult | None,
) -> None:
    if artifacts_dir is None:
        return
    outcome = "restored" if result is None or result.success else "restore failed"
    append_gate_shell_log_text(
        artifacts_dir,
        (
            f"! gate-shell-settle-restore: creator pid {claim.pid} is still "
            f"alive; {outcome} workspace #{claim.workspace_num} claim to "
            f"{claim.workflow}\n"
        ),
    )


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


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | str):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


__all__ = [
    "GateClaimMove",
    "move_gate_shell_claim",
    "release_gate_shell_claim",
    "restore_gate_shell_claim",
]

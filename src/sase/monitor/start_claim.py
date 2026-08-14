"""RUNNING-field claim moves a monitor start makes on behalf of a supervisor.

Split out of :mod:`sase.monitor.start`: taking the starter's workspace claim
(or a fresh one), and giving it back untouched when the start fails, is a
self-contained transaction over the RUNNING field. The claim *label* itself
lives in the dependency-free :mod:`sase.monitor.claims` leaf.
"""

from __future__ import annotations

from dataclasses import dataclass

from sase.running_field import (
    ClaimResult,
    WorkspaceClaim,
    claim_workspace,
    get_claimed_workspaces,
    release_workspace,
    transfer_workspace_claim,
)

from .claims import MONITOR_WORKSPACE_CLAIM_WORKFLOW


@dataclass(frozen=True)
class _MonitorClaimAttempt:
    """Outcome of the forward claim move, plus what it has to be undone to.

    ``starter_claim`` is captured *before* a transfer so a later reversal (a
    missing startup acknowledgement) can hand the exact same workflow and
    artifacts timestamp back to the starter instead of guessing at them.
    """

    result: ClaimResult
    starter_claim: WorkspaceClaim | None


def claim_monitor_workspace(
    project_file: str,
    workspace_num: int,
    *,
    supervisor_pid: int,
    transfer_from_pid: int | None,
    artifacts_timestamp: str,
    cl_name: str | None,
) -> _MonitorClaimAttempt:
    """Claim *workspace_num* for the supervisor.

    With *transfer_from_pid* the starter's own live claim moves to the
    supervisor; without one the monitor takes a fresh claim on the
    (workspace-less) member instead.
    """
    if transfer_from_pid is None:
        return _MonitorClaimAttempt(
            result=claim_workspace(
                project_file,
                workspace_num,
                MONITOR_WORKSPACE_CLAIM_WORKFLOW,
                supervisor_pid,
                cl_name,
                artifacts_timestamp=artifacts_timestamp,
            ),
            starter_claim=None,
        )

    starter_claim = _find_claim(
        project_file,
        workspace_num=workspace_num,
        pid=transfer_from_pid,
    )
    return _MonitorClaimAttempt(
        result=transfer_workspace_claim(
            project_file,
            workspace_num,
            from_pid=transfer_from_pid,
            to_pid=supervisor_pid,
            new_workflow=MONITOR_WORKSPACE_CLAIM_WORKFLOW,
            new_artifacts_timestamp=artifacts_timestamp,
            cl_name=cl_name,
        ),
        starter_claim=starter_claim,
    )


def undo_monitor_claim(
    project_file: str,
    workspace_num: int,
    *,
    supervisor_pid: int,
    starter_claim: WorkspaceClaim | None,
    cl_name: str | None,
) -> None:
    """Give a dead-on-arrival supervisor's claim back to the still-live starter.

    A missing acknowledgement means the starter agent -- not the supervisor
    -- is the process that is actually still alive, and it must get its
    workspace back exactly as it held it, never released into the free pool
    where another agent could claim it out from under the starter.
    """
    if starter_claim is not None:
        result = transfer_workspace_claim(
            project_file,
            workspace_num,
            from_pid=supervisor_pid,
            to_pid=starter_claim.pid,
            new_workflow=starter_claim.workflow,
            new_artifacts_timestamp=starter_claim.artifacts_timestamp,
            cl_name=cl_name,
        )
        if result.success:
            return
    release_monitor_claim(project_file, workspace_num, cl_name=cl_name)


def release_monitor_claim(
    project_file: str,
    workspace_num: int,
    *,
    cl_name: str | None,
) -> None:
    """Release the monitor's claim on *workspace_num* back into the free pool."""
    release_workspace(
        project_file,
        workspace_num,
        MONITOR_WORKSPACE_CLAIM_WORKFLOW,
        cl_name=cl_name,
    )


def _find_claim(
    project_file: str,
    *,
    workspace_num: int,
    pid: int,
) -> WorkspaceClaim | None:
    """Return the live claim for *workspace_num*/*pid*, if any."""
    return next(
        (
            claim
            for claim in get_claimed_workspaces(project_file)
            if claim.workspace_num == workspace_num and claim.pid == pid
        ),
        None,
    )


__all__ = [
    "claim_monitor_workspace",
    "release_monitor_claim",
    "undo_monitor_claim",
]

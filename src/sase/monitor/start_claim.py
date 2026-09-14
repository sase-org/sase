"""RUNNING-field claim moves a monitor start makes on behalf of a supervisor.

Split out of :mod:`sase.monitor.start`: taking the starter's workspace claim
(or a fresh one), and giving it back untouched when the start fails, is a
self-contained transaction over the RUNNING field. The claim *label* itself
lives in the dependency-free :mod:`sase.monitor.claims` leaf.
"""

from __future__ import annotations

from dataclasses import dataclass

from sase.ace.hooks.processes import is_process_running
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


@dataclass(frozen=True)
class _MonitorClaimPreflight:
    """Claim feasibility for a monitor start before it creates artifacts."""

    transfer_from_pid: int | None
    error: str | None = None


def preflight_monitor_workspace_claim(
    project_file: str,
    workspace_num: int,
    *,
    transfer_from_pid: int | None,
    cl_name: str | None,
) -> _MonitorClaimPreflight:
    """Return the safe transfer pid for a monitor workspace claim.

    A monitor start may inherit a lane member's stale metadata pid. When the
    current RUNNING row for the lane belongs to a dead pid, the monitor can
    adopt that orphan by transferring from the row's pid. A live holder is a
    conflict and must be surfaced before a doomed monitor member is minted.
    """
    return _preflight_monitor_workspace_claim(
        project_file,
        workspace_num,
        transfer_from_pid=transfer_from_pid,
        cl_name=cl_name,
    )


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
    preflight = _preflight_monitor_workspace_claim(
        project_file,
        workspace_num,
        transfer_from_pid=transfer_from_pid,
        cl_name=cl_name,
    )
    if preflight.error is not None:
        return _MonitorClaimAttempt(
            result=ClaimResult(False, preflight.error),
            starter_claim=None,
        )
    transfer_from_pid = preflight.transfer_from_pid
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
    _release_monitor_claim(
        project_file,
        workspace_num,
        supervisor_pid=supervisor_pid,
        cl_name=cl_name,
    )


def _release_monitor_claim(
    project_file: str,
    workspace_num: int,
    *,
    supervisor_pid: int,
    cl_name: str | None,
) -> None:
    """Release the monitor's claim on *workspace_num* back into the free pool."""
    release_workspace(
        project_file,
        workspace_num,
        MONITOR_WORKSPACE_CLAIM_WORKFLOW,
        cl_name=cl_name,
        expected_pid=supervisor_pid,
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


def _preflight_monitor_workspace_claim(
    project_file: str,
    workspace_num: int,
    *,
    transfer_from_pid: int | None,
    cl_name: str | None,
) -> _MonitorClaimPreflight:
    if workspace_num == 0:
        return _MonitorClaimPreflight(transfer_from_pid)

    claims = [
        claim
        for claim in get_claimed_workspaces(project_file)
        if claim.workspace_num == workspace_num
    ]
    if not claims:
        return _MonitorClaimPreflight(transfer_from_pid)

    live_conflict = next(
        (
            claim
            for claim in claims
            if claim.pid != transfer_from_pid and is_process_running(claim.pid)
        ),
        None,
    )
    if live_conflict is not None:
        return _MonitorClaimPreflight(
            transfer_from_pid,
            _claim_conflict_error(workspace_num, transfer_from_pid),
        )

    if transfer_from_pid is None or any(
        claim.pid == transfer_from_pid for claim in claims
    ):
        return _MonitorClaimPreflight(transfer_from_pid)

    lane_claim = _matching_lane_claim(claims, cl_name=cl_name)
    if lane_claim is not None and not is_process_running(lane_claim.pid):
        return _MonitorClaimPreflight(lane_claim.pid)

    return _MonitorClaimPreflight(transfer_from_pid)


def _matching_lane_claim(
    claims: list[WorkspaceClaim],
    *,
    cl_name: str | None,
) -> WorkspaceClaim | None:
    return next((claim for claim in claims if claim.cl_name == cl_name), None)


def _claim_conflict_error(
    workspace_num: int,
    transfer_from_pid: int | None,
) -> str:
    if transfer_from_pid is None:
        return f"workspace #{workspace_num} is already claimed"
    return f"workspace #{workspace_num} with pid {transfer_from_pid} was not found"


__all__ = [
    "claim_monitor_workspace",
    "preflight_monitor_workspace_claim",
    "undo_monitor_claim",
]

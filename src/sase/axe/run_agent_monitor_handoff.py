"""Workspace-claim checks for monitor handoff shutdown paths."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from typing import Protocol


class _WorkspaceClaimLike(Protocol):
    workspace_num: int
    workflow: str
    cl_name: str | None
    pid: int


def monitor_handoff_claim_transferred(
    project_file: str,
    workspace_num: int,
    *,
    cl_name: str | None = None,
    runner_pid: int | None = None,
    get_claimed_workspaces: Callable[[str], Iterable[_WorkspaceClaimLike]]
    | None = None,
    process_running: Callable[[int], bool] | None = None,
) -> bool:
    """Return whether a live monitor supervisor owns this runner's claim."""
    if runner_pid is None:
        runner_pid = os.getpid()

    try:
        claims_loader: Callable[[str], Iterable[_WorkspaceClaimLike]]
        if get_claimed_workspaces is None:
            from sase.running_field import (
                get_claimed_workspaces as default_get_claimed_workspaces,
            )

            claims_loader = default_get_claimed_workspaces
        else:
            claims_loader = get_claimed_workspaces

        process_probe: Callable[[int], bool]
        if process_running is None:
            from sase.ace.hooks.processes import (
                is_process_running as default_process_running,
            )

            process_probe = default_process_running
        else:
            process_probe = process_running

        from sase.monitor.claims import MONITOR_WORKSPACE_CLAIM_WORKFLOW

        claims = tuple(claims_loader(project_file))
    except Exception:
        return False

    for claim in claims:
        if claim.workspace_num != workspace_num:
            continue
        if claim.workflow != MONITOR_WORKSPACE_CLAIM_WORKFLOW:
            continue
        if cl_name is not None and claim.cl_name != cl_name:
            continue
        if claim.pid == runner_pid:
            continue
        try:
            if process_probe(claim.pid):
                return True
        except Exception:
            continue
    return False


__all__ = ["monitor_handoff_claim_transferred"]

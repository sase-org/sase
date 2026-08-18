"""Checkout occupancy guard for destructive workspace preparation.

Part of the ``guard`` phase of the workspace-exclusivity epic (sase-q0):
refuse to clean, hard-reset, or check out a checkout that another live
agent already occupies, instead of silently destroying its work. The
conflict decision itself lives in ``sase_core`` (see
``decide_workspace_occupant_conflict``); this module supplies the two
Python-only inputs the decision needs — process liveness and the checkout
paths — and raises on conflict so callers can let the exception propagate
into the runner's normal failure path.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from sase.running_field._model import WorkspaceClaim
from sase.running_field._query import get_claimed_workspaces

# Must come after the running_field imports above: sase.core.agent_launch_claims
# and sase.running_field import each other, and running_field's own __init__
# is what resolves that cycle safely. Importing agent_launch_claims first (as
# this module's very first sase import) reliably crashes with a circular
# ImportError instead.
from sase.core.agent_launch_claims import decide_workspace_occupant_conflict
from sase.workspace_provider.occupant import read_occupant_record


class WorkspaceOccupiedError(RuntimeError):
    """Raised when a destructive workspace prep would clobber another agent."""


@dataclass(frozen=True)
class OccupancyCaller:
    """Identity of the process asking whether it may prepare a checkout."""

    pid: int
    workspace_num: int
    project: str
    workflow: str
    artifacts_timestamp: str | None = None

    def to_wire_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "workspace_num": self.workspace_num,
            "project": self.project,
            "workflow": self.workflow,
            "artifacts_timestamp": self.artifacts_timestamp,
        }


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _running_claim_row(project_file: str, workspace_num: int) -> WorkspaceClaim | None:
    return next(
        (
            claim
            for claim in get_claimed_workspaces(project_file)
            if claim.workspace_num == workspace_num
        ),
        None,
    )


def _claim_wire_dict(claim: WorkspaceClaim) -> dict[str, Any]:
    return {
        "workspace_num": claim.workspace_num,
        "workflow": claim.workflow,
        "cl_name": claim.cl_name,
        "pid": claim.pid,
        "artifacts_timestamp": claim.artifacts_timestamp,
        "pinned": claim.pinned,
    }


def ensure_workspace_not_occupied(
    checkout_dir: str,
    *,
    project_file: str,
    caller: OccupancyCaller,
) -> None:
    """Raise :class:`WorkspaceOccupiedError` if another live agent holds
    *checkout_dir*.

    Cross-checks the checkout-local occupant marker against the RUNNING
    field's claim row for ``caller.workspace_num`` as two independent
    sources of truth: a live occupant that is not the caller, or a
    disagreement between the two sources, both refuse the run rather than
    risk destroying another agent's work. A missing occupant marker is
    always treated as unoccupied, so checkouts created before this guard
    existed are never bricked.
    """
    occupant = read_occupant_record(checkout_dir)
    running_claim = _running_claim_row(project_file, caller.workspace_num)

    occupant_pid_alive = occupant is not None and _pid_is_alive(occupant.pid)
    running_claim_pid_alive = running_claim is not None and _pid_is_alive(
        running_claim.pid
    )

    decision = decide_workspace_occupant_conflict(
        occupant.to_wire_dict() if occupant is not None else None,
        caller.to_wire_dict(),
        occupant_pid_alive,
        _claim_wire_dict(running_claim) if running_claim is not None else None,
        running_claim_pid_alive,
    )
    if not bool(decision["may_proceed"]):
        raise WorkspaceOccupiedError(str(decision["reason"]))


__all__ = [
    "OccupancyCaller",
    "WorkspaceOccupiedError",
    "ensure_workspace_not_occupied",
]

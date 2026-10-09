"""Human-readable workspace occupant descriptions."""

from __future__ import annotations

import os

from sase.running_field._model import WorkspaceClaim


def describe_workspace_occupant(
    project_file: str,
    workspace_num: int,
    *,
    checkout_dir: str | None = None,
) -> str | None:
    """Describe who holds *workspace_num* in *project_file*.

    Returns a ``"; "``-joined occupant summary in the historical
    ``name (pid N, live/dead, workflow W[, artifacts T])`` format, or
    ``None`` when nothing is claimed. When *checkout_dir* names a checkout
    whose occupant record matches a claimed pid and carries an agent name,
    that agent name leads the description.
    """
    from sase.running_field._query import get_claimed_workspaces

    occupants = [
        claim
        for claim in get_claimed_workspaces(project_file)
        if claim.workspace_num == workspace_num
    ]
    if not occupants:
        return None
    if checkout_dir:
        try:
            from sase.workspace_provider.occupant import read_occupant_record

            record = read_occupant_record(checkout_dir)
        except Exception:
            record = None
        if record is not None and record.agent_name:
            for claim in occupants:
                if claim.pid == record.pid:
                    lead = format_workspace_occupant(
                        claim, display_name=record.agent_name
                    )
                    rest = [
                        format_workspace_occupant(other)
                        for other in occupants
                        if other is not claim
                    ]
                    return "; ".join([lead, *rest])
    return "; ".join(format_workspace_occupant(claim) for claim in occupants)


def format_workspace_occupant(
    claim: WorkspaceClaim, *, display_name: str | None = None
) -> str:
    """Format one workspace claim as a human-readable occupant summary."""
    name = display_name or claim.cl_name or claim.workflow
    liveness = "live" if pid_is_alive(claim.pid) else "dead"
    detail = f"{name} (pid {claim.pid}, {liveness}, workflow {claim.workflow}"
    if claim.artifacts_timestamp:
        detail += f", artifacts {claim.artifacts_timestamp}"
    return detail + ")"


def pid_is_alive(pid: int) -> bool:
    """Return whether *pid* currently exists."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


__all__ = [
    "describe_workspace_occupant",
    "format_workspace_occupant",
    "pid_is_alive",
]

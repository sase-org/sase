"""Workspace-claim checks for gate handoff shutdown paths."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Protocol


class _WorkspaceClaimLike(Protocol):
    workspace_num: int
    workflow: str
    cl_name: str | None


def gate_handoff_claim_moved(
    project_file: str,
    workspace_num: int,
    *,
    cl_name: str | None = None,
    get_claimed_workspaces: Callable[[str], Iterable[_WorkspaceClaimLike]]
    | None = None,
) -> bool:
    """Return whether a pending gate shell owns this runner's claim."""
    try:
        claims_loader: Callable[[str], Iterable[_WorkspaceClaimLike]]
        if get_claimed_workspaces is None:
            from sase.running_field import (
                get_claimed_workspaces as default_get_claimed_workspaces,
            )

            claims_loader = default_get_claimed_workspaces
        else:
            claims_loader = get_claimed_workspaces

        from sase.gate_shell.claims import GATE_WORKSPACE_CLAIM_WORKFLOW

        claims = tuple(claims_loader(project_file))
    except Exception:
        return False

    for claim in claims:
        if claim.workspace_num != workspace_num:
            continue
        if claim.workflow != GATE_WORKSPACE_CLAIM_WORKFLOW:
            continue
        if cl_name is not None and claim.cl_name != cl_name:
            continue
        return True
    return False


__all__ = ["gate_handoff_claim_moved"]

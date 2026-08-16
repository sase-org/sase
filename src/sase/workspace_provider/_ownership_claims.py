"""Live RUNNING claim lookup for workspace ownership decisions.

Split out of :mod:`sase.workspace_provider.ownership`; ownership never
infers a lease from a ``_<num>`` path suffix, so every machine-owned
decision funnels through the claim probes here.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from sase.running_field import WorkspaceClaim, get_claimed_workspaces
from sase.workspace_provider._ownership_types import (
    ProcessRunningProbe,
    normalize_workspace_num,
)


def live_claim_for_workspace(
    workspace_num: int,
    *,
    project_file: Path | None,
    claims: Sequence[WorkspaceClaim] | None,
    process_running: ProcessRunningProbe | None,
) -> WorkspaceClaim | None:
    """Return the claim for *workspace_num* only when its owner is alive."""

    claim = claim_for_workspace(
        workspace_num,
        project_file=project_file,
        claims=claims,
    )
    if claim is None or not claim_is_alive(claim, process_running):
        return None
    return claim


def claim_for_workspace(
    workspace_num: int,
    *,
    project_file: Path | None,
    claims: Sequence[WorkspaceClaim] | None,
) -> WorkspaceClaim | None:
    """Find the recorded claim for *workspace_num*, alive or not."""

    if claims is None:
        if project_file is None or not project_file.is_file():
            return None
        claims = get_claimed_workspaces(str(project_file))
    for claim in claims:
        if normalize_workspace_num(claim.workspace_num) == workspace_num:
            return claim
    return None


def claim_is_alive(
    claim: WorkspaceClaim | None,
    process_running: ProcessRunningProbe | None,
) -> bool:
    """Return whether *claim*'s owning process is still running."""

    if claim is None:
        return False
    probe = process_running if process_running is not None else _pid_is_alive
    try:
        return bool(probe(claim.pid))
    except (OSError, RuntimeError, ValueError):
        return False


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


__all__ = [
    "claim_for_workspace",
    "claim_is_alive",
    "live_claim_for_workspace",
]

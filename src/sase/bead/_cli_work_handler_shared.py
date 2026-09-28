"""Shared epic-work result and selection helpers.

This private module owns the helpers needed by more than one
``cli_work_handler_*`` split module. Names are public so the split modules can
import them without a ``_``-prefixed cross-module import.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sase.bead.cli_work_handler_errors import EpicLaunchState


@dataclass(frozen=True)
class EpicWorkResult:
    """Outcome of one epic bead-work request."""

    epic_id: str
    launch_state: EpicLaunchState
    launched_agent_names: tuple[str, ...] = ()
    preserved_agent_names: tuple[str, ...] = ()
    workspace_num: int | None = None

    @property
    def launched(self) -> bool:
        return self.launch_state == "launched"

    def __bool__(self) -> bool:
        return self.launched


def epic_bead_assignees(proj: Any, plan: Any) -> dict[str, str]:
    """Map every epic/phase bead id in ``plan`` to its current assignee."""
    bead_ids = {plan.epic_id, *plan.phase_bead_ids}
    issues = {issue.id: issue for issue in proj.list_issues() if issue.id in bead_ids}
    return {
        bead_id: issue.assignee if (issue := issues.get(bead_id)) is not None else ""
        for bead_id in bead_ids
    }


def resume_command(epic_id: str, *, capacity: int | None) -> str:
    """Return the retry command recorded for launch failure diagnostics."""
    command = f"sase bead work {epic_id}"
    if capacity is not None:
        command += f" --capacity {capacity}"
    return command


def ordered_selected_names(plan: Any, launch_names: frozenset[str]) -> tuple[str, ...]:
    """Return ``launch_names`` in wave order with the land agent last."""
    ordered = [
        assignment.agent_name
        for wave in plan.waves
        for assignment in wave
        if assignment.agent_name in launch_names
    ]
    if plan.land_agent_name in launch_names:
        ordered.append(plan.land_agent_name)
    return tuple(ordered)


__all__ = [
    "EpicWorkResult",
    "epic_bead_assignees",
    "ordered_selected_names",
    "resume_command",
]

"""DAG → wave plan → multi-prompt rendering for ``sase bead work`` automation.

Pure-library helpers that the ``sase bead work <epic_id>`` handler will call
to (a) compute a phase-wave schedule from an epic's dependency DAG and
(b) render a multi-prompt that ``launch_agent_from_cwd`` can dispatch.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sase.bead import db
from sase.bead.model import IssueType, Status

if TYPE_CHECKING:
    from sase.xprompt.workflow_models import Workflow


@dataclass(frozen=True)
class PhaseAssignment:
    """One phase bead's assignment to an agent in a wave."""

    bead_id: str
    agent_name: str
    waits_on: tuple[str, ...]
    wave: int


@dataclass(frozen=True)
class EpicWorkPlan:
    """Wave-partitioned plan to work an epic plus its final land agent."""

    epic_id: str
    waves: tuple[tuple[PhaseAssignment, ...], ...]
    land_agent_name: str
    land_waits_on: tuple[str, ...]


@dataclass(frozen=True)
class ChangeSpecLaunchContext:
    """VCS launch wrapper for ChangeSpec-attached epic work."""

    changespec_name: str
    vcs_workflow: str
    project_name: str
    bug_id: str = ""


class EpicPlanError(ValueError):
    """Base error for epic-work-plan construction failures."""


class CycleError(EpicPlanError):
    """Raised when the open phase children form a dependency cycle."""


class CrossEpicBlockerError(EpicPlanError):
    """Raised when a phase has an out-of-epic blocker that is not closed."""


def _phase_agent_name(bead_id: str) -> str:
    # Phase bead IDs are <epic_id>.<N> by construction; use as-is.
    return bead_id


def _land_agent_name(epic_id: str) -> str:
    return f"{epic_id}.land"


def build_epic_work_plan(conn: sqlite3.Connection, epic_id: str) -> EpicWorkPlan:
    """Compute a wave-partitioned plan to work non-closed phase children.

    Non-closed phase children are layered Kahn-style: wave 0 is every phase
    whose in-epic non-closed blockers are all already satisfied (closed);
    wave *k* is every phase whose remaining in-epic non-closed blockers fall
    in waves < *k*.

    Raises:
        EpicPlanError: If the epic does not exist, is not a plan-type bead,
            or has no non-closed phase children.
        CrossEpicBlockerError: If a phase depends on an out-of-epic blocker
            that is not closed.
        CycleError: If the open phases form a dependency cycle.
    """
    epic = db.get_issue(conn, epic_id)
    if epic is None:
        raise EpicPlanError(f"Epic {epic_id!r} not found")
    if epic.issue_type != IssueType.PLAN:
        raise EpicPlanError(f"{epic_id!r} is not a plan/epic bead")

    children = db.get_epic_children(conn, epic_id)
    open_phases = [
        c
        for c in children
        if c.issue_type == IssueType.PHASE and c.status != Status.CLOSED
    ]
    if not open_phases:
        raise EpicPlanError(f"Epic {epic_id!r} has no non-closed phase children")

    in_epic_phase_ids = {c.id for c in children if c.issue_type == IssueType.PHASE}
    open_phase_ids = {p.id for p in open_phases}

    deps: dict[str, set[str]] = {}
    for phase in open_phases:
        in_epic_open: set[str] = set()
        for dep in phase.dependencies:
            blocker_id = dep.depends_on_id
            if blocker_id in in_epic_phase_ids:
                if blocker_id in open_phase_ids:
                    in_epic_open.add(blocker_id)
                continue
            blocker = db.get_issue(conn, blocker_id)
            if blocker is None or blocker.status != Status.CLOSED:
                raise CrossEpicBlockerError(
                    f"Phase {phase.id!r} depends on out-of-epic blocker "
                    f"{blocker_id!r} that is not closed"
                )
        deps[phase.id] = in_epic_open

    waves: list[list[str]] = []
    placed: set[str] = set()
    remaining = set(open_phase_ids)
    sort_key = {p.id: (p.created_at, p.id) for p in open_phases}
    while remaining:
        ready = sorted(
            (pid for pid in remaining if deps[pid] <= placed),
            key=lambda pid: sort_key[pid],
        )
        if not ready:
            raise CycleError(
                f"Cycle detected among phases of epic {epic_id!r}: {sorted(remaining)}"
            )
        waves.append(ready)
        placed.update(ready)
        remaining.difference_update(ready)

    assigned_waves: list[tuple[PhaseAssignment, ...]] = []
    for wave_index, wave_ids in enumerate(waves):
        assignments = []
        for pid in wave_ids:
            waits = tuple(_phase_agent_name(b) for b in sorted(deps[pid]))
            assignments.append(
                PhaseAssignment(
                    bead_id=pid,
                    agent_name=_phase_agent_name(pid),
                    waits_on=waits,
                    wave=wave_index,
                )
            )
        assigned_waves.append(tuple(assignments))

    has_dependent: set[str] = set()
    for blockers in deps.values():
        has_dependent.update(blockers)
    leaves = sorted(open_phase_ids - has_dependent)

    return EpicWorkPlan(
        epic_id=epic_id,
        waves=tuple(assigned_waves),
        land_agent_name=_land_agent_name(epic_id),
        land_waits_on=tuple(_phase_agent_name(b) for b in leaves),
    )


def render_multi_prompt(
    plan: EpicWorkPlan,
    work_phase_xprompt: Workflow,
    land_epic_xprompt: Workflow,
    changespec_context: ChangeSpecLaunchContext | None = None,
) -> str:
    """Render *plan* as a ``---``-separated multi-prompt string.

    Each phase becomes a segment with ``%name``, optional ``%w``, and a
    ``#<work_phase_xprompt.name>:<bead_id>`` reference. A final land segment
    invokes ``#<land_epic_xprompt.name>:<epic_id>`` and waits on every leaf
    phase agent. Tag-resolved xprompt names are substituted into the ``#...``
    references so user overrides flow through unchanged.

    When *changespec_context* is provided, every segment is prefixed with the
    appropriate VCS xprompt. The first phase segment targets the project ref and
    includes ``#pr`` to create/own the ChangeSpec; later phase segments and the
    land segment target the ChangeSpec ref directly.
    """
    if changespec_context is not None:
        _validate_changespec_context(changespec_context)

    segments: list[str] = []
    is_first_phase = True
    for wave in plan.waves:
        for assignment in wave:
            lines = _segment_prefix(changespec_context, is_first_phase)
            is_first_phase = False
            lines.extend([f"%name:{assignment.agent_name}", "%approve"])
            if assignment.waits_on:
                lines.append(f"%w:{','.join(assignment.waits_on)}")
            lines.append(f"#{work_phase_xprompt.name}:{assignment.bead_id}")
            segments.append("\n".join(lines))

    land_lines = _segment_prefix(changespec_context, is_first_phase=False)
    land_lines.extend([f"%name:{plan.land_agent_name}", "%approve"])
    if plan.land_waits_on:
        land_lines.append(f"%w:{','.join(plan.land_waits_on)}")
    land_lines.append(f"#{land_epic_xprompt.name}:{plan.epic_id}")
    segments.append("\n".join(land_lines))

    return "\n---\n".join(segments)


def _validate_changespec_context(ctx: ChangeSpecLaunchContext) -> None:
    missing = []
    if not ctx.changespec_name:
        missing.append("changespec_name")
    if not ctx.vcs_workflow:
        missing.append("vcs_workflow")
    if not ctx.project_name:
        missing.append("project_name")
    if missing:
        raise ValueError(
            "ChangeSpec launch context is missing required field(s): "
            + ", ".join(missing)
        )


def _segment_prefix(
    ctx: ChangeSpecLaunchContext | None,
    is_first_phase: bool,
) -> list[str]:
    if ctx is None:
        return []

    ref = ctx.project_name if is_first_phase else ctx.changespec_name
    line = f"#{ctx.vcs_workflow}:{ref}"
    if is_first_phase:
        line = f"{line} {_pr_reference(ctx)}"
    return [line]


def _pr_reference(ctx: ChangeSpecLaunchContext) -> str:
    if ctx.bug_id:
        return f"#pr(name={ctx.changespec_name}, bug_id={ctx.bug_id})"
    return f"#pr:{ctx.changespec_name}"

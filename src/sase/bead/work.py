"""DAG → wave plan → multi-prompt rendering for ``sase bead work`` automation.

Pure-library helpers that the ``sase bead work <epic_id>`` handler will call
to (a) compute a phase-wave schedule from an epic's dependency DAG and
(b) render a multi-prompt that ``launch_agent_from_cwd`` can dispatch.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

from sase.bead import db
from sase.bead.model import Dependency, Issue
from sase.core.rust import require_rust_binding

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
class VCSLaunchContext:
    """VCS launch wrapper for project-scoped epic work."""

    vcs_workflow: str
    project_name: str


@dataclass(frozen=True)
class ChangeSpecLaunchContext(VCSLaunchContext):
    """VCS launch wrapper for ChangeSpec-attached epic work."""

    changespec_name: str
    bug_id: str = ""


class EpicPlanError(ValueError):
    """Base error for epic-work-plan construction failures."""


class CycleError(EpicPlanError):
    """Raised when the open phase children form a dependency cycle."""


class CrossEpicBlockerError(EpicPlanError):
    """Raised when a phase has an out-of-epic blocker that is not closed."""


def build_epic_work_plan(
    source: sqlite3.Connection | str | Path,
    epic_id: str,
) -> EpicWorkPlan:
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
    if isinstance(source, sqlite3.Connection):
        return _build_epic_work_plan_from_issues(db.list_issues(source), epic_id)

    binding = require_rust_binding("bead_build_epic_work_plan")
    try:
        payload: dict[str, Any] = binding(str(source), epic_id)
    except ValueError as exc:
        _raise_epic_plan_error(exc)
    return _plan_from_payload(payload)


def build_epic_work_plan_from_beads_dir(
    beads_dir: str | Path,
    epic_id: str,
) -> EpicWorkPlan:
    """Compute an epic work plan directly from a bead store through Rust."""
    return build_epic_work_plan(beads_dir, epic_id)


def _build_epic_work_plan_from_issues(
    issues: list[Issue],
    epic_id: str,
) -> EpicWorkPlan:
    binding = require_rust_binding("bead_build_epic_work_plan_from_issues")
    try:
        payload: dict[str, Any] = binding(
            [_issue_to_wire_dict(issue) for issue in issues],
            epic_id,
        )
    except ValueError as exc:
        _raise_epic_plan_error(exc)
    return _plan_from_payload(payload)


def _plan_from_payload(payload: dict[str, Any]) -> EpicWorkPlan:
    return EpicWorkPlan(
        epic_id=str(payload["epic_id"]),
        waves=tuple(
            tuple(
                PhaseAssignment(
                    bead_id=str(assignment["bead_id"]),
                    agent_name=str(assignment["agent_name"]),
                    waits_on=tuple(str(v) for v in assignment.get("waits_on", [])),
                    wave=int(assignment["wave"]),
                )
                for assignment in wave
            )
            for wave in payload["waves"]
        ),
        land_agent_name=str(payload["land_agent_name"]),
        land_waits_on=tuple(str(v) for v in payload.get("land_waits_on", [])),
    )


def _issue_to_wire_dict(issue: Issue) -> dict[str, object]:
    return {
        "id": issue.id,
        "title": issue.title,
        "status": issue.status.value,
        "issue_type": issue.issue_type.value,
        "tier": issue.tier.value if issue.tier else None,
        "parent_id": issue.parent_id,
        "owner": issue.owner,
        "assignee": issue.assignee,
        "created_at": issue.created_at,
        "created_by": issue.created_by,
        "updated_at": issue.updated_at,
        "closed_at": issue.closed_at,
        "close_reason": issue.close_reason,
        "description": issue.description,
        "notes": issue.notes,
        "design": issue.design,
        "is_ready_to_work": issue.is_ready_to_work,
        "changespec_name": issue.changespec_name,
        "changespec_bug_id": issue.changespec_bug_id,
        "dependencies": [_dependency_to_wire_dict(dep) for dep in issue.dependencies],
    }


def _dependency_to_wire_dict(dep: Dependency) -> dict[str, str]:
    return {
        "issue_id": dep.issue_id,
        "depends_on_id": dep.depends_on_id,
        "created_at": dep.created_at,
        "created_by": dep.created_by,
    }


def _raise_epic_plan_error(exc: ValueError) -> None:
    kind, message = _split_rust_error(str(exc))
    if kind == "cycle":
        raise CycleError(message) from exc
    if kind == "cross_epic_blocker":
        raise CrossEpicBlockerError(message) from exc
    raise EpicPlanError(message) from exc


def _split_rust_error(text: str) -> tuple[str, str]:
    if ": " not in text:
        return "validation", text
    kind, message = text.split(": ", 1)
    return kind, message


def render_multi_prompt(
    plan: EpicWorkPlan,
    work_phase_xprompt: Workflow,
    land_epic_xprompt: Workflow,
    vcs_context: VCSLaunchContext | None = None,
    changespec_context: ChangeSpecLaunchContext | None = None,
) -> str:
    """Render *plan* as a ``---``-separated multi-prompt string.

    Each phase becomes a segment with ``%name``, optional ``%w``, and a
    ``#<work_phase_xprompt.name>:<bead_id>`` reference. A final land segment
    invokes ``#<land_epic_xprompt.name>:<epic_id>`` and waits on every leaf
    phase agent. Tag-resolved xprompt names are substituted into the ``#...``
    references so user overrides flow through unchanged.

    When *vcs_context* is provided, every segment is prefixed with the project
    VCS xprompt. When *changespec_context* is provided, the first phase segment
    targets the project ref and includes ``#pr`` to create/own the ChangeSpec;
    later phase segments and the land segment target the ChangeSpec ref
    directly.
    """
    if vcs_context is not None and changespec_context is not None:
        raise ValueError("provide either vcs_context or changespec_context, not both")
    launch_context = changespec_context or vcs_context
    if launch_context is not None:
        _validate_vcs_context(launch_context)
    if changespec_context is not None:
        _validate_changespec_context(changespec_context)

    segments: list[str] = []
    is_first_phase = True
    for wave in plan.waves:
        for assignment in wave:
            lines = _segment_prefix(launch_context, is_first_phase)
            is_first_phase = False
            lines.extend([f"%name:{assignment.agent_name}", "%approve"])
            if assignment.waits_on:
                lines.append(f"%w:{','.join(assignment.waits_on)}")
            lines.append(f"#{work_phase_xprompt.name}:{assignment.bead_id}")
            segments.append("\n".join(lines))

    land_lines = _segment_prefix(launch_context, is_first_phase=False)
    land_lines.extend([f"%name:{plan.land_agent_name}", "%approve"])
    if plan.land_waits_on:
        land_lines.append(f"%w:{','.join(plan.land_waits_on)}")
    land_lines.append(f"#{land_epic_xprompt.name}:{plan.epic_id}")
    segments.append("\n".join(land_lines))

    return "\n---\n".join(segments)


def _validate_vcs_context(ctx: VCSLaunchContext) -> None:
    missing = []
    if not ctx.vcs_workflow:
        missing.append("vcs_workflow")
    if not ctx.project_name:
        missing.append("project_name")
    if missing:
        raise ValueError(
            "VCS launch context is missing required field(s): " + ", ".join(missing)
        )


def _validate_changespec_context(ctx: ChangeSpecLaunchContext) -> None:
    missing = []
    if not ctx.changespec_name:
        missing.append("changespec_name")
    if missing:
        raise ValueError(
            "ChangeSpec launch context is missing required field(s): "
            + ", ".join(missing)
        )


def _segment_prefix(
    ctx: VCSLaunchContext | None,
    is_first_phase: bool,
) -> list[str]:
    if ctx is None:
        return []

    if isinstance(ctx, ChangeSpecLaunchContext):
        ref = ctx.project_name if is_first_phase else ctx.changespec_name
    else:
        ref = ctx.project_name
    line = f"#{ctx.vcs_workflow}:{ref}"
    if is_first_phase and isinstance(ctx, ChangeSpecLaunchContext):
        line = f"{line} {_pr_reference(ctx)}"
    return [line]


def _pr_reference(ctx: ChangeSpecLaunchContext) -> str:
    if ctx.bug_id:
        return f"#pr(name={ctx.changespec_name}, bug_id={ctx.bug_id})"
    return f"#pr:{ctx.changespec_name}"

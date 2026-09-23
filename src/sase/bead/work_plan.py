"""Wave-plan construction for ``sase bead work`` automation.

Computes a phase-wave schedule from an epic's dependency DAG via the Rust
``bead_build_epic_work_plan`` binding. The plan types live here (rather than
in :mod:`sase.bead.work_types`) so the file-private assignment and error
helpers are constructed, raised, and consumed in their defining file.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.bead import db
from sase.bead.close_history_codec import close_history_to_dicts
from sase.bead.model import Dependency, Issue, PhaseSize
from sase.bead.work_types import EpicPlanError
from sase.core.rust import require_rust_binding


@dataclass(frozen=True)
class _PhaseAssignment:
    """One phase bead's assignment to an agent in a wave."""

    bead_id: str
    agent_name: str
    waits_on: tuple[str, ...]
    blocker_bead_ids: tuple[str, ...]
    wave: int
    model: str = ""
    size: PhaseSize | None = None


@dataclass(frozen=True)
class EpicWorkPlan:
    """Wave-partitioned plan to work an epic plus its final land agent."""

    epic_id: str
    launch_tag_id: str
    total_phase_count: int
    phase_bead_ids: tuple[str, ...]
    waves: tuple[tuple[_PhaseAssignment, ...], ...]
    land_agent_name: str
    land_waits_on: tuple[str, ...]
    land_model: str = ""


class _CycleError(EpicPlanError):
    """Raised when the open phase children form a dependency cycle."""


class _CrossEpicBlockerError(EpicPlanError):
    """Raised when a phase has an out-of-epic blocker that is not closed."""


def _build_epic_work_plan(
    source: sqlite3.Connection | str | Path,
    epic_id: str,
) -> EpicWorkPlan:
    """Compute a wave-partitioned plan to work an epic's authored phases.

    Non-closed phase children are layered Kahn-style: wave 0 is every phase
    whose in-epic non-closed blockers are all already satisfied (closed);
    wave *k* is every phase whose remaining in-epic non-closed blockers fall
    in waves < *k*. An epic with authored phases that are all closed returns a
    land-only plan with no phase waves.

    Raises:
        EpicPlanError: If the epic does not exist, is not a plan-type bead,
            or has no authored phase children.
        _CrossEpicBlockerError: If a phase depends on an out-of-epic blocker
            that is not closed.
        _CycleError: If the open phases form a dependency cycle.
    """
    if isinstance(source, sqlite3.Connection):
        return _build_epic_work_plan_from_issues(db.list_issues(source), epic_id)

    from sase.core.bead_read_facade import resolve_id

    epic_id = resolve_id(source, epic_id)
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
    return _build_epic_work_plan(beads_dir, epic_id)


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
    epic_id = str(payload["epic_id"])
    raw_waves = [list(wave) for wave in payload["waves"]]
    agent_names = {
        str(assignment["agent_name"]): _epic_clan_agent_name(
            epic_id,
            str(assignment["agent_name"]),
        )
        for wave in raw_waves
        for assignment in wave
    }

    def _membership_name(value: object) -> str:
        raw_name = str(value)
        return agent_names.get(raw_name, _epic_clan_agent_name(epic_id, raw_name))

    return EpicWorkPlan(
        epic_id=epic_id,
        launch_tag_id=str(payload.get("launch_tag_id", epic_id)),
        total_phase_count=int(
            payload.get(
                "total_phase_count",
                sum(len(wave) for wave in payload["waves"]),
            )
        ),
        waves=tuple(
            tuple(
                _PhaseAssignment(
                    bead_id=str(assignment["bead_id"]),
                    agent_name=_membership_name(assignment["agent_name"]),
                    waits_on=tuple(
                        _membership_name(v) for v in assignment.get("waits_on", [])
                    ),
                    blocker_bead_ids=tuple(
                        str(v) for v in assignment["blocker_bead_ids"]
                    ),
                    wave=int(assignment["wave"]),
                    model=str(assignment.get("model", "")),
                    size=(
                        PhaseSize(str(assignment["size"]))
                        if assignment.get("size")
                        else None
                    ),
                )
                for assignment in wave
            )
            for wave in raw_waves
        ),
        phase_bead_ids=tuple(str(v) for v in payload["phase_bead_ids"]),
        land_agent_name=_epic_clan_agent_name(
            epic_id,
            str(payload["land_agent_name"]),
        ),
        land_waits_on=tuple(
            _membership_name(v) for v in payload.get("land_waits_on", [])
        ),
        land_model=str(payload.get("land_model", "")),
    )


def _epic_clan_agent_name(epic_id: str, agent_name: str) -> str:
    prefix = f"{epic_id}."
    return agent_name if agent_name.startswith(prefix) else f"{prefix}{agent_name}"


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
        "resolution": issue.resolution.value if issue.resolution else None,
        "description": issue.description,
        "notes": issue.notes_text,
        "design": issue.design,
        "model": issue.model,
        "size": issue.size.value if issue.size else None,
        "is_ready_to_work": issue.is_ready_to_work,
        "changespec_name": issue.changespec_name,
        "changespec_bug_id": issue.changespec_bug_id,
        "dependencies": [_dependency_to_wire_dict(dep) for dep in issue.dependencies],
        "plus_one_evidence": [
            {
                "timestamp": evidence.timestamp,
                "reporter": evidence.reporter,
                "note": evidence.note,
                "refs": evidence.refs,
            }
            for evidence in issue.plus_one_evidence
        ],
        "close_history": close_history_to_dicts(issue.close_history),
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
        raise _CycleError(message) from exc
    if kind == "cross_epic_blocker":
        raise _CrossEpicBlockerError(message) from exc
    raise EpicPlanError(message) from exc


def _split_rust_error(text: str) -> tuple[str, str]:
    if ": " not in text:
        return "validation", text
    kind, message = text.split(": ", 1)
    return kind, message


__all__ = [
    "EpicWorkPlan",
    "_CrossEpicBlockerError",
    "_CycleError",
    "_PhaseAssignment",
    "_build_epic_work_plan",
    "_build_epic_work_plan_from_issues",
    "_dependency_to_wire_dict",
    "_epic_clan_agent_name",
    "_issue_to_wire_dict",
    "_plan_from_payload",
    "_raise_epic_plan_error",
    "_split_rust_error",
    "build_epic_work_plan_from_beads_dir",
]

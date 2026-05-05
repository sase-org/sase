"""Shared helpers for bead work unit tests."""

from __future__ import annotations

import sqlite3

from sase.bead import db
from sase.bead.model import BeadTier, Issue, IssueType, Status
from sase.bead.work import EpicWorkPlan, PhaseAssignment

NOW = "2026-04-25T00:00:00Z"


def epic(epic_id: str = "e1") -> Issue:
    return Issue(
        id=epic_id,
        title=f"Epic {epic_id}",
        issue_type=IssueType.PLAN,
        parent_id=None,
        created_at=NOW,
        updated_at=NOW,
    )


def legend(
    legend_id: str = "l1",
    *,
    epic_count: int | None = 3,
    design: str = "sdd/legends/202605/roadmap.md",
) -> Issue:
    return Issue(
        id=legend_id,
        title=f"Legend {legend_id}",
        issue_type=IssueType.PLAN,
        tier=BeadTier.LEGEND,
        epic_count=epic_count,
        design=design,
        created_at=NOW,
        updated_at=NOW,
    )


def phase(
    phase_id: str,
    parent_id: str = "e1",
    *,
    status: Status = Status.OPEN,
    created_at: str = NOW,
) -> Issue:
    return Issue(
        id=phase_id,
        title=f"Phase {phase_id}",
        issue_type=IssueType.PHASE,
        parent_id=parent_id,
        status=status,
        created_at=created_at,
        updated_at=created_at,
    )


def seed(conn: sqlite3.Connection, issues: list[Issue]) -> None:
    for issue in issues:
        db.create_issue(conn, issue)


def depends(conn: sqlite3.Connection, child: str, blocker: str) -> None:
    db.add_dependency(conn, child, blocker, NOW)


def wave_bead_ids(plan: EpicWorkPlan, wave_index: int) -> list[str]:
    assignments: tuple[PhaseAssignment, ...] = plan.waves[wave_index]
    return [a.bead_id for a in assignments]

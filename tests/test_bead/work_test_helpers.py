"""Shared helpers for bead work unit tests."""

from __future__ import annotations

import sqlite3

from sase.bead import db
from sase.bead.model import Issue, IssueType, PhaseSize, Status
from sase.bead.work import EpicWorkPlan, _PhaseAssignment as PhaseAssignment
from sase.xprompt.directives import extract_prompt_directives

NOW = "2026-04-25T00:00:00Z"


def epic(
    epic_id: str = "e1",
    *,
    parent_id: str | None = None,
    model: str = "",
) -> Issue:
    return Issue(
        id=epic_id,
        title=f"Epic {epic_id}",
        issue_type=IssueType.PLAN,
        parent_id=parent_id,
        model=model,
        created_at=NOW,
        updated_at=NOW,
    )


def phase(
    phase_id: str,
    parent_id: str = "e1",
    *,
    status: Status = Status.OPEN,
    created_at: str = NOW,
    model: str = "",
    size: PhaseSize | None = None,
) -> Issue:
    return Issue(
        id=phase_id,
        title=f"Phase {phase_id}",
        issue_type=IssueType.PHASE,
        parent_id=parent_id,
        status=status,
        model=model,
        size=size,
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


def assert_bare_auto_directives(rendered: str) -> None:
    segments = rendered.split("\n---\n")
    for segment in segments:
        assert "%auto" in segment.splitlines()
        assert "%auto:tale" not in segment
        _, directives = extract_prompt_directives(segment)
        assert directives.auto_enabled is True
        assert directives.auto_argument is None

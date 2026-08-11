"""Row-to-model mapping for the compatibility bead mirror."""

from __future__ import annotations

import sqlite3

from sase.bead._db_codec import (
    close_history_from_json,
    plus_one_evidence_from_json,
    snooze_from_json,
)
from sase.bead.model import (
    BeadTier,
    Dependency,
    Issue,
    IssueType,
    PhaseSize,
    Resolution,
    Status,
)


def row_to_issue(row: sqlite3.Row) -> Issue:
    return Issue(
        id=row["id"],
        title=row["title"],
        status=Status(row["status"]),
        issue_type=IssueType(row["issue_type"]),
        tier=BeadTier(row["tier"]) if row["tier"] else None,
        parent_id=row["parent_id"],
        owner=row["owner"] or "",
        assignee=row["assignee"] or "",
        created_at=row["created_at"],
        created_by=row["created_by"] or "",
        updated_at=row["updated_at"],
        closed_at=row["closed_at"],
        close_reason=row["close_reason"],
        resolution=Resolution(row["resolution"]) if row["resolution"] else None,
        description=row["description"] or "",
        notes=row["notes"] or "",
        design=row["design"] or "",
        refs=(row["refs"] or "").splitlines(),
        plus_one_evidence=plus_one_evidence_from_json(row["plus_one_evidence"]),
        close_history=close_history_from_json(row["close_history"]),
        snooze=snooze_from_json(row["snooze"]),
        model=row["model"] or "",
        size=PhaseSize(row["size"]) if row["size"] else None,
        is_ready_to_work=bool(row["is_ready_to_work"]),
        changespec_name=row["changespec_name"] or "",
        changespec_bug_id=row["changespec_bug_id"] or "",
        external_ref=row["external_ref"] or "",
    )


def load_dependencies(conn: sqlite3.Connection, issue_id: str) -> list[Dependency]:
    rows = conn.execute(
        "SELECT issue_id, depends_on_id, created_at, created_by "
        "FROM dependencies WHERE issue_id = ?",
        (issue_id,),
    ).fetchall()
    return [
        Dependency(
            issue_id=r["issue_id"],
            depends_on_id=r["depends_on_id"],
            created_at=r["created_at"],
            created_by=r["created_by"] or "",
        )
        for r in rows
    ]


def rows_to_issues(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> list[Issue]:
    """Map result rows to issues, each with its mirrored dependency edges."""
    issues = []
    for row in rows:
        issue = row_to_issue(row)
        issue.dependencies = load_dependencies(conn, issue.id)
        issues.append(issue)
    return issues

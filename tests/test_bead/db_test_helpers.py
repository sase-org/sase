"""Shared helpers for bead database tests."""

import sqlite3

from sase.bead.db import list_issues, update_issue
from sase.bead.model import Issue, IssueType, Status

NOW = "2026-03-17T00:00:00Z"


def ready_issues(conn: sqlite3.Connection) -> list[Issue]:
    issues = list_issues(conn)
    issue_by_id = {issue.id: issue for issue in issues}

    blocked_ids: set[str] = set()
    for issue in issues:
        for dep in issue.dependencies:
            blocker = issue_by_id.get(dep.depends_on_id)
            if blocker is not None and blocker.status in {
                Status.OPEN,
                Status.CLAIMED,
                Status.READY,
                Status.IN_PROGRESS,
            }:
                blocked_ids.add(issue.id)

    return [
        issue
        for issue in issues
        if issue.id not in blocked_ids
        and issue.issue_type == IssueType.TASK
        and issue.status == Status.READY
    ]


def epic(id: str = "e-1", title: str = "Epic") -> Issue:
    return Issue(
        id=id,
        title=title,
        issue_type=IssueType.PLAN,
        parent_id=None,
        created_at=NOW,
        updated_at=NOW,
    )


def child(id: str = "c-1", parent_id: str = "e-1", title: str = "Child") -> Issue:
    return Issue(
        id=id,
        title=title,
        issue_type=IssueType.PHASE,
        parent_id=parent_id,
        created_at=NOW,
        updated_at=NOW,
    )


def close_issue(
    conn: sqlite3.Connection,
    issue_id: str,
    closed_at: str,
    reason: str | None = None,
) -> Issue | None:
    return update_issue(
        conn,
        issue_id,
        status="closed",
        closed_at=closed_at,
        close_reason=reason,
        updated_at=closed_at,
    )

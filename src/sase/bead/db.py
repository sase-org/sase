"""Compatibility SQLite helpers for bead tests and legacy callers.

Production bead reads and mutations route through ``sase_core_rs`` facades.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from sase.bead._db_codec import (
    close_history_json,
    plus_one_evidence_from_json,
    plus_one_evidence_json,
    snooze_json,
)
from sase.bead._db_migrations import run_migrations
from sase.bead._db_rows import load_dependencies, row_to_issue, rows_to_issues
from sase.bead._db_schema import SCHEMA_SQL, connect
from sase.bead.model import (
    BeadTier,
    Dependency,
    Issue,
    IssueType,
    Status,
)


def init_db(db_path: Path) -> sqlite3.Connection:
    """Create or open the database, ensuring schema exists."""
    conn = connect(db_path)
    run_migrations(conn)
    conn.executescript(SCHEMA_SQL)
    return conn


def create_issue(
    conn: sqlite3.Connection, issue: Issue, *, commit: bool = True
) -> Issue:
    """Insert a new issue into the database."""
    if issue.issue_type == IssueType.PLAN and issue.tier is None:
        issue.tier = BeadTier.EPIC
    issue.validate()
    conn.execute(
        "INSERT INTO issues "
        "(id, title, status, issue_type, parent_id, owner, assignee, "
        "tier, created_at, created_by, updated_at, closed_at, close_reason, "
        "resolution, "
        "description, notes, design, refs, plus_one_evidence, close_history, "
        "snooze, model, size, is_ready_to_work, "
        "changespec_name, changespec_bug_id, external_ref) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
        "?, ?, ?)",
        (
            issue.id,
            issue.title,
            issue.status.value,
            issue.issue_type.value,
            issue.parent_id,
            issue.owner,
            issue.assignee,
            issue.tier.value if issue.tier else None,
            issue.created_at,
            issue.created_by,
            issue.updated_at,
            issue.closed_at,
            issue.close_reason,
            issue.resolution.value if issue.resolution else None,
            issue.description,
            issue.notes,
            issue.design,
            "\n".join(issue.refs),
            plus_one_evidence_json(issue.plus_one_evidence),
            close_history_json(issue.close_history),
            snooze_json(issue.snooze),
            issue.model,
            issue.size.value if issue.size else None,
            int(issue.is_ready_to_work),
            issue.changespec_name,
            issue.changespec_bug_id,
            issue.external_ref or None,
        ),
    )
    if commit:
        conn.commit()
    return issue


def get_issue(conn: sqlite3.Connection, issue_id: str) -> Issue | None:
    """Fetch a single issue by ID, with its dependencies."""
    row = conn.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
    if row is None:
        return None
    issue = row_to_issue(row)
    issue.dependencies = load_dependencies(conn, issue_id)
    return issue


def list_issues(
    conn: sqlite3.Connection,
    statuses: list[Status] | None = None,
    issue_types: list[IssueType] | None = None,
    tiers: list[BeadTier] | None = None,
) -> list[Issue]:
    """List issues with optional status/type/tier filters."""
    query = "SELECT * FROM issues WHERE 1=1"
    params: list[str] = []
    if statuses is not None:
        placeholders = ",".join("?" for _ in statuses)
        query += f" AND status IN ({placeholders})"
        params.extend(s.value for s in statuses)
    if issue_types is not None:
        placeholders = ",".join("?" for _ in issue_types)
        query += f" AND issue_type IN ({placeholders})"
        params.extend(t.value for t in issue_types)
    if tiers is not None:
        placeholders = ",".join("?" for _ in tiers)
        query += f" AND tier IN ({placeholders})"
        params.extend(t.value for t in tiers)
    query += " ORDER BY created_at ASC"
    return rows_to_issues(conn, conn.execute(query, params).fetchall())


def update_issue(
    conn: sqlite3.Connection,
    issue_id: str,
    *,
    commit: bool = True,
    **fields: str | int | None,
) -> Issue | None:
    """Update specific fields on an issue."""
    allowed = {
        "title",
        "status",
        "assignee",
        "updated_at",
        "closed_at",
        "close_reason",
        "resolution",
        "description",
        "notes",
        "design",
        "refs",
        "plus_one_evidence",
        "close_history",
        "snooze",
        "model",
        "size",
        "tier",
        "is_ready_to_work",
        "changespec_name",
        "changespec_bug_id",
        "external_ref",
    }
    to_set: dict[str, str | int | None] = {
        k: (
            int(v)
            if k == "is_ready_to_work" and v is not None
            else (None if k == "external_ref" and not v else v)
        )
        for k, v in fields.items()
        if k in allowed
    }
    if not to_set:
        return get_issue(conn, issue_id)
    set_clause = ", ".join(f"{k} = ?" for k in to_set)
    values = list(to_set.values()) + [issue_id]
    conn.execute(
        f"UPDATE issues SET {set_clause} WHERE id = ?",  # noqa: S608
        values,
    )
    if commit:
        conn.commit()
    return get_issue(conn, issue_id)


def add_dependency(
    conn: sqlite3.Connection,
    issue_id: str,
    depends_on_id: str,
    created_at: str,
    created_by: str = "",
    *,
    commit: bool = True,
) -> Dependency:
    """Add a dependency: issue_id depends on depends_on_id."""
    conn.execute(
        "INSERT INTO dependencies (issue_id, depends_on_id, created_at, created_by) "
        "VALUES (?, ?, ?, ?)",
        (issue_id, depends_on_id, created_at, created_by),
    )
    if commit:
        conn.commit()
    return Dependency(
        issue_id=issue_id,
        depends_on_id=depends_on_id,
        created_at=created_at,
        created_by=created_by,
    )


def delete_dependencies_not_in(
    conn: sqlite3.Connection,
    issue_id: str,
    depends_on_ids: list[str],
    *,
    commit: bool = True,
) -> int:
    """Delete mirrored edges for issue_id that are absent from the projection."""
    if depends_on_ids:
        placeholders = ", ".join("?" for _ in depends_on_ids)
        cursor = conn.execute(
            "DELETE FROM dependencies "
            f"WHERE issue_id = ? AND depends_on_id NOT IN ({placeholders})",
            [issue_id, *depends_on_ids],
        )
    else:
        cursor = conn.execute(
            "DELETE FROM dependencies WHERE issue_id = ?",
            (issue_id,),
        )
    if commit:
        conn.commit()
    return cursor.rowcount


def get_epic_children(conn: sqlite3.Connection, epic_id: str) -> list[Issue]:
    """Get all child issues of an epic."""
    rows = conn.execute(
        "SELECT * FROM issues WHERE parent_id = ? ORDER BY created_at ASC",
        (epic_id,),
    ).fetchall()
    return rows_to_issues(conn, rows)


def stats(conn: sqlite3.Connection) -> dict[str, int]:
    """Return counts by status/type plus derived task +1 evidence."""
    result: dict[str, int] = {}
    for row in conn.execute(
        "SELECT status, COUNT(*) as cnt FROM issues GROUP BY status"
    ).fetchall():
        result[row["status"]] = row["cnt"]
    for row in conn.execute(
        "SELECT issue_type, COUNT(*) as cnt FROM issues GROUP BY issue_type"
    ).fetchall():
        result[row["issue_type"]] = row["cnt"]
    result["total"] = sum(
        r["cnt"] for r in conn.execute("SELECT COUNT(*) as cnt FROM issues").fetchall()
    )
    result["plus_one"] = sum(
        len(plus_one_evidence_from_json(row["plus_one_evidence"]))
        for row in conn.execute("SELECT plus_one_evidence FROM issues").fetchall()
    )
    return result

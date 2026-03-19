"""SQLite database layer for issue storage."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from sase.bead.model import Dependency, Issue, IssueType, Status

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS issues (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open'
                  CHECK(status IN ('open', 'in_progress', 'closed')),
    issue_type  TEXT NOT NULL DEFAULT 'phase'
                  CHECK(issue_type IN ('plan', 'phase')),
    parent_id   TEXT
                  REFERENCES issues(id) ON DELETE CASCADE,
    owner       TEXT,
    assignee    TEXT,
    created_at  TEXT NOT NULL,
    created_by  TEXT,
    updated_at  TEXT NOT NULL,
    closed_at   TEXT,
    close_reason TEXT,
    description TEXT,
    notes       TEXT,
    design      TEXT,
    CHECK(
        (issue_type = 'phase' AND parent_id IS NOT NULL) OR
        (issue_type = 'plan')
    )
);

CREATE TABLE IF NOT EXISTS dependencies (
    issue_id       TEXT NOT NULL,
    depends_on_id  TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    created_by     TEXT,
    PRIMARY KEY (issue_id, depends_on_id),
    FOREIGN KEY (issue_id) REFERENCES issues(id) ON DELETE CASCADE,
    FOREIGN KEY (depends_on_id) REFERENCES issues(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_issues_status ON issues(status);
CREATE INDEX IF NOT EXISTS idx_issues_type ON issues(issue_type);
CREATE INDEX IF NOT EXISTS idx_issues_parent ON issues(parent_id);
CREATE INDEX IF NOT EXISTS idx_deps_depends_on ON dependencies(depends_on_id);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _migrate_issue_types(conn: sqlite3.Connection) -> None:
    """Migrate from epic/child to plan/phase schema if needed."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='issues'"
    ).fetchone()
    if row is None or "'plan'" in row["sql"]:
        return  # No table yet or already migrated

    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute(
        "CREATE TABLE _issues_new ("
        "  id TEXT PRIMARY KEY, title TEXT NOT NULL,"
        "  status TEXT NOT NULL DEFAULT 'open'"
        "    CHECK(status IN ('open','in_progress','closed')),"
        "  issue_type TEXT NOT NULL DEFAULT 'phase'"
        "    CHECK(issue_type IN ('plan','phase')),"
        "  parent_id TEXT, owner TEXT, assignee TEXT,"
        "  created_at TEXT NOT NULL, created_by TEXT,"
        "  updated_at TEXT NOT NULL, closed_at TEXT,"
        "  close_reason TEXT, description TEXT, notes TEXT, design TEXT,"
        "  CHECK((issue_type='phase' AND parent_id IS NOT NULL)"
        "    OR (issue_type='plan'))"
        ")"
    )
    conn.execute(
        "INSERT INTO _issues_new "
        "SELECT id, title, status,"
        "  CASE issue_type"
        "    WHEN 'epic' THEN 'plan' WHEN 'child' THEN 'phase'"
        "    ELSE issue_type END,"
        "  parent_id, owner, assignee, created_at, created_by,"
        "  updated_at, closed_at, close_reason, description, notes, design "
        "FROM issues"
    )
    conn.execute("DROP TABLE issues")
    conn.execute("ALTER TABLE _issues_new RENAME TO issues")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_issues_status ON issues(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_issues_type ON issues(issue_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_issues_parent ON issues(parent_id)")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.commit()


# pyvision: tests/test_bead/test_db.py
def init_db(db_path: Path) -> sqlite3.Connection:
    """Create or open the database, ensuring schema exists."""
    conn = _connect(db_path)
    _migrate_issue_types(conn)
    conn.executescript(_SCHEMA)
    return conn


# pyvision: public_api_methods.txt
def create_memory_db() -> sqlite3.Connection:
    """Create an in-memory database with the beads schema."""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _row_to_issue(row: sqlite3.Row) -> Issue:
    return Issue(
        id=row["id"],
        title=row["title"],
        status=Status(row["status"]),
        issue_type=IssueType(row["issue_type"]),
        parent_id=row["parent_id"],
        owner=row["owner"] or "",
        assignee=row["assignee"] or "",
        created_at=row["created_at"],
        created_by=row["created_by"] or "",
        updated_at=row["updated_at"],
        closed_at=row["closed_at"],
        close_reason=row["close_reason"],
        description=row["description"] or "",
        notes=row["notes"] or "",
        design=row["design"] or "",
    )


def _load_dependencies(conn: sqlite3.Connection, issue_id: str) -> list[Dependency]:
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


# pyvision: tests/test_bead/test_db.py
def create_issue(conn: sqlite3.Connection, issue: Issue) -> Issue:
    """Insert a new issue into the database."""
    issue.validate()
    conn.execute(
        "INSERT INTO issues "
        "(id, title, status, issue_type, parent_id, owner, assignee, "
        "created_at, created_by, updated_at, closed_at, close_reason, "
        "description, notes, design) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            issue.id,
            issue.title,
            issue.status.value,
            issue.issue_type.value,
            issue.parent_id,
            issue.owner,
            issue.assignee,
            issue.created_at,
            issue.created_by,
            issue.updated_at,
            issue.closed_at,
            issue.close_reason,
            issue.description,
            issue.notes,
            issue.design,
        ),
    )
    conn.commit()
    return issue


# pyvision: tests/test_bead/test_db.py
def get_issue(conn: sqlite3.Connection, issue_id: str) -> Issue | None:
    """Fetch a single issue by ID, with its dependencies."""
    row = conn.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
    if row is None:
        return None
    issue = _row_to_issue(row)
    issue.dependencies = _load_dependencies(conn, issue_id)
    return issue


# pyvision: tests/test_bead/test_db.py
def list_issues(
    conn: sqlite3.Connection,
    statuses: list[Status] | None = None,
    issue_types: list[IssueType] | None = None,
) -> list[Issue]:
    """List issues with optional status/type filters."""
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
    query += " ORDER BY created_at ASC"
    rows = conn.execute(query, params).fetchall()
    issues = []
    for row in rows:
        issue = _row_to_issue(row)
        issue.dependencies = _load_dependencies(conn, issue.id)
        issues.append(issue)
    return issues


# pyvision: tests/test_bead/test_db.py
def update_issue(
    conn: sqlite3.Connection, issue_id: str, **fields: str | None
) -> Issue | None:
    """Update specific fields on an issue."""
    allowed = {
        "title",
        "status",
        "assignee",
        "updated_at",
        "closed_at",
        "close_reason",
        "description",
        "notes",
        "design",
    }
    to_set = {k: v for k, v in fields.items() if k in allowed}
    if not to_set:
        return get_issue(conn, issue_id)
    set_clause = ", ".join(f"{k} = ?" for k in to_set)
    values = list(to_set.values()) + [issue_id]
    conn.execute(
        f"UPDATE issues SET {set_clause} WHERE id = ?",  # noqa: S608
        values,
    )
    conn.commit()
    return get_issue(conn, issue_id)


# pyvision: tests/test_bead/test_db.py
def close_issue(
    conn: sqlite3.Connection,
    issue_id: str,
    closed_at: str,
    reason: str | None = None,
) -> Issue | None:
    """Close an issue by setting its status to closed."""
    conn.execute(
        "UPDATE issues SET status = ?, closed_at = ?, close_reason = ?, "
        "updated_at = ? WHERE id = ?",
        ("closed", closed_at, reason, closed_at, issue_id),
    )
    conn.commit()
    return get_issue(conn, issue_id)


# pyvision: tests/test_bead/test_db.py
def ready_issues(conn: sqlite3.Connection) -> list[Issue]:
    """Return open issues with no active (non-closed) blockers."""
    rows = conn.execute(
        "SELECT i.* FROM issues i "
        "WHERE i.status = 'open' "
        "  AND i.id NOT IN ("
        "    SELECT d.issue_id FROM dependencies d "
        "    JOIN issues blocker ON d.depends_on_id = blocker.id "
        "    WHERE blocker.status IN ('open', 'in_progress')"
        "  ) "
        "ORDER BY i.created_at ASC"
    ).fetchall()
    issues = []
    for row in rows:
        issue = _row_to_issue(row)
        issue.dependencies = _load_dependencies(conn, issue.id)
        issues.append(issue)
    return issues


# pyvision: tests/test_bead/test_db.py
def blocked_issues(conn: sqlite3.Connection) -> list[Issue]:
    """Return issues that have at least one active (non-closed) blocker."""
    rows = conn.execute(
        "SELECT DISTINCT i.* FROM issues i "
        "JOIN dependencies d ON i.id = d.issue_id "
        "JOIN issues blocker ON d.depends_on_id = blocker.id "
        "WHERE blocker.status IN ('open', 'in_progress') "
        "ORDER BY i.created_at ASC"
    ).fetchall()
    issues = []
    for row in rows:
        issue = _row_to_issue(row)
        issue.dependencies = _load_dependencies(conn, issue.id)
        issues.append(issue)
    return issues


# pyvision: tests/test_bead/test_db.py
def delete_issue(conn: sqlite3.Connection, issue_id: str) -> bool:
    """Delete an issue by ID.

    Returns True if the issue existed and was deleted.
    Child issues and dependencies are cascade-deleted by the database.
    """
    cursor = conn.execute("DELETE FROM issues WHERE id = ?", (issue_id,))
    conn.commit()
    return cursor.rowcount > 0


# pyvision: tests/test_bead/test_db.py
def add_dependency(
    conn: sqlite3.Connection,
    issue_id: str,
    depends_on_id: str,
    created_at: str,
    created_by: str = "",
) -> Dependency:
    """Add a dependency: issue_id depends on depends_on_id."""
    conn.execute(
        "INSERT INTO dependencies (issue_id, depends_on_id, created_at, created_by) "
        "VALUES (?, ?, ?, ?)",
        (issue_id, depends_on_id, created_at, created_by),
    )
    conn.commit()
    return Dependency(
        issue_id=issue_id,
        depends_on_id=depends_on_id,
        created_at=created_at,
        created_by=created_by,
    )


# pyvision: tests/test_bead/test_db.py
def get_dependencies(conn: sqlite3.Connection, issue_id: str) -> list[Dependency]:
    """Get all dependencies for an issue."""
    return _load_dependencies(conn, issue_id)


# pyvision: tests/test_bead/test_db.py
def get_epic_children(conn: sqlite3.Connection, epic_id: str) -> list[Issue]:
    """Get all child issues of an epic."""
    rows = conn.execute(
        "SELECT * FROM issues WHERE parent_id = ? ORDER BY created_at ASC",
        (epic_id,),
    ).fetchall()
    issues = []
    for row in rows:
        issue = _row_to_issue(row)
        issue.dependencies = _load_dependencies(conn, issue.id)
        issues.append(issue)
    return issues


# pyvision: tests/test_bead/test_db.py
def stats(conn: sqlite3.Connection) -> dict[str, int]:
    """Return counts by status and type."""
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
    return result

"""Schema DDL and connection setup for the compatibility bead mirror."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS issues (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open'
                  CHECK(status IN ('open', 'claimed', 'ready', 'snoozed', 'in_progress', 'closed')),
    issue_type  TEXT NOT NULL DEFAULT 'phase'
                  CHECK(issue_type IN ('plan', 'phase', 'task', 'flag')),
    tier        TEXT
                  CHECK(tier IN ('plan', 'epic')),
    parent_id   TEXT
                  REFERENCES issues(id) ON DELETE CASCADE,
    owner       TEXT,
    assignee    TEXT,
    created_at  TEXT NOT NULL,
    created_by  TEXT,
    updated_at  TEXT NOT NULL,
    closed_at   TEXT,
    close_reason TEXT,
    resolution  TEXT
                  CHECK(resolution IN ('done', 'canceled', 'superseded')),
    description TEXT,
    notes       TEXT,
    design      TEXT,
    refs        TEXT NOT NULL DEFAULT '',
    plus_one_evidence TEXT NOT NULL DEFAULT '[]',
    close_history TEXT NOT NULL DEFAULT '[]',
    snooze      TEXT,
    flag        TEXT,
    model       TEXT NOT NULL DEFAULT '',
    size        TEXT
                  CHECK(
                    size IS NULL OR
                    (issue_type IN ('phase', 'task') AND
                     size IN ('xsmall', 'small', 'medium', 'large', 'xlarge'))
                  ),
    task_type   TEXT,
    task_type_fields TEXT NOT NULL DEFAULT '{}',
    is_ready_to_work INTEGER NOT NULL DEFAULT 0,
    changespec_name TEXT NOT NULL DEFAULT '',
    changespec_bug_id TEXT NOT NULL DEFAULT '',
    external_ref TEXT,
    CHECK(
        (issue_type = 'phase' AND parent_id IS NOT NULL) OR
        (issue_type = 'plan') OR
        (issue_type = 'task' AND parent_id IS NULL) OR
        (issue_type = 'flag' AND parent_id IS NULL)
    ),
    CHECK(issue_type = 'plan' OR tier IS NULL),
    CHECK(is_ready_to_work IN (0, 1)),
    CHECK(issue_type = 'plan' OR is_ready_to_work = 0),
    CHECK(status != 'ready' OR issue_type = 'task'),
    CHECK(status != 'snoozed' OR issue_type = 'task'),
    CHECK((status = 'snoozed') = (snooze IS NOT NULL)),
    CHECK((issue_type = 'flag') = (flag IS NOT NULL)),
    CHECK(
        issue_type = 'plan' OR
        (changespec_name = '' AND changespec_bug_id = '')
    ),
    CHECK(changespec_name != '' OR changespec_bug_id = ''),
    CHECK(task_type IS NULL OR issue_type = 'task')
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
CREATE INDEX IF NOT EXISTS idx_issues_tier ON issues(tier);
CREATE INDEX IF NOT EXISTS idx_issues_parent ON issues(parent_id);
CREATE INDEX IF NOT EXISTS idx_issues_task_type ON issues(task_type);
CREATE UNIQUE INDEX IF NOT EXISTS idx_issues_external_ref
    ON issues(external_ref)
    WHERE external_ref IS NOT NULL AND external_ref != ''
      AND issue_type != 'flag';
CREATE INDEX IF NOT EXISTS idx_deps_depends_on ON dependencies(depends_on_id);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    """Open the mirror database with the pragmas every caller expects."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn

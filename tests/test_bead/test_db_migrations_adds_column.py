"""Column-addition migrations for the SQLite bead database.

Split from ``tests.test_bead.test_db_migrations``; the original module
re-exports these tests so its import path keeps working.
"""

import sqlite3

import pytest

from sase.bead._db_schema import SCHEMA_SQL
from sase.bead.db import get_issue, init_db
from sase.bead.model import Resolution

from .db_test_helpers import NOW

__all__ = ["TestMigrationAddsColumn"]

_RESOLUTION_COLUMN_DEFINITION = """\
    resolution  TEXT
                  CHECK(resolution IN ('done', 'canceled', 'superseded')),
"""
_REFS_COLUMN_DEFINITION = "    refs        TEXT NOT NULL DEFAULT '',\n"
_EXTERNAL_REF_COLUMN_DEFINITION = "    external_ref TEXT,\n"
_EXTERNAL_REF_INDEX_DEFINITION = """\
CREATE UNIQUE INDEX IF NOT EXISTS idx_issues_external_ref
    ON issues(external_ref)
    WHERE external_ref IS NOT NULL AND external_ref != '';
"""
_TASK_TYPE_COLUMN_DEFINITION = "    task_type   TEXT,\n"
_TASK_TYPE_FIELDS_COLUMN_DEFINITION = (
    "    task_type_fields TEXT NOT NULL DEFAULT '{}',\n"
)
_TASK_TYPE_INDEX_DEFINITION = (
    "CREATE INDEX IF NOT EXISTS idx_issues_task_type ON issues(task_type);\n"
)


def _flag_era_schema() -> str:
    """Return the current schema rebuilt as the historical flag-issue-type shape."""
    return (
        SCHEMA_SQL.replace(
            "CHECK(issue_type IN ('plan', 'phase', 'task'))",
            "CHECK(issue_type IN ('plan', 'phase', 'task', 'flag'))",
        )
        .replace(
            "    snooze      TEXT,\n    model",
            "    snooze      TEXT,\n    flag        TEXT,\n    model",
        )
        .replace(
            "        (issue_type = 'task' AND parent_id IS NULL)\n    )",
            "        (issue_type = 'task' AND parent_id IS NULL) OR\n"
            "        (issue_type = 'flag' AND parent_id IS NULL)\n    )",
        )
        .replace(
            "    CHECK((status = 'snoozed') = (snooze IS NOT NULL)),\n    CHECK(",
            "    CHECK((status = 'snoozed') = (snooze IS NOT NULL)),\n"
            "    CHECK((issue_type = 'flag') = (flag IS NOT NULL)),\n    CHECK(",
        )
        .replace(
            "WHERE external_ref IS NOT NULL AND external_ref != '';",
            "WHERE external_ref IS NOT NULL AND external_ref != ''\n"
            "      AND issue_type != 'flag';",
        )
    )


class TestMigrationAddsColumn:
    def test_pre_refs_db_gets_empty_reference_list(self, tmp_path) -> None:
        db_path = tmp_path / "old_refs.db"
        old = sqlite3.connect(str(db_path))
        schema_without_refs = SCHEMA_SQL.replace(_REFS_COLUMN_DEFINITION, "")
        assert schema_without_refs != SCHEMA_SQL
        old.executescript(schema_without_refs)
        old.execute(
            "INSERT INTO issues "
            "(id, title, status, issue_type, tier, created_at, updated_at) "
            "VALUES ('e-old', 'Old', 'open', 'plan', 'epic', ?, ?)",
            (NOW, NOW),
        )
        old.commit()
        old.close()

        conn = init_db(db_path)
        try:
            issue = get_issue(conn, "e-old")
            assert issue is not None
            assert issue.refs == []
        finally:
            conn.close()

    def test_pre_resolution_db_gets_nullable_constrained_column(self, tmp_path) -> None:
        db_path = tmp_path / "old_resolution.db"
        old = sqlite3.connect(str(db_path))
        schema_without_resolution = SCHEMA_SQL.replace(
            _RESOLUTION_COLUMN_DEFINITION, ""
        )
        assert schema_without_resolution != SCHEMA_SQL
        old.executescript(schema_without_resolution)
        old.execute(
            "INSERT INTO issues "
            "(id, title, status, issue_type, tier, created_at, updated_at) "
            "VALUES ('e-old', 'Old', 'closed', 'plan', 'epic', ?, ?)",
            (NOW, NOW),
        )
        old.commit()
        old.close()

        conn = init_db(db_path)
        try:
            issue = get_issue(conn, "e-old")
            assert issue is not None
            assert issue.resolution is None
            conn.execute("UPDATE issues SET resolution='canceled' WHERE id='e-old'")
            updated = get_issue(conn, "e-old")
            assert updated is not None
            assert updated.resolution is Resolution.CANCELED
            conn.commit()
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "UPDATE issues SET resolution='abandoned' WHERE id='e-old'"
                )
        finally:
            conn.close()

    def test_pre_column_db_gets_migrated(self, tmp_path) -> None:
        """A database created without is_ready_to_work gains the column."""
        db_path = tmp_path / "old.db"
        old = sqlite3.connect(str(db_path))
        old.execute(
            "CREATE TABLE issues ("
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
        old.execute(
            "INSERT INTO issues (id, title, issue_type, created_at, updated_at) "
            "VALUES ('e-old', 'Old', 'plan', ?, ?)",
            (NOW, NOW),
        )
        old.commit()
        old.close()

        # init_db should add the column without losing data.
        conn = init_db(db_path)
        try:
            issue = get_issue(conn, "e-old")
            assert issue is not None
            assert issue.is_ready_to_work is False
        finally:
            conn.close()

    def test_pre_patch_db_gets_migrated(self, tmp_path) -> None:
        """A database created without Patch columns gains them."""
        db_path = tmp_path / "old_patch.db"
        old = sqlite3.connect(str(db_path))
        old.execute(
            "CREATE TABLE issues ("
            "  id TEXT PRIMARY KEY, title TEXT NOT NULL,"
            "  status TEXT NOT NULL DEFAULT 'open'"
            "    CHECK(status IN ('open','in_progress','closed')),"
            "  issue_type TEXT NOT NULL DEFAULT 'phase'"
            "    CHECK(issue_type IN ('plan','phase')),"
            "  parent_id TEXT, owner TEXT, assignee TEXT,"
            "  created_at TEXT NOT NULL, created_by TEXT,"
            "  updated_at TEXT NOT NULL, closed_at TEXT,"
            "  close_reason TEXT, description TEXT, notes TEXT, design TEXT,"
            "  is_ready_to_work INTEGER NOT NULL DEFAULT 0,"
            "  CHECK((issue_type='phase' AND parent_id IS NOT NULL)"
            "    OR (issue_type='plan'))"
            ")"
        )
        old.execute(
            "INSERT INTO issues (id, title, issue_type, created_at, updated_at) "
            "VALUES ('e-old', 'Old', 'plan', ?, ?)",
            (NOW, NOW),
        )
        old.commit()
        old.close()

        conn = init_db(db_path)
        try:
            issue = get_issue(conn, "e-old")
            assert issue is not None
            assert issue.changespec_name == ""
            assert issue.changespec_bug_id == ""
        finally:
            conn.close()

    def test_pre_external_ref_db_gets_nullable_indexed_column(self, tmp_path) -> None:
        db_path = tmp_path / "old_external_ref.db"
        old = sqlite3.connect(str(db_path))
        schema_without_external_ref = SCHEMA_SQL.replace(
            _EXTERNAL_REF_COLUMN_DEFINITION, ""
        ).replace(_EXTERNAL_REF_INDEX_DEFINITION, "")
        assert schema_without_external_ref != SCHEMA_SQL
        old.executescript(schema_without_external_ref)
        old.execute(
            "INSERT INTO issues "
            "(id, title, status, issue_type, tier, created_at, updated_at) "
            "VALUES ('e-old', 'Old', 'open', 'plan', 'epic', ?, ?)",
            (NOW, NOW),
        )
        old.commit()
        old.close()

        conn = init_db(db_path)
        try:
            issue = get_issue(conn, "e-old")
            assert issue is not None
            assert issue.external_ref == ""
            indexes = {
                row["name"]
                for row in conn.execute("PRAGMA index_list(issues)").fetchall()
            }
            assert "idx_issues_external_ref" in indexes
            conn.execute(
                "UPDATE issues SET external_ref='bug:sase#42' WHERE id='e-old'"
            )
            conn.commit()
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO issues "
                    "(id, title, status, issue_type, tier, created_at, updated_at, "
                    " external_ref) "
                    "VALUES ('e-dupe', 'Dupe', 'open', 'plan', 'epic', ?, ?, ?)",
                    (NOW, NOW, "bug:sase#42"),
                )
            conn.commit()
        finally:
            conn.close()

    def test_pre_task_type_db_gets_migrated(self, tmp_path) -> None:
        db_path = tmp_path / "old_task_type.db"
        old = sqlite3.connect(str(db_path))
        schema_without = (
            SCHEMA_SQL.replace(_TASK_TYPE_COLUMN_DEFINITION, "")
            .replace(_TASK_TYPE_FIELDS_COLUMN_DEFINITION, "")
            .replace(_TASK_TYPE_INDEX_DEFINITION, "")
            .replace(",\n    CHECK(task_type IS NULL OR issue_type = 'task')", "")
        )
        assert schema_without != SCHEMA_SQL
        old.executescript(schema_without)
        old.execute(
            "INSERT INTO issues "
            "(id, title, status, issue_type, created_at, updated_at) "
            "VALUES ('t-old', 'Old', 'open', 'task', ?, ?)",
            (NOW, NOW),
        )
        old.commit()
        old.close()

        conn = init_db(db_path)
        try:
            issue = get_issue(conn, "t-old")
            assert issue is not None
            assert issue.task_type == ""
            assert issue.task_type_fields == {}
            indexes = {
                row["name"]
                for row in conn.execute("PRAGMA index_list(issues)").fetchall()
            }
            assert "idx_issues_task_type" in indexes
        finally:
            conn.close()

    def test_drop_flag_type_removes_flag_rows_and_universalizes_external_ref(
        self, tmp_path
    ) -> None:
        db_path = tmp_path / "flag_era.db"
        old = sqlite3.connect(str(db_path))
        old.executescript(_flag_era_schema())
        old.execute(
            "INSERT INTO issues "
            "(id, title, status, issue_type, tier, created_at, updated_at, "
            " external_ref) "
            "VALUES ('e-old', 'Old', 'open', 'plan', 'epic', ?, ?, ?)",
            (NOW, NOW, "bug:sase#42"),
        )
        old.execute(
            "INSERT INTO issues "
            "(id, title, status, issue_type, created_at, updated_at, "
            " flag, external_ref) "
            "VALUES ('e-flag', 'Flag', 'open', 'flag', ?, ?, ?, ?)",
            (
                NOW,
                NOW,
                (
                    '{"key":"demo_key","remove_by_date":"2026-12-01",'
                    '"remove_by_release":"0.19.0"}'
                ),
                "bug:sase#42",
            ),
        )
        old.commit()
        old.close()

        conn = init_db(db_path)
        try:
            assert get_issue(conn, "e-flag") is None
            remaining = get_issue(conn, "e-old")
            assert remaining is not None
            assert remaining.external_ref == "bug:sase#42"
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO issues "
                    "(id, title, status, issue_type, created_at, updated_at) "
                    "VALUES ('e-flag', 'Flag', 'open', 'flag', ?, ?)",
                    (NOW, NOW),
                )
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO issues "
                    "(id, title, status, issue_type, created_at, updated_at, "
                    " task_type, external_ref) "
                    "VALUES ('e-task', 'Task', 'open', 'task', ?, ?, 'bug', ?)",
                    (NOW, NOW, "bug:sase#42"),
                )
        finally:
            conn.close()

    def test_pre_model_db_gets_migrated(self, tmp_path) -> None:
        """A database created without the model column gains it as ''."""
        db_path = tmp_path / "old_model.db"
        old = sqlite3.connect(str(db_path))
        old.execute(
            "CREATE TABLE issues ("
            "  id TEXT PRIMARY KEY, title TEXT NOT NULL,"
            "  status TEXT NOT NULL DEFAULT 'open'"
            "    CHECK(status IN ('open','in_progress','closed')),"
            "  issue_type TEXT NOT NULL DEFAULT 'phase'"
            "    CHECK(issue_type IN ('plan','phase')),"
            "  tier TEXT CHECK(tier IN ('plan','epic')),"
            "  parent_id TEXT, owner TEXT, assignee TEXT,"
            "  created_at TEXT NOT NULL, created_by TEXT,"
            "  updated_at TEXT NOT NULL, closed_at TEXT,"
            "  close_reason TEXT, description TEXT, notes TEXT, design TEXT,"
            "  is_ready_to_work INTEGER NOT NULL DEFAULT 0,"
            "  changespec_name TEXT NOT NULL DEFAULT '',"
            "  changespec_bug_id TEXT NOT NULL DEFAULT '',"
            "  CHECK((issue_type='phase' AND parent_id IS NOT NULL)"
            "    OR (issue_type='plan'))"
            ")"
        )
        old.execute(
            "INSERT INTO issues "
            "(id, title, issue_type, tier, created_at, updated_at) "
            "VALUES ('e-old', 'Old', 'plan', 'epic', ?, ?)",
            (NOW, NOW),
        )
        old.commit()
        old.close()

        conn = init_db(db_path)
        try:
            issue = get_issue(conn, "e-old")
            assert issue is not None
            assert issue.model == ""
        finally:
            conn.close()

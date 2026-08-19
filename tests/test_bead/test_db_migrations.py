"""Tests for SQLite database schema migrations."""

import sqlite3

import pytest

from sase.bead._db_schema import SCHEMA_SQL
from sase.bead.db import (
    add_dependency,
    create_issue,
    get_issue,
    init_db,
    list_issues,
)
from sase.bead.model import Issue, IssueType, PhaseSize, Resolution, Status

from .db_test_helpers import NOW, child, epic

_SIZE_COLUMN_DEFINITION = """\
    size        TEXT
                  CHECK(
                    size IS NULL OR
                    (issue_type IN ('phase', 'task') AND
                     size IN ('xsmall', 'small', 'medium', 'large', 'xlarge'))
                  ),
"""
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


def _assert_columns_survive_rebuild(
    conn: sqlite3.Connection, expected_columns: list[str]
) -> None:
    """Assert a table rebuild kept every pre-existing column.

    Earlier rebuild migrations copy an explicit column list that predates
    close_history, so they drop that column and ``_migrate_add_close_history``
    re-appends it. The snoozed-status rebuild copies close_history. Task-type
    columns are added after those rebuilds, so they may move to the end.
    """
    migrated_columns = [
        row["name"] for row in conn.execute("PRAGMA table_info(issues)")
    ]
    added = {"task_type", "task_type_fields"}
    assert [name for name in migrated_columns if name not in added] == [
        name for name in expected_columns if name not in added
    ]
    assert added.issubset(migrated_columns)


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


class TestSizeConstraintMigration:
    def test_pre_size_db_adds_column_without_rebuilding_table(self, tmp_path) -> None:
        db_path = tmp_path / "old_without_size.db"
        old = sqlite3.connect(str(db_path))
        schema_without_size = SCHEMA_SQL.replace(_SIZE_COLUMN_DEFINITION, "")
        assert schema_without_size != SCHEMA_SQL
        old.executescript(schema_without_size)
        old.execute(
            "INSERT INTO issues "
            "(id, title, issue_type, tier, created_at, updated_at) "
            "VALUES ('e-old', 'Old', 'plan', 'epic', ?, ?)",
            (NOW, NOW),
        )
        rootpage_before = old.execute(
            "SELECT rootpage FROM sqlite_master WHERE type='table' AND name='issues'"
        ).fetchone()[0]
        old.commit()
        old.close()

        conn = init_db(db_path)
        try:
            rootpage_after = conn.execute(
                "SELECT rootpage FROM sqlite_master "
                "WHERE type='table' AND name='issues'"
            ).fetchone()["rootpage"]
            assert rootpage_after == rootpage_before

            for issue_id, size in [
                ("c-xsmall", PhaseSize.XSMALL),
                ("c-xlarge", PhaseSize.XLARGE),
            ]:
                new_child = child(issue_id, "e-old")
                new_child.size = size
                create_issue(conn, new_child)
                loaded_child = get_issue(conn, issue_id)
                assert loaded_child is not None
                assert loaded_child.size is size
        finally:
            conn.close()

    def test_legacy_three_size_db_is_relaxed_and_idempotent(self, tmp_path) -> None:
        db_path = tmp_path / "legacy_three_sizes.db"
        legacy_schema = SCHEMA_SQL.replace(
            "('xsmall', 'small', 'medium', 'large', 'xlarge')",
            "('small', 'medium', 'large')",
        )
        assert legacy_schema != SCHEMA_SQL

        old = sqlite3.connect(str(db_path))
        old.executescript(legacy_schema)
        plan = epic("e-legacy", "Legacy plan")
        plan.description = "preserved description"
        phase = child("c-medium", "e-legacy", "Legacy phase")
        phase.notes = "preserved notes"
        phase.size = PhaseSize.MEDIUM
        create_issue(old, plan)
        create_issue(old, phase)
        add_dependency(old, phase.id, plan.id, NOW, "legacy-user")
        expected_columns = [
            row[1] for row in old.execute("PRAGMA table_info(issues)").fetchall()
        ]
        expected_indexes = {
            row[0]
            for row in old.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
            ).fetchall()
        }
        old.close()

        conn = init_db(db_path)
        try:
            loaded_plan = get_issue(conn, plan.id)
            assert loaded_plan is not None
            assert loaded_plan.description == "preserved description"
            loaded_phase = get_issue(conn, phase.id)
            assert loaded_phase is not None
            assert loaded_phase.notes == "preserved notes"
            assert loaded_phase.size is PhaseSize.MEDIUM
            assert [
                dependency.depends_on_id for dependency in loaded_phase.dependencies
            ] == [plan.id]

            _assert_columns_survive_rebuild(conn, expected_columns)
            assert {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='index' AND sql IS NOT NULL"
                )
            } == expected_indexes
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

            for issue_id, size in [
                ("c-xsmall", PhaseSize.XSMALL),
                ("c-xlarge", PhaseSize.XLARGE),
            ]:
                new_child = child(issue_id, plan.id)
                new_child.size = size
                create_issue(conn, new_child)

            schema_before_reopen = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='issues'"
            ).fetchone()["sql"]
            rootpage_before_reopen = conn.execute(
                "SELECT rootpage FROM sqlite_master "
                "WHERE type='table' AND name='issues'"
            ).fetchone()["rootpage"]
        finally:
            conn.close()

        reopened = init_db(db_path)
        try:
            schema_after_reopen = reopened.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='issues'"
            ).fetchone()["sql"]
            rootpage_after_reopen = reopened.execute(
                "SELECT rootpage FROM sqlite_master "
                "WHERE type='table' AND name='issues'"
            ).fetchone()["rootpage"]
            assert schema_after_reopen == schema_before_reopen
            assert rootpage_after_reopen == rootpage_before_reopen
            assert {
                issue.size for issue in list_issues(reopened) if issue.size is not None
            } == {
                PhaseSize.XSMALL,
                PhaseSize.MEDIUM,
                PhaseSize.XLARGE,
            }
            assert reopened.execute("PRAGMA foreign_key_check").fetchall() == []
        finally:
            reopened.close()


class TestStatusConstraintMigration:
    def test_pre_task_ready_db_is_migrated_and_idempotent(self, tmp_path) -> None:
        db_path = tmp_path / "legacy_three_statuses.db"
        legacy_schema = (
            SCHEMA_SQL.replace(
                "('open', 'claimed', 'ready', 'in_progress', 'closed')",
                "('open', 'in_progress', 'closed')",
            )
            .replace("('plan', 'phase', 'task')", "('plan', 'phase')")
            .replace("('phase', 'task')", "('phase')")
            .replace(
                " OR\n        (issue_type = 'task' AND parent_id IS NULL)",
                "",
            )
            .replace(
                "    CHECK(issue_type = 'plan' OR is_ready_to_work = 0),\n",
                "",
            )
            .replace(
                "    CHECK(status != 'ready' OR issue_type = 'task'),\n",
                "",
            )
        )
        assert legacy_schema != SCHEMA_SQL

        old = sqlite3.connect(str(db_path))
        old.executescript(legacy_schema)
        plan = epic("e-legacy", "Legacy plan")
        plan.description = "preserved description"
        phase = child("c-running", plan.id, "Running phase")
        phase.status = Status.IN_PROGRESS
        phase.notes = "preserved notes"
        create_issue(old, plan)
        create_issue(old, phase)
        add_dependency(old, phase.id, plan.id, NOW, "legacy-user")
        expected_columns = [
            row[1] for row in old.execute("PRAGMA table_info(issues)").fetchall()
        ]
        expected_indexes = {
            row[0]
            for row in old.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
            ).fetchall()
        }
        old.close()

        conn = init_db(db_path)
        try:
            loaded_plan = get_issue(conn, plan.id)
            assert loaded_plan is not None
            assert loaded_plan.description == "preserved description"
            loaded_phase = get_issue(conn, phase.id)
            assert loaded_phase is not None
            assert loaded_phase.status is Status.IN_PROGRESS
            assert loaded_phase.notes == "preserved notes"
            assert [
                dependency.depends_on_id for dependency in loaded_phase.dependencies
            ] == [plan.id]

            _assert_columns_survive_rebuild(conn, expected_columns)
            assert {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='index' AND sql IS NOT NULL"
                )
            } == expected_indexes
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

            claimed = child("c-claimed", plan.id, "Claimed phase")
            claimed.status = Status.CLAIMED
            create_issue(conn, claimed)
            assert get_issue(conn, claimed.id).status is Status.CLAIMED

            task = Issue(
                id="task-ready",
                title="Ready task",
                status=Status.READY,
                issue_type=IssueType.TASK,
                created_at=NOW,
                updated_at=NOW,
            )
            create_issue(conn, task)
            assert get_issue(conn, task.id).status is Status.READY

            schema_before_reopen = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='issues'"
            ).fetchone()["sql"]
            rootpage_before_reopen = conn.execute(
                "SELECT rootpage FROM sqlite_master "
                "WHERE type='table' AND name='issues'"
            ).fetchone()["rootpage"]
        finally:
            conn.close()

        reopened = init_db(db_path)
        try:
            schema_after_reopen = reopened.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='issues'"
            ).fetchone()["sql"]
            rootpage_after_reopen = reopened.execute(
                "SELECT rootpage FROM sqlite_master "
                "WHERE type='table' AND name='issues'"
            ).fetchone()["rootpage"]
            assert schema_after_reopen == schema_before_reopen
            assert rootpage_after_reopen == rootpage_before_reopen
            assert get_issue(reopened, "c-claimed").status is Status.CLAIMED
            assert reopened.execute("PRAGMA foreign_key_check").fetchall() == []
        finally:
            reopened.close()

    def test_current_db_schema_is_unchanged_on_reopen(self, tmp_path) -> None:
        db_path = tmp_path / "current.db"
        conn = init_db(db_path)
        create_issue(conn, epic())
        schema_before = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='issues'"
        ).fetchone()["sql"]
        rootpage_before = conn.execute(
            "SELECT rootpage FROM sqlite_master WHERE type='table' AND name='issues'"
        ).fetchone()["rootpage"]
        conn.close()

        reopened = init_db(db_path)
        try:
            schema_after = reopened.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='issues'"
            ).fetchone()["sql"]
            rootpage_after = reopened.execute(
                "SELECT rootpage FROM sqlite_master "
                "WHERE type='table' AND name='issues'"
            ).fetchone()["rootpage"]
            assert schema_after == schema_before
            assert rootpage_after == rootpage_before
            assert get_issue(reopened, "e-1") is not None
        finally:
            reopened.close()

"""Table-rebuild migrations for the SQLite bead database.

Split from ``tests.test_bead.test_db_migrations``; the original module
re-exports these tests so its import path keeps working.
"""

import sqlite3

import pytest

from sase.bead import db as bead_db
from sase.bead._db_schema import SCHEMA_SQL
from sase.bead.db import (
    add_dependency,
    create_issue,
    get_issue,
    init_db,
    list_issues,
)
from sase.bead.model import BeadNote, Issue, IssueType, PhaseSize, Status

from .db_test_helpers import NOW, child, epic

__all__ = [
    "TestIssueTypeRebuildRestartability",
    "TestSizeConstraintMigration",
    "TestStatusConstraintMigration",
]

_SIZE_COLUMN_DEFINITION = """\
    size        TEXT
                  CHECK(
                    size IS NULL OR
                    (issue_type IN ('phase', 'task') AND
                     size IN ('xsmall', 'small', 'medium', 'large', 'xlarge'))
                  ),
"""


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
        phase.notes = [
            BeadNote(
                id="note-1",
                timestamp="2026-01-01T00:00:00Z",
                author="legacy-user",
                text="preserved notes",
            )
        ]
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
            assert (
                loaded_phase.notes_text
                == "[2026-01-01T00:00:00Z · legacy-user] preserved notes"
            )
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
        phase.notes = [
            BeadNote(
                id="note-1",
                timestamp="2026-01-01T00:00:00Z",
                author="legacy-user",
                text="preserved notes",
            )
        ]
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
            assert (
                loaded_phase.notes_text
                == "[2026-01-01T00:00:00Z · legacy-user] preserved notes"
            )
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


class TestIssueTypeRebuildRestartability:
    def test_leftover_issues_new_does_not_wedge_init_db(self, tmp_path) -> None:
        db_path = tmp_path / "half_migrated.db"
        old = sqlite3.connect(str(db_path))
        old.execute(
            "CREATE TABLE issues ("
            "  id TEXT PRIMARY KEY, title TEXT NOT NULL,"
            "  status TEXT NOT NULL DEFAULT 'open'"
            "    CHECK(status IN ('open','in_progress','closed')),"
            "  issue_type TEXT NOT NULL DEFAULT 'child'"
            "    CHECK(issue_type IN ('epic','child')),"
            "  parent_id TEXT, owner TEXT, assignee TEXT,"
            "  created_at TEXT NOT NULL, created_by TEXT,"
            "  updated_at TEXT NOT NULL, closed_at TEXT,"
            "  close_reason TEXT, description TEXT, notes TEXT, design TEXT"
            ")"
        )
        old.execute(
            "INSERT INTO issues (id, title, issue_type, created_at, updated_at) "
            "VALUES ('e-old', 'Old', 'epic', ?, ?)",
            (NOW, NOW),
        )
        old.execute(
            "INSERT INTO issues "
            "(id, title, issue_type, parent_id, created_at, updated_at) "
            "VALUES ('c-old', 'Child', 'child', 'e-old', ?, ?)",
            (NOW, NOW),
        )
        old.execute("CREATE TABLE _issues_new (id TEXT PRIMARY KEY, title TEXT)")
        old.commit()
        old.close()

        conn = init_db(db_path)
        try:
            plan = get_issue(conn, "e-old")
            phase = get_issue(conn, "c-old")
            assert plan is not None
            assert plan.issue_type is IssueType.PLAN
            assert phase is not None
            assert phase.issue_type is IssueType.PHASE
            leftover = conn.execute(
                "SELECT name FROM sqlite_master WHERE name = '_issues_new'"
            ).fetchone()
            assert leftover is None
        finally:
            conn.close()

    def test_init_db_closes_connection_when_migration_raises(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db_path = tmp_path / "fail.db"
        opened: list[sqlite3.Connection] = []
        real_connect = bead_db.connect

        def tracking_connect(path):
            conn = real_connect(path)
            opened.append(conn)
            return conn

        def boom(_conn: sqlite3.Connection) -> None:
            raise RuntimeError("migration boom")

        monkeypatch.setattr(bead_db, "connect", tracking_connect)
        monkeypatch.setattr(bead_db, "run_migrations", boom)

        with pytest.raises(RuntimeError, match="migration boom"):
            init_db(db_path)

        assert opened
        for conn in opened:
            with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                conn.execute("SELECT 1")

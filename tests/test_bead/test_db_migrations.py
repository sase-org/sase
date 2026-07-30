"""Tests for SQLite database schema migrations."""

import sqlite3

import pytest

from sase.bead.db import (
    _SCHEMA,
    add_dependency,
    create_issue,
    get_issue,
    init_db,
    list_issues,
)
from sase.bead.model import PhaseSize, Resolution, Status

from .db_test_helpers import NOW, child, epic

_SIZE_COLUMN_DEFINITION = """\
    size        TEXT
                  CHECK(size IN ('xsmall', 'small', 'medium', 'large', 'xlarge')),
"""
_PHASE_SIZE_TABLE_CHECK = "    CHECK(issue_type = 'phase' OR size IS NULL),\n"
_RESOLUTION_COLUMN_DEFINITION = """\
    resolution  TEXT
                  CHECK(resolution IN ('done', 'canceled', 'superseded')),
"""
_REFS_COLUMN_DEFINITION = "    refs        TEXT NOT NULL DEFAULT '',\n"


class TestMigrationAddsColumn:
    def test_pre_refs_db_gets_empty_reference_list(self, tmp_path) -> None:
        db_path = tmp_path / "old_refs.db"
        old = sqlite3.connect(str(db_path))
        schema_without_refs = _SCHEMA.replace(_REFS_COLUMN_DEFINITION, "")
        assert schema_without_refs != _SCHEMA
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
        schema_without_resolution = _SCHEMA.replace(_RESOLUTION_COLUMN_DEFINITION, "")
        assert schema_without_resolution != _SCHEMA
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

    def test_pre_changespec_db_gets_migrated(self, tmp_path) -> None:
        """A database created without ChangeSpec columns gains them."""
        db_path = tmp_path / "old_changespec.db"
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
        schema_without_size = _SCHEMA.replace(_SIZE_COLUMN_DEFINITION, "").replace(
            _PHASE_SIZE_TABLE_CHECK, ""
        )
        assert schema_without_size != _SCHEMA
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
        legacy_schema = _SCHEMA.replace(
            "('xsmall', 'small', 'medium', 'large', 'xlarge')",
            "('small', 'medium', 'large')",
        )
        assert legacy_schema != _SCHEMA

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

            assert [
                row["name"] for row in conn.execute("PRAGMA table_info(issues)")
            ] == expected_columns
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
    def test_legacy_three_status_db_is_relaxed_and_idempotent(self, tmp_path) -> None:
        db_path = tmp_path / "legacy_three_statuses.db"
        legacy_schema = _SCHEMA.replace(
            "('open', 'claimed', 'in_progress', 'closed')",
            "('open', 'in_progress', 'closed')",
        )
        assert legacy_schema != _SCHEMA

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

            assert [
                row["name"] for row in conn.execute("PRAGMA table_info(issues)")
            ] == expected_columns
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

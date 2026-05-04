"""Tests for the SQLite database layer."""

import sqlite3

import pytest

from sase.bead.db import (
    add_dependency,
    blocked_issues,
    close_issue,
    create_issue,
    delete_issue,
    get_dependencies,
    get_epic_children,
    get_issue,
    init_db,
    list_issues,
    mark_issue_ready_to_work,
    ready_issues,
    stats,
    update_issue,
)
from sase.bead.model import BeadTier, Issue, IssueType, Status

NOW = "2026-03-17T00:00:00Z"


@pytest.fixture
def conn(tmp_path: object):
    from pathlib import Path

    assert isinstance(tmp_path, Path)
    connection = init_db(tmp_path / "test.db")
    yield connection
    connection.close()


def _epic(id: str = "e-1", title: str = "Epic") -> Issue:
    return Issue(
        id=id,
        title=title,
        issue_type=IssueType.PLAN,
        parent_id=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _child(id: str = "c-1", parent_id: str = "e-1", title: str = "Child") -> Issue:
    return Issue(
        id=id,
        title=title,
        issue_type=IssueType.PHASE,
        parent_id=parent_id,
        created_at=NOW,
        updated_at=NOW,
    )


class TestCreateAndGet:
    def test_create_epic(self, conn: sqlite3.Connection) -> None:
        epic = _epic()
        result = create_issue(conn, epic)
        assert result.id == "e-1"
        assert result.issue_type == IssueType.PLAN

    def test_create_child(self, conn: sqlite3.Connection) -> None:
        create_issue(conn, _epic())
        child = _child()
        result = create_issue(conn, child)
        assert result.id == "c-1"
        assert result.parent_id == "e-1"

    def test_get_issue(self, conn: sqlite3.Connection) -> None:
        create_issue(conn, _epic())
        issue = get_issue(conn, "e-1")
        assert issue is not None
        assert issue.title == "Epic"

    def test_get_nonexistent_returns_none(self, conn: sqlite3.Connection) -> None:
        assert get_issue(conn, "no-such") is None

    def test_child_without_parent_fails_db_constraint(
        self, conn: sqlite3.Connection
    ) -> None:
        child = Issue(
            id="c-1",
            title="Orphan",
            issue_type=IssueType.PHASE,
            parent_id="nonexistent",
            created_at=NOW,
            updated_at=NOW,
        )
        with pytest.raises(sqlite3.IntegrityError):
            create_issue(conn, child)

    def test_plan_with_parent_succeeds(self, conn: sqlite3.Connection) -> None:
        """Plan with parent_id is valid (sub-plan)."""
        create_issue(conn, _epic())
        sub_plan = Issue(
            id="e-2",
            title="Sub-plan",
            issue_type=IssueType.PLAN,
            parent_id="e-1",
            created_at=NOW,
            updated_at=NOW,
        )
        result = create_issue(conn, sub_plan)
        assert result.id == "e-2"
        assert result.parent_id == "e-1"

    def test_create_plan_with_changespec_metadata(
        self, conn: sqlite3.Connection
    ) -> None:
        create_issue(
            conn,
            Issue(
                id="e-1",
                title="Epic",
                issue_type=IssueType.PLAN,
                created_at=NOW,
                updated_at=NOW,
                changespec_name="feature_epic",
                changespec_bug_id="12345",
            ),
        )
        issue = get_issue(conn, "e-1")
        assert issue is not None
        assert issue.changespec_name == "feature_epic"
        assert issue.changespec_bug_id == "12345"

    def test_create_legend_with_epic_count(self, conn: sqlite3.Connection) -> None:
        create_issue(
            conn,
            Issue(
                id="l-1",
                title="Legend",
                issue_type=IssueType.PLAN,
                tier=BeadTier.LEGEND,
                created_at=NOW,
                updated_at=NOW,
                epic_count=4,
            ),
        )
        issue = get_issue(conn, "l-1")
        assert issue is not None
        assert issue.epic_count == 4

    def test_create_phase_with_changespec_metadata_fails(
        self, conn: sqlite3.Connection
    ) -> None:
        create_issue(conn, _epic())
        child = Issue(
            id="c-1",
            title="Child",
            issue_type=IssueType.PHASE,
            parent_id="e-1",
            created_at=NOW,
            updated_at=NOW,
            changespec_name="feature_epic",
        )
        with pytest.raises(ValueError, match="Phase issues cannot carry"):
            create_issue(conn, child)


class TestListIssues:
    def test_list_all(self, conn: sqlite3.Connection) -> None:
        create_issue(conn, _epic())
        create_issue(conn, _child())
        issues = list_issues(conn)
        assert len(issues) == 2

    def test_filter_by_status(self, conn: sqlite3.Connection) -> None:
        create_issue(conn, _epic())
        issues = list_issues(conn, statuses=[Status.OPEN])
        assert len(issues) == 1
        assert list_issues(conn, statuses=[Status.CLOSED]) == []

    def test_filter_by_type(self, conn: sqlite3.Connection) -> None:
        create_issue(conn, _epic())
        create_issue(conn, _child())
        epics = list_issues(conn, issue_types=[IssueType.PLAN])
        assert len(epics) == 1
        assert epics[0].id == "e-1"


class TestUpdateIssue:
    def test_update_title(self, conn: sqlite3.Connection) -> None:
        create_issue(conn, _epic())
        updated = update_issue(conn, "e-1", title="New Title", updated_at=NOW)
        assert updated is not None
        assert updated.title == "New Title"

    def test_update_status(self, conn: sqlite3.Connection) -> None:
        create_issue(conn, _epic())
        updated = update_issue(conn, "e-1", status="in_progress", updated_at=NOW)
        assert updated is not None
        assert updated.status == Status.IN_PROGRESS

    def test_update_nonexistent_returns_none(self, conn: sqlite3.Connection) -> None:
        assert update_issue(conn, "no-such", title="X") is None

    def test_update_changespec_metadata(self, conn: sqlite3.Connection) -> None:
        create_issue(conn, _epic())
        updated = update_issue(
            conn,
            "e-1",
            changespec_name="feature_epic",
            changespec_bug_id="12345",
            updated_at=NOW,
        )
        assert updated is not None
        assert updated.changespec_name == "feature_epic"
        assert updated.changespec_bug_id == "12345"

    def test_update_epic_count(self, conn: sqlite3.Connection) -> None:
        create_issue(
            conn,
            Issue(
                id="l-1",
                title="Legend",
                issue_type=IssueType.PLAN,
                tier=BeadTier.LEGEND,
                created_at=NOW,
                updated_at=NOW,
                epic_count=2,
            ),
        )
        updated = update_issue(conn, "l-1", epic_count=5, updated_at=NOW)
        assert updated is not None
        assert updated.epic_count == 5


class TestCloseIssue:
    def test_close_issue(self, conn: sqlite3.Connection) -> None:
        create_issue(conn, _epic())
        closed = close_issue(conn, "e-1", closed_at=NOW, reason="Done")
        assert closed is not None
        assert closed.status == Status.CLOSED
        assert closed.closed_at == NOW
        assert closed.close_reason == "Done"


class TestReadyAndBlocked:
    def test_ready_no_deps(self, conn: sqlite3.Connection) -> None:
        create_issue(conn, _epic())
        ready = ready_issues(conn)
        assert len(ready) == 1

    def test_blocked_by_open_dep(self, conn: sqlite3.Connection) -> None:
        create_issue(conn, _epic("e-1", "Epic 1"))
        create_issue(conn, _epic("e-2", "Epic 2"))
        add_dependency(conn, "e-2", "e-1", NOW)
        ready = ready_issues(conn)
        assert len(ready) == 1
        assert ready[0].id == "e-1"
        blocked = blocked_issues(conn)
        assert len(blocked) == 1
        assert blocked[0].id == "e-2"

    def test_unblocked_after_close(self, conn: sqlite3.Connection) -> None:
        create_issue(conn, _epic("e-1", "Epic 1"))
        create_issue(conn, _epic("e-2", "Epic 2"))
        add_dependency(conn, "e-2", "e-1", NOW)
        close_issue(conn, "e-1", closed_at=NOW)
        ready = ready_issues(conn)
        assert any(i.id == "e-2" for i in ready)
        assert blocked_issues(conn) == []

    def test_in_progress_not_ready(self, conn: sqlite3.Connection) -> None:
        """in_progress issues should NOT appear in ready list."""
        create_issue(conn, _epic())
        update_issue(conn, "e-1", status="in_progress")
        ready = ready_issues(conn)
        assert len(ready) == 0


class TestDependencies:
    def test_add_and_get(self, conn: sqlite3.Connection) -> None:
        create_issue(conn, _epic("e-1"))
        create_issue(conn, _epic("e-2"))
        add_dependency(conn, "e-2", "e-1", NOW, "user")
        deps = get_dependencies(conn, "e-2")
        assert len(deps) == 1
        assert deps[0].depends_on_id == "e-1"

    def test_duplicate_dependency_fails(self, conn: sqlite3.Connection) -> None:
        create_issue(conn, _epic("e-1"))
        create_issue(conn, _epic("e-2"))
        add_dependency(conn, "e-2", "e-1", NOW)
        with pytest.raises(sqlite3.IntegrityError):
            add_dependency(conn, "e-2", "e-1", NOW)


class TestEpicChildren:
    def test_get_children(self, conn: sqlite3.Connection) -> None:
        create_issue(conn, _epic())
        create_issue(conn, _child("c-1"))
        create_issue(conn, _child("c-2"))
        children = get_epic_children(conn, "e-1")
        assert len(children) == 2

    def test_no_children(self, conn: sqlite3.Connection) -> None:
        create_issue(conn, _epic())
        assert get_epic_children(conn, "e-1") == []


class TestDeleteIssue:
    def test_delete_existing(self, conn: sqlite3.Connection) -> None:
        create_issue(conn, _epic())
        assert delete_issue(conn, "e-1") is True
        assert get_issue(conn, "e-1") is None

    def test_delete_nonexistent(self, conn: sqlite3.Connection) -> None:
        assert delete_issue(conn, "no-such") is False

    def test_delete_cascades_children(self, conn: sqlite3.Connection) -> None:
        create_issue(conn, _epic())
        create_issue(conn, _child("c-1"))
        create_issue(conn, _child("c-2"))
        delete_issue(conn, "e-1")
        assert get_issue(conn, "c-1") is None
        assert get_issue(conn, "c-2") is None

    def test_delete_cascades_dependencies(self, conn: sqlite3.Connection) -> None:
        create_issue(conn, _epic("e-1"))
        create_issue(conn, _epic("e-2"))
        add_dependency(conn, "e-2", "e-1", NOW)
        delete_issue(conn, "e-1")
        assert get_dependencies(conn, "e-2") == []


class TestIsReadyToWork:
    def test_default_is_false(self, conn: sqlite3.Connection) -> None:
        create_issue(conn, _epic())
        issue = get_issue(conn, "e-1")
        assert issue is not None
        assert issue.is_ready_to_work is False

    def test_mark_ready_to_work(self, conn: sqlite3.Connection) -> None:
        create_issue(conn, _epic())
        result = mark_issue_ready_to_work(conn, "e-1", NOW)
        assert result is not None
        assert result.is_ready_to_work is True

    def test_mark_ready_to_work_skips_phase(self, conn: sqlite3.Connection) -> None:
        create_issue(conn, _epic())
        create_issue(conn, _child("c-1"))
        result = mark_issue_ready_to_work(conn, "c-1", NOW)
        assert result is not None
        assert result.is_ready_to_work is False

    def test_jsonl_roundtrip(self, conn: sqlite3.Connection, tmp_path) -> None:
        from sase.bead.jsonl import export_to_jsonl, import_from_jsonl

        create_issue(conn, _epic())
        mark_issue_ready_to_work(conn, "e-1", NOW)
        path = tmp_path / "issues.jsonl"
        export_to_jsonl(conn, path)
        # Re-import into a fresh DB.
        conn2 = init_db(tmp_path / "second.db")
        try:
            import_from_jsonl(path, conn2)
            issue = get_issue(conn2, "e-1")
            assert issue is not None
            assert issue.is_ready_to_work is True
        finally:
            conn2.close()


class TestMigrationAddsColumn:
    def test_pre_column_db_gets_migrated(self, tmp_path) -> None:
        """A database created without is_ready_to_work gains the column."""
        import sqlite3 as sq

        db_path = tmp_path / "old.db"
        old = sq.connect(str(db_path))
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
        import sqlite3 as sq

        db_path = tmp_path / "old_changespec.db"
        old = sq.connect(str(db_path))
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


class TestUpdateIssueRejectsNothingDB:
    """The internal db.update_issue allows is_ready_to_work for round-tripping;
    user-facing rejection lives in BeadProject.update."""

    def test_db_update_can_set_is_ready_to_work(self, conn: sqlite3.Connection) -> None:
        create_issue(conn, _epic())
        updated = update_issue(conn, "e-1", is_ready_to_work=1, updated_at=NOW)
        assert updated is not None
        assert updated.is_ready_to_work is True


class TestStats:
    def test_stats(self, conn: sqlite3.Connection) -> None:
        create_issue(conn, _epic("e-1"))
        create_issue(conn, _child("c-1"))
        create_issue(conn, _child("c-2"))
        close_issue(conn, "c-2", NOW)
        s = stats(conn)
        assert s["total"] == 3
        assert s["open"] == 2
        assert s["closed"] == 1
        assert s["plan"] == 1
        assert s["phase"] == 2

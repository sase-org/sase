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
    ready_issues,
    stats,
    update_issue,
)
from sase.bead.model import Issue, IssueType, Status

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


class TestListIssues:
    def test_list_all(self, conn: sqlite3.Connection) -> None:
        create_issue(conn, _epic())
        create_issue(conn, _child())
        issues = list_issues(conn)
        assert len(issues) == 2

    def test_filter_by_status(self, conn: sqlite3.Connection) -> None:
        create_issue(conn, _epic())
        issues = list_issues(conn, status=Status.OPEN)
        assert len(issues) == 1
        assert list_issues(conn, status=Status.CLOSED) == []

    def test_filter_by_type(self, conn: sqlite3.Connection) -> None:
        create_issue(conn, _epic())
        create_issue(conn, _child())
        epics = list_issues(conn, issue_type=IssueType.PLAN)
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

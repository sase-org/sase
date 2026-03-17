"""Tests for JSONL import/export."""

import json
import sqlite3

import pytest

from sase.bead.db import (
    add_dependency,
    create_issue,
    get_issue,
    init_db,
    list_issues,
)
from sase.bead.jsonl import export_to_jsonl, import_from_jsonl
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
        issue_type=IssueType.EPIC,
        parent_id=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _child(id: str = "c-1", parent_id: str = "e-1", title: str = "Child") -> Issue:
    return Issue(
        id=id,
        title=title,
        issue_type=IssueType.CHILD,
        parent_id=parent_id,
        created_at=NOW,
        updated_at=NOW,
    )


class TestExport:
    def test_export_sorted_by_id(
        self, conn: sqlite3.Connection, tmp_path: object
    ) -> None:
        from pathlib import Path

        assert isinstance(tmp_path, Path)
        create_issue(conn, _epic("z-1"))
        create_issue(conn, _epic("a-1"))
        jsonl_path = tmp_path / "issues.jsonl"
        export_to_jsonl(conn, jsonl_path)
        lines = jsonl_path.read_text().strip().splitlines()
        assert len(lines) == 2
        ids = [json.loads(line)["id"] for line in lines]
        assert ids == ["a-1", "z-1"]

    def test_export_includes_dependencies(
        self, conn: sqlite3.Connection, tmp_path: object
    ) -> None:
        from pathlib import Path

        assert isinstance(tmp_path, Path)
        create_issue(conn, _epic("e-1"))
        create_issue(conn, _epic("e-2"))
        add_dependency(conn, "e-2", "e-1", NOW, "user")
        jsonl_path = tmp_path / "issues.jsonl"
        export_to_jsonl(conn, jsonl_path)
        lines = jsonl_path.read_text().strip().splitlines()
        e2_data = next(
            json.loads(line) for line in lines if json.loads(line)["id"] == "e-2"
        )
        assert len(e2_data["dependencies"]) == 1
        assert e2_data["dependencies"][0]["depends_on_id"] == "e-1"

    def test_export_empty_db(self, conn: sqlite3.Connection, tmp_path: object) -> None:
        from pathlib import Path

        assert isinstance(tmp_path, Path)
        jsonl_path = tmp_path / "issues.jsonl"
        export_to_jsonl(conn, jsonl_path)
        assert jsonl_path.read_text() == ""


class TestImport:
    def test_import_creates_issues(
        self, conn: sqlite3.Connection, tmp_path: object
    ) -> None:
        from pathlib import Path

        assert isinstance(tmp_path, Path)
        jsonl_path = tmp_path / "issues.jsonl"
        data = {
            "id": "e-1",
            "title": "Imported Epic",
            "status": "open",
            "issue_type": "epic",
            "parent_id": None,
            "owner": "",
            "assignee": "",
            "created_at": NOW,
            "created_by": "",
            "updated_at": NOW,
            "closed_at": None,
            "close_reason": None,
            "description": "",
            "notes": "",
            "design": "",
            "dependencies": [],
        }
        jsonl_path.write_text(json.dumps(data) + "\n")
        imported = import_from_jsonl(jsonl_path, conn)
        assert len(imported) == 1
        issue = get_issue(conn, "e-1")
        assert issue is not None
        assert issue.title == "Imported Epic"

    def test_import_missing_file(
        self, conn: sqlite3.Connection, tmp_path: object
    ) -> None:
        from pathlib import Path

        assert isinstance(tmp_path, Path)
        result = import_from_jsonl(tmp_path / "nonexistent.jsonl", conn)
        assert result == []

    def test_import_empty_file(
        self, conn: sqlite3.Connection, tmp_path: object
    ) -> None:
        from pathlib import Path

        assert isinstance(tmp_path, Path)
        jsonl_path = tmp_path / "empty.jsonl"
        jsonl_path.write_text("")
        result = import_from_jsonl(jsonl_path, conn)
        assert result == []

    def test_import_skips_corrupt_lines(
        self, conn: sqlite3.Connection, tmp_path: object
    ) -> None:
        from pathlib import Path

        assert isinstance(tmp_path, Path)
        jsonl_path = tmp_path / "issues.jsonl"
        good = {
            "id": "e-1",
            "title": "Good",
            "status": "open",
            "issue_type": "epic",
            "parent_id": None,
            "created_at": NOW,
            "updated_at": NOW,
            "dependencies": [],
        }
        jsonl_path.write_text(
            "NOT VALID JSON\n" + json.dumps(good) + "\n" + "{bad json\n"
        )
        imported = import_from_jsonl(jsonl_path, conn)
        assert len(imported) == 1
        assert imported[0].id == "e-1"


class TestRoundTrip:
    def test_export_import_roundtrip(
        self, conn: sqlite3.Connection, tmp_path: object
    ) -> None:
        from pathlib import Path

        assert isinstance(tmp_path, Path)
        # Create some issues
        create_issue(conn, _epic("e-1", "Epic One"))
        create_issue(conn, _child("c-1", "e-1", "Child One"))
        create_issue(conn, _child("c-2", "e-1", "Child Two"))
        add_dependency(conn, "c-2", "c-1", NOW, "user")

        # Export
        jsonl_path = tmp_path / "issues.jsonl"
        export_to_jsonl(conn, jsonl_path)

        # Import into fresh database
        conn2 = init_db(tmp_path / "test2.db")
        try:
            imported = import_from_jsonl(jsonl_path, conn2)
            assert len(imported) == 3

            # Verify data integrity
            original_issues = sorted(list_issues(conn), key=lambda i: i.id)
            imported_issues = sorted(list_issues(conn2), key=lambda i: i.id)
            assert len(original_issues) == len(imported_issues)
            for orig, imp in zip(original_issues, imported_issues, strict=True):
                assert orig.id == imp.id
                assert orig.title == imp.title
                assert orig.status == imp.status
                assert orig.issue_type == imp.issue_type
                assert orig.parent_id == imp.parent_id
        finally:
            conn2.close()

    def test_upsert_updates_existing(
        self, conn: sqlite3.Connection, tmp_path: object
    ) -> None:
        from pathlib import Path

        assert isinstance(tmp_path, Path)
        create_issue(conn, _epic("e-1", "Original"))
        jsonl_path = tmp_path / "issues.jsonl"
        data = {
            "id": "e-1",
            "title": "Updated",
            "status": "open",
            "issue_type": "epic",
            "parent_id": None,
            "created_at": NOW,
            "updated_at": NOW,
            "dependencies": [],
        }
        jsonl_path.write_text(json.dumps(data) + "\n")
        import_from_jsonl(jsonl_path, conn)
        issue = get_issue(conn, "e-1")
        assert issue is not None
        assert issue.title == "Updated"

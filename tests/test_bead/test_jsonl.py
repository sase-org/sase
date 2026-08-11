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
from sase.bead.model import Issue, IssueType

NOW = "2026-03-17T00:00:00Z"


class _CountingConnection(sqlite3.Connection):
    commit_count = 0

    def commit(self) -> None:
        self.commit_count += 1
        super().commit()


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

    def test_export_includes_patch_metadata(
        self, conn: sqlite3.Connection, tmp_path: object
    ) -> None:
        from pathlib import Path

        assert isinstance(tmp_path, Path)
        epic = _epic("e-1")
        epic.changespec_name = "feature_epic"
        epic.changespec_bug_id = "12345"
        create_issue(conn, epic)
        jsonl_path = tmp_path / "issues.jsonl"
        export_to_jsonl(conn, jsonl_path)
        data = json.loads(jsonl_path.read_text())
        assert data["changespec_name"] == "feature_epic"
        assert data["changespec_bug_id"] == "12345"

    def test_export_includes_external_ref_only_when_nonempty(
        self, conn: sqlite3.Connection, tmp_path: object
    ) -> None:
        from pathlib import Path

        assert isinstance(tmp_path, Path)
        with_ref = _epic("e-1")
        with_ref.external_ref = "bug:sase#42"
        create_issue(conn, with_ref)
        create_issue(conn, _epic("e-2"))
        jsonl_path = tmp_path / "issues.jsonl"
        export_to_jsonl(conn, jsonl_path)

        rows = {
            row["id"]: row
            for row in (
                json.loads(line) for line in jsonl_path.read_text().splitlines()
            )
        }
        assert rows["e-1"]["external_ref"] == "bug:sase#42"
        assert "external_ref" not in rows["e-2"]

    def test_export_includes_model(
        self, conn: sqlite3.Connection, tmp_path: object
    ) -> None:
        from pathlib import Path

        assert isinstance(tmp_path, Path)
        epic = _epic("e-1")
        epic.model = "codex/gpt-5.5"
        create_issue(conn, epic)
        jsonl_path = tmp_path / "issues.jsonl"
        export_to_jsonl(conn, jsonl_path)
        data = json.loads(jsonl_path.read_text())
        assert data["model"] == "codex/gpt-5.5"

    def test_export_default_model_empty(
        self, conn: sqlite3.Connection, tmp_path: object
    ) -> None:
        from pathlib import Path

        assert isinstance(tmp_path, Path)
        create_issue(conn, _epic("e-1"))
        jsonl_path = tmp_path / "issues.jsonl"
        export_to_jsonl(conn, jsonl_path)
        data = json.loads(jsonl_path.read_text())
        assert data["model"] == ""

    def test_export_refs_only_when_nonempty(
        self, conn: sqlite3.Connection, tmp_path: object
    ) -> None:
        from pathlib import Path

        assert isinstance(tmp_path, Path)
        without_refs = _epic("e-1")
        with_refs = _epic("e-2")
        with_refs.refs = ["research:202607/report.md", "bead:sase-bb.1"]
        create_issue(conn, without_refs)
        create_issue(conn, with_refs)
        jsonl_path = tmp_path / "issues.jsonl"

        export_to_jsonl(conn, jsonl_path)

        rows = {
            row["id"]: row
            for row in (
                json.loads(line) for line in jsonl_path.read_text().splitlines()
            )
        }
        assert "refs" not in rows["e-1"]
        assert rows["e-2"]["refs"] == with_refs.refs

    def test_export_empty_db(self, conn: sqlite3.Connection, tmp_path: object) -> None:
        from pathlib import Path

        assert isinstance(tmp_path, Path)
        jsonl_path = tmp_path / "issues.jsonl"
        export_to_jsonl(conn, jsonl_path)
        assert jsonl_path.read_text() == ""


class TestImport:
    def test_import_uses_one_transaction_and_skips_invalid_dependency(
        self, tmp_path: object
    ) -> None:
        from pathlib import Path

        assert isinstance(tmp_path, Path)
        db_path = tmp_path / "batched.db"
        schema_conn = init_db(db_path)
        schema_conn.close()
        conn = sqlite3.connect(str(db_path), factory=_CountingConnection)
        assert isinstance(conn, _CountingConnection)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        jsonl_path = tmp_path / "issues.jsonl"
        first = {
            "id": "e-1",
            "title": "First",
            "status": "open",
            "issue_type": "plan",
            "parent_id": None,
            "created_at": NOW,
            "updated_at": NOW,
            "dependencies": [],
        }
        second = {
            "id": "e-2",
            "title": "Second",
            "status": "open",
            "issue_type": "plan",
            "parent_id": None,
            "created_at": NOW,
            "updated_at": NOW,
            "dependencies": [
                {
                    "issue_id": "e-2",
                    "depends_on_id": "e-1",
                    "created_at": NOW,
                },
                {
                    "issue_id": "e-2",
                    "depends_on_id": "missing",
                    "created_at": NOW,
                },
            ],
        }
        jsonl_path.write_text(
            "\n".join(json.dumps(issue) for issue in (first, second)) + "\n"
        )

        try:
            imported = import_from_jsonl(jsonl_path, conn)

            assert conn.commit_count == 1
            assert [issue.id for issue in imported] == ["e-1", "e-2"]
            stored = get_issue(conn, "e-2")
            assert stored is not None
            assert [dep.depends_on_id for dep in stored.dependencies] == ["e-1"]
        finally:
            conn.close()

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
            "issue_type": "plan",
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

    def test_import_refs_and_tolerates_missing_field(
        self, conn: sqlite3.Connection, tmp_path: object
    ) -> None:
        from pathlib import Path

        assert isinstance(tmp_path, Path)
        jsonl_path = tmp_path / "issues.jsonl"
        with_refs = {
            "id": "e-1",
            "title": "With refs",
            "status": "open",
            "issue_type": "plan",
            "created_at": NOW,
            "updated_at": NOW,
            "refs": ["research:202607/report.md", "bead:sase-bb.1"],
        }
        without_refs = {
            "id": "e-2",
            "title": "Without refs",
            "status": "open",
            "issue_type": "plan",
            "created_at": NOW,
            "updated_at": NOW,
        }
        jsonl_path.write_text(
            "\n".join(json.dumps(row) for row in (with_refs, without_refs)) + "\n"
        )

        import_from_jsonl(jsonl_path, conn)

        first = get_issue(conn, "e-1")
        second = get_issue(conn, "e-2")
        assert first is not None and first.refs == with_refs["refs"]
        assert second is not None and second.refs == []

    def test_import_patch_metadata(
        self, conn: sqlite3.Connection, tmp_path: object
    ) -> None:
        from pathlib import Path

        assert isinstance(tmp_path, Path)
        jsonl_path = tmp_path / "issues.jsonl"
        data = {
            "id": "e-1",
            "title": "Imported Epic",
            "status": "open",
            "issue_type": "plan",
            "parent_id": None,
            "created_at": NOW,
            "updated_at": NOW,
            "changespec_name": "feature_epic",
            "changespec_bug_id": "12345",
            "dependencies": [],
        }
        jsonl_path.write_text(json.dumps(data) + "\n")
        import_from_jsonl(jsonl_path, conn)
        issue = get_issue(conn, "e-1")
        assert issue is not None
        assert issue.changespec_name == "feature_epic"
        assert issue.changespec_bug_id == "12345"

    def test_import_external_ref_and_missing_field_defaults_empty(
        self, conn: sqlite3.Connection, tmp_path: object
    ) -> None:
        from pathlib import Path

        assert isinstance(tmp_path, Path)
        jsonl_path = tmp_path / "issues.jsonl"
        with_ref = {
            "id": "e-1",
            "title": "Imported Epic",
            "status": "open",
            "issue_type": "plan",
            "created_at": NOW,
            "updated_at": NOW,
            "external_ref": "bug:sase#42",
        }
        without_ref = {
            "id": "e-2",
            "title": "Other Epic",
            "status": "open",
            "issue_type": "plan",
            "created_at": NOW,
            "updated_at": NOW,
        }
        jsonl_path.write_text(
            "\n".join(json.dumps(row) for row in (with_ref, without_ref)) + "\n"
        )

        import_from_jsonl(jsonl_path, conn)

        first = get_issue(conn, "e-1")
        second = get_issue(conn, "e-2")
        assert first is not None
        assert first.external_ref == "bug:sase#42"
        assert second is not None
        assert second.external_ref == ""

    def test_import_patch_metadata_aliases(
        self, conn: sqlite3.Connection, tmp_path: object
    ) -> None:
        from pathlib import Path

        assert isinstance(tmp_path, Path)
        jsonl_path = tmp_path / "issues.jsonl"
        data = {
            "id": "e-1",
            "title": "Imported Epic",
            "status": "open",
            "issue_type": "plan",
            "parent_id": None,
            "created_at": NOW,
            "updated_at": NOW,
            "patch_name": "feature_epic",
            "patch_bug_id": "12345",
            "dependencies": [],
        }
        jsonl_path.write_text(json.dumps(data) + "\n")
        import_from_jsonl(jsonl_path, conn)
        issue = get_issue(conn, "e-1")
        assert issue is not None
        assert issue.patch_name == "feature_epic"
        assert issue.patch_bug_id == "12345"

    def test_import_missing_patch_metadata_defaults_empty(
        self, conn: sqlite3.Connection, tmp_path: object
    ) -> None:
        from pathlib import Path

        assert isinstance(tmp_path, Path)
        jsonl_path = tmp_path / "issues.jsonl"
        data = {
            "id": "e-1",
            "title": "Imported Epic",
            "status": "open",
            "issue_type": "plan",
            "parent_id": None,
            "created_at": NOW,
            "updated_at": NOW,
            "dependencies": [],
        }
        jsonl_path.write_text(json.dumps(data) + "\n")
        import_from_jsonl(jsonl_path, conn)
        issue = get_issue(conn, "e-1")
        assert issue is not None
        assert issue.changespec_name == ""
        assert issue.changespec_bug_id == ""

    def test_import_model(self, conn: sqlite3.Connection, tmp_path: object) -> None:
        from pathlib import Path

        assert isinstance(tmp_path, Path)
        jsonl_path = tmp_path / "issues.jsonl"
        data = {
            "id": "e-1",
            "title": "Imported Epic",
            "status": "open",
            "issue_type": "plan",
            "parent_id": None,
            "created_at": NOW,
            "updated_at": NOW,
            "model": "codex/gpt-5.5",
            "dependencies": [],
        }
        jsonl_path.write_text(json.dumps(data) + "\n")
        import_from_jsonl(jsonl_path, conn)
        issue = get_issue(conn, "e-1")
        assert issue is not None
        assert issue.model == "codex/gpt-5.5"

    def test_import_missing_model_defaults_empty(
        self, conn: sqlite3.Connection, tmp_path: object
    ) -> None:
        from pathlib import Path

        assert isinstance(tmp_path, Path)
        jsonl_path = tmp_path / "issues.jsonl"
        data = {
            "id": "e-1",
            "title": "Imported Epic",
            "status": "open",
            "issue_type": "plan",
            "parent_id": None,
            "created_at": NOW,
            "updated_at": NOW,
            "dependencies": [],
        }
        jsonl_path.write_text(json.dumps(data) + "\n")
        import_from_jsonl(jsonl_path, conn)
        issue = get_issue(conn, "e-1")
        assert issue is not None
        assert issue.model == ""

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
            "issue_type": "plan",
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

    def test_export_import_roundtrip_patch_metadata(
        self, conn: sqlite3.Connection, tmp_path: object
    ) -> None:
        from pathlib import Path

        assert isinstance(tmp_path, Path)
        epic = _epic("e-1", "Epic One")
        epic.changespec_name = "feature_epic"
        epic.changespec_bug_id = "12345"
        create_issue(conn, epic)

        jsonl_path = tmp_path / "issues.jsonl"
        export_to_jsonl(conn, jsonl_path)

        conn2 = init_db(tmp_path / "test_patch_roundtrip.db")
        try:
            import_from_jsonl(jsonl_path, conn2)
            imported = get_issue(conn2, "e-1")
            assert imported is not None
            assert imported.changespec_name == "feature_epic"
            assert imported.changespec_bug_id == "12345"
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
            "issue_type": "plan",
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

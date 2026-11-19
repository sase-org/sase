"""Legacy-store and explicit-export coverage (no SQLite mirror)."""

from __future__ import annotations

import json
import sqlite3
import unittest.mock as _mock
from pathlib import Path

from sase.bead.model import IssueType
from sase.bead.project import BeadProject


def test_legacy_jsonl_store_reads_and_exports_without_sqlite(tmp_path: Path) -> None:
    beads_dir = tmp_path / "beads"
    beads_dir.mkdir()
    (beads_dir / "config.json").write_text(
        json.dumps(
            {"issue_prefix": "legacy", "next_counter": 2, "owner": ""},
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    (beads_dir / "issues.jsonl").write_text(
        json.dumps(
            {
                "id": "legacy-1",
                "title": "Legacy",
                "status": "open",
                "issue_type": "plan",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
                "dependencies": [],
            },
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )

    opened: list[str] = []
    real_connect = sqlite3.connect

    def _guarded_connect(*args: object, **kwargs: object) -> object:
        target = str(args[0]) if args else str(kwargs.get("database", ""))
        if target.endswith("beads.db"):
            opened.append(target)
            raise AssertionError("Python must not open beads.db via stdlib sqlite3")
        return real_connect(*args, **kwargs)  # type: ignore[arg-type]

    with _mock.patch("sqlite3.connect", side_effect=_guarded_connect):
        with BeadProject(tmp_path, beads_dirname="beads") as project:
            assert project.show("legacy-1").title == "Legacy"
            assert [issue.id for issue in project.list_issues()] == ["legacy-1"]
            project._export()
            assert opened == []

    assert "legacy-1" in (beads_dir / "issues.jsonl").read_text(encoding="utf-8")


def test_explicit_export_succeeds_without_python_database(tmp_path: Path) -> None:
    with BeadProject.init(tmp_path) as project:
        issue = project.create("Exported", IssueType.PLAN)

    beads_dir = tmp_path / "sdd" / "beads"
    (beads_dir / "issues.jsonl").write_text("", encoding="utf-8")

    opened: list[str] = []
    real_connect = sqlite3.connect

    def _guarded_connect(*args: object, **kwargs: object) -> object:
        target = str(args[0]) if args else str(kwargs.get("database", ""))
        if target.endswith("beads.db"):
            opened.append(target)
            raise AssertionError("Python must not open beads.db via stdlib sqlite3")
        return real_connect(*args, **kwargs)  # type: ignore[arg-type]

    with _mock.patch("sqlite3.connect", side_effect=_guarded_connect):
        with BeadProject(tmp_path) as project:
            project._export()
            assert opened == []
            assert issue.id in (beads_dir / "issues.jsonl").read_text(encoding="utf-8")

"""Tests for rebuild_from_jsonl in sase.bead.sync."""

from __future__ import annotations

import time

from sase.bead.db import create_issue, get_issue, init_db
from sase.bead.jsonl import export_to_jsonl
from sase.bead.model import Issue, IssueType
from sase.bead.sync import rebuild_from_jsonl


def test_rebuild_from_jsonl_creates_db(tmp_path):
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    db_path = beads_dir / "beads.db"
    jsonl_path = beads_dir / "issues.jsonl"

    # Create a database with an issue, export to JSONL
    conn = init_db(db_path)
    create_issue(
        conn,
        Issue(
            id="test-1",
            title="Test",
            issue_type=IssueType.PLAN,
            created_at="2024-01-01",
            updated_at="2024-01-01",
        ),
    )
    export_to_jsonl(conn, jsonl_path)
    conn.close()

    # Delete the db
    db_path.unlink()
    assert not db_path.exists()

    # Rebuild from JSONL
    result = rebuild_from_jsonl(beads_dir)
    assert result is True
    assert db_path.exists()

    # Verify the issue was restored
    conn = init_db(db_path)
    issue = get_issue(conn, "test-1")
    conn.close()
    assert issue is not None
    assert issue.title == "Test"


def test_rebuild_from_jsonl_noop_when_db_newer(tmp_path):
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    jsonl_path = beads_dir / "issues.jsonl"
    db_path = beads_dir / "beads.db"

    jsonl_path.write_text("")
    time.sleep(0.01)  # sase-test-wait: orders db newer than jsonl
    db_path.write_text("")

    result = rebuild_from_jsonl(beads_dir)
    assert result is False

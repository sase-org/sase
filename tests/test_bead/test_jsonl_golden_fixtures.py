"""Golden JSONL/config fixtures for future bead backend parity tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from sase.bead.config import load_config
from sase.bead.db import get_issue, init_db
from sase.bead.jsonl import import_from_jsonl

GOLDEN = Path(__file__).parent / "golden"
JSONL = GOLDEN / "jsonl"


def _import_fixture(tmp_path: Path, fixture_name: str) -> sqlite3.Connection:
    conn = init_db(tmp_path / f"{fixture_name}.db")
    import_from_jsonl(JSONL / fixture_name, conn)
    return conn


def test_current_schema_fixture_imports_hierarchy_dependencies_and_metadata(
    tmp_path: Path,
) -> None:
    conn = _import_fixture(tmp_path, "current_schema.jsonl")
    try:
        parent = get_issue(conn, "gold-1")
        child = get_issue(conn, "gold-1.1")
    finally:
        conn.close()

    assert parent is not None
    assert parent.is_ready_to_work is True
    assert parent.changespec_name == "current_changespec"
    assert parent.changespec_bug_id == "BUG-100"
    assert child is not None
    assert child.parent_id == "gold-1"
    assert [dep.depends_on_id for dep in child.dependencies] == ["gold-1"]


def test_pre_is_ready_to_work_schema_defaults_flag_false(tmp_path: Path) -> None:
    conn = _import_fixture(tmp_path, "pre_is_ready_to_work_schema.jsonl")
    try:
        issue = get_issue(conn, "legacy-ready-1")
    finally:
        conn.close()

    assert issue is not None
    assert issue.is_ready_to_work is False


def test_pre_changespec_metadata_schema_defaults_metadata_empty(tmp_path: Path) -> None:
    conn = _import_fixture(tmp_path, "pre_changespec_metadata_schema.jsonl")
    try:
        issue = get_issue(conn, "legacy-meta-1")
    finally:
        conn.close()

    assert issue is not None
    assert issue.changespec_name == ""
    assert issue.changespec_bug_id == ""


def test_corrupt_jsonl_fixture_skips_bad_lines(tmp_path: Path) -> None:
    conn = _import_fixture(tmp_path, "corrupt_lines.jsonl")
    try:
        assert get_issue(conn, "corrupt-1") is not None
    finally:
        conn.close()


def test_empty_and_missing_jsonl_fixtures_import_as_empty(tmp_path: Path) -> None:
    conn = init_db(tmp_path / "empty.db")
    try:
        assert import_from_jsonl(JSONL / "empty.jsonl", conn) == []
        assert import_from_jsonl(JSONL / "missing.jsonl", conn) == []
    finally:
        conn.close()


def test_current_config_fixture_loads(tmp_path: Path) -> None:
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    (beads_dir / "config.json").write_text(
        (GOLDEN / "config" / "current.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    assert load_config(beads_dir) == {
        "issue_prefix": "gold",
        "next_counter": 42,
        "owner": "owner@example.com",
    }

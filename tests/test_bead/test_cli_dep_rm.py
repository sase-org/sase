"""CLI coverage for removing bead dependency edges."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
from unittest.mock import patch

import pytest

from sase.bead import cli as bead_cli
from sase.bead.jsonl import import_from_jsonl
from sase.bead.model import BeadTier, IssueType
from sase.bead.project import BeadProject
from sase.bead.sync import rebuild_from_jsonl
from sase.main.parser import create_parser


def _dependency_fixture(
    project_dir: Path,
) -> tuple[str, str, str]:
    with BeadProject(project_dir) as project:
        epic = project.create(
            "Epic",
            IssueType.PLAN,
            tier=BeadTier.EPIC,
        )
        source = project.create(
            "Source",
            IssueType.PHASE,
            parent_id=epic.id,
        )
        first = project.create(
            "First blocker",
            IssueType.PHASE,
            parent_id=epic.id,
        )
        second = project.create(
            "Second blocker",
            IssueType.PHASE,
            parent_id=epic.id,
        )
        project.add_dependency(source.id, first.id)
        project.add_dependency(source.id, second.id)
    return source.id, first.id, second.id


def _rm_args(issue_id: str, *depends_on_ids: str) -> argparse.Namespace:
    return argparse.Namespace(
        dep_action="rm",
        issue=issue_id,
        depends_on=list(depends_on_ids),
    )


def test_dep_rm_removes_edge_reports_readiness_and_records_history(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_id, first_id, second_id = _dependency_fixture(project_dir)

    bead_cli.handle_bead_dep(_rm_args(source_id, first_id, second_id))

    output = capsys.readouterr().out
    assert (
        f"✗ Removed dependency: {source_id} no longer depends on {first_id}" in output
    )
    assert (
        f"✗ Removed dependency: {source_id} no longer depends on {second_id}" in output
    )
    assert f"○ {source_id} has no active blockers." in output
    with BeadProject(project_dir) as project:
        assert project.show(source_id).dependencies == []
        history = project.history(source_id)
    removal_entries = [
        entry
        for entry in history["entries"]
        if entry["operation"] == "dependency_removed"
    ]
    assert len(removal_entries) == 2
    assert all(
        any(change["field"] == "dependencies" for change in entry["changes"])
        for entry in removal_entries
    )


def test_dep_rm_reports_the_remaining_active_blocker(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_id, first_id, second_id = _dependency_fixture(project_dir)

    bead_cli.handle_bead_dep(_rm_args(source_id, first_id))

    assert (
        f"○ {source_id} still has 1 active blocker: {second_id}."
        in capsys.readouterr().out
    )


def test_dep_rm_errors_are_nonzero_and_leave_the_batch_untouched(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_id, first_id, second_id = _dependency_fixture(project_dir)

    with pytest.raises(SystemExit, match="1"):
        bead_cli.handle_bead_dep(_rm_args(source_id, first_id, "missing-edge"))

    assert "Error: issue not found: missing-edge" in capsys.readouterr().err
    with BeadProject(project_dir) as project:
        assert [
            dependency.depends_on_id
            for dependency in project.show(source_id).dependencies
        ] == [first_id, second_id]

    with pytest.raises(SystemExit, match="1"):
        bead_cli.handle_bead_dep(_rm_args("missing-source", first_id))
    assert "Error: issue not found: missing-source" in capsys.readouterr().err


def test_dep_rm_auto_commit_message(
    project_dir: Path,
) -> None:
    source_id, first_id, second_id = _dependency_fixture(project_dir)

    with patch("sase.bead.cli_dep.auto_commit_bead_store") as auto_commit:
        bead_cli.handle_bead_dep(_rm_args(source_id, first_id, second_id, first_id))

    auto_commit.assert_called_once_with(
        f"chore(beads): unlink {source_id} -> {first_id} {second_id}",
        push_after_commit=False,
        already_locked=False,
    )


def test_dep_rm_parser_accepts_multiple_targets() -> None:
    parser = create_parser()

    args = parser.parse_args(["bead", "dep", "rm", "source", "first", "second"])

    assert args.dep_action == "rm"
    assert args.issue == "source"
    assert args.depends_on == ["first", "second"]


def test_mirror_rebuild_and_fallback_export_do_not_resurrect_removed_edge(
    project_dir: Path,
) -> None:
    source_id, first_id, _second_id = _dependency_fixture(project_dir)
    beads_dir = project_dir / "sdd/beads"
    with BeadProject(project_dir) as project:
        import_from_jsonl(beads_dir / "issues.jsonl", project._conn)
        import_from_jsonl(beads_dir / "issues.jsonl", project._conn)
        assert (
            project._conn.execute(
                "SELECT 1 FROM dependencies WHERE issue_id = ? AND depends_on_id = ?",
                (source_id, first_id),
            ).fetchone()
            is not None
        )
        project.remove_dependencies(source_id, [first_id])
        db_mtime_ns = (beads_dir / "beads.db").stat().st_mtime_ns
        os.utime(
            beads_dir / "issues.jsonl",
            ns=(
                db_mtime_ns + 1_000_000_000,
                db_mtime_ns + 1_000_000_000,
            ),
        )
        assert rebuild_from_jsonl(beads_dir)

        row = project._conn.execute(
            "SELECT 1 FROM dependencies WHERE issue_id = ? AND depends_on_id = ?",
            (source_id, first_id),
        ).fetchone()
        assert row is None

        with patch(
            "sase.core.bead_mutation_facade.export_jsonl",
            side_effect=ValueError("force compatibility fallback"),
        ):
            project._export()

    records = [
        json.loads(line)
        for line in (beads_dir / "issues.jsonl").read_text().splitlines()
    ]
    source = next(record for record in records if record["id"] == source_id)
    assert all(
        dependency["depends_on_id"] != first_id for dependency in source["dependencies"]
    )
    with sqlite3.connect(beads_dir / "beads.db") as connection:
        assert (
            connection.execute(
                "SELECT 1 FROM dependencies WHERE issue_id = ? AND depends_on_id = ?",
                (source_id, first_id),
            ).fetchone()
            is None
        )

"""CLI coverage for required bead creation reasons."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead.cli_crud_create import normalize_creation_reason
from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from sase.main.parser import create_parser


REASON = "A second agent reproduced dropped retries after the queue change"


def _task_argv(reason: str) -> list[str]:
    return [
        "bead",
        "create",
        "--title",
        "Fix retry race",
        "--type",
        "task(bug)",
        "--size",
        "medium",
        "--reason",
        reason,
        "--field",
        "location=src/retry.py",
        "--field",
        "repro=fails on retry",
    ]


def test_create_missing_reason_exits_before_mutation(
    project_dir: Path,
) -> None:
    jsonl_path = project_dir / "sdd" / "beads" / "issues.jsonl"
    before = jsonl_path.read_bytes() if jsonl_path.exists() else b""
    with pytest.raises(SystemExit) as exc_info:
        create_parser().parse_args(
            [
                "bead",
                "create",
                "--title",
                "Fix retry race",
                "--type",
                "task(bug)",
                "--size",
                "medium",
                "--field",
                "location=src/retry.py",
                "--field",
                "repro=fails on retry",
            ]
        )
    assert exc_info.value.code == 2
    if jsonl_path.exists():
        assert jsonl_path.read_bytes() == before


def test_create_rejects_blank_reason(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = create_parser().parse_args(_task_argv("   "))
    with pytest.raises(SystemExit) as exc_info:
        bead_cli.handle_bead_create(args)
    assert exc_info.value.code == 1
    assert "cannot be empty or blank" in capsys.readouterr().err
    with BeadProject(project_dir) as project:
        assert project.list_issues(issue_types=[IssueType.TASK]) == []


def test_create_rejects_too_long_reason(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = create_parser().parse_args(_task_argv("r" * 2001))
    with pytest.raises(SystemExit) as exc_info:
        bead_cli.handle_bead_create(args)
    assert exc_info.value.code == 1
    assert "at most 2000 characters" in capsys.readouterr().err
    with BeadProject(project_dir) as project:
        assert project.list_issues(issue_types=[IssueType.TASK]) == []


def test_create_reason_reads_at_path(
    project_dir: Path,
    tmp_path: Path,
) -> None:
    reason_file = tmp_path / "reason.md"
    reason_file.write_text("Filed from triage with notes\n", encoding="utf-8")
    bead_cli.handle_bead_create(
        create_parser().parse_args(_task_argv(f"@{reason_file}"))
    )
    with BeadProject(project_dir) as project:
        task = project.list_issues(issue_types=[IssueType.TASK])[0]
    assert task.creation_reason == "Filed from triage with notes"


def test_create_valid_reason_persists_and_reads_back(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bead_cli.handle_bead_create(create_parser().parse_args(_task_argv(REASON)))
    capsys.readouterr()
    with BeadProject(project_dir) as project:
        task = project.list_issues(issue_types=[IssueType.TASK])[0]
        assert task.creation_reason == REASON
        assert task.description == ""
        assert project.show(task.id).creation_reason == REASON


def test_normalize_creation_reason_matches_core_semantics() -> None:
    assert normalize_creation_reason("  why  ") == "why"
    with pytest.raises(ValueError, match="requires -w/--reason"):
        normalize_creation_reason(None)
    with pytest.raises(ValueError, match="cannot be empty or blank"):
        normalize_creation_reason("   ")
    with pytest.raises(ValueError, match="at most 2000 characters"):
        normalize_creation_reason("y" * 2001)

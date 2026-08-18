"""CLI coverage for ``@<path>`` on bead free-text values."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from sase.main.bead_fast_path import try_handle_bead_fast_path
from sase.main.entry import main as sase_main
from sase.main.parser import create_parser


def _issues_jsonl(project_dir: Path) -> Path:
    return project_dir / "sdd" / "beads" / "issues.jsonl"


def _flake_create_argv(*extra: str) -> list[str]:
    return [
        "bead",
        "create",
        "--title",
        "Visual flake",
        "--type",
        "task(flake)",
        "--size",
        "medium",
        "--field",
        "node_id=tests/foo.py::test_bar",
        "--field",
        "evidence=failed then passed",
        *extra,
    ]


def test_create_description_reads_at_path(
    project_dir: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    desc = tmp_path / "description-clean.md"
    contents = "full flake diagnosis\nwith a trailing newline\n"
    desc.write_text(contents, encoding="utf-8")
    at_token = f"@{desc}"

    bead_cli.handle_bead_create(
        create_parser().parse_args(_flake_create_argv("--description", at_token))
    )

    with BeadProject(project_dir) as project:
        task = project.list_issues(issue_types=[IssueType.TASK])[0]
    assert task.description == contents
    assert task.description != at_token

    capsys.readouterr()
    bead_cli.handle_bead_show(create_parser().parse_args(["bead", "show", task.id]))
    output = capsys.readouterr().out
    assert "full flake diagnosis" in output
    assert at_token not in output


def test_create_missing_description_file_creates_no_bead(
    project_dir: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / "gone.md"
    jsonl_path = _issues_jsonl(project_dir)
    before = jsonl_path.read_bytes()

    with pytest.raises(SystemExit) as exc_info:
        bead_cli.handle_bead_create(
            create_parser().parse_args(
                _flake_create_argv("--description", f"@{missing}")
            )
        )

    assert exc_info.value.code == 1
    assert "file not found" in capsys.readouterr().err
    assert jsonl_path.read_bytes() == before
    with BeadProject(project_dir) as project:
        assert project.list_issues(issue_types=[IssueType.TASK]) == []


def test_entry_update_description_reads_at_path(
    project_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desc = tmp_path / "desc.md"
    desc.write_text("expanded through the public entry\n", encoding="utf-8")
    with BeadProject(project_dir) as project:
        issue = project.create(
            "Needs expansion", IssueType.TASK, task_type="bug", size="small"
        )
    monkeypatch.setattr(
        sys,
        "argv",
        ["sase", "bead", "update", issue.id, "-d", f"@{desc}"],
    )

    with pytest.raises(SystemExit) as exc_info:
        sase_main()

    assert exc_info.value.code == 0
    with BeadProject(project_dir) as project:
        assert (
            project.show(issue.id).description == "expanded through the public entry\n"
        )


def test_update_and_note_at_path_skip_rust_fast_path() -> None:
    assert (
        try_handle_bead_fast_path(["update", "sase-1", "-d", "@/tmp/desc.md"]) is None
    )
    assert (
        try_handle_bead_fast_path(["update", "sase-1", "--notes=@/tmp/notes.md"])
        is None
    )
    assert try_handle_bead_fast_path(["update", "sase-1", "-d", "@@literal"]) is None
    assert try_handle_bead_fast_path(["note", "sase-1", "@/tmp/note.md"]) is None


def test_create_double_at_description_stores_literal(
    project_dir: Path,
) -> None:
    bead_cli.handle_bead_create(
        create_parser().parse_args(_flake_create_argv("--description", "@@literal"))
    )

    with BeadProject(project_dir) as project:
        task = project.list_issues(issue_types=[IssueType.TASK])[0]
    assert task.description == "@literal"

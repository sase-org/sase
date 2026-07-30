"""CLI coverage for appending bead notes."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.bead import cli as bead_cli
from sase.bead.config import load_config, save_config
from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from sase.main.parser import create_parser


def _create_issue(project_dir: Path) -> str:
    with BeadProject(project_dir) as project:
        issue = project.create("Note target", IssueType.PLAN)
    return issue.id


def _run_note(
    argv: list[str],
    capsys: pytest.CaptureFixture[str],
) -> str:
    args = create_parser().parse_args(["bead", "note", *argv])
    bead_cli.handle_bead_note(args)
    return capsys.readouterr().out


def _run_history(
    argv: list[str],
    capsys: pytest.CaptureFixture[str],
) -> str:
    args = create_parser().parse_args(["bead", "history", *argv])
    bead_cli.handle_bead_history(args)
    return capsys.readouterr().out


def _set_store_owner(project_dir: Path, owner: str) -> None:
    beads_dir = project_dir / "sdd/beads"
    config = load_config(beads_dir)
    config["owner"] = owner
    save_config(beads_dir, config)


def test_note_parser_contract() -> None:
    args = create_parser().parse_args(
        ["bead", "note", "sase-1", "-a", "alice", "done", "with", "tests"]
    )

    assert args.id == "sase-1"
    assert args.author == "alice"
    assert args.text == ["done", "with", "tests"]


def test_note_appends_to_empty_notes_with_explicit_author(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue_id = _create_issue(project_dir)
    monkeypatch.setattr("sase.bead.project._now", lambda: "2026-01-01T00:01:00Z")

    output = _run_note([issue_id, "--author", "alice", "first note"], capsys)

    assert f"Noted: {issue_id}" in output
    with BeadProject(project_dir) as project:
        issue = project.show(issue_id)
    assert issue.notes == "[2026-01-01T00:01:00Z · alice] first note"


def test_note_appends_to_existing_notes_and_history_shows_revisions(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue_id = _create_issue(project_dir)
    monkeypatch.setattr("sase.bead.project._now", lambda: "2026-01-01T00:01:00Z")
    _run_note([issue_id, "--author", "alice", "first note"], capsys)
    monkeypatch.setattr("sase.bead.project._now", lambda: "2026-01-01T00:02:00Z")
    _run_note([issue_id, "--author", "alice", "second note"], capsys)

    with BeadProject(project_dir) as project:
        issue = project.show(issue_id)
    assert issue.notes == (
        "[2026-01-01T00:01:00Z · alice] first note\n\n"
        "[2026-01-01T00:02:00Z · alice] second note"
    )
    stream_path = project_dir / f"sdd/beads/events/streams/{issue_id}.jsonl"
    operations = [
        json.loads(line)["operation"]
        for line in stream_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert operations == ["issue_created", "note_appended", "note_appended"]

    history = _run_history([issue_id, "--field", "notes", "--format", "full"], capsys)
    assert "from: [2026-01-01T00:01:00Z · alice] first note" in history
    assert "[2026-01-01T00:02:00Z · alice] second note" in history


def test_note_rejects_blank_entry_without_writing_or_committing(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue_id = _create_issue(project_dir)

    with patch("sase.bead.cli_crud.auto_commit_bead_store") as auto_commit:
        with pytest.raises(SystemExit) as excinfo:
            _run_note([issue_id, "   "], capsys)

    assert excinfo.value.code == 1
    assert "note entry cannot be empty or blank" in capsys.readouterr().err
    auto_commit.assert_not_called()
    with BeadProject(project_dir) as project:
        assert project.show(issue_id).notes == ""


def test_note_defaults_author_from_agent_identity(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue_id = _create_issue(project_dir)
    monkeypatch.setenv("SASE_AGENT_NAME", "phase-agent")
    monkeypatch.setattr("sase.bead.project._now", lambda: "2026-01-01T00:01:00Z")

    _run_note([issue_id, "agent note"], capsys)

    with BeadProject(project_dir) as project:
        issue = project.show(issue_id)
    assert issue.notes == "[2026-01-01T00:01:00Z · phase-agent] agent note"


def test_note_defaults_author_from_store_owner_without_agent_identity(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue_id = _create_issue(project_dir)
    _set_store_owner(project_dir, "owner@example.com")
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
    monkeypatch.delenv("SASE_AGENT", raising=False)
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    monkeypatch.setattr("sase.bead.project._now", lambda: "2026-01-01T00:01:00Z")

    _run_note([issue_id, "owner note"], capsys)

    with BeadProject(project_dir) as project:
        issue = project.show(issue_id)
    assert issue.notes == "[2026-01-01T00:01:00Z · owner@example.com] owner note"


def test_handle_bead_note_auto_commit_message(project_dir: Path) -> None:
    issue_id = _create_issue(project_dir)

    with patch("sase.bead.cli_crud.auto_commit_bead_store") as auto_commit:
        bead_cli.handle_bead_note(
            create_parser().parse_args(
                ["bead", "note", issue_id, "--author", "alice", "done"]
            )
        )

    auto_commit.assert_called_once_with(
        f"chore(beads): note {issue_id}",
        push_after_commit=False,
        already_locked=False,
    )

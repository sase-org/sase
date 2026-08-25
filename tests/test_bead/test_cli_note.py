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
    assert args.edit is None
    assert args.remove is None


def test_note_parser_accepts_edit_and_remove_flags() -> None:
    edit_args = create_parser().parse_args(
        ["bead", "note", "sase-1", "-e", "2", "corrected"]
    )
    assert edit_args.edit == 2
    assert edit_args.text == ["corrected"]

    remove_args = create_parser().parse_args(["bead", "note", "sase-1", "-x", "1"])
    assert remove_args.remove == 1
    assert remove_args.text == []


def test_note_parser_rejects_edit_and_remove_together() -> None:
    with pytest.raises(SystemExit):
        create_parser().parse_args(
            ["bead", "note", "sase-1", "-e", "1", "-x", "2", "text"]
        )


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
    assert issue.notes_text == "[2026-01-01T00:01:00Z · alice] first note"


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
    assert issue.notes_text == (
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

    with patch("sase.bead.cli_crud_evidence.auto_commit_bead_store") as auto_commit:
        with pytest.raises(SystemExit) as excinfo:
            _run_note([issue_id, "   "], capsys)

    assert excinfo.value.code == 1
    assert "note entry cannot be empty or blank" in capsys.readouterr().err
    auto_commit.assert_not_called()
    with BeadProject(project_dir) as project:
        assert project.show(issue_id).notes_text == ""


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
    assert issue.notes_text == "[2026-01-01T00:01:00Z · phase-agent] agent note"


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
    assert issue.notes_text == "[2026-01-01T00:01:00Z · owner@example.com] owner note"


def test_note_single_token_at_path_expands(
    project_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue_id = _create_issue(project_dir)
    note_file = tmp_path / "note.md"
    note_file.write_text("from file", encoding="utf-8")
    monkeypatch.setattr("sase.bead.project._now", lambda: "2026-01-01T00:01:00Z")

    _run_note([issue_id, "--author", "alice", f"@{note_file}"], capsys)

    with BeadProject(project_dir) as project:
        issue = project.show(issue_id)
    assert issue.notes_text == "[2026-01-01T00:01:00Z · alice] from file"


def test_note_multi_token_text_still_joins_with_spaces(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue_id = _create_issue(project_dir)
    monkeypatch.setattr("sase.bead.project._now", lambda: "2026-01-01T00:01:00Z")

    _run_note([issue_id, "--author", "alice", "@not-a-file", "and", "more"], capsys)

    with BeadProject(project_dir) as project:
        issue = project.show(issue_id)
    assert issue.notes_text == "[2026-01-01T00:01:00Z · alice] @not-a-file and more"


def test_handle_bead_note_auto_commit_message(project_dir: Path) -> None:
    issue_id = _create_issue(project_dir)

    with patch("sase.bead.cli_crud_evidence.auto_commit_bead_store") as auto_commit:
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


def test_note_edit_rewrites_text_and_preserves_original_authorship(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue_id = _create_issue(project_dir)
    monkeypatch.setattr("sase.bead.project._now", lambda: "2026-01-01T00:01:00Z")
    _run_note([issue_id, "--author", "alice", "first draft"], capsys)
    monkeypatch.setattr("sase.bead.project._now", lambda: "2026-01-01T00:02:00Z")

    output = _run_note([issue_id, "--author", "bob", "-e", "1", "corrected"], capsys)

    assert f"Note #1 edited: {issue_id}" in output
    with BeadProject(project_dir) as project:
        issue = project.show(issue_id)
    assert len(issue.notes) == 1
    note = issue.notes[0]
    assert note.text == "corrected"
    assert note.timestamp == "2026-01-01T00:01:00Z"
    assert note.author == "alice"
    assert note.edited_at == "2026-01-01T00:02:00Z"
    assert note.edited_by == "bob"

    stream_path = project_dir / f"sdd/beads/events/streams/{issue_id}.jsonl"
    operations = [
        json.loads(line)["operation"]
        for line in stream_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert operations == ["issue_created", "note_appended", "note_edited"]

    history = _run_history([issue_id, "--field", "notes", "--format", "full"], capsys)
    assert "from: [2026-01-01T00:01:00Z · alice] first draft" in history
    assert "to: [2026-01-01T00:01:00Z · alice] corrected" in history


def test_note_edit_rejects_out_of_range_ordinal_without_writing(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue_id = _create_issue(project_dir)
    monkeypatch.setattr("sase.bead.project._now", lambda: "2026-01-01T00:01:00Z")
    _run_note([issue_id, "--author", "alice", "only note"], capsys)

    with patch("sase.bead.cli_crud_evidence.auto_commit_bead_store") as auto_commit:
        with pytest.raises(SystemExit) as excinfo:
            _run_note([issue_id, "-e", "2", "too far"], capsys)

    assert excinfo.value.code == 1
    assert "note #2 does not exist" in capsys.readouterr().err
    auto_commit.assert_not_called()
    with BeadProject(project_dir) as project:
        assert project.show(issue_id).notes_text == (
            "[2026-01-01T00:01:00Z · alice] only note"
        )


def test_note_edit_requires_text(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue_id = _create_issue(project_dir)

    with pytest.raises(SystemExit) as excinfo:
        _run_note([issue_id, "-e", "1"], capsys)

    assert excinfo.value.code == 1
    assert "--edit requires note text" in capsys.readouterr().err


def test_note_remove_retracts_the_record_and_history_keeps_it(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue_id = _create_issue(project_dir)
    monkeypatch.setattr("sase.bead.project._now", lambda: "2026-01-01T00:01:00Z")
    _run_note([issue_id, "--author", "alice", "retract me"], capsys)
    monkeypatch.setattr("sase.bead.project._now", lambda: "2026-01-01T00:02:00Z")

    output = _run_note([issue_id, "--author", "bob", "-x", "1"], capsys)

    assert f"Note #1 removed: {issue_id}" in output
    with BeadProject(project_dir) as project:
        issue = project.show(issue_id)
    assert issue.notes == []
    assert issue.notes_text == ""

    stream_path = project_dir / f"sdd/beads/events/streams/{issue_id}.jsonl"
    operations = [
        json.loads(line)["operation"]
        for line in stream_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert operations == ["issue_created", "note_appended", "note_removed"]

    history = _run_history([issue_id, "--field", "notes", "--format", "full"], capsys)
    assert "from: [2026-01-01T00:01:00Z · alice] retract me" in history


def test_note_remove_rejects_out_of_range_ordinal_without_writing(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue_id = _create_issue(project_dir)

    with patch("sase.bead.cli_crud_evidence.auto_commit_bead_store") as auto_commit:
        with pytest.raises(SystemExit) as excinfo:
            _run_note([issue_id, "-x", "1"], capsys)

    assert excinfo.value.code == 1
    assert "note #1 does not exist" in capsys.readouterr().err
    auto_commit.assert_not_called()


def test_note_remove_forbids_text(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue_id = _create_issue(project_dir)
    monkeypatch.setattr("sase.bead.project._now", lambda: "2026-01-01T00:01:00Z")
    _run_note([issue_id, "--author", "alice", "note text"], capsys)

    with pytest.raises(SystemExit) as excinfo:
        _run_note([issue_id, "-x", "1", "stray", "text"], capsys)

    assert excinfo.value.code == 1
    assert "--remove does not take note text" in capsys.readouterr().err


def test_handle_bead_note_edit_and_remove_auto_commit_messages(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue_id = _create_issue(project_dir)
    monkeypatch.setattr("sase.bead.project._now", lambda: "2026-01-01T00:01:00Z")
    _run_note([issue_id, "--author", "alice", "first draft"], capsys)

    with patch("sase.bead.cli_crud_evidence.auto_commit_bead_store") as auto_commit:
        bead_cli.handle_bead_note(
            create_parser().parse_args(
                ["bead", "note", issue_id, "--author", "alice", "-e", "1", "fixed"]
            )
        )
    auto_commit.assert_called_once_with(
        f"chore(beads): edit note {issue_id}",
        push_after_commit=False,
        already_locked=False,
    )

    with patch("sase.bead.cli_crud_evidence.auto_commit_bead_store") as auto_commit:
        bead_cli.handle_bead_note(
            create_parser().parse_args(
                ["bead", "note", issue_id, "--author", "alice", "-x", "1"]
            )
        )
    auto_commit.assert_called_once_with(
        f"chore(beads): remove note {issue_id}",
        push_after_commit=False,
        already_locked=False,
    )

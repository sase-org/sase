"""CLI coverage for closing beads with an attributed note."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import IssueType, Resolution, Status
from sase.bead.project import BeadProject
from sase.core import bead_touch_index_facade as touch_index
from sase.main import bead_fast_path
from sase.main.bead_fast_path import try_handle_bead_fast_path
from sase.main.parser import create_parser
from tests.main.parser_cli_helpers import parse_sase_args


def test_close_note_parser_accepts_long_and_short_options() -> None:
    parser = create_parser()

    long_args = parser.parse_args(["bead", "close", "sase-1", "--note", "verified"])
    short_args = parser.parse_args(["bead", "close", "sase-1", "-n", "tested"])

    assert long_args.note == "verified"
    assert short_args.note == "tested"


def test_close_with_note_uses_one_slow_path_commit_and_agent_attribution(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with BeadProject(project_dir) as project:
        issue = project.create("Close target", IssueType.PLAN)
    monkeypatch.setenv("SASE_AGENT_NAME", "phase-agent")
    monkeypatch.setattr("sase.bead.project._now", lambda: "2026-01-01T00:01:00Z")
    args = create_parser().parse_args(
        [
            "bead",
            "close",
            issue.id,
            "--note",
            "verified with just check",
        ]
    )

    with patch("sase.bead.cli_crud_lifecycle.auto_commit_bead_store") as auto_commit:
        bead_cli.handle_bead_close(args)

    auto_commit.assert_called_once_with(
        f"chore(beads): close {issue.id}",
        push_after_commit=False,
        already_locked=False,
    )
    with BeadProject(project_dir) as project:
        closed = project.show(issue.id)
    assert closed.status is Status.CLOSED
    assert closed.notes_text == (
        "[2026-01-01T00:01:00Z · phase-agent] verified with just check"
    )


def test_close_with_note_applies_to_each_explicit_id(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with BeadProject(project_dir) as project:
        first = project.create("First", IssueType.PLAN)
        second = project.create("Second", IssueType.PLAN)
    monkeypatch.setattr("sase.bead.project._now", lambda: "2026-01-01T00:01:00Z")
    args = create_parser().parse_args(
        [
            "bead",
            "close",
            first.id,
            second.id,
            "--note",
            "multi close verified",
        ]
    )

    bead_cli.handle_bead_close(args)

    with BeadProject(project_dir) as project:
        for issue_id in (first.id, second.id):
            issue = project.show(issue_id)
            assert issue.status is Status.CLOSED
            assert issue.notes_text.endswith("] multi close verified")


def test_force_close_with_note_only_notes_explicit_parent(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with BeadProject(project_dir) as project:
        epic = project.create("Canceled epic", IssueType.PLAN)
        phase = project.create(
            "Unfinished phase",
            IssueType.PHASE,
            parent_id=epic.id,
        )
    monkeypatch.setattr("sase.bead.project._now", lambda: "2026-01-01T00:01:00Z")
    args = create_parser().parse_args(
        [
            "bead",
            "close",
            epic.id,
            "--force",
            "--note",
            "requirements changed",
            "--reason",
            "No longer needed",
            "--resolution",
            "canceled",
        ]
    )

    bead_cli.handle_bead_close(args)

    with BeadProject(project_dir) as project:
        closed_epic = project.show(epic.id)
        swept_phase = project.show(phase.id)
    assert closed_epic.notes_text.endswith("] requirements changed")
    assert closed_epic.resolution is Resolution.CANCELED
    assert swept_phase.notes_text == ""
    assert swept_phase.resolution is Resolution.CANCELED


def test_close_with_note_defers_to_truthful_slow_path(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with BeadProject(project_dir) as project:
        issue = project.create("Slow close", IssueType.PLAN)
    beads_dir = project_dir / "sdd/beads"
    context = bead_fast_path._FastPathContext(
        read_beads_dirs=[beads_dir],
        write_beads_dir=beads_dir,
        relativize_design_paths=True,
    )
    summaries: list[dict[str, object]] = []
    monkeypatch.chdir(project_dir)
    monkeypatch.setattr(
        bead_fast_path,
        "_resolve_fast_path_context",
        lambda _argv: context,
    )
    monkeypatch.setattr(
        bead_fast_path,
        "_apply_mutation_side_effects",
        lambda _beads_dir, summary: summaries.append(summary),
    )
    monkeypatch.setattr(
        "sase.bead.sync.schedule_current_bead_refresh",
        lambda: None,
    )

    assert try_handle_bead_fast_path(["close", issue.id, "--note", "verified"]) is None

    assert summaries == []
    with BeadProject(project_dir) as project:
        unchanged = project.show(issue.id)
    assert unchanged.status is Status.OPEN
    assert unchanged.notes_text == ""


def test_reclose_with_note_reports_both_outcomes_and_commits_note(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        issue = project.create("Already finished", IssueType.PLAN)
        project.close([issue.id])
        first_closed_at = project.show(issue.id).closed_at
    monkeypatch.setattr("sase.bead.project._now", lambda: "2026-01-01T00:02:00Z")
    args = create_parser().parse_args(
        ["bead", "close", issue.id, "--note", "second look"]
    )

    with patch("sase.bead.cli_crud_lifecycle.auto_commit_bead_store") as auto_commit:
        bead_cli.handle_bead_close(args)

    output = capsys.readouterr().out
    assert (
        f"· Already closed  {issue.id} — {issue.title} "
        f"({first_closed_at} · done)\n" in output
    )
    assert f"+ Noted           {issue.id} — {issue.title}\n" in output
    auto_commit.assert_called_once_with(
        f"chore(beads): note {issue.id}",
        push_after_commit=False,
        already_locked=False,
    )
    with BeadProject(project_dir) as project:
        reclosed = project.show(issue.id)
    assert reclosed.closed_at == first_closed_at
    assert reclosed.notes_text.endswith("] second look")


def test_close_without_note_credits_acting_agent_not_creator(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        issue = project.create(
            "Close attribution",
            IssueType.PLAN,
            created_by="agent-a",
        )
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-b")
    args = create_parser().parse_args(["bead", "close", issue.id])

    with patch("sase.bead.cli_crud_lifecycle.auto_commit_bead_store"):
        bead_cli.handle_bead_close(args)

    with BeadProject(project_dir) as project:
        index_path = project_dir / "agent_bead_touches.json"
        touch_index._refresh_touch_index(project.beads_dir, index_path)
    query = touch_index.query_touch_index(index_path)
    closer_rows = [
        touch
        for touch in query.touches
        if touch.bead_id == issue.id and touch.actor == "agent-b"
    ]
    creator_rows = [
        touch
        for touch in query.touches
        if touch.bead_id == issue.id and touch.actor == "agent-a"
    ]
    assert len(closer_rows) == 1
    assert closer_rows[0].verbs.get("closed") == 1
    assert closer_rows[0].close is not None
    assert closer_rows[0].close.standing is True
    assert all("closed" not in touch.verbs for touch in creator_rows)

    stream_path = (
        project_dir / "sdd" / "beads" / "events" / "streams" / f"{issue.id}.jsonl"
    )
    events = [
        json.loads(line)
        for line in stream_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    closed = next(event for event in events if event["operation"] == "issue_closed")
    assert closed["actor"] == "agent-b"
    assert closed["payload"]["closed_by"] == "agent-b"

    capsys.readouterr()
    bead_cli.handle_bead_history(
        parse_sase_args(["bead", "history", issue.id, "--format", "json"])
    )
    history = json.loads(capsys.readouterr().out)
    close_entries = [
        entry for entry in history["entries"] if entry["operation"] == "issue_closed"
    ]
    assert close_entries[0]["actor"] == "agent-b"

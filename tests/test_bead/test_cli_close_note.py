"""CLI coverage for closing beads with an attributed note."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import IssueType, Resolution, Status
from sase.bead.project import BeadProject
from sase.main import bead_fast_path
from sase.main.bead_fast_path import try_handle_bead_fast_path
from sase.main.parser import create_parser


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

    with patch("sase.bead.cli_crud.auto_commit_bead_store") as auto_commit:
        bead_cli.handle_bead_close(args)

    auto_commit.assert_called_once_with(
        f"chore(beads): close {issue.id}",
        push_after_commit=False,
        already_locked=False,
    )
    with BeadProject(project_dir) as project:
        closed = project.show(issue.id)
    assert closed.status is Status.CLOSED
    assert closed.notes == (
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
            assert issue.notes.endswith("] multi close verified")


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
    assert closed_epic.notes.endswith("] requirements changed")
    assert closed_epic.resolution is Resolution.CANCELED
    assert swept_phase.notes == ""
    assert swept_phase.resolution is Resolution.CANCELED


def test_close_with_note_uses_one_fast_path_side_effect(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with BeadProject(project_dir) as project:
        issue = project.create("Fast close", IssueType.PLAN)
    beads_dir = project_dir / "sdd/beads"
    context = bead_fast_path._FastPathContext(
        read_beads_dirs=[beads_dir],
        write_beads_dir=beads_dir,
        relativize_design_paths=True,
    )
    summaries: list[dict[str, object]] = []
    monkeypatch.chdir(project_dir)
    monkeypatch.setenv("SASE_AGENT_NAME", "fast-agent")
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

    assert (
        try_handle_bead_fast_path(
            ["close", issue.id, "--note", "verified on fast path"]
        )
        == 0
    )

    assert len(summaries) == 1
    assert summaries[0]["operation"] == "close"
    with BeadProject(project_dir) as project:
        closed = project.show(issue.id)
    assert closed.status is Status.CLOSED
    assert closed.notes.endswith("· fast-agent] verified on fast path")

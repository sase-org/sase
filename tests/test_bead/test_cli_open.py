"""CLI coverage for the ``sase bead open`` shortcut."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import IssueType, Status
from sase.bead.project import BeadProject
from sase.main.parser import create_parser


@pytest.fixture
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    with BeadProject.init(tmp_path):
        pass
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sase.bead.workspace.resolve_primary_workspace", lambda: None)
    yield tmp_path


def test_open_parser_sets_bead_subcommand_and_id() -> None:
    args = create_parser().parse_args(["bead", "open", "beads-001"])

    assert args.command == "bead"
    assert args.bead_subcommand == "open"
    assert args.id == "beads-001"


def test_handle_bead_open_reopens_issue(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        issue = proj.create("Reopen me", IssueType.PLAN)
        proj.close([issue.id], reason="done")

    bead_cli.handle_bead_open(argparse.Namespace(id=issue.id))

    with BeadProject(project_dir) as proj:
        reopened = proj.show(issue.id)
        assert reopened.status == Status.OPEN
        assert reopened.closed_at is None
        assert reopened.close_reason is None
        assert reopened.resolution is None

    assert f"○ Opened: {issue.id} — Reopen me" in capsys.readouterr().out


def test_handle_bead_open_missing_id_exits_with_update_style_error(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_open(argparse.Namespace(id="beads-missing"))

    assert excinfo.value.code == 1
    assert capsys.readouterr().err == "Error: issue not found: beads-missing\n"


def test_handle_bead_open_reopens_closed_ancestors(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        epic = proj.create("Epic", IssueType.PLAN)
        phase = proj.create("Phase", IssueType.PHASE, parent_id=epic.id)
        proj.close([phase.id])
        proj.close([epic.id])

    bead_cli.handle_bead_open(argparse.Namespace(id=phase.id))

    with BeadProject(project_dir) as proj:
        assert proj.show(phase.id).status is Status.OPEN
        reopened_epic = proj.show(epic.id)
        assert reopened_epic.status is Status.OPEN
        assert reopened_epic.resolution is None
    output = capsys.readouterr().out
    assert f"○ Reopened ancestor: {epic.id} — Epic" in output


def test_handle_bead_open_records_acting_agent_as_opener(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SASE_AGENT_NAME", "tester.host.0oa")
    with BeadProject(project_dir) as proj:
        issue = proj.create("Reopen me", IssueType.PLAN)
        proj.close([issue.id], reason="done")

    bead_cli.handle_bead_open(argparse.Namespace(id=issue.id))

    stream_path = (
        project_dir / "sdd" / "beads" / "events" / "streams" / f"{issue.id}.jsonl"
    )
    events = [
        json.loads(line)
        for line in stream_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    opened = [event for event in events if event["operation"] == "issue_opened"]
    assert len(opened) == 1
    assert opened[0]["actor"] == "tester.host.0oa"
    assert f"○ Opened: {issue.id} — Reopen me" in capsys.readouterr().out


def test_handle_bead_open_already_open_is_noop(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        issue = proj.create("Already open", IssueType.PLAN)
        created_at = proj.show(issue.id).updated_at

    bead_cli.handle_bead_open(argparse.Namespace(id=issue.id))

    with BeadProject(project_dir) as proj:
        reopened = proj.show(issue.id)
        assert reopened.status == Status.OPEN
        assert reopened.updated_at == created_at
    assert f"· Already open: {issue.id} — Already open" in capsys.readouterr().out
    stream_path = (
        project_dir / "sdd" / "beads" / "events" / "streams" / f"{issue.id}.jsonl"
    )
    events = [
        json.loads(line)
        for line in stream_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert all(event["operation"] != "issue_opened" for event in events)


def test_open_parser_help_says_closed_and_not_a_viewer(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = create_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["bead", "open", "-h"])

    assert excinfo.value.code == 0
    help_text = capsys.readouterr().out
    assert "closed" in help_text
    assert "not a viewer" in help_text
    assert "sase bead read" in help_text

"""CLI coverage for the ``sase bead open`` shortcut."""

from __future__ import annotations

import argparse
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
        assert reopened.closed_at is not None
        assert reopened.close_reason == "done"

    assert f"○ Opened: {issue.id} — Reopen me" in capsys.readouterr().out


def test_handle_bead_open_missing_id_exits_with_update_style_error(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_open(argparse.Namespace(id="beads-missing"))

    assert excinfo.value.code == 1
    assert capsys.readouterr().err == "Error: issue not found: beads-missing\n"

"""On-demand ``sase bead export`` coverage for projection-off (sase-1h8.11)."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from sase.bead import cli_admin
from sase.bead.model import IssueType
from sase.bead.project import BeadProject


def test_export_regenerates_store_projection(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        issue = project.create("Exported", IssueType.PLAN)
    beads_dir = project_dir / "sdd" / "beads"
    if not (beads_dir / "issues.jsonl").exists():
        beads_dir = project_dir / "beads"
    assert (beads_dir / "issues.jsonl").exists()
    (beads_dir / "issues.jsonl").write_text("", encoding="utf-8")

    cli_admin.handle_bead_export(argparse.Namespace(output=None))

    exported = (beads_dir / "issues.jsonl").read_text(encoding="utf-8")
    assert issue.id in exported
    assert "Exported bead state to" in capsys.readouterr().out


def test_export_output_writes_alternate_path(
    project_dir: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        issue = project.create("Exported", IssueType.PLAN)
    beads_dir = project_dir / "sdd" / "beads"
    if not (beads_dir / "issues.jsonl").exists():
        beads_dir = project_dir / "beads"
    alternate = tmp_path / "snapshot.jsonl"

    cli_admin.handle_bead_export(argparse.Namespace(output=str(alternate)))

    exported = alternate.read_text(encoding="utf-8")
    assert issue.id in exported
    assert "Exported bead state to" in capsys.readouterr().out


def test_export_parser_accepts_output_alias() -> None:
    import argparse as _argparse

    from sase.main.parser_bead_store import register_bead_export_parser

    top = _argparse.ArgumentParser()
    sub = top.add_subparsers(dest="bead_subcommand")
    register_bead_export_parser(sub)
    args = top.parse_args(["export", "-o", "out.jsonl"])
    assert args.output == "out.jsonl"
    args = top.parse_args(["export", "--output", "out.jsonl"])
    assert args.output == "out.jsonl"
    args = top.parse_args(["export"])
    assert args.output is None

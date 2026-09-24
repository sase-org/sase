"""Regression: piped ``sase`` renders bead color under ``FORCE_COLOR``.

``capsys`` streams are not TTYs, so they model the Command Line proc case: a
``sase`` child whose stdout is a pipe. With ``FORCE_COLOR=1`` the bead list
and bead show renderers must still emit SGR sequences; ``NO_COLOR`` must
still win over the force variable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import Issue, IssueType
from sase.bead.project import BeadProject
from tests.main.parser_cli_helpers import parse_sase_args
from tests.test_bead.cli_show_test_helpers import show, use_single_issue_view


def _scrub_color_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("NO_COLOR", "FORCE_COLOR", "CLICOLOR_FORCE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")


def _seed_pair(project_dir: Path) -> Issue:
    with BeadProject(project_dir) as project:
        root = project.create("Root", IssueType.PLAN)
        blocker = project.create("Blocker", IssueType.PLAN)
        project.add_dependency(root.id, blocker.id)
        return project.show(root.id)


def test_bead_dep_list_colors_piped_output_under_force_color(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _seed_pair(project_dir)
    _scrub_color_env(monkeypatch)
    monkeypatch.setenv("FORCE_COLOR", "1")

    bead_cli.handle_bead_dep(parse_sase_args(["bead", "dep", "list", root.id]))

    assert "\x1b[" in capsys.readouterr().out


def test_bead_dep_list_stays_plain_on_pipe_by_default(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _seed_pair(project_dir)
    _scrub_color_env(monkeypatch)

    bead_cli.handle_bead_dep(parse_sase_args(["bead", "dep", "list", root.id]))

    assert "\x1b[" not in capsys.readouterr().out


def test_bead_show_colors_piped_output_under_force_color(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    issue = Issue(id="beads-color", title="Color me", issue_type=IssueType.TASK)
    use_single_issue_view(monkeypatch, issue)
    _scrub_color_env(monkeypatch)
    monkeypatch.setenv("FORCE_COLOR", "1")

    out = show(issue, capsys)

    assert "\x1b[" in out


def test_no_color_wins_over_force_color_for_bead_renderers(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _seed_pair(project_dir)
    _scrub_color_env(monkeypatch)
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.setenv("NO_COLOR", "1")

    bead_cli.handle_bead_dep(parse_sase_args(["bead", "dep", "list", root.id]))

    assert "\x1b[" not in capsys.readouterr().out

    issue = Issue(id="beads-nocolor", title="Plain", issue_type=IssueType.TASK)
    use_single_issue_view(monkeypatch, issue)

    assert "\x1b[" not in show(issue, capsys)

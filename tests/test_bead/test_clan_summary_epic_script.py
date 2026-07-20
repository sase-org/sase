"""Tests for the built-in epic clan-summary console script."""

from __future__ import annotations

from pathlib import Path

import pytest
from rich.text import Text

from sase.bead.model import BeadTier, IssueType
from sase.bead.project import BeadProject
from sase.scripts.sase_clan_summary_epic import main


def test_epic_summary_renders_goal_and_numbered_phase_titles(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        epic = project.create(
            "Beautiful [clan] summaries",
            IssueType.PLAN,
            description=(
                "Show the epic goal on one line while keeping the output "
                "stable after launch."
            ),
            tier=BeadTier.EPIC,
        )
        project.create(
            "Parse [bold]directives[/bold]",
            IssueType.PHASE,
            parent_id=epic.id,
        )
        project.create(
            "Render the clan panel",
            IssueType.PHASE,
            parent_id=epic.id,
        )

    monkeypatch.setenv("SASE_CLAN_NAME", epic.id)

    assert main() == 0

    markup = capsys.readouterr().out.rstrip("\n")
    rendered = Text.from_markup(markup)
    assert rendered.plain.splitlines() == [
        f"EPIC {epic.id} · Beautiful [clan] summaries",
        "Show the epic goal on one line while keeping the output stable after launch.",
        "1. Parse [bold]directives[/bold]",
        "2. Render the clan panel",
    ]
    assert "[bold #D75FFF]" in markup
    assert "[dim #D7D7FF]" in markup
    assert "[bold #87D7FF]1." in markup
    assert all(len(line) <= 76 for line in rendered.plain.splitlines())


def test_epic_summary_falls_back_when_lookup_fails(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SASE_CLAN_NAME", "missing-epic")

    assert main() == 0

    assert capsys.readouterr().out == "[bold]EPIC missing-epic[/]\n"

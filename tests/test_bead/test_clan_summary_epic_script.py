"""Tests for the built-in epic clan-summary console script."""

from __future__ import annotations

from pathlib import Path

import pytest
from rich.text import Text

from sase.bead.config import load_config
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
    refresh_calls = 0

    def unexpected_refresh() -> None:
        nonlocal refresh_calls
        refresh_calls += 1

    monkeypatch.setattr(
        "sase.scripts.sase_clan_summary_epic.refresh_current_bead_store",
        unexpected_refresh,
    )

    assert main() == 0

    captured = capsys.readouterr()
    markup = captured.out.rstrip("\n")
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
    assert captured.err == ""
    assert refresh_calls == 0


def test_epic_summary_refreshes_once_and_retries_missing_epic(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue_prefix = load_config(project_dir / "sdd/beads")["issue_prefix"]
    epic_id = f"{issue_prefix}-1"
    monkeypatch.setenv("SASE_CLAN_NAME", epic_id)
    monkeypatch.setattr(
        "sase.scripts.sase_clan_summary_epic.bead_refresh_mode",
        lambda: "background",
    )
    refresh_calls = 0

    def create_remote_epic() -> None:
        nonlocal refresh_calls
        refresh_calls += 1
        with BeadProject(project_dir) as project:
            epic = project.create(
                "Fresh remote epic",
                IssueType.PLAN,
                description="Available after integration.",
                tier=BeadTier.EPIC,
            )
            assert epic.id == epic_id
            project.create(
                "Recovered phase",
                IssueType.PHASE,
                parent_id=epic.id,
            )

    monkeypatch.setattr(
        "sase.scripts.sase_clan_summary_epic.refresh_current_bead_store",
        create_remote_epic,
    )

    assert main() == 0

    captured = capsys.readouterr()
    rendered = Text.from_markup(captured.out)
    assert rendered.plain.splitlines() == [
        f"EPIC {epic_id} · Fresh remote epic",
        "Available after integration.",
        "1. Recovered phase",
    ]
    assert captured.err == ""
    assert refresh_calls == 1


def test_epic_summary_refresh_off_falls_back_with_diagnostics(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del project_dir
    monkeypatch.setenv("SASE_CLAN_NAME", "missing-epic")
    monkeypatch.setattr(
        "sase.scripts.sase_clan_summary_epic.bead_refresh_mode",
        lambda: "off",
    )

    def unexpected_refresh() -> None:
        raise AssertionError("refresh mode off must not integrate")

    monkeypatch.setattr(
        "sase.scripts.sase_clan_summary_epic.refresh_current_bead_store",
        unexpected_refresh,
    )

    assert main() == 0

    captured = capsys.readouterr()
    assert captured.out == "[bold]EPIC missing-epic[/]\n"
    assert "Unable to load epic clan summary for 'missing-epic'" in captured.err
    assert "Traceback (most recent call last):" in captured.err
    assert "KeyError" in captured.err


def test_epic_summary_invalid_bead_does_not_refresh(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        plan = project.create(
            "Not an epic",
            IssueType.PLAN,
            tier=BeadTier.PLAN,
        )
    monkeypatch.setenv("SASE_CLAN_NAME", plan.id)

    def unexpected_refresh() -> None:
        raise AssertionError("invalid bead types must not trigger integration")

    monkeypatch.setattr(
        "sase.scripts.sase_clan_summary_epic.refresh_current_bead_store",
        unexpected_refresh,
    )

    assert main() == 0

    captured = capsys.readouterr()
    assert captured.out == f"[bold]EPIC {plan.id}[/]\n"
    assert "ValueError" in captured.err
    assert "is not an epic plan" in captured.err


@pytest.mark.parametrize("failure", ["refresh", "retry"])
def test_epic_summary_refresh_failure_falls_back_with_diagnostics(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: str,
) -> None:
    del project_dir
    monkeypatch.setenv("SASE_CLAN_NAME", "missing-epic")
    monkeypatch.setattr(
        "sase.scripts.sase_clan_summary_epic.bead_refresh_mode",
        lambda: "background",
    )

    def refresh() -> None:
        if failure == "refresh":
            raise RuntimeError("remote integration failed")

    monkeypatch.setattr(
        "sase.scripts.sase_clan_summary_epic.refresh_current_bead_store",
        refresh,
    )

    assert main() == 0

    captured = capsys.readouterr()
    assert captured.out == "[bold]EPIC missing-epic[/]\n"
    assert "Unable to load epic clan summary for 'missing-epic'" in captured.err
    assert "Traceback (most recent call last):" in captured.err
    expected_error = (
        "RuntimeError: remote integration failed"
        if failure == "refresh"
        else "KeyError"
    )
    assert expected_error in captured.err

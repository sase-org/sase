"""CLI coverage for close-time leftover ``--epic-symbol`` discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import BeadTier, IssueType, Status
from sase.bead.project import BeadProject
from sase.main.parser import create_parser


def _write_justfile(project_dir: Path, *flags: str) -> None:
    lines = " \\\n        ".join(flags)
    project_dir.joinpath("Justfile").write_text(
        f"symvision src \\\n        {lines}\n",
        encoding="utf-8",
    )


def test_close_refuses_leftover_epic_symbols_for_a_phase(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        epic = project.create("Ranking", IssueType.PLAN, tier=BeadTier.EPIC)
        phase = project.create("Store", IssueType.PHASE, parent_id=epic.id)
    _write_justfile(
        project_dir,
        f'--epic-symbol "{phase.id}(CommonPlaceholderIndex)"',
        f'--epic-symbol "{phase.id}(load_common_placeholder_index)"',
        '--epic-symbol "sase-unrelated(OtherSymbol)"',
    )

    args = create_parser().parse_args(["bead", "close", phase.id, "--note", "done"])
    with pytest.raises(SystemExit, match="1"):
        bead_cli.handle_bead_close(args)

    error = capsys.readouterr().err
    assert f"refusing to close {phase.id}" in error
    assert f'--epic-symbol "{phase.id}(CommonPlaceholderIndex)"' in error
    assert f'--epic-symbol "{phase.id}(load_common_placeholder_index)"' in error
    assert "sase-unrelated(OtherSymbol)" not in error
    assert f"sase bead epic-symbols {phase.id}" in error
    with BeadProject(project_dir) as project:
        assert project.show(phase.id).status is not Status.CLOSED


def test_close_of_epic_surfaces_descendant_phase_entries(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        epic = project.create("Ranking", IssueType.PLAN, tier=BeadTier.EPIC)
        phase = project.create("Scoring", IssueType.PHASE, parent_id=epic.id)
        project.close([phase.id])
    _write_justfile(
        project_dir,
        f'--epic-symbol "{phase.id}(RankedPlaceholder)"',
    )

    args = create_parser().parse_args(["bead", "close", epic.id])
    with pytest.raises(SystemExit, match="1"):
        bead_cli.handle_bead_close(args)

    error = capsys.readouterr().err
    assert f"refusing to close {epic.id}" in error
    assert f'--epic-symbol "{phase.id}(RankedPlaceholder)"' in error
    with BeadProject(project_dir) as project:
        assert project.show(epic.id).status is not Status.CLOSED


def test_close_of_one_phase_ignores_sibling_phase_entries(
    project_dir: Path,
) -> None:
    with BeadProject(project_dir) as project:
        epic = project.create("Ranking", IssueType.PLAN, tier=BeadTier.EPIC)
        first = project.create("Context", IssueType.PHASE, parent_id=epic.id)
        second = project.create("Scoring", IssueType.PHASE, parent_id=epic.id)
    _write_justfile(project_dir, f'--epic-symbol "{second.id}(RankedPlaceholder)"')

    bead_cli.handle_bead_close(create_parser().parse_args(["bead", "close", first.id]))

    with BeadProject(project_dir) as project:
        assert project.show(first.id).status is Status.CLOSED
        assert project.show(second.id).status is not Status.CLOSED


def test_close_succeeds_after_justfile_entries_are_removed(
    project_dir: Path,
) -> None:
    with BeadProject(project_dir) as project:
        issue = project.create("Cleanup", IssueType.PLAN)
    _write_justfile(project_dir, f'--epic-symbol "{issue.id}(TempSymbol)"')
    project_dir.joinpath("Justfile").write_text("symvision src\n", encoding="utf-8")

    bead_cli.handle_bead_close(create_parser().parse_args(["bead", "close", issue.id]))

    with BeadProject(project_dir) as project:
        assert project.show(issue.id).status is Status.CLOSED


def test_reclose_of_already_closed_bead_skips_leftover_check(
    project_dir: Path,
) -> None:
    with BeadProject(project_dir) as project:
        issue = project.create("Already landed", IssueType.PLAN)
        project.close([issue.id])
    _write_justfile(project_dir, f'--epic-symbol "{issue.id}(StaleSymbol)"')

    bead_cli.handle_bead_close(create_parser().parse_args(["bead", "close", issue.id]))

    with BeadProject(project_dir) as project:
        assert project.show(issue.id).status is Status.CLOSED


def test_force_close_still_refuses_leftover_epic_symbols(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        epic = project.create("Canceled", IssueType.PLAN, tier=BeadTier.EPIC)
        project.create("Unfinished", IssueType.PHASE, parent_id=epic.id)
    _write_justfile(project_dir, f'--epic-symbol "{epic.id}(TempSymbol)"')

    args = create_parser().parse_args(
        [
            "bead",
            "close",
            epic.id,
            "--force",
            "--reason",
            "abandoning",
            "--resolution",
            "canceled",
        ]
    )
    with pytest.raises(SystemExit, match="1"):
        bead_cli.handle_bead_close(args)

    error = capsys.readouterr().err
    assert f'--epic-symbol "{epic.id}(TempSymbol)"' in error
    with BeadProject(project_dir) as project:
        assert project.show(epic.id).status is not Status.CLOSED

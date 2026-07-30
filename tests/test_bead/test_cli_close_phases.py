"""CLI coverage for closing selected epic phase beads."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import BeadTier, Issue, IssueType, Resolution, Status
from sase.bead.phase_selector import (
    PhaseSelectorError,
    parse_phase_selectors,
    resolve_epic_phase_ids,
)
from sase.bead.project import BeadProject
from sase.main.parser import create_parser


def _create_epic_with_phases(
    project_dir: Path,
    count: int = 3,
) -> tuple[Issue, list[Issue]]:
    with BeadProject(project_dir) as project:
        epic = project.create(
            "Epic",
            IssueType.PLAN,
            tier=BeadTier.EPIC,
        )
        phases = [
            project.create(
                f"Phase {number}",
                IssueType.PHASE,
                parent_id=epic.id,
            )
            for number in range(1, count + 1)
        ]
    return epic, phases


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (["1,2,3"], (1, 2, 3)),
        (["1-3"], (1, 2, 3)),
        (["1-3,5,8-9"], (1, 2, 3, 5, 8, 9)),
        ([" 1, 3 - 5 "], (1, 3, 4, 5)),
        (["3,1,1-2", "2,4"], (1, 2, 3, 4)),
    ],
)
def test_parse_phase_selectors(
    values: list[str],
    expected: tuple[int, ...],
) -> None:
    assert parse_phase_selectors(values) == expected


@pytest.mark.parametrize(
    ("values", "message"),
    [
        (
            ["x"],
            "invalid --phases value: 'x' "
            "(expected phase numbers or ranges, e.g. 1,3,5-7)",
        ),
        (
            [""],
            "invalid --phases value: '' "
            "(expected phase numbers or ranges, e.g. 1,3,5-7)",
        ),
        (
            ["1,,2"],
            "invalid --phases value: '' "
            "(expected phase numbers or ranges, e.g. 1,3,5-7)",
        ),
        (
            ["0"],
            "invalid --phases value: '0' (phase numbers start at 1)",
        ),
        (
            ["-2"],
            "invalid --phases value: '-2' (phase numbers start at 1)",
        ),
        (
            ["5-3"],
            "invalid --phases range: '5-3' (start must not exceed end)",
        ),
    ],
)
def test_parse_phase_selectors_rejects_invalid_values(
    values: list[str],
    message: str,
) -> None:
    with pytest.raises(PhaseSelectorError) as exc_info:
        parse_phase_selectors(values)
    assert str(exc_info.value) == message


def test_close_parser_wires_repeatable_phase_selectors() -> None:
    parser = create_parser()

    assert parser.parse_args(["bead", "close", "x"]).phases is None
    args = parser.parse_args(["bead", "close", "x", "-p", "1,3", "--phases", "5-7"])
    assert args.phases == ["1,3", "5-7"]


@pytest.mark.parametrize(
    ("issue", "actual"),
    [
        (
            Issue(
                id="sase-at.1",
                title="Phase",
                issue_type=IssueType.PHASE,
                parent_id="sase-at",
            ),
            "phase",
        ),
        (
            Issue(
                id="sase-at",
                title="Plan",
                issue_type=IssueType.PLAN,
                tier=BeadTier.PLAN,
            ),
            "plan",
        ),
        (
            Issue(
                id="sase-at",
                title="Untiered plan",
                issue_type=IssueType.PLAN,
            ),
            "missing tier",
        ),
    ],
)
def test_resolve_epic_phase_ids_rejects_non_epics(
    issue: Issue,
    actual: str,
) -> None:
    project = cast(Any, _FakeProject(issue))

    with pytest.raises(
        PhaseSelectorError,
        match=(
            rf"^--phases only applies to epic plan beads "
            rf"\(got {actual} for {issue.id}\)$"
        ),
    ):
        resolve_epic_phase_ids(project, issue.id, (1,))


def test_resolve_epic_phase_ids_rejects_a_non_phase_child() -> None:
    epic = Issue(
        id="sase-at",
        title="Epic",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
    )
    child = Issue(
        id="sase-at.3",
        title="Nested plan",
        issue_type=IssueType.PLAN,
        tier=BeadTier.PLAN,
        parent_id=epic.id,
    )
    project = cast(Any, _FakeProject(epic, [child]))

    with pytest.raises(
        PhaseSelectorError,
        match=(
            r"^sase-at\.3 is not a phase bead; "
            r"close it by ID if that is intended$"
        ),
    ):
        resolve_epic_phase_ids(project, epic.id, (3,))


def test_resolve_epic_phase_ids_truncates_a_long_missing_list() -> None:
    epic = Issue(
        id="sase-at",
        title="Epic",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
    )
    phase = Issue(
        id="sase-at.1",
        title="Phase",
        issue_type=IssueType.PHASE,
        parent_id=epic.id,
    )
    project = cast(Any, _FakeProject(epic, [phase]))

    with pytest.raises(PhaseSelectorError) as exc_info:
        resolve_epic_phase_ids(project, epic.id, tuple(range(2, 15)))

    assert str(exc_info.value) == (
        "epic sase-at has no phase 2, 3, 4, 5, 6, 7, 8, 9, 10, 11 "
        "(+3 more) (existing phases: 1)"
    )


def test_resolve_epic_phase_ids_reports_an_epic_without_phases() -> None:
    epic = Issue(
        id="sase-at",
        title="Epic",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
    )
    project = cast(Any, _FakeProject(epic))

    with pytest.raises(PhaseSelectorError) as exc_info:
        resolve_epic_phase_ids(project, epic.id, (1,))

    assert str(exc_info.value) == (
        "epic sase-at has no phase 1 (epic has no phase beads)"
    )


def test_close_selected_phases_leaves_epic_and_other_phases_open(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic, phases = _create_epic_with_phases(project_dir)
    args = create_parser().parse_args(["bead", "close", epic.id, "--phases", "1-2"])

    bead_cli.handle_bead_close(args)

    assert capsys.readouterr().out == (
        f"✓ Closed          {phases[0].id} — {phases[0].title}\n"
        f"✓ Closed          {phases[1].id} — {phases[1].title}\n"
    )
    with BeadProject(project_dir) as project:
        assert project.show(epic.id).status is Status.OPEN
        assert project.show(phases[0].id).status is Status.CLOSED
        assert project.show(phases[1].id).status is Status.CLOSED
        assert project.show(phases[2].id).status is Status.OPEN


def test_phase_close_composes_with_note_reason_and_resolution(
    project_dir: Path,
) -> None:
    epic, phases = _create_epic_with_phases(project_dir, count=2)
    args = create_parser().parse_args(
        [
            "bead",
            "close",
            epic.id,
            "-p",
            "1,2",
            "--note",
            "landed together",
            "--reason",
            "Replaced by the combined implementation",
            "--resolution",
            "superseded",
        ]
    )

    bead_cli.handle_bead_close(args)

    with BeadProject(project_dir) as project:
        for phase in phases:
            closed = project.show(phase.id)
            assert closed.notes.endswith("] landed together")
            assert closed.close_reason == "Replaced by the combined implementation"
            assert closed.resolution is Resolution.SUPERSEDED


def test_phase_close_rejects_non_epics_without_writes(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic, phases = _create_epic_with_phases(project_dir, count=1)
    with BeadProject(project_dir) as project:
        plan = project.create(
            "Tale plan",
            IssueType.PLAN,
            tier=BeadTier.PLAN,
        )

    for target, actual in ((plan.id, "plan"), (phases[0].id, "phase")):
        args = create_parser().parse_args(["bead", "close", target, "--phases", "1"])
        with pytest.raises(SystemExit, match="1"):
            bead_cli.handle_bead_close(args)
        assert capsys.readouterr().err == (
            "Error: --phases only applies to epic plan beads "
            f"(got {actual} for {target})\n"
        )

        with BeadProject(project_dir) as project:
            assert project.show(epic.id).status is Status.OPEN
            assert project.show(phases[0].id).status is Status.OPEN
            assert project.show(plan.id).status is Status.OPEN


def test_phase_close_rejects_missing_phase_without_writes(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic, phases = _create_epic_with_phases(project_dir)
    args = create_parser().parse_args(["bead", "close", epic.id, "--phases", "4"])

    with pytest.raises(SystemExit, match="1"):
        bead_cli.handle_bead_close(args)

    assert capsys.readouterr().err == (
        f"Error: epic {epic.id} has no phase 4 (existing phases: 1, 2, 3)\n"
    )
    with BeadProject(project_dir) as project:
        assert project.show(epic.id).status is Status.OPEN
        assert all(project.show(phase.id).status is Status.OPEN for phase in phases)


def test_phase_close_rejects_invalid_selector_without_writes(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic, phases = _create_epic_with_phases(project_dir, count=1)
    args = create_parser().parse_args(["bead", "close", epic.id, "--phases", "1,,2"])

    with pytest.raises(SystemExit, match="1"):
        bead_cli.handle_bead_close(args)

    assert capsys.readouterr().err == (
        "Error: invalid --phases value: '' "
        "(expected phase numbers or ranges, e.g. 1,3,5-7)\n"
    )
    with BeadProject(project_dir) as project:
        assert project.show(epic.id).status is Status.OPEN
        assert project.show(phases[0].id).status is Status.OPEN


def test_phase_close_reports_a_missing_epic_without_writes(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic, phases = _create_epic_with_phases(project_dir, count=1)
    args = create_parser().parse_args(
        ["bead", "close", "beads-missing", "--phases", "1"]
    )

    with pytest.raises(SystemExit, match="1"):
        bead_cli.handle_bead_close(args)

    assert capsys.readouterr().err == "Error: issue not found: beads-missing\n"
    with BeadProject(project_dir) as project:
        assert project.show(epic.id).status is Status.OPEN
        assert project.show(phases[0].id).status is Status.OPEN


def test_phase_close_requires_exactly_one_positional_target(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    first, _ = _create_epic_with_phases(project_dir, count=1)
    with BeadProject(project_dir) as project:
        second = project.create(
            "Second epic",
            IssueType.PLAN,
            tier=BeadTier.EPIC,
        )
    args = create_parser().parse_args(
        ["bead", "close", first.id, second.id, "--phases", "1"]
    )

    with pytest.raises(SystemExit, match="1"):
        bead_cli.handle_bead_close(args)

    assert capsys.readouterr().err == (
        f"Error: --phases takes exactly one epic bead ID "
        f"(got 2: {first.id}, {second.id})\n"
    )
    with BeadProject(project_dir) as project:
        assert all(issue.status is Status.OPEN for issue in project.list_issues())


def test_phase_close_auto_commit_names_expanded_ids(project_dir: Path) -> None:
    epic, phases = _create_epic_with_phases(project_dir, count=2)
    args = argparse.Namespace(
        ids=[epic.id],
        phases=["2,1"],
        reason=None,
        note=None,
        resolution="done",
        force=False,
    )

    with patch("sase.bead.cli_crud.auto_commit_bead_store") as auto_commit:
        bead_cli.handle_bead_close(args)

    auto_commit.assert_called_once_with(
        f"chore(beads): close {phases[0].id} {phases[1].id}",
        push_after_commit=False,
        already_locked=False,
    )


def test_phase_close_reports_closed_and_already_closed_in_one_invocation(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic, phases = _create_epic_with_phases(project_dir, count=2)
    with BeadProject(project_dir) as project:
        project.close([phases[0].id])
        first = project.show(phases[0].id)
    args = create_parser().parse_args(["bead", "close", epic.id, "--phases", "1-2"])

    bead_cli.handle_bead_close(args)

    assert capsys.readouterr().out == (
        f"· Already closed  {first.id} — {first.title} "
        f"({first.closed_at} · done)\n"
        f"✓ Closed          {phases[1].id} — {phases[1].title}\n"
    )


def test_force_close_renders_cascade_and_commits_only_requested_id(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic, phases = _create_epic_with_phases(project_dir, count=1)
    args = create_parser().parse_args(
        [
            "bead",
            "close",
            epic.id,
            "--force",
            "--reason",
            "Canceled",
            "--resolution",
            "canceled",
        ]
    )

    with patch("sase.bead.cli_crud.auto_commit_bead_store") as auto_commit:
        bead_cli.handle_bead_close(args)

    assert capsys.readouterr().out == (
        f"↳ Closed          {phases[0].id} — {phases[0].title}\n"
        f"✓ Closed          {epic.id} — {epic.title}\n"
    )
    auto_commit.assert_called_once_with(
        f"chore(beads): close {epic.id}",
        push_after_commit=False,
        already_locked=False,
    )


class _FakeProject:
    def __init__(self, target: Issue, children: list[Issue] | None = None) -> None:
        self.target = target
        self.children = children or []

    def show(self, _issue_id: str) -> Issue:
        return self.target

    def get_epic_children(self, _epic_id: str) -> list[Issue]:
        return self.children

"""CLI coverage for typed bead close resolutions."""

from pathlib import Path

from sase.bead import cli as bead_cli
from sase.bead.model import IssueType, Resolution, Status
from sase.bead.project import BeadProject
from sase.main.parser import create_parser


def test_close_parser_defaults_to_done_and_accepts_alias() -> None:
    parser = create_parser()

    defaults = parser.parse_args(["bead", "close", "beads-1"])
    assert defaults.resolution == "done"
    assert defaults.force is False
    assert (
        parser.parse_args(["bead", "close", "beads-1", "-R", "superseded"]).resolution
        == "superseded"
    )
    assert parser.parse_args(["bead", "close", "beads-1", "-f"]).force is True


def test_close_resolution_round_trips_end_to_end(
    project_dir: Path,
) -> None:
    with BeadProject(project_dir) as project:
        issue = project.create("Old approach", IssueType.PLAN)

    args = create_parser().parse_args(
        [
            "bead",
            "close",
            issue.id,
            "--reason",
            "A replacement shipped",
            "--resolution",
            "superseded",
        ]
    )
    bead_cli.handle_bead_close(args)

    with BeadProject(project_dir) as project:
        closed = project.show(issue.id)
    assert closed.resolution is Resolution.SUPERSEDED
    assert closed.close_reason == "A replacement shipped"


def test_force_close_sweeps_unfinished_child_end_to_end(
    project_dir: Path,
) -> None:
    with BeadProject(project_dir) as project:
        epic = project.create("Canceled epic", IssueType.PLAN)
        phase = project.create(
            "Unfinished phase",
            IssueType.PHASE,
            parent_id=epic.id,
        )

    args = create_parser().parse_args(
        [
            "bead",
            "close",
            epic.id,
            "--force",
            "--reason",
            "Requirements changed",
            "--resolution",
            "canceled",
        ]
    )
    bead_cli.handle_bead_close(args)

    with BeadProject(project_dir) as project:
        swept = project.show(phase.id)
        assert swept.status is Status.CLOSED
        assert swept.resolution is Resolution.CANCELED
        assert swept.close_reason == f"forced by {epic.id}: Requirements changed"

"""CLI coverage for typed bead close resolutions."""

from pathlib import Path

from sase.bead import cli as bead_cli
from sase.bead.model import IssueType, Resolution
from sase.bead.project import BeadProject
from sase.main.parser import create_parser


def test_close_parser_defaults_to_done_and_accepts_alias() -> None:
    parser = create_parser()

    assert parser.parse_args(["bead", "close", "beads-1"]).resolution == "done"
    assert (
        parser.parse_args(["bead", "close", "beads-1", "-R", "superseded"]).resolution
        == "superseded"
    )


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

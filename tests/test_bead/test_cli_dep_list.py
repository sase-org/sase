"""CLI coverage for ``sase bead dep list``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import Issue, IssueType
from sase.bead.project import BeadProject
from sase.main.parser import create_parser, default_list_delegation_notice


def _seed_graph(project_dir: Path) -> dict[str, Issue]:
    with BeadProject(project_dir) as project:
        root = project.create("Root", IssueType.PLAN)
        satisfied = project.create("Satisfied", IssueType.PLAN)
        blocker = project.create("Blocker", IssueType.PLAN)
        dependent = project.create("Dependent", IssueType.PLAN)
        project.close([satisfied.id], reason="done")
        project.add_dependency(root.id, satisfied.id)
        project.add_dependency(root.id, blocker.id)
        project.add_dependency(dependent.id, root.id)
        return {
            "root": root,
            "satisfied": project.show(satisfied.id),
            "blocker": blocker,
            "dependent": dependent,
        }


def _run(argv: list[str]) -> None:
    bead_cli.handle_bead_dep(create_parser().parse_args(["bead", "dep", *argv]))


def test_dep_parser_supports_bare_list_delegation_and_sorted_options() -> None:
    args = create_parser().parse_args(["bead", "dep"])

    assert args.dep_action == "list"
    assert args.id is None
    assert args.color == "auto"
    assert args.direction == "both"
    assert args.format == "compact"
    assert args.limit == 0
    assert args.status is None
    assert default_list_delegation_notice(args) == (
        "No subcommand provided for 'sase bead dep'; "
        "delegating to 'sase bead dep list'."
    )


def test_dep_list_scoped_compact_shows_both_directions_and_verdicts(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issues = _seed_graph(project_dir)

    _run(["list", issues["root"].id, "--color", "never"])

    output = capsys.readouterr().out
    assert f"○ {issues['root'].id} · Root   [OPEN]" in output
    assert "DEPENDS ON (2)" in output
    assert f"✓ {issues['satisfied'].id} · Satisfied" in output
    assert "satisfied" in output
    assert f"○ {issues['blocker'].id} · Blocker" in output
    assert "blocking" in output
    assert "BLOCKS (1)" in output
    assert f"← ○ {issues['dependent'].id} · Dependent" in output
    assert "Blocked by 1 of 2 dependencies." in output


def test_dep_list_scoped_full_adds_provenance(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issues = _seed_graph(project_dir)

    _run(["list", issues["root"].id, "--format", "full", "--direction", "out"])

    output = capsys.readouterr().out
    assert output.count("      added ") == 2
    assert " by " in output


def test_dep_list_scoped_json_uses_shared_resolved_reference_shape(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issues = _seed_graph(project_dir)

    _run(["list", issues["root"].id, "--format", "json"])

    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"] == issues["root"].id
    assert payload["direction"] == "both"
    assert payload["count"] == 3
    outgoing = next(
        edge
        for edge in payload["edges"]
        if edge["depends_on"]["id"] == issues["satisfied"].id
    )
    assert outgoing["issue"]["resolved"] is True
    assert outgoing["depends_on"]["status"] == "closed"
    assert outgoing["satisfied"] is True
    assert outgoing["direction"] == "out"


@pytest.mark.parametrize(
    ("direction", "present", "absent"),
    [
        ("out", "DEPENDS ON", "BLOCKS ("),
        ("in", "BLOCKS (", "DEPENDS ON"),
    ],
)
def test_dep_list_scoped_direction_filters_sections(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
    direction: str,
    present: str,
    absent: str,
) -> None:
    issues = _seed_graph(project_dir)

    _run(["list", issues["root"].id, "--direction", direction])

    output = capsys.readouterr().out
    assert present in output
    assert absent not in output


def test_dep_list_scoped_explicit_status_filters_endpoints(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issues = _seed_graph(project_dir)

    _run(
        [
            "list",
            issues["root"].id,
            "--direction",
            "out",
            "--status",
            "closed",
        ]
    )

    output = capsys.readouterr().out
    assert issues["satisfied"].id in output
    assert issues["blocker"].id not in output


def test_dep_list_store_wide_compact_groups_and_prints_census(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issues = _seed_graph(project_dir)

    _run(["list", "--color", "never"])

    output = capsys.readouterr().out
    assert f"○ {issues['root'].id} · Root" in output
    assert f"○ {issues['dependent'].id} · Dependent" in output
    assert "3 dependencies · 2 beads · 1 satisfied · 2 active" in output


def test_dep_list_store_wide_full_and_json_render(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_graph(project_dir)

    _run(["list", "--format", "full"])
    full = capsys.readouterr().out
    assert "[OPEN]" in full
    assert "      added " in full

    _run(["list", "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"] is None
    assert payload["count"] == 3
    assert {edge["direction"] for edge in payload["edges"]} == {"out"}


def test_dep_list_store_wide_status_default_filters_closed_sources(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        closed_source = project.create("Closed source", IssueType.PLAN)
        target = project.create("Target", IssueType.PLAN)
        project.add_dependency(closed_source.id, target.id)
        project.close([closed_source.id], reason="done")

    _run(["list", "--direction", "out"])
    assert capsys.readouterr().out == "No dependencies found.\n"

    _run(["list", closed_source.id, "--direction", "out"])
    assert target.id in capsys.readouterr().out


def test_dep_list_limit_caps_store_wide_root_beads(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_graph(project_dir)

    _run(["list", "--direction", "out", "--limit", "1"])

    output = capsys.readouterr().out
    assert "1 bead" in output
    assert output.count("\n○ ") == 0


def test_dep_list_unknown_id_exits_one(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        _run(["list", "missing"])

    assert excinfo.value.code == 1
    assert capsys.readouterr().err == "Error: issue not found: missing\n"


def test_dep_list_color_modes_override_non_tty(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issues = _seed_graph(project_dir)

    _run(["list", issues["root"].id, "--color", "never"])
    assert "\x1b[" not in capsys.readouterr().out

    _run(["list", issues["root"].id, "--color", "always"])
    assert "\x1b[" in capsys.readouterr().out


def test_dep_list_json_is_never_colored(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issues = _seed_graph(project_dir)

    _run(
        [
            "list",
            issues["root"].id,
            "--color",
            "always",
            "--format",
            "json",
        ]
    )

    assert "\x1b[" not in capsys.readouterr().out


def test_dep_list_empty_messages_are_successful(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        issue = project.create("Alone", IssueType.PLAN)

    _run(["list"])
    assert capsys.readouterr().out == "No dependencies found.\n"

    _run(["list", issue.id])
    assert capsys.readouterr().out == f"{issue.id} has no dependencies.\n"

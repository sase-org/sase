"""CLI coverage for ``sase bead dep tree``."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
from collections.abc import Iterator

import pytest

from sase.bead import cli as bead_cli
from sase.bead import cli_dep
from sase.bead.model import Dependency, Issue, IssueType
from sase.bead.project import BeadProject
from tests.main.parser_cli_helpers import parse_sase_args


def _run(argv: list[str]) -> None:
    bead_cli.handle_bead_dep(parse_sase_args(["bead", "dep", *argv]))


def _create(project: BeadProject, title: str) -> Issue:
    return project.create(title, IssueType.PLAN)


def test_dep_tree_parser_defaults_and_sorted_public_options() -> None:
    args = parse_sase_args(["bead", "dep", "tree"])

    assert args.id is None
    assert args.color == "auto"
    assert args.direction == "out"
    assert args.format == "compact"
    assert args.levels == 0
    assert args.status is None

    help_text = parse_sase_args(["bead", "dep"])
    assert help_text.dep_action == "list"


def test_dep_tree_renders_linear_chain_and_longest_chain(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        root = _create(project, "Root")
        middle = _create(project, "Middle")
        leaf = _create(project, "Leaf")
        project.add_dependency(root.id, middle.id)
        project.add_dependency(middle.id, leaf.id)

    _run(["tree", root.id, "--color", "never"])

    output = capsys.readouterr().out
    assert f"○ {root.id} · Root" in output
    assert f"└─ ○ {middle.id} · Middle" in output
    assert f"   └─ ○ {leaf.id} · Leaf" in output
    assert "3 beads · depth 3 · 2 active blockers" in output
    assert f"Longest chain: {root.id} → {middle.id} → {leaf.id}" in output


def test_dep_tree_marks_diamond_repeat_instead_of_cycle(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        root = _create(project, "Root")
        left = _create(project, "Left")
        right = _create(project, "Right")
        shared = _create(project, "Shared")
        project.add_dependency(root.id, left.id)
        project.add_dependency(root.id, right.id)
        project.add_dependency(left.id, shared.id)
        project.add_dependency(right.id, shared.id)

    _run(["tree", root.id])

    output = capsys.readouterr().out
    assert output.count(f"○ {shared.id}") == 2
    assert "⇡ (shown above)" in output
    assert "↻ (cycle)" not in output


def test_dep_tree_cycle_terminates_and_prints_warning(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        first = _create(project, "First")
        second = _create(project, "Second")
        project.add_dependency(first.id, second.id)
        project.add_dependency(second.id, first.id)

    _run(["tree", first.id])

    output = capsys.readouterr().out
    assert "↻ (cycle)" in output
    assert "Warning: 1 dependency cycle detected:" in output
    assert f"{first.id} → {second.id} → {first.id}" in output


def test_dep_tree_levels_marks_truncated_remainder(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        root = _create(project, "Root")
        middle = _create(project, "Middle")
        leaf = _create(project, "Leaf")
        project.add_dependency(root.id, middle.id)
        project.add_dependency(middle.id, leaf.id)

    _run(["tree", root.id, "--levels", "1"])

    output = capsys.readouterr().out
    assert f"{middle.id} · Middle (+1 more, use --levels 0)" in output
    assert leaf.id not in output


def test_dep_tree_direction_in_inverts_walk(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        blocked = _create(project, "Blocked")
        blocker = _create(project, "Blocker")
        project.add_dependency(blocked.id, blocker.id)

    _run(["tree", blocker.id, "--direction", "in"])

    output = capsys.readouterr().out
    assert output.index(blocker.id) < output.index(blocked.id)
    assert f"└─ ○ {blocked.id} · Blocked" in output


def test_dep_tree_direction_both_renders_two_trees(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        root = _create(project, "Root")
        blocker = _create(project, "Blocker")
        dependent = _create(project, "Dependent")
        project.add_dependency(root.id, blocker.id)
        project.add_dependency(dependent.id, root.id)

    _run(["tree", root.id, "--direction", "both"])

    output = capsys.readouterr().out
    assert "DEPENDS ON\n" in output
    assert "BLOCKS\n" in output
    assert blocker.id in output
    assert dependent.id in output


def test_dep_tree_renders_unresolved_target(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = Issue(
        id="source",
        title="Source",
        issue_type=IssueType.PLAN,
        dependencies=[
            Dependency(
                issue_id="source",
                depends_on_id="missing",
                created_at="2026-07-27T14:02:11Z",
                created_by="author@example.com",
            )
        ],
    )

    class _View:
        def list_issues(self) -> list[Issue]:
            return [source]

    @contextmanager
    def fake_read_view() -> Iterator[_View]:
        yield _View()

    monkeypatch.setattr(cli_dep, "get_read_view", fake_read_view)

    _run(["tree", source.id])

    output = capsys.readouterr().out
    assert "? missing (not found)" in output


def test_dep_tree_store_wide_forest_selects_top_level_roots(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        first_root = _create(project, "First root")
        first_leaf = _create(project, "First leaf")
        second_root = _create(project, "Second root")
        second_leaf = _create(project, "Second leaf")
        project.add_dependency(first_root.id, first_leaf.id)
        project.add_dependency(second_root.id, second_leaf.id)

    _run(["tree"])

    output = capsys.readouterr().out
    assert output.startswith(f"○ {first_root.id} · First root")
    assert f"\n\n○ {second_root.id} · Second root" in output
    assert output.count("\n└─ ") == 2


def test_dep_tree_json_node_shape_and_full_provenance(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        root = _create(project, "Root")
        child = _create(project, "Child")
        project.add_dependency(root.id, child.id)

    _run(["tree", root.id, "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    node = payload["roots"][0]
    child_node = node["children"][0]
    assert payload["scope"] == root.id
    assert payload["direction"] == "out"
    assert set(node) == {
        "issue",
        "edge",
        "repeat",
        "cycle",
        "truncated",
        "children",
    }
    assert node["issue"]["id"] == root.id
    assert node["issue"]["resolved"] is True
    assert node["edge"] is None
    assert node["repeat"] is False
    assert node["cycle"] is False
    assert node["truncated"] is False
    assert node["children"] == [child_node]
    assert child_node["edge"]["issue_id"] == root.id
    assert child_node["edge"]["depends_on_id"] == child.id
    assert child_node["edge"]["satisfied"] is False
    assert child_node["children"] == []

    _run(["tree", root.id, "--format", "full"])
    assert "   added " in capsys.readouterr().out


def test_dep_tree_output_is_byte_identical_across_runs(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        root = _create(project, "Root")
        left = _create(project, "Left")
        right = _create(project, "Right")
        project.add_dependency(root.id, right.id)
        project.add_dependency(root.id, left.id)

    _run(["tree", root.id, "--color", "never"])
    first = capsys.readouterr().out
    _run(["tree", root.id, "--color", "never"])
    second = capsys.readouterr().out

    assert first == second


def test_dep_tree_rows_end_with_the_bead_created_cell_after_graph_markers(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        root = _create(project, "Root")
        middle = _create(project, "Middle")
        leaf = _create(project, "Leaf")
        project.add_dependency(root.id, middle.id)
        project.add_dependency(middle.id, leaf.id)

    _run(["tree", root.id, "--levels", "1", "--color", "never"])

    lines = capsys.readouterr().out.splitlines()
    root_line = next(line for line in lines if root.id in line)
    truncated_line = next(line for line in lines if middle.id in line)

    assert root_line.endswith("· Root  ⧖ now")
    assert truncated_line.endswith("(+1 more, use --levels 0)  ⧖ now")

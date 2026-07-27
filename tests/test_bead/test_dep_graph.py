"""Tests for the pure read-side dependency graph adapter."""

from __future__ import annotations

from sase.bead.dep_graph import DepGraph
from sase.bead.model import Dependency, Issue, IssueType, Status


def _issue(
    issue_id: str,
    *,
    status: Status = Status.OPEN,
    dependencies: tuple[str, ...] = (),
) -> Issue:
    return Issue(
        id=issue_id,
        title=issue_id,
        issue_type=IssueType.PLAN,
        status=status,
        dependencies=[
            Dependency(
                issue_id=issue_id,
                depends_on_id=target,
                created_at="2026-07-27T14:02:11Z",
                created_by="author@example.com",
            )
            for target in dependencies
        ],
    )


def test_graph_builds_deterministic_forward_and_reverse_adjacency() -> None:
    graph = DepGraph.build(
        [
            _issue("beads-3"),
            _issue("beads-1", dependencies=("beads-3", "beads-2")),
            _issue("beads-2"),
        ]
    )

    assert list(graph.issues) == ["beads-1", "beads-2", "beads-3"]
    assert [(edge.issue_id, edge.depends_on_id) for edge in graph.edges] == [
        ("beads-1", "beads-2"),
        ("beads-1", "beads-3"),
    ]
    assert [edge.depends_on_id for edge in graph.outgoing("beads-1")] == [
        "beads-2",
        "beads-3",
    ]
    assert [edge.issue_id for edge in graph.incoming("beads-2")] == ["beads-1"]


def test_graph_marks_only_resolved_closed_targets_satisfied() -> None:
    graph = DepGraph.build(
        [
            _issue("beads-1", dependencies=("beads-2", "missing")),
            _issue("beads-2", status=Status.CLOSED),
        ]
    )

    closed, unresolved = graph.outgoing("beads-1")
    assert closed.satisfied is True
    assert unresolved.satisfied is False
    assert graph.resolve("missing") is None
    assert graph.incoming("missing") == (unresolved,)


def test_graph_walk_marks_diamond_as_repeat_not_cycle() -> None:
    graph = DepGraph.build(
        [
            _issue("a", dependencies=("b", "c")),
            _issue("b", dependencies=("d",)),
            _issue("c", dependencies=("d",)),
            _issue("d"),
        ]
    )

    walk = graph.walk("a", direction="out")
    first_d = walk.children[0].children[0]
    second_d = walk.children[1].children[0]

    assert first_d.repeat is False
    assert first_d.cycle is False
    assert second_d.repeat is True
    assert second_d.cycle is False
    assert second_d.children == ()


def test_graph_walk_terminates_and_marks_cycle_per_path() -> None:
    graph = DepGraph.build(
        [
            _issue("a", dependencies=("b",)),
            _issue("b", dependencies=("a",)),
        ]
    )

    walk = graph.walk("a", direction="out")
    cycle = walk.children[0].children[0]

    assert cycle.issue_id == "a"
    assert cycle.cycle is True
    assert cycle.repeat is False
    assert cycle.children == ()


def test_graph_walk_honors_depth_bound_and_reverse_direction() -> None:
    graph = DepGraph.build(
        [
            _issue("a", dependencies=("b",)),
            _issue("b", dependencies=("c",)),
            _issue("c"),
        ]
    )

    forward = graph.walk("a", direction="out", levels=1)
    reverse = graph.walk("c", direction="in", levels=1)

    assert forward.children[0].issue_id == "b"
    assert forward.children[0].truncated is True
    assert forward.children[0].children == ()
    assert reverse.children[0].issue_id == "b"
    assert reverse.children[0].truncated is True

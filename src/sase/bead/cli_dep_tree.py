"""Traversal and rendering for ``sase bead dep tree``."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from typing import Literal

from sase.bead.cli_dep_render import (
    ANSI_BOLD_BLUE,
    ANSI_YELLOW,
    render_issue,
    resolve_color,
    styled,
)
from sase.bead.cli_common import created_cell
from sase.bead.cli_detail import ref_to_wire_dict
from sase.bead.dep_graph import DepDirection, DepGraph, DepTraversalNode
from sase.bead.model import IssueType, Status


@dataclass(frozen=True)
class _TreeWalk:
    direction: DepDirection
    roots: tuple[DepTraversalNode, ...]


@dataclass(frozen=True)
class _TreeStats:
    issue_ids: frozenset[str]
    depth: int
    active_edges: frozenset[tuple[str, str]]
    longest_chain: tuple[str, ...]
    cycle_paths: tuple[tuple[str, ...], ...]


def print_bead_dep_tree(
    graph: DepGraph,
    *,
    scope: str | None,
    direction: Literal["both", "in", "out"],
    statuses: frozenset[Status] | None,
    levels: int,
    output_format: str,
    color: str,
) -> None:
    """Build and print dependency tree walks from a prebuilt graph."""
    visible_graph = _visible_tree_graph(graph, scope=scope, statuses=statuses)
    walks = _tree_walks(
        visible_graph,
        scope=scope,
        direction=direction,
        levels=levels,
    )

    if output_format == "json":
        print(
            _render_dep_tree_json(
                visible_graph,
                walks,
                scope=scope,
                direction=direction,
            ),
            end="",
        )
        return

    if not walks:
        print("No dependency graph found.")
        return

    print(
        _render_dep_tree_text(
            visible_graph,
            walks,
            direction=direction,
            full=output_format == "full",
            use_color=resolve_color(color),
        ),
        end="",
    )


def _visible_tree_graph(
    graph: DepGraph,
    *,
    scope: str | None,
    statuses: frozenset[Status] | None,
) -> DepGraph:
    if statuses is None:
        return graph

    visible_ids = {
        issue.id for issue in graph.issues.values() if issue.status in statuses
    }
    if scope is not None:
        visible_ids.add(scope)

    visible_issues = []
    for issue_id in sorted(visible_ids):
        issue = graph.resolve(issue_id)
        if issue is None:
            continue
        dependencies = [
            dependency
            for dependency in issue.dependencies
            if graph.resolve(dependency.depends_on_id) is None
            or dependency.depends_on_id in visible_ids
        ]
        visible_issues.append(replace(issue, dependencies=dependencies))
    return DepGraph.build(visible_issues)


def _tree_walks(
    graph: DepGraph,
    *,
    scope: str | None,
    direction: Literal["both", "in", "out"],
    levels: int,
) -> tuple[_TreeWalk, ...]:
    directions: tuple[DepDirection, ...] = (
        ("out", "in") if direction == "both" else (direction,)
    )
    walks: list[_TreeWalk] = []
    for walk_direction in directions:
        root_ids = (
            (scope,)
            if scope is not None
            else _forest_root_ids(graph, direction=walk_direction)
        )
        if root_ids:
            walks.append(
                _TreeWalk(
                    direction=walk_direction,
                    roots=graph.walk_many(
                        root_ids,
                        direction=walk_direction,
                        levels=levels,
                    ),
                )
            )
    return tuple(walks)


def _forest_root_ids(
    graph: DepGraph,
    *,
    direction: DepDirection,
) -> tuple[str, ...]:
    participants = {
        issue_id
        for edge in graph.edges
        for issue_id in (edge.issue_id, edge.depends_on_id)
    }
    if not participants:
        return ()

    def adjacent(issue_id: str) -> tuple[str, ...]:
        if direction == "out":
            return tuple(edge.depends_on_id for edge in graph.outgoing(issue_id))
        return tuple(edge.issue_id for edge in graph.incoming(issue_id))

    roots = [
        issue_id
        for issue_id in sorted(participants)
        if not (
            graph.incoming(issue_id) if direction == "out" else graph.outgoing(issue_id)
        )
    ]
    covered: set[str] = set()

    def mark_reachable(root_id: str) -> None:
        pending = [root_id]
        while pending:
            issue_id = pending.pop()
            if issue_id in covered:
                continue
            covered.add(issue_id)
            pending.extend(reversed(adjacent(issue_id)))

    for root_id in roots:
        mark_reachable(root_id)

    for issue_id in sorted(participants - covered):
        roots.append(issue_id)
        mark_reachable(issue_id)
    return tuple(roots)


def _render_dep_tree_text(
    graph: DepGraph,
    walks: tuple[_TreeWalk, ...],
    *,
    direction: Literal["both", "in", "out"],
    full: bool,
    use_color: bool,
) -> str:
    lines: list[str] = []
    for walk_index, walk in enumerate(walks):
        if walk_index:
            lines.append("")
        if direction == "both":
            lines.append("DEPENDS ON" if walk.direction == "out" else "BLOCKS")
            lines.append("")
        for root_index, root in enumerate(walk.roots):
            if root_index:
                lines.append("")
            lines.extend(
                _render_tree_node(
                    graph,
                    root,
                    direction=walk.direction,
                    full=full,
                    use_color=use_color,
                    prefix="",
                    is_last=True,
                    is_root=True,
                )
            )

    stats = _tree_stats(walks)
    bead_count = len(stats.issue_ids)
    active_count = len(stats.active_edges)
    lines.extend(
        [
            "",
            "─" * 60,
            (
                f"{bead_count} {'bead' if bead_count == 1 else 'beads'} · "
                f"depth {stats.depth} · {active_count} active "
                f"{'blocker' if active_count == 1 else 'blockers'}"
            ),
        ]
    )
    if stats.longest_chain:
        lines.append(f"Longest chain: {' → '.join(stats.longest_chain)}")
    if stats.cycle_paths:
        cycle_count = len(stats.cycle_paths)
        lines.append(
            f"Warning: {cycle_count} dependency "
            f"{'cycle' if cycle_count == 1 else 'cycles'} detected: "
            + "; ".join(" → ".join(path) for path in stats.cycle_paths)
        )
    return "\n".join(lines) + "\n"


def _render_tree_node(
    graph: DepGraph,
    node: DepTraversalNode,
    *,
    direction: DepDirection,
    full: bool,
    use_color: bool,
    prefix: str,
    is_last: bool,
    is_root: bool,
) -> list[str]:
    connector = "" if is_root else ("└─ " if is_last else "├─ ")
    issue = graph.resolve(node.issue_id)
    if issue is None:
        row = f"? {styled(node.issue_id, ANSI_BOLD_BLUE, use_color)} (not found)"
    else:
        row = render_issue(issue, label=full, use_color=use_color)
        if full and issue.issue_type in {IssueType.PHASE, IssueType.TASK}:
            size = issue.size.value if issue.size is not None else "small"
            row += f" · Size: {size}"

    if node.repeat:
        row += " ⇡ (shown above)"
    elif node.cycle:
        row += " " + styled("↻ (cycle)", ANSI_YELLOW, use_color)
    elif node.truncated:
        adjacent = (
            graph.outgoing(node.issue_id)
            if direction == "out"
            else graph.incoming(node.issue_id)
        )
        row += f" (+{len(adjacent)} more, use --levels 0)"

    # Trailing, like every other bead row: the bead's own creation time is the
    # last cell, after the graph-state markers.
    if issue is not None:
        row += created_cell(issue, use_color=use_color)

    lines = [f"{prefix}{connector}{row}"]
    child_prefix = prefix if is_root else prefix + ("   " if is_last else "│  ")
    if full and node.edge is not None:
        created_at = node.edge.created_at or "(unknown)"
        created_by = node.edge.created_by or "(unknown)"
        lines.append(f"{child_prefix}   added {created_at} by {created_by}")

    for index, child in enumerate(node.children):
        lines.extend(
            _render_tree_node(
                graph,
                child,
                direction=direction,
                full=full,
                use_color=use_color,
                prefix=child_prefix,
                is_last=index == len(node.children) - 1,
                is_root=False,
            )
        )
    return lines


def _tree_stats(walks: tuple[_TreeWalk, ...]) -> _TreeStats:
    issue_ids: set[str] = set()
    active_edges: set[tuple[str, str]] = set()
    longest_chain: tuple[str, ...] = ()
    cycle_paths_by_edges: dict[frozenset[tuple[str, str]], tuple[str, ...]] = {}

    def visit(
        node: DepTraversalNode,
        path: tuple[str, ...],
        path_edges: tuple[tuple[str, str], ...],
    ) -> None:
        nonlocal longest_chain
        issue_ids.add(node.issue_id)
        current_path = (*path, node.issue_id)
        current_edges = path_edges
        if node.edge is not None:
            edge_key = (node.edge.issue_id, node.edge.depends_on_id)
            current_edges = (*path_edges, edge_key)
            if not node.edge.satisfied:
                active_edges.add(edge_key)

        if node.cycle:
            cycle_start = current_path[:-1].index(node.issue_id)
            cycle_edges = frozenset(current_edges[cycle_start:])
            cycle_paths_by_edges.setdefault(cycle_edges, current_path[cycle_start:])
            chain = current_path[:-1]
        elif node.repeat:
            chain = current_path[:-1]
        else:
            chain = current_path
        if len(chain) > len(longest_chain):
            longest_chain = chain

        for child in node.children:
            visit(child, current_path, current_edges)

    for walk in walks:
        for root in walk.roots:
            visit(root, (), ())

    return _TreeStats(
        issue_ids=frozenset(issue_ids),
        depth=len(longest_chain),
        active_edges=frozenset(active_edges),
        longest_chain=longest_chain,
        cycle_paths=tuple(cycle_paths_by_edges.values()),
    )


def _render_dep_tree_json(
    graph: DepGraph,
    walks: tuple[_TreeWalk, ...],
    *,
    scope: str | None,
    direction: Literal["both", "in", "out"],
) -> str:
    return (
        json.dumps(
            {
                "scope": scope,
                "direction": direction,
                "roots": [
                    _tree_node_to_wire(graph, root)
                    for walk in walks
                    for root in walk.roots
                ],
            },
            indent=2,
        )
        + "\n"
    )


def _tree_node_to_wire(
    graph: DepGraph,
    node: DepTraversalNode,
) -> dict[str, object]:
    edge = node.edge
    edge_wire = (
        None
        if edge is None
        else {
            "issue_id": edge.issue_id,
            "depends_on_id": edge.depends_on_id,
            "created_at": edge.created_at,
            "created_by": edge.created_by,
            "satisfied": edge.satisfied,
        }
    )
    return {
        "issue": ref_to_wire_dict(node.issue_id, graph.resolve(node.issue_id)),
        "edge": edge_wire,
        "repeat": node.repeat,
        "cycle": node.cycle,
        "truncated": node.truncated,
        "children": [_tree_node_to_wire(graph, child) for child in node.children],
    }

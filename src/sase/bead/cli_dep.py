"""Dependency command handlers and read-side renderers."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
import json
import os
import sys
from typing import Literal

from sase.bead.cli_common import (
    auto_commit_bead_store,
    bead_store_mutation,
    get_read_view,
)
from sase.bead.cli_detail import ref_to_wire_dict
from sase.bead.dep_graph import DepDirection, DepEdge, DepGraph, DepTraversalNode
from sase.bead.model import Issue, IssueType, Status
from sase.bead_status_presentation import bead_status_presentation

_ANSI_RESET = "\x1b[0m"
_ANSI_BOLD_BLUE = "\x1b[1;34m"
_ANSI_YELLOW = "\x1b[33m"
_ACTIVE_STATUSES = frozenset({Status.OPEN, Status.CLAIMED, Status.IN_PROGRESS})


@dataclass(frozen=True)
class _DisplayedEdge:
    root_id: str
    edge: DepEdge
    direction: DepDirection


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


def handle_bead_dep(args: argparse.Namespace) -> None:
    """Dispatch one ``sase bead dep`` action."""
    if args.dep_action == "add":
        with bead_store_mutation(auto_commit_bead_store) as mutation:
            dep = mutation.project.add_dependency(args.issue, args.depends_on)
            mutation.commit(f"chore(beads): link {dep.issue_id} -> {dep.depends_on_id}")
        print(f"✓ Added dependency: {dep.issue_id} depends on {dep.depends_on_id}")
    elif args.dep_action == "rm":
        with bead_store_mutation(auto_commit_bead_store) as mutation:
            try:
                removed = mutation.project.remove_dependencies(
                    args.issue, args.depends_on
                )
            except KeyError:
                print(f"Error: issue not found: {args.issue}", file=sys.stderr)
                sys.exit(1)
            except ValueError as exc:
                message = str(exc).removeprefix("validation: ")
                print(f"Error: {message}", file=sys.stderr)
                sys.exit(1)
            mutation.commit(
                "chore(beads): unlink "
                f"{args.issue} -> "
                f"{' '.join(dep.depends_on_id for dep in removed)}"
            )
            issues = mutation.project.list_issues()
            status_by_id = {issue.id: issue.status for issue in issues}
            source = next(issue for issue in issues if issue.id == args.issue)
            active_blockers = [
                dependency.depends_on_id
                for dependency in source.dependencies
                if status_by_id.get(dependency.depends_on_id) in _ACTIVE_STATUSES
            ]
            ready_ids = {issue.id for issue in mutation.project.ready()}
        for dependency in removed:
            print(
                "✗ Removed dependency: "
                f"{dependency.issue_id} no longer depends on "
                f"{dependency.depends_on_id}"
            )
        if args.issue in ready_ids:
            print(f"○ {args.issue} is now ready (no active blockers).")
        elif active_blockers:
            blocker_word = "blocker" if len(active_blockers) == 1 else "blockers"
            print(
                f"○ {args.issue} still has {len(active_blockers)} active "
                f"{blocker_word}: {', '.join(active_blockers)}."
            )
        else:
            print(f"○ {args.issue} has no active blockers.")
    elif args.dep_action == "list":
        handle_bead_dep_list(args)
    elif args.dep_action == "tree":
        handle_bead_dep_tree(args)
    else:
        print(f"Unknown dep action: {args.dep_action}", file=sys.stderr)
        sys.exit(1)


def handle_bead_dep_list(args: argparse.Namespace) -> None:
    """List dependency edges with their provenance and blocking state."""
    with get_read_view() as view:
        graph = DepGraph.build(view.list_issues())
        scope = args.id
        if scope is not None and graph.resolve(scope) is None:
            print(f"Error: issue not found: {scope}", file=sys.stderr)
            sys.exit(1)

        displayed = _select_edges(
            graph,
            scope=scope,
            direction=args.direction,
            statuses=(
                frozenset(Status(value) for value in args.status)
                if args.status
                else None
            ),
            limit=args.limit,
        )
        if args.format == "json":
            print(
                _render_dep_list_json(
                    graph,
                    displayed,
                    scope=scope,
                    direction=args.direction,
                ),
                end="",
            )
            return

        if not displayed:
            print(
                "No dependencies found."
                if scope is None
                else f"{scope} has no dependencies."
            )
            return

        use_color = _resolve_color(args.color)
        if scope is not None:
            output = _render_scoped(
                graph,
                displayed,
                scope=scope,
                direction=args.direction,
                full=args.format == "full",
                use_color=use_color,
            )
        else:
            output = _render_store_wide(
                graph,
                displayed,
                full=args.format == "full",
                use_color=use_color,
            )
        print(output, end="")


def handle_bead_dep_tree(args: argparse.Namespace) -> None:
    """Render the dependency graph as one or two terminating trees."""
    with get_read_view() as view:
        graph = DepGraph.build(view.list_issues())
        scope = args.id
        if scope is not None and graph.resolve(scope) is None:
            print(f"Error: issue not found: {scope}", file=sys.stderr)
            sys.exit(1)

        statuses = (
            frozenset(Status(value) for value in args.status)
            if args.status
            else (None if scope is not None else _ACTIVE_STATUSES)
        )
        visible_graph = _visible_tree_graph(graph, scope=scope, statuses=statuses)
        walks = _tree_walks(
            visible_graph,
            scope=scope,
            direction=args.direction,
            levels=args.levels,
        )

        if args.format == "json":
            print(
                _render_dep_tree_json(
                    visible_graph,
                    walks,
                    scope=scope,
                    direction=args.direction,
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
                direction=args.direction,
                full=args.format == "full",
                use_color=_resolve_color(args.color),
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
        row = f"? {_styled(node.issue_id, _ANSI_BOLD_BLUE, use_color)} (not found)"
    else:
        row = _render_issue(issue, label=full, use_color=use_color)
        if full and issue.issue_type == IssueType.PHASE:
            size = issue.size.value if issue.size is not None else "small"
            row += f" · Size: {size}"

    if node.repeat:
        row += " ⇡ (shown above)"
    elif node.cycle:
        row += " " + _styled("↻ (cycle)", _ANSI_YELLOW, use_color)
    elif node.truncated:
        adjacent = (
            graph.outgoing(node.issue_id)
            if direction == "out"
            else graph.incoming(node.issue_id)
        )
        row += f" (+{len(adjacent)} more, use --levels 0)"

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


def _select_edges(
    graph: DepGraph,
    *,
    scope: str | None,
    direction: Literal["both", "in", "out"],
    statuses: frozenset[Status] | None,
    limit: int,
) -> tuple[_DisplayedEdge, ...]:
    if scope is not None:
        allowed = statuses
        selected: list[_DisplayedEdge] = []
        if direction in {"both", "out"}:
            selected.extend(
                _DisplayedEdge(scope, edge, "out")
                for edge in graph.outgoing(scope)
                if _endpoint_is_allowed(graph, edge.depends_on_id, allowed)
            )
        if direction in {"both", "in"}:
            selected.extend(
                _DisplayedEdge(scope, edge, "in")
                for edge in graph.incoming(scope)
                if _endpoint_is_allowed(graph, edge.issue_id, allowed)
            )
        return tuple(selected)

    allowed_roots = statuses if statuses is not None else _ACTIVE_STATUSES
    selected = []
    for edge in graph.edges:
        source = graph.resolve(edge.issue_id)
        target = graph.resolve(edge.depends_on_id)
        source_allowed = source is not None and source.status in allowed_roots
        target_allowed = target is not None and target.status in allowed_roots
        if direction == "out" and source_allowed:
            selected.append(_DisplayedEdge(edge.issue_id, edge, "out"))
        elif direction == "in" and target_allowed:
            selected.append(_DisplayedEdge(edge.depends_on_id, edge, "in"))
        elif direction == "both":
            if source_allowed:
                selected.append(_DisplayedEdge(edge.issue_id, edge, "out"))
            elif target_allowed:
                selected.append(_DisplayedEdge(edge.depends_on_id, edge, "in"))

    if limit == 0:
        return tuple(selected)
    root_ids = list(dict.fromkeys(item.root_id for item in selected))[:limit]
    roots = frozenset(root_ids)
    return tuple(item for item in selected if item.root_id in roots)


def _endpoint_is_allowed(
    graph: DepGraph,
    issue_id: str,
    allowed: frozenset[Status] | None,
) -> bool:
    if allowed is None:
        return True
    issue = graph.resolve(issue_id)
    return issue is None or issue.status in allowed


def _render_scoped(
    graph: DepGraph,
    displayed: tuple[_DisplayedEdge, ...],
    *,
    scope: str,
    direction: Literal["both", "in", "out"],
    full: bool,
    use_color: bool,
) -> str:
    issue = graph.resolve(scope)
    assert issue is not None
    outgoing = tuple(item for item in displayed if item.direction == "out")
    incoming = tuple(item for item in displayed if item.direction == "in")
    lines = [_render_issue(issue, label=True, use_color=use_color)]

    if direction in {"both", "out"} and outgoing:
        lines.extend(["", f"DEPENDS ON ({len(outgoing)})"])
        for item in outgoing:
            lines.extend(
                _render_edge(
                    graph,
                    item,
                    label=True,
                    full=full,
                    use_color=use_color,
                )
            )
    if direction in {"both", "in"} and incoming:
        lines.extend(["", f"BLOCKS ({len(incoming)})"])
        for item in incoming:
            lines.extend(
                _render_edge(
                    graph,
                    item,
                    label=True,
                    full=full,
                    use_color=use_color,
                )
            )

    lines.extend(["", "─" * 60])
    if direction == "in":
        count = len(incoming)
        lines.append(f"Blocks {count} {'bead' if count == 1 else 'beads'}.")
    else:
        active = sum(not item.edge.satisfied for item in outgoing)
        total = len(outgoing)
        lines.append(
            f"Blocked by {active} of {total} "
            f"{'dependency' if total == 1 else 'dependencies'}."
        )
    return "\n".join(lines) + "\n"


def _render_store_wide(
    graph: DepGraph,
    displayed: tuple[_DisplayedEdge, ...],
    *,
    full: bool,
    use_color: bool,
) -> str:
    lines: list[str] = []
    root_ids = list(dict.fromkeys(item.root_id for item in displayed))
    for root_index, root_id in enumerate(root_ids):
        if root_index:
            lines.append("")
        root = graph.resolve(root_id)
        assert root is not None
        lines.append(_render_issue(root, label=full, use_color=use_color))
        for item in displayed:
            if item.root_id == root_id:
                lines.extend(
                    _render_edge(
                        graph,
                        item,
                        label=full,
                        full=full,
                        use_color=use_color,
                    )
                )

    unique_edges = {
        (item.edge.issue_id, item.edge.depends_on_id): item.edge for item in displayed
    }
    satisfied = sum(edge.satisfied for edge in unique_edges.values())
    total = len(unique_edges)
    active = total - satisfied
    lines.extend(
        [
            "",
            "─" * 60,
            (
                f"{total} {'dependency' if total == 1 else 'dependencies'} · "
                f"{len(root_ids)} {'bead' if len(root_ids) == 1 else 'beads'} · "
                f"{satisfied} satisfied · {active} active"
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def _render_issue(issue: Issue, *, label: bool, use_color: bool) -> str:
    presentation = bead_status_presentation(issue.status)
    glyph = _styled(presentation.glyph, presentation.cli_style, use_color)
    issue_id = _styled(issue.id, _ANSI_BOLD_BLUE, use_color)
    suffix = f"   [{presentation.label}]" if label else ""
    return f"{glyph} {issue_id} · {issue.title}{suffix}"


def _render_edge(
    graph: DepGraph,
    displayed: _DisplayedEdge,
    *,
    label: bool,
    full: bool,
    use_color: bool,
) -> list[str]:
    edge = displayed.edge
    endpoint_id = edge.depends_on_id if displayed.direction == "out" else edge.issue_id
    endpoint = graph.resolve(endpoint_id)
    arrow = "→" if displayed.direction == "out" else "←"
    if endpoint is None:
        endpoint_text = (
            f"? {_styled(endpoint_id, _ANSI_BOLD_BLUE, use_color)} (not found)"
        )
        line = f"  {arrow} {endpoint_text}"
    else:
        presentation = bead_status_presentation(endpoint.status)
        glyph = _styled(presentation.glyph, presentation.cli_style, use_color)
        issue_id = _styled(endpoint.id, _ANSI_BOLD_BLUE, use_color)
        status = f"   [{presentation.label}]" if label else ""
        verdict = ""
        if displayed.direction == "out" and label:
            verdict = "   satisfied" if edge.satisfied else "   blocking"
        line = f"  {arrow} {glyph} {issue_id} · {endpoint.title}{status}{verdict}"

    lines = [line]
    if full:
        created_at = edge.created_at or "(unknown)"
        created_by = edge.created_by or "(unknown)"
        lines.append(f"      added {created_at} by {created_by}")
    return lines


def _render_dep_list_json(
    graph: DepGraph,
    displayed: tuple[_DisplayedEdge, ...],
    *,
    scope: str | None,
    direction: Literal["both", "in", "out"],
) -> str:
    edges = []
    for item in displayed:
        edge = item.edge
        edges.append(
            {
                "issue": ref_to_wire_dict(
                    edge.issue_id,
                    graph.resolve(edge.issue_id),
                ),
                "depends_on": ref_to_wire_dict(
                    edge.depends_on_id,
                    graph.resolve(edge.depends_on_id),
                ),
                "created_at": edge.created_at,
                "created_by": edge.created_by,
                "satisfied": edge.satisfied,
                "direction": item.direction,
            }
        )
    return (
        json.dumps(
            {
                "scope": scope,
                "direction": direction,
                "count": len(edges),
                "edges": edges,
            },
            indent=2,
        )
        + "\n"
    )


def _resolve_color(color: str) -> bool:
    if color == "always":
        return True
    if color == "never":
        return False
    if os.environ.get("NO_COLOR") is not None:
        return False
    return sys.stdout.isatty()


def _styled(value: str, style: str, use_color: bool) -> str:
    if not use_color:
        return value
    return f"{style}{value}{_ANSI_RESET}"

"""Dependency command handlers and read-side renderers."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
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
from sase.bead.dep_graph import DepDirection, DepEdge, DepGraph
from sase.bead.model import Issue, Status
from sase.bead_status_presentation import bead_status_presentation

_ANSI_RESET = "\x1b[0m"
_ANSI_BOLD_BLUE = "\x1b[1;34m"
_ACTIVE_STATUSES = frozenset({Status.OPEN, Status.CLAIMED, Status.IN_PROGRESS})


@dataclass(frozen=True)
class _DisplayedEdge:
    root_id: str
    edge: DepEdge
    direction: DepDirection


def handle_bead_dep(args: argparse.Namespace) -> None:
    """Dispatch one ``sase bead dep`` action."""
    if args.dep_action == "add":
        with bead_store_mutation(auto_commit_bead_store) as mutation:
            dep = mutation.project.add_dependency(args.issue, args.depends_on)
            mutation.commit(f"chore(beads): link {dep.issue_id} -> {dep.depends_on_id}")
        print(f"✓ Added dependency: {dep.issue_id} depends on {dep.depends_on_id}")
    elif args.dep_action == "list":
        handle_bead_dep_list(args)
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

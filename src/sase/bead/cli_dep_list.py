"""Selection and rendering for ``sase bead dep list``."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Literal

from sase.bead.cli_dep_render import (
    ACTIVE_STATUSES,
    ANSI_BOLD_BLUE,
    render_issue,
    resolve_color,
    styled,
)
from sase.bead.cli_common import created_cell
from sase.bead.cli_detail import ref_to_wire_dict
from sase.bead.dep_graph import DepDirection, DepEdge, DepGraph
from sase.bead.model import Status
from sase.bead_status_presentation import bead_status_presentation


@dataclass(frozen=True)
class _DisplayedEdge:
    root_id: str
    edge: DepEdge
    direction: DepDirection


def print_bead_dep_list(
    graph: DepGraph,
    *,
    scope: str | None,
    direction: Literal["both", "in", "out"],
    statuses: frozenset[Status] | None,
    limit: int,
    output_format: str,
    color: str,
) -> None:
    """Select and print dependency edges from a prebuilt graph."""
    displayed = _select_edges(
        graph,
        scope=scope,
        direction=direction,
        statuses=statuses,
        limit=limit,
    )
    if output_format == "json":
        print(
            _render_dep_list_json(
                graph,
                displayed,
                scope=scope,
                direction=direction,
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

    use_color = resolve_color(color)
    if scope is not None:
        output = _render_scoped(
            graph,
            displayed,
            scope=scope,
            direction=direction,
            full=output_format == "full",
            use_color=use_color,
        )
    else:
        output = _render_store_wide(
            graph,
            displayed,
            full=output_format == "full",
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

    allowed_roots = statuses if statuses is not None else ACTIVE_STATUSES
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
    lines = [
        render_issue(issue, label=True, use_color=use_color)
        + created_cell(issue, use_color=use_color)
    ]

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
        lines.append(
            render_issue(root, label=full, use_color=use_color)
            + created_cell(root, use_color=use_color)
        )
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
            f"? {styled(endpoint_id, ANSI_BOLD_BLUE, use_color)} (not found)"
        )
        line = f"  {arrow} {endpoint_text}"
    else:
        presentation = bead_status_presentation(endpoint.status)
        glyph = styled(presentation.glyph, presentation.cli_style, use_color)
        issue_id = styled(endpoint.id, ANSI_BOLD_BLUE, use_color)
        status = f"   [{presentation.label}]" if label else ""
        verdict = ""
        if displayed.direction == "out" and label:
            verdict = "   satisfied" if edge.satisfied else "   blocking"
        created = created_cell(endpoint, use_color=use_color)
        line = (
            f"  {arrow} {glyph} {issue_id} · {endpoint.title}{status}{verdict}{created}"
        )

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

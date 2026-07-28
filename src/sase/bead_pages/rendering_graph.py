"""Bounded Mermaid lineage graphs for root bead pages."""

from __future__ import annotations

from collections.abc import Iterable

from sase.agents_sync.rendering_markdown import md_mermaid
from sase.bead.model import Issue
from sase.bead_pages.paths import bead_lineage_root

MAX_RENDERED_LINEAGE_NODES = 50


def render_lineage_graph(root: Issue, issues: Iterable[Issue]) -> list[str]:
    """Render a root lineage graph, omitting graphs above the node cap."""

    if root.id != bead_lineage_root(root.id):
        return []
    lineage = _lineage_issues(root.id, issues)
    if not lineage or len(lineage) > MAX_RENDERED_LINEAGE_NODES:
        return []
    node_ids = {issue.id: f"n{index}" for index, issue in enumerate(lineage)}
    lines = ["", "## Lineage", "", "```mermaid", "flowchart TD"]
    for issue in lineage:
        label = md_mermaid(f"{issue.id}: {issue.title} [{issue.status.value}]")
        lines.append(f'    {node_ids[issue.id]}["{label}"]')
    for issue in lineage:
        if issue.parent_id in node_ids:
            lines.append(f"    {node_ids[issue.parent_id]} --> {node_ids[issue.id]}")
    dependencies = sorted(
        {
            (dependency.depends_on_id, issue.id)
            for issue in lineage
            for dependency in issue.dependencies
            if dependency.depends_on_id in node_ids
        }
    )
    for dependency_id, issue_id in dependencies:
        lines.append(f"    {node_ids[dependency_id]} -.-> {node_ids[issue_id]}")
    lines.append("```")
    return lines


def _lineage_issues(root_id: str, issues: Iterable[Issue]) -> tuple[Issue, ...]:
    by_id = {issue.id: issue for issue in issues}
    if root_id not in by_id:
        return ()
    included = [
        issue for issue in by_id.values() if _stored_root(issue.id, by_id) == root_id
    ]
    return tuple(sorted(included, key=lambda issue: issue.id))


def _stored_root(bead_id: str, by_id: dict[str, Issue]) -> str | None:
    current = bead_id
    seen: set[str] = set()
    while current not in seen:
        seen.add(current)
        issue = by_id.get(current)
        if issue is None:
            return None
        if issue.parent_id is None:
            return issue.id
        current = issue.parent_id
    return None


__all__ = ["MAX_RENDERED_LINEAGE_NODES", "render_lineage_graph"]

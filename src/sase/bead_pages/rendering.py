"""Deterministic Markdown rendering for published bead pages."""

from __future__ import annotations

from sase.agents_sync.rendering_markdown import page_bytes
from sase.bead.cli_detail import resolve_issue_detail
from sase.bead.model import Issue
from sase.bead.project import BeadProject
from sase.bead_pages.associations import BeadAssociationIndex
from sase.bead_pages.paths import bead_lineage_root
from sase.bead_pages.rendering_graph import render_lineage_graph
from sase.bead_pages.rendering_identity import (
    PlanLinkResolver,
    render_identity,
    render_prose_sections,
)
from sase.bead_pages.rendering_tables import (
    render_agents,
    render_commits,
    render_dependencies,
    render_phases,
)


def render_bead_page(
    view: BeadProject,
    issue: Issue,
    association_index: BeadAssociationIndex,
    *,
    link_resolver: PlanLinkResolver | None = None,
) -> str:
    """Render one timestamp-free, byte-stable bead page."""

    detail = resolve_issue_detail(view, issue)
    associations = association_index.for_bead(issue.id)
    lines = render_identity(detail, plan_links=link_resolver)
    lines.extend(render_prose_sections(issue))
    if issue.id == bead_lineage_root(issue.id):
        lines.extend(render_phases(detail, association_index))
        lines.extend(render_lineage_graph(issue, view.list_issues()))
    lines.extend(render_dependencies(detail))
    lines.extend(render_agents(issue, associations.agents))
    lines.extend(render_commits(issue, associations.commits))
    return "\n".join(lines).rstrip() + "\n"


def render_bead_page_bytes(
    view: BeadProject,
    issue: Issue,
    association_index: BeadAssociationIndex,
    *,
    link_resolver: PlanLinkResolver | None = None,
) -> bytes:
    """Render one bead page as its final publication payload."""

    return page_bytes(
        render_bead_page(
            view,
            issue,
            association_index,
            link_resolver=link_resolver,
        )
    )


__all__ = ["render_bead_page", "render_bead_page_bytes"]

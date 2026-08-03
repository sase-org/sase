"""Deterministic Markdown rendering for published bead pages."""

from __future__ import annotations

from sase.agents_sync.rendering_markdown import page_bytes
from sase.agents_sync.rendering_markdown import md_code, relative_page_url
from sase.bead.cli_detail import IssueDetail, resolve_issue_detail
from sase.bead.model import Issue
from sase.bead.project import BeadProject
from sase.bead_pages.associations import BeadAssociationIndex
from sase.bead_pages.paths import bead_lineage_root
from sase.bead_pages.rendering_graph import render_lineage_graph
from sase.bead_pages.rendering_identity import (
    PlanLinkResolver,
    render_identity,
    render_plus_one_evidence,
    render_prose_sections,
    render_references,
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
    return _render_bead_page_from_detail(
        detail,
        view.list_issues(),
        association_index,
        link_resolver=link_resolver,
    )


def _render_bead_page_from_detail(
    detail: IssueDetail,
    all_issues: tuple[Issue, ...] | list[Issue],
    association_index: BeadAssociationIndex,
    *,
    link_resolver: PlanLinkResolver | None = None,
) -> str:
    """Render one page from a pre-resolved bead detail snapshot."""

    issue = detail.issue
    associations = association_index.for_bead(issue.id)
    lines = render_identity(detail, plan_links=link_resolver)
    lines.extend(render_prose_sections(issue))
    lines.extend(render_plus_one_evidence(issue, plan_links=link_resolver))
    lines.extend(render_references(issue, plan_links=link_resolver))
    if issue.id == bead_lineage_root(issue.id):
        lines.extend(render_phases(detail, association_index))
        lines.extend(render_lineage_graph(issue, all_issues))
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


def render_bead_page_detail_bytes(
    detail: IssueDetail,
    all_issues: tuple[Issue, ...],
    association_index: BeadAssociationIndex,
    *,
    link_resolver: PlanLinkResolver | None = None,
) -> bytes:
    """Render one pre-resolved bead page as its final publication payload."""

    return page_bytes(
        _render_bead_page_from_detail(
            detail,
            all_issues,
            association_index,
            link_resolver=link_resolver,
        )
    )


def render_bead_alias_page_bytes(old_id: str, canonical_id: str) -> bytes:
    """Render one deterministic compatibility page for a historical bead ID."""

    from sase.bead_pages.paths import bead_page_path

    source = bead_page_path(old_id).removeprefix("pages/")
    target = bead_page_path(canonical_id).removeprefix("pages/")
    relative_target = relative_page_url(source, target)
    return page_bytes(
        "<!-- sase:bead-id-alias -->\n\n"
        "# Bead moved\n\n"
        f"Historical ID `{md_code(old_id)}` now resolves to "
        f"[`{md_code(canonical_id)}`]({relative_target}).\n"
    )


__all__ = [
    "render_bead_page",
    "render_bead_alias_page_bytes",
    "render_bead_page_bytes",
    "render_bead_page_detail_bytes",
]

"""Deterministic Markdown rendering for published bead pages."""

from __future__ import annotations

from sase.agents_sync.rendering_markdown import page_bytes
from sase.bead.cli_detail import IssueDetail, resolve_issue_detail
from sase.bead.model import Issue
from sase.bead.project import BeadProject
from sase.bead_pages.associations import BeadAssociationIndex
from sase.bead_pages.paths import bead_lineage_root
from sase.bead_pages.rendering_graph import render_lineage_graph
from sase.bead_pages.rendering_identity import (
    PlanLinkResolver,
    render_close_history,
    render_flag,
    render_identity,
    render_plus_one_evidence,
    render_prose_sections,
    render_references,
    render_snooze,
)
from sase.bead_pages.rendering_links import apply_bead_page_link_tables
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
    extra_link_rows: tuple[dict[str, object], ...] = (),
) -> str:
    """Render one timestamp-free, byte-stable bead page."""

    detail = resolve_issue_detail(view, issue)
    return _render_bead_page_from_detail(
        detail,
        view.list_issues(),
        association_index,
        link_resolver=link_resolver,
        extra_link_rows=extra_link_rows,
    )


def _render_bead_page_from_detail(
    detail: IssueDetail,
    all_issues: tuple[Issue, ...] | list[Issue],
    association_index: BeadAssociationIndex,
    *,
    link_resolver: PlanLinkResolver | None = None,
    extra_link_rows: tuple[dict[str, object], ...] = (),
) -> str:
    """Render one page from a pre-resolved bead detail snapshot."""

    issue = detail.issue
    associations = association_index.for_bead(issue.id)
    identity = render_identity(detail, plan_links=link_resolver)
    identity.extend(render_snooze(issue))
    identity.extend(render_flag(issue))
    identity.extend(render_close_history(issue))
    rest = render_prose_sections(issue)
    rest.extend(render_plus_one_evidence(issue, plan_links=link_resolver))
    rest.extend(render_references(issue, plan_links=link_resolver))
    if issue.id == bead_lineage_root(issue.id):
        rest.extend(render_phases(detail, association_index))
        rest.extend(render_lineage_graph(issue, all_issues))
    rest.extend(render_dependencies(detail))
    rest.extend(render_agents(issue, associations.agents))
    rest.extend(render_commits(issue, associations.commits))
    document = "\n".join([*identity, *rest]).rstrip() + "\n"
    return apply_bead_page_link_tables(
        document,
        issue,
        tuple(all_issues),
        extra_rows=extra_link_rows,
        link_urls=_link_urls(tuple(all_issues), extra_link_rows, link_resolver),
        identity_line_count=len(identity),
    )


def render_bead_page_bytes(
    view: BeadProject,
    issue: Issue,
    association_index: BeadAssociationIndex,
    *,
    link_resolver: PlanLinkResolver | None = None,
    extra_link_rows: tuple[dict[str, object], ...] = (),
) -> bytes:
    """Render one bead page as its final publication payload."""

    return page_bytes(
        render_bead_page(
            view,
            issue,
            association_index,
            link_resolver=link_resolver,
            extra_link_rows=extra_link_rows,
        )
    )


def render_bead_page_detail_bytes(
    detail: IssueDetail,
    all_issues: tuple[Issue, ...],
    association_index: BeadAssociationIndex,
    *,
    link_resolver: PlanLinkResolver | None = None,
    extra_link_rows: tuple[dict[str, object], ...] = (),
) -> bytes:
    """Render one pre-resolved bead page as its final publication payload."""

    return page_bytes(
        _render_bead_page_from_detail(
            detail,
            all_issues,
            association_index,
            link_resolver=link_resolver,
            extra_link_rows=extra_link_rows,
        )
    )


def _link_urls(
    all_issues: tuple[Issue, ...],
    extra_rows: tuple[dict[str, object], ...],
    link_resolver: PlanLinkResolver | None,
) -> dict[str, str]:
    urls: dict[str, str] = {}
    if link_resolver is None:
        return urls
    refs: set[str] = set()
    for issue in all_issues:
        for link in issue.links:
            refs.add(link.target_ref)
        refs.add(f"bead:{issue.id}")
    for row in extra_rows:
        refs.add(str(row.get("source_ref") or ""))
        refs.add(str(row.get("target_ref") or ""))
    for ref in refs:
        url = _url_for_ref(link_resolver, ref)
        if url:
            urls[ref] = url
    return urls


def _url_for_ref(link_resolver: PlanLinkResolver, ref: str) -> str | None:
    kind, _sep, rest = ref.partition(":")
    bead_url = getattr(link_resolver, "bead_url", None)
    plan_url = getattr(link_resolver, "plan_url", None)
    agent_url = getattr(link_resolver, "agent_url", None)
    commit_url = getattr(link_resolver, "commit_url", None)
    if kind == "bead" and callable(bead_url):
        return bead_url(rest)
    if kind == "plan" and callable(plan_url):
        return plan_url(ref)
    if kind == "agent" and callable(agent_url):
        return agent_url(rest)
    if kind == "stitch" and callable(commit_url):
        _repo, _sep, sha = rest.partition("@")
        return commit_url(sha) if sha else None
    return None


__all__ = [
    "render_bead_page",
    "render_bead_page_bytes",
    "render_bead_page_detail_bytes",
]

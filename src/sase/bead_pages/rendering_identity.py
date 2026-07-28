"""Identity, breadcrumb, and prose rendering for bead pages."""

from __future__ import annotations

from datetime import UTC, datetime
import re
from typing import Protocol

from sase.agents_sync.rendering_markdown import md_cell, md_code, md_escape
from sase.bead.cli_common import status_icon
from sase.bead.cli_detail import IssueDetail
from sase.bead.model import Issue, Status
from sase.bead_pages.paths import bead_lineage_root

MAX_RENDERED_PROSE_CHARS = 10_000

_STRUCTURAL_PROSE_RE = re.compile(r"^(\s{0,3})(#{1,6}(?:\s|$)|`{3,}|~{3,})")


class PlanLinkResolver(Protocol):
    """The hosted-link capability needed by the page renderer."""

    def plan_url(self, plan_ref: str) -> str | None: ...


def render_identity(
    detail: IssueDetail,
    *,
    plan_links: PlanLinkResolver | None,
) -> list[str]:
    """Render title, breadcrumb, stable bead facts, and plan reference."""

    issue = detail.issue
    lines = [
        f"# Bead: {md_cell(issue.id)} — {md_cell(issue.title)}",
        "",
        _breadcrumb(issue),
        "",
        _primary_facts(issue),
    ]
    ownership = _ownership_facts(issue)
    if ownership:
        lines.append(ownership)
    lifecycle = _lifecycle_facts(issue)
    if lifecycle:
        lines.append(lifecycle)
    plan = _plan_fact(detail, plan_links)
    if plan:
        lines.append(plan)
    return lines


def render_prose_sections(issue: Issue) -> list[str]:
    """Render bounded free-form prose without allowing structural injection."""

    lines: list[str] = []
    for heading, value in (("Description", issue.description), ("Notes", issue.notes)):
        if not value:
            continue
        lines.extend(["", f"## {heading}", "", _bounded_prose(value)])
    return lines


def _breadcrumb(issue: Issue) -> str:
    root = bead_lineage_root(issue.id)
    if issue.id == root:
        return f"[Bead Pages](../README.md) / {md_escape(issue.id)}"
    parent = issue.parent_id or root
    parent_href = "README.md" if parent == root else f"{parent}.md"
    return (
        "[Bead Pages](../README.md) / "
        f"[{md_escape(parent)}]({parent_href}) / {md_escape(issue.id)}"
    )


def _primary_facts(issue: Issue) -> str:
    values = [
        f"**Status:** {status_icon(issue.status)} {issue.status.value}",
        f"**Type:** {issue.issue_type.value}",
    ]
    if issue.tier is not None:
        values.append(f"**Tier:** {issue.tier.value}")
    if issue.status == Status.CLOSED:
        resolution = issue.resolution.value if issue.resolution else "(unrecorded)"
        values.insert(1, f"**Resolution:** {resolution}")
    return " · ".join(values)


def _ownership_facts(issue: Issue) -> str:
    values: list[str] = []
    if issue.owner:
        values.append(f"**Owner:** `{md_code(issue.owner)}`")
    if issue.assignee:
        values.append(f"**Assignee:** `{md_code(issue.assignee)}`")
    if issue.size is not None:
        values.append(f"**Size:** {issue.size.value}")
    return " · ".join(values)


def _lifecycle_facts(issue: Issue) -> str:
    values: list[str] = []
    if issue.created_at:
        values.append(f"**Created:** {_render_instant(issue.created_at)}")
    if issue.closed_at:
        values.append(f"**Closed:** {_render_instant(issue.closed_at)}")
    return " · ".join(values)


def _plan_fact(
    detail: IssueDetail,
    resolver: PlanLinkResolver | None,
) -> str:
    if detail.plan is None:
        return ""
    plan_ref = detail.plan.path
    label = plan_ref.removeprefix("plans:")
    target = resolver.plan_url(plan_ref) if resolver is not None else None
    rendered = md_escape(label)
    if target:
        rendered = f"[{rendered}]({target})"
    return f"**Plan:** {rendered}"


def _render_instant(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    except ValueError:
        return md_escape(value)


def _bounded_prose(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    hidden = max(0, len(normalized) - MAX_RENDERED_PROSE_CHARS)
    visible = normalized[:MAX_RENDERED_PROSE_CHARS].rstrip() if hidden else normalized
    safe_lines = [_neutralize_structural_line(line) for line in visible.splitlines()]
    if hidden:
        safe_lines.extend(["", f"… and {hidden} more characters"])
    return "\n".join(safe_lines)


def _neutralize_structural_line(line: str) -> str:
    return _STRUCTURAL_PROSE_RE.sub(r"\1\\\2", line, count=1)


__all__ = [
    "MAX_RENDERED_PROSE_CHARS",
    "PlanLinkResolver",
    "render_identity",
    "render_prose_sections",
]

"""Identity, breadcrumb, and prose rendering for bead pages."""

from __future__ import annotations

import re
from typing import Protocol, runtime_checkable

from sase.agents_sync.rendering_markdown import md_cell, md_code, md_escape
from sase.bead.cli_common import status_icon
from sase.bead.cli_detail import IssueDetail
from sase.bead.model import Issue, IssueType, Status
from sase.bead.plus_one_presentation import (
    PLUS_ONE_SECTION_LABEL,
    POST_CLOSE_EVIDENCE_MARKER,
    evidence_recorded_after_current_close,
    post_close_plus_one_badge,
    post_close_plus_one_count,
    plus_one_badge,
)
from sase.bead.reopen_presentation import (
    REOPEN_GLYPH,
    REOPEN_SECTION_LABEL,
    close_history_display_order,
    close_record_label,
    close_record_reopened_label,
    reopen_badge,
)
from sase.bead.snooze_presentation import (
    SNOOZE_SECTION_LABEL,
    snooze_plus_one_label,
)
from sase.bead_pages.paths import bead_lineage_root
from sase.bead_time_presentation import BEAD_TIME_UNKNOWN_LABEL, bead_instant_label
from sase.bead_type_presentation import bead_type_presentation
from sase.task_type_presentation import task_type_presentation
from sase.task_types import (
    TASK_TYPE_BODY_SEPARATOR,
    issue_task_type_slug,
    render_task_type_display_block,
)
from sase.sdd.plan_refs import PLAN_REFERENCE_KIND, PLAN_REFERENCE_PREFIX

MAX_RENDERED_PROSE_CHARS = 10_000

_STRUCTURAL_PROSE_RE = re.compile(r"^(\s{0,3})(#{1,6}(?:\s|$)|`{3,}|~{3,})")


class PlanLinkResolver(Protocol):
    """The hosted-link capability needed by the page renderer."""

    def plan_url(self, plan_ref: str) -> str | None: ...


@runtime_checkable
class _AgentLinkResolver(Protocol):
    def agent_url(self, agent_name: str) -> str | None: ...


@runtime_checkable
class _BeadLinkResolver(Protocol):
    def bead_url(self, bead_id: str) -> str | None: ...


@runtime_checkable
class _CommitLinkResolver(Protocol):
    def commit_url(self, sha: str) -> str | None: ...


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
    ownership = _ownership_facts(issue, plan_links)
    if ownership:
        lines.append(ownership)
    lifecycle = _lifecycle_facts(issue)
    if lifecycle:
        lines.append(lifecycle)
    plan = _plan_fact(detail, plan_links)
    if plan:
        lines.append(plan)
    return lines


def render_references(
    issue: Issue,
    *,
    plan_links: PlanLinkResolver | None,
) -> list[str]:
    """Render the bead's stored artifact references as a bullet list.

    A published page is a public artifact, so a reference the resolver cannot
    turn into a hosted URL renders as escaped plain text rather than as a
    broken link.
    """

    if not issue.refs:
        return []
    lines = ["", "## References", ""]
    lines.extend(
        f"- {_reference_item(reference, plan_links)}" for reference in issue.refs
    )
    return lines


def render_prose_sections(issue: Issue) -> list[str]:
    """Render bounded free-form prose without allowing structural injection."""

    lines: list[str] = []
    description = issue.description
    body = render_task_type_display_block(issue)
    if description.strip() or body:
        lines.extend(["", "## Description"])
        if description.strip():
            lines.extend(["", _bounded_prose(description)])
        if body:
            if description.strip():
                lines.extend(["", TASK_TYPE_BODY_SEPARATOR, ""])
            else:
                lines.append("")
            lines.append(_bounded_prose(body))
    if issue.notes.strip():
        lines.extend(["", "## Notes", "", _bounded_prose(issue.notes)])
    return lines


def render_plus_one_evidence(
    issue: Issue,
    *,
    plan_links: PlanLinkResolver | None,
) -> list[str]:
    """Render bounded, structurally safe corroboration callouts."""

    if not issue.plus_one_evidence:
        return []
    lines = ["", f"## {PLUS_ONE_SECTION_LABEL.title()}", ""]
    evidence_rows = sorted(
        issue.plus_one_evidence,
        key=lambda item: (item.timestamp, item.reporter, item.note, item.refs),
    )
    for index, evidence in enumerate(evidence_rows):
        if index:
            lines.append("")
        instant = _render_instant(evidence.timestamp)
        marker = (
            f" · **{md_escape(POST_CLOSE_EVIDENCE_MARKER)}**"
            if evidence_recorded_after_current_close(issue, evidence)
            else ""
        )
        lines.append(f"> **+1** by `{md_code(evidence.reporter)}` · {instant}{marker}")
        if evidence.observed_since:
            lines.append(
                f"> **Observed since:** {_render_instant(evidence.observed_since)}"
            )
        lines.append(">")
        lines.extend(
            f"> {line}" if line else ">"
            for line in _bounded_prose(evidence.note).splitlines()
        )
        if evidence.refs:
            lines.append(">")
            refs = ", ".join(
                _reference_item(reference, plan_links) for reference in evidence.refs
            )
            lines.append(f"> **References:** {refs}")
    return lines


def render_snooze(issue: Issue) -> list[str]:
    """Render the wake conditions of a snoozed task.

    A published page is byte-stable, so this renders the absolute wake
    instant only; the relative "in 3d" form belongs to surfaces that are
    re-rendered on every read.
    """

    record = issue.snooze
    if record is None:
        return []
    lines = ["", f"## {SNOOZE_SECTION_LABEL.title()}", ""]
    lines.append(f"> **Until:** {_render_instant(record.until)}")
    lines.append(
        f"> **Snoozed by:** `{md_code(record.snoozed_by)}`"
        f" · {_render_instant(record.snoozed_at)}"
    )
    if plus_one := snooze_plus_one_label(issue):
        lines.append(f"> **+1 target:** {md_escape(plus_one)}")
    if record.reason:
        lines.append(">")
        lines.extend(
            f"> {line}" if line else ">"
            for line in _bounded_prose(record.reason).splitlines()
        )
    return lines


def render_flag(issue: Issue) -> list[str]:
    """Render stable feature-flag identity for published bead pages."""
    record = issue.flag
    if record is None:
        return []
    return [
        "",
        "## Flag",
        "",
        f"- **Key:** `{md_code(record.key)}`",
        f"- **Remove by date:** `{md_code(record.remove_by_date)}`",
        f"- **Remove by release:** `v{md_code(record.remove_by_release)}`",
        "- **Due states:** `live`, `soon`, `due`",
    ]


def render_close_history(issue: Issue) -> list[str]:
    """Render bounded, structurally safe archived close callouts."""

    if not issue.close_history:
        return []
    lines = ["", f"## {REOPEN_SECTION_LABEL.title()}", ""]
    records = close_history_display_order(issue.close_history)
    for index, record in enumerate(records):
        if index:
            lines.append("")
        lines.append(f"> {close_record_label(record)}")
        lines.append(">")
        reason = record.close_reason if record.close_reason else "(none)"
        lines.extend(
            f"> {line}" if line else ">" for line in _bounded_prose(reason).splitlines()
        )
        lines.append(">")
        lines.append(f"> {close_record_reopened_label(record)}")
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
        f"**Type:** {bead_type_presentation(issue.issue_type).glyph}"
        f" {issue.issue_type.value}",
    ]
    if issue.tier is not None:
        values.append(f"**Tier:** {issue.tier.value}")
    if issue.issue_type is IssueType.TASK:
        task_presentation = task_type_presentation(issue.task_type)
        task_slug = issue_task_type_slug(issue.task_type)
        values.append(f"**Task type:** {task_presentation.glyph} {md_code(task_slug)}")
    if issue.flag is not None:
        glyph = bead_type_presentation("flag").glyph
        values.append(f"**Flag:** {glyph} `{md_code(issue.flag.key)}`")
    if badge := plus_one_badge(issue.plus_one_count):
        values.append(f"**+1 reports:** {badge}")
    if badge := post_close_plus_one_badge(post_close_plus_one_count(issue)):
        values.append(f"**Post-close +1:** {md_escape(badge)}")
    if badge := reopen_badge(len(issue.close_history)):
        values.append(f"**{REOPEN_GLYPH} Reopened:** {badge}")
    if issue.status == Status.CLOSED:
        resolution = issue.resolution.value if issue.resolution else "(unrecorded)"
        values.insert(1, f"**Resolution:** {resolution}")
    return " · ".join(values)


def _ownership_facts(issue: Issue, resolver: PlanLinkResolver | None) -> str:
    values: list[str] = []
    if issue.owner:
        values.append(f"**Owner:** `{md_code(issue.owner)}`")
    if issue.created_by:
        values.append(
            f"**Created by:** {_created_by_value(issue.created_by, resolver)}"
        )
    if issue.assignee:
        values.append(f"**Assignee:** `{md_code(issue.assignee)}`")
    if issue.size is not None:
        values.append(f"**Size:** {issue.size.value}")
    return " · ".join(values)


def _created_by_value(
    created_by: str,
    resolver: PlanLinkResolver | None,
) -> str:
    label = md_escape(created_by)
    target = None
    if isinstance(resolver, _AgentLinkResolver):
        target = resolver.agent_url(created_by)
    return f"[{label}]({target})" if target else f"`{md_code(created_by)}`"


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
    label = plan_ref.removeprefix(PLAN_REFERENCE_PREFIX)
    target = resolver.plan_url(plan_ref) if resolver is not None else None
    rendered = md_escape(label)
    if target:
        rendered = f"[{rendered}]({target})"
    return f"**Plan:** {rendered}"


def _reference_item(reference: str, resolver: PlanLinkResolver | None) -> str:
    label = md_escape(reference)
    target = _reference_url(reference, resolver)
    return f"[{label}]({target})" if target else label


def _reference_url(reference: str, resolver: PlanLinkResolver | None) -> str | None:
    """Return the hosted URL for *reference*, or ``None`` when there is none."""

    if resolver is None:
        return None
    from sase.artifact_ref_operations import parse_artifact_ref

    try:
        parsed = parse_artifact_ref(reference)
    except Exception:
        return None
    payload = parsed.payload
    try:
        if parsed.kind_type == "document" and parsed.kind == PLAN_REFERENCE_KIND:
            return resolver.plan_url(parsed.rendered)
        if parsed.kind_type == "bead" and payload.id:
            if isinstance(resolver, _BeadLinkResolver):
                return resolver.bead_url(payload.id)
        elif parsed.kind_type == "agent" and payload.name:
            if isinstance(resolver, _AgentLinkResolver):
                return resolver.agent_url(payload.name)
        elif parsed.kind_type == "commit" and payload.sha:
            if isinstance(resolver, _CommitLinkResolver):
                return resolver.commit_url(payload.sha)
    except Exception:
        return None
    return None


def _render_instant(value: str) -> str:
    label = bead_instant_label(value)
    if label == BEAD_TIME_UNKNOWN_LABEL:
        return md_escape(value)
    return label


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
    "render_flag",
    "render_close_history",
    "render_identity",
    "render_plus_one_evidence",
    "render_prose_sections",
    "render_references",
]

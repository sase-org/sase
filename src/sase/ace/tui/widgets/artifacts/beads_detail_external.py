"""External issue link rendering for the shared bead presentation."""

from __future__ import annotations

from rich.text import Text

from sase.bead.model import Issue
from sase.core.time import format_local

from .beads_data_models import ExternalIssueLink
from .types import EXTERNAL_ACCENT

_REMOTE_BODY_PREVIEW_CHARS = 4000


def external_issue_property_text(
    links: tuple[ExternalIssueLink, ...],
) -> Text:
    if not links:
        return Text("—", style="dim")
    text = Text()
    for index, link in enumerate(links):
        if index:
            text.append("\n")
        text.append(_external_issue_chip_label(link), style=_external_issue_style(link))
        text.append(f" {link.relation}", style="dim")
        if link.issue is not None and link.issue.title:
            text.append(f"  {link.issue.title}", style="white")
        elif link.stale:
            text.append("  not present in cached issue list", style=EXTERNAL_ACCENT)
        if link.drift:
            text.append("  drift", style=f"bold {EXTERNAL_ACCENT}")
    return text


def external_issue_markdown(
    issue: Issue,
    links: tuple[ExternalIssueLink, ...],
) -> list[str]:
    if not links:
        return []
    lines = ["## External Issues", ""]
    for index, link in enumerate(links):
        if index:
            lines.append("")
        lines.append(f"### {external_issue_inline(link)}")
        details = [
            f"- Relation: {link.relation}",
            f"- Project: {link.display_project}",
            f"- State: {link.state}",
            f"- Ref: `{link.external_ref}`",
        ]
        if link.issue is not None:
            details.extend(
                [
                    f"- Title: {link.issue.title}",
                    f"- Author: {link.issue.author or '(unknown)'}",
                    f"- Comments: {link.issue.comment_count}",
                    f"- Updated: {format_local(link.issue.updated_at, default='')}",
                ]
            )
            if link.issue.labels:
                details.append(f"- Labels: {', '.join(link.issue.labels)}")
            if link.issue.assignees:
                details.append(f"- Assignees: {', '.join(link.issue.assignees)}")
            if link.issue.url:
                details.append(f"- URL: {link.issue.url}")
        if link.stale:
            details.append("- Cache: stale local link, absent from complete issue list")
        if link.drift:
            details.append("- Drift: mirrored local bead differs from cached issue")
        reverse_beads = tuple(
            bead.id for bead in link.reverse_beads if bead.id != issue.id
        )
        if reverse_beads:
            details.append(f"- Linked beads: {', '.join(reverse_beads)}")
        if link.reverse_patches:
            details.append(
                f"- Linked Patches: {', '.join(patch.name for patch in link.reverse_patches)}"
            )
        lines.extend(details)
        if link.issue is not None:
            body = link.issue.body.strip()
            if body:
                lines.extend(["", "#### Remote Body Preview", "", _preview_body(body)])
    lines.append("")
    return lines


def external_issue_inline(link: ExternalIssueLink) -> str:
    state = link.state
    flags = [
        flag
        for flag, active in (("stale", link.stale), ("drift", link.drift))
        if active
    ]
    suffix = f" ({', '.join(flags)})" if flags else ""
    return f"{link.display_project} #{link.issue_id} · {state}{suffix}"


def _external_issue_chip_label(link: ExternalIssueLink) -> str:
    glyph = (
        "?"
        if link.stale
        else "●"
        if link.issue and link.issue.state == "closed"
        else "○"
    )
    return f"{glyph}#{link.issue_id}"


def _external_issue_style(link: ExternalIssueLink) -> str:
    if link.stale or link.drift:
        return f"bold #1a1a1a on {EXTERNAL_ACCENT}"
    return f"bold {EXTERNAL_ACCENT}"


def _preview_body(body: str) -> str:
    if len(body) <= _REMOTE_BODY_PREVIEW_CHARS:
        return body
    return f"{body[:_REMOTE_BODY_PREVIEW_CHARS].rstrip()}\n\n_(truncated)_"


__all__ = [
    "external_issue_inline",
    "external_issue_markdown",
    "external_issue_property_text",
]

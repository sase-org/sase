"""Pure Rich render helpers for tracker issues in the Bugs pane."""

from __future__ import annotations

from datetime import datetime

from rich.text import Text

from sase.core.time import local_now, to_local
from sase.vcs_provider import IssueWire

from .types import ARTIFACTS_ACCENTS

BUG_ACCENT = ARTIFACTS_ACCENTS["bugs"]


def issue_row(issue: IssueWire) -> Text:
    text = Text()
    glyph = "○" if issue.state == "open" else "●"
    state_style = "bold #5FD787" if issue.state == "open" else "dim #888888"
    text.append(f" {glyph} ", style=state_style)
    text.append(f"#{issue.number:<5}", style=f"bold {BUG_ACCENT}")
    text.append(issue.title, style="white")
    for label in issue.labels[:3]:
        text.append(f"  {label}", style="bold #FFAF5F")
    if issue.assignees:
        text.append(f"  @{issue.assignees[0]}", style="dim #87AFFF")
    if issue.updated_at:
        text.append(f"  {_updated_age(issue.updated_at)}", style="dim")
    return text


def issue_meta(issue: IssueWire) -> Text:
    text = Text()
    text.append(
        f" {issue.state.upper()} ",
        style=(
            "bold #1a1a1a on #5FD787"
            if issue.state == "open"
            else "bold white on #666666"
        ),
    )
    if issue.author:
        text.append(f"  by {issue.author}", style="dim")
    if issue.assignees:
        text.append(f"  ·  assigned {', '.join(issue.assignees)}", style="dim")
    if issue.comment_count:
        text.append(f"  ·  {issue.comment_count} comments", style="dim")
    if issue.labels:
        text.append("  ·  ", style="dim")
        for label in issue.labels:
            text.append(f" {label} ", style="bold #FFAF5F")
    return text


def _updated_age(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        age = max(0, int((local_now() - to_local(parsed)).total_seconds()))
    except (TypeError, ValueError):
        return value[:10]
    if age < 60:
        return "now"
    if age < 3600:
        return f"{age // 60}m"
    if age < 86_400:
        return f"{age // 3600}h"
    if age < 604_800:
        return f"{age // 86_400}d"
    return f"{age // 604_800}w"


__all__ = ["BUG_ACCENT", "issue_meta", "issue_row"]

"""Scrollable presentation for a focused collapsed Agents panel."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.widgets import Static

from sase.agent.status_buckets import (
    AGENT_STATUS_BUCKET_GLYPHS,
    FEEDBACK_STATUS,
    PLAN_APPROVED_STATUS,
    TALE_APPROVED_STATUS,
    WORKING_PLAN_STATUS,
    WORKING_TALE_STATUS,
)

from ..agent_count_chip import format_agent_count_chip
from ..models.agent_panel_summary import (
    AgentPanelSummaryRow,
    AgentPanelSummarySnapshot,
)
from ..models.agent_status import STOPPED_COLOR, STOPPED_STATUS


_BUCKET_STYLES: dict[str, str] = {
    "Stopped": "bold #FFAF00",
    "Failed": "bold #FF5F5F",
    "Starting": "bold #87D7FF",
    "Running": "bold #00D7AF",
    "Waiting": "bold #AF87FF",
    "Unread": "bold #1a1a1a on #FFD700",
    "Done": "bold #5FD7FF",
}


def _status_style(status: str) -> str:
    """Return the status color used by the Agents list for ``status``."""
    if status == "STARTING":
        return "bold #87D7FF"
    if status == "RUNNING":
        return "bold #FFD700"
    if status in {"DONE", "PLAN DONE", "TALE DONE", "PLAN COMMITTED"}:
        return "bold #5FD75F"
    if status == "PLAN REJECTED":
        return "bold #D7AF5F"
    if status == STOPPED_STATUS:
        return f"bold {STOPPED_COLOR}"
    if status in {"EPIC CREATED", "EPIC APPROVED"}:
        return "bold #5FD7AF"
    if status.startswith("FAILED"):
        return "bold #FF5F5F"
    if status == "PLAN":
        return "bold #FF87AF"
    if status == FEEDBACK_STATUS:
        return "bold #FF5FD7"
    if status == PLAN_APPROVED_STATUS:
        return "bold #00D7AF"
    if status == TALE_APPROVED_STATUS:
        return "bold #00D7D7"
    if status == WORKING_PLAN_STATUS:
        return "bold #00AF87"
    if status == WORKING_TALE_STATUS:
        return "bold #00AFAF"
    if status == "WAITING":
        return "bold #AF87FF"
    if status == "QUESTION":
        return "bold #FFAF00"
    if status == "ANSWERED":
        return "bold #5FD7FF"
    if status == "RETRYING":
        return "bold #FF8700"
    return "dim"


def _composition_label(snapshot: AgentPanelSummarySnapshot) -> str:
    if snapshot.nested_count:
        return (
            f"{snapshot.entry_count} entries  ·  {snapshot.root_count} roots  ·  "
            f"{snapshot.nested_count} nested"
        )
    noun = "agent" if snapshot.entry_count == 1 else "agents"
    return f"{snapshot.entry_count} {noun}"


def _append_row(text: Text, row: AgentPanelSummaryRow, *, name_width: int) -> None:
    text.append("  ")
    if row.depth:
        text.append("  " * (row.depth - 1), style="dim #808080")
        text.append("└─ ", style="dim #808080")
    else:
        text.append("• ", style=_BUCKET_STYLES.get(row.roster_bucket, "dim"))

    if row.is_marked:
        text.append("[✓] ", style="bold #00D700")
    if row.is_unread:
        marker = "❌ " if row.status_bucket == "Failed" else "✅ "
        text.append(marker, style="#5FD7FF")

    padding = max(1, name_width - len(row.display_name) + 2)
    text.append(row.display_name, style="#00D7AF")
    text.append(" " * padding)
    text.append(row.display_status, style=_status_style(row.display_status))

    details = [*row.context]
    if row.model:
        details.append(row.model)
    if row.time_label:
        details.append(row.time_label)
    if details:
        text.append("  ·  ", style="dim")
        text.append("  ·  ".join(details), style="dim #AFAFAF")
    text.append("\n")


def _build_agent_panel_summary_text(snapshot: AgentPanelSummarySnapshot) -> Text:
    """Render ``snapshot`` as wrapping Rich text without dropping members."""
    text = Text()
    text.append("COLLAPSED AGENT PANEL\n", style="dim bold #AFAFAF")
    text.append(snapshot.label, style="bold #FFD75F")
    text.append("  COLLAPSED\n", style="dim #FFD75F")
    text.append(_composition_label(snapshot), style="dim #BCBCBC")

    text.append("\n\nSTATUS OVERVIEW  ", style="bold #87D7FF")
    text.append_text(
        format_agent_count_chip(
            stopped=snapshot.counts.stopped,
            running=snapshot.counts.running,
            waiting=snapshot.counts.waiting,
            failed=snapshot.counts.failed,
            unread=snapshot.counts.unread,
            done=snapshot.counts.done,
        )
    )
    text.append("\n\nAGENTS", style="bold #87D7FF")

    if not snapshot.rows:
        text.append("\n\n  No rendered agents in this panel.", style="dim italic")
        return text

    name_width = min(28, max(len(row.display_name) for row in snapshot.rows))
    current_bucket: str | None = None
    bucket_counts: dict[str, int] = {}
    for row in snapshot.rows:
        bucket_counts[row.roster_bucket] = bucket_counts.get(row.roster_bucket, 0) + 1

    for row in snapshot.rows:
        if row.roster_bucket != current_bucket:
            current_bucket = row.roster_bucket
            glyph = (
                "●"
                if current_bucket == "Unread"
                else AGENT_STATUS_BUCKET_GLYPHS.get(current_bucket, "•")
            )
            style = _BUCKET_STYLES.get(current_bucket, "dim")
            text.append("\n\n")
            text.append(f"{glyph} {current_bucket.upper()}", style=style)
            text.append(f"  {bucket_counts[current_bucket]}", style="dim")
            text.append("\n")
        _append_row(text, row, name_width=name_width)
    return text


class AgentPanelSummary(Static):
    """Static Rich surface hosted by AgentDetail's full-height scroll region."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._snapshot: AgentPanelSummarySnapshot | None = None

    @property
    def snapshot(self) -> AgentPanelSummarySnapshot | None:
        return self._snapshot

    def show_snapshot(self, snapshot: AgentPanelSummarySnapshot) -> None:
        self._snapshot = snapshot
        self.update(_build_agent_panel_summary_text(snapshot))


__all__ = ["AgentPanelSummary"]

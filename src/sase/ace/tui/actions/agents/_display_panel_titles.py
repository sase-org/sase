"""Agent panel border-title labels and scoped metric counts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from rich.text import Text
from sase.agent.status_buckets import agent_is_asking

from ...agent_count_chip import (
    AGENT_COUNT_CHIP_METRIC_STYLES,
    AGENT_COUNT_CHIP_METRICS,
    AGENT_COUNT_CHIP_NEUTRAL_STYLE,
    format_agent_count_chip,
)
from ...models.agent_groups import status_bucket_for
from ._loading_helpers import DISMISSABLE_STATUSES

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_panels import PanelKey

_PANEL_TAG_STYLE = "bold #FFD75F"
_PANEL_UNTAGGED_STYLE = "dim #AFAFAF"
_PANEL_COUNT_STYLE = AGENT_COUNT_CHIP_NEUTRAL_STYLE
_PANEL_METRIC_STYLES: dict[str, str] = {
    "asking" if name == "stopped" else "read" if name == "done" else name: style
    for name, style in AGENT_COUNT_CHIP_METRIC_STYLES.items()
}
_PANEL_METRIC_LABELS: tuple[tuple[str, str], ...] = tuple(
    ("asking" if name == "stopped" else "read" if name == "done" else name, label)
    for name, label in AGENT_COUNT_CHIP_METRICS
)


@dataclass(frozen=True)
class AgentPanelCounts:
    """Compact top-level agent counts scoped to one rendered panel."""

    asking: int = 0
    running: int = 0
    waiting: int = 0
    failed: int = 0
    unread: int = 0
    read: int = 0

    def metric_items(self) -> list[tuple[str, int]]:
        return [
            (name, getattr(self, name))
            for name, _label in _PANEL_METRIC_LABELS
            if getattr(self, name)
        ]


def agent_panel_counts(
    agents: list[Agent],
    unread_ids: set[tuple[AgentType, str, str | None]],
) -> AgentPanelCounts:
    """Return the top-strip metric categories for a single panel slice."""
    visible_top_level_agents = [
        agent for agent in agents if not agent.is_workflow_child
    ]
    buckets = [(agent, status_bucket_for(agent)) for agent in visible_top_level_agents]
    asking = sum(1 for agent, _bucket in buckets if agent_is_asking(agent.status))
    running = sum(
        1
        for agent, bucket in buckets
        if agent.status not in DISMISSABLE_STATUSES
        and bucket != "Starting"
        and bucket != "Waiting"
        and bucket != "Failed"
        and not agent_is_asking(agent.status)
    )
    waiting = sum(1 for _agent, bucket in buckets if bucket == "Waiting")
    failed = sum(1 for _agent, bucket in buckets if bucket == "Failed")
    unread = sum(
        1 for agent in visible_top_level_agents if agent.identity in unread_ids
    )
    read = sum(
        1
        for agent, bucket in buckets
        if bucket == "Done" and agent.identity not in unread_ids
    )
    return AgentPanelCounts(
        asking=asking,
        running=running,
        waiting=waiting,
        failed=failed,
        unread=unread,
        read=read,
    )


def agent_panel_border_title(
    key: PanelKey,
    agent_count: int,
    *,
    merge_tag_panels: bool = False,
    counts: AgentPanelCounts | None = None,
    collapsed: bool = False,
    jump_hint: str | None = None,
    selection_hint: int | None = None,
) -> Text:
    """Build a styled panel title while preserving its plain-text label."""
    title = Text()
    hint = selection_hint if selection_hint is not None else jump_hint
    if hint is not None:
        title.append(f"[{hint}] ", style="bold #FFFF00")
    if collapsed:
        title.append("▸ ", style=_PANEL_COUNT_STYLE)
    if merge_tag_panels:
        title.append("All agents", style="bold #AFFFFF")
    elif key is None:
        title.append("(untagged)", style=_PANEL_UNTAGGED_STYLE)
    else:
        title.append(f"#{key}", style=_PANEL_TAG_STYLE)
    title.append(f" · {agent_count}", style=_PANEL_COUNT_STYLE)
    if counts is not None:
        chip = format_agent_count_chip(
            stopped=counts.asking,
            running=counts.running,
            waiting=counts.waiting,
            failed=counts.failed,
            unread=counts.unread,
            done=counts.read,
        )
        if chip:
            title.append(" ", style=_PANEL_COUNT_STYLE)
            title.append_text(chip)
    return title

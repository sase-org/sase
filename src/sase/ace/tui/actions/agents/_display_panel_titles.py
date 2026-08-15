"""Agent panel border-title labels and scoped metric counts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from rich.text import Text

from ..._restore_markers import ARMED_RESTORE_STYLE, FOLD_RESTORE_GLYPH
from ...agent_count_chip import (
    AGENT_COUNT_CHIP_METRIC_STYLES,
    AGENT_COUNT_CHIP_METRICS,
    AGENT_COUNT_CHIP_NEUTRAL_STYLE,
    format_agent_count_chip,
)
from ...models._agent_clan import sase_agent_status_counts
from ...models._agent_tree import agent_is_tree_child
from ...models.agent_panels import agent_panel_label
from ...models.tribe_display import compose_tribe_identity_style

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_panels import PanelKey

_PANEL_SELECTED_CHROME_STYLE = "#FFD75F"
_PANEL_TRIBE_STYLE = compose_tribe_identity_style("", bold=True)
_PANEL_COUNT_STYLE = AGENT_COUNT_CHIP_NEUTRAL_STYLE
_PANEL_ISOLATION_RESTORE_STYLE = ARMED_RESTORE_STYLE
_PANEL_FOLD_RESTORE_GLYPH = FOLD_RESTORE_GLYPH
_PANEL_FOLD_RESTORE_STYLE = ARMED_RESTORE_STYLE
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
    """Lane total and status counts for one rendered panel."""

    lane_count: int = 0
    asking: int = 0
    running: int = 0
    queued: int = 0
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
        agent for agent in agents if not agent_is_tree_child(agent)
    ]
    projected = sase_agent_status_counts(
        visible_top_level_agents,
        unread_ids,
    )
    return AgentPanelCounts(
        lane_count=projected.total,
        asking=projected.stopped,
        running=projected.running,
        queued=projected.queued,
        waiting=projected.waiting,
        failed=projected.failed,
        unread=projected.unread,
        read=projected.done,
    )


def agent_panel_border_title(
    key: PanelKey,
    lane_count: int,
    *,
    merge_tribe_panels: bool = False,
    counts: AgentPanelCounts | None = None,
    collapsed: bool = False,
    selected: bool = False,
    isolation_restore_marked: bool = False,
    fold_restore_marked_count: int = 0,
    jump_hint: str | None = None,
    icon: str = "",
    color: str = "",
) -> Text:
    """Build a styled panel title while preserving its plain-text label."""
    title = Text()
    identity_style = compose_tribe_identity_style(color, bold=True)
    if jump_hint is not None:
        title.append(f"[{jump_hint}] ", style="bold #FFFF00")
    if selected and not collapsed:
        title.append("❖ ", style=_PANEL_SELECTED_CHROME_STYLE)
    if collapsed:
        title.append(
            "▸ ",
            style=(_PANEL_SELECTED_CHROME_STYLE if selected else _PANEL_COUNT_STYLE),
        )
    if merge_tribe_panels:
        title.append("All agents", style="bold #AFFFFF")
    else:
        if icon:
            title.append(f"{icon} ", style=identity_style)
        title.append(agent_panel_label(key), style=identity_style)
    if isolation_restore_marked:
        title.append(" ", style=_PANEL_COUNT_STYLE)
        title.append("↺", style=_PANEL_ISOLATION_RESTORE_STYLE)
    if fold_restore_marked_count > 0:
        title.append(" ", style=_PANEL_COUNT_STYLE)
        title.append(
            f"{_PANEL_FOLD_RESTORE_GLYPH}{fold_restore_marked_count}",
            style=_PANEL_FOLD_RESTORE_STYLE,
        )
    title.append(" · ", style=_PANEL_COUNT_STYLE)
    title.append(
        str(lane_count),
        style=_PANEL_SELECTED_CHROME_STYLE if selected else _PANEL_COUNT_STYLE,
    )
    if counts is not None:
        chip = format_agent_count_chip(
            stopped=counts.asking,
            running=counts.running,
            queued=counts.queued,
            waiting=counts.waiting,
            failed=counts.failed,
            unread=counts.unread,
            done=counts.read,
            chrome_style=_PANEL_SELECTED_CHROME_STYLE if selected else None,
        )
        if chip:
            title.append(" ", style=_PANEL_COUNT_STYLE)
            title.append_text(chip)
    return title

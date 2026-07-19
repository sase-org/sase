"""Agent panel border-title labels and scoped metric counts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from rich.text import Text

from ...agent_count_chip import (
    AGENT_COUNT_CHIP_METRIC_STYLES,
    AGENT_COUNT_CHIP_METRICS,
    AGENT_COUNT_CHIP_NEUTRAL_STYLE,
    format_agent_count_chip,
)
from ...models._agent_clan import (
    agent_status_projections,
    agent_summary_status_counts,
)
from ...models._agent_tree import (
    agent_is_tree_child,
    presentation_anchor_lookup,
    tree_parent_lookup,
)
from ...models.agent_family_members import (
    is_sequential_family_container,
    is_workflow_aggregate_row,
)

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_panels import PanelKey

_PANEL_SELECTED_CHROME_STYLE = "#FFD75F"
_PANEL_TRIBE_STYLE = f"bold {_PANEL_SELECTED_CHROME_STYLE}"
_PANEL_NO_TRIBE_STYLE = "dim #AFAFAF"
_PANEL_COUNT_STYLE = AGENT_COUNT_CHIP_NEUTRAL_STYLE
_PANEL_ISOLATION_RESTORE_STYLE = "bold #D7AF5F"
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

    total: int = 0
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
        agent for agent in agents if not agent_is_tree_child(agent)
    ]
    projected = agent_summary_status_counts(
        visible_top_level_agents,
        unread_ids,
    )
    total = _panel_concrete_agent_total(agents, visible_top_level_agents)
    return AgentPanelCounts(
        total=total,
        asking=projected.stopped,
        running=projected.running,
        waiting=projected.waiting,
        failed=projected.failed,
        unread=projected.unread,
        read=projected.done,
    )


def _panel_concrete_agent_total(
    agents: list[Agent],
    roots: list[Agent],
) -> int:
    """Count container roots concretely while preserving ordinary row totals."""
    if not roots:
        return 0
    anchors = presentation_anchor_lookup(agents, tree_parent_lookup(agents))
    row_count_by_anchor: dict[int, int] = {}
    for agent in agents:
        anchor = anchors.get(id(agent), agent)
        row_count_by_anchor[id(anchor)] = row_count_by_anchor.get(id(anchor), 0) + 1

    total = 0
    for root in roots:
        project_concretely = (
            root.is_clan_container
            or is_sequential_family_container(root)
            or (not root.agent_family_parallel and is_workflow_aggregate_row(root))
        )
        if project_concretely:
            total += len(agent_status_projections((root,)))
        else:
            total += row_count_by_anchor.get(id(root), 1)
    return total


def agent_panel_border_title(
    key: PanelKey,
    agent_count: int,
    *,
    merge_tribe_panels: bool = False,
    counts: AgentPanelCounts | None = None,
    collapsed: bool = False,
    selected: bool = False,
    isolation_restore_marked: bool = False,
    jump_hint: str | None = None,
    selection_hint: int | None = None,
) -> Text:
    """Build a styled panel title while preserving its plain-text label."""
    title = Text()
    hint = selection_hint if selection_hint is not None else jump_hint
    if hint is not None:
        title.append(f"[{hint}] ", style="bold #FFFF00")
    if selected:
        title.append("❖ ", style=_PANEL_TRIBE_STYLE)
    if collapsed:
        title.append("▸ ", style=_PANEL_COUNT_STYLE)
    if merge_tribe_panels:
        title.append("All agents", style="bold #AFFFFF")
    elif key is None:
        title.append("(no tribe)", style=_PANEL_NO_TRIBE_STYLE)
    else:
        title.append(f"@{key}", style=_PANEL_TRIBE_STYLE)
    if isolation_restore_marked:
        title.append(" ", style=_PANEL_COUNT_STYLE)
        title.append("↺", style=_PANEL_ISOLATION_RESTORE_STYLE)
    title.append(" · ", style=_PANEL_COUNT_STYLE)
    title.append(
        str(agent_count),
        style=_PANEL_SELECTED_CHROME_STYLE if selected else _PANEL_COUNT_STYLE,
    )
    if counts is not None:
        chip = format_agent_count_chip(
            stopped=counts.asking,
            running=counts.running,
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

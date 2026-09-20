"""Layout composition and sizing constants for :class:`AceApp`."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from .models.agent_live_query_engine import agents_live_query_profile
from ._patch_list_layout import (
    CL_LIST_MAX_PANEL_WIDTH,
    CL_LIST_MIN_PANEL_WIDTH,
)
from .widgets import (
    AgentDetail,
    AgentInfoPanel,
    AgentList,
    AgentsFilterBar,
    AliasOverridesIndicator,
    ArtifactsView,
    AxeDashboard,
    AxeInfoPanel,
    BgCmdList,
    CurrentProjectIndicator,
    KeybindingFooter,
    LinkRail,
    LLMOverrideIndicator,
    MonitorIndicator,
    NotificationIndicator,
    ProviderDisablesIndicator,
    StashedPromptsIndicator,
    TabBar,
    TabQuickStart,
    ProcIndicator,
    UpdatesAvailableIndicator,
    UsageHeader,
)

# Width bounds for dynamic list panel sizing (in terminal cells). The minimum
# must fit the PR status line plus padding/border; the refresh countdown lives
# on the info panel's second row.
MIN_LIST_WIDTH = CL_LIST_MIN_PANEL_WIDTH
MAX_LIST_WIDTH = CL_LIST_MAX_PANEL_WIDTH

# Width bounds for the agent list panel.
MIN_AGENT_LIST_WIDTH = 60
MAX_AGENT_LIST_WIDTH = 130


def agent_list_column_width(requested_widths: Iterable[int], *, fallback: int) -> int:
    """Return the agent-list column width for the mounted panels' requests.

    The widest panel decides. *fallback* only applies while no panel has
    requested a width yet, so a stale message width can never hold the column
    wider than the panels now need.
    """
    desired = max((width for width in requested_widths if width > 0), default=fallback)
    return max(MIN_AGENT_LIST_WIDTH, min(MAX_AGENT_LIST_WIDTH, desired))


# Width bounds for the AXE-tab sidebar (#bgcmd-list-container). The minimum
# matches the historical default. The larger maximum lets long lumberjack,
# chop, and bgcmd labels fit without starving the dashboard on narrow screens.
MIN_BGCMD_LIST_WIDTH = 35
MAX_BGCMD_LIST_WIDTH = 80
BGCMD_LIST_RESERVED_FOR_DASHBOARD = 40


class AppLayoutMixin:
    """Compose the top-level ACE widgets."""

    def compose(self: Any) -> ComposeResult:
        """Compose the app layout."""
        from .util.startup_clock import composing

        with composing():
            yield from self._compose_layout()

    def _compose_layout(self: Any) -> ComposeResult:
        """Yield the top-level ACE widgets (timed by :meth:`compose`)."""
        initial_tab = self.current_tab
        cs_classes = "" if initial_tab == "artifacts" else "hidden"
        agents_classes = "" if initial_tab == "agents" else "hidden"
        axe_classes = "" if initial_tab == "axe" else "hidden"
        yield UsageHeader(id="ace-header")
        with Horizontal(id="top-bar"):
            yield TabBar(id="tab-bar")
            yield ProcIndicator(id="proc-indicator")
            yield MonitorIndicator(id="monitor-indicator")
            yield UpdatesAvailableIndicator(id="updates-indicator")
            yield LLMOverrideIndicator(id="llm-override-indicator")
            yield AliasOverridesIndicator(id="alias-overrides-indicator")
            yield ProviderDisablesIndicator(id="provider-disables-indicator")
            yield CurrentProjectIndicator(id="current-project-indicator")
            yield StashedPromptsIndicator(id="stashed-prompts-indicator")
            yield NotificationIndicator(id="notification-indicator")
        with Horizontal(id="main-container"):
            yield ArtifactsView(
                commits_default_filter=self._commits_default_filter,
                id="artifacts-view",
                classes=cs_classes,
            )
            with Vertical(id="agents-view", classes=agents_classes):
                yield AgentInfoPanel(id="agent-info-panel")
                yield AgentsFilterBar(
                    id="agents-filter-bar",
                    profile=agents_live_query_profile(),
                )
                with Horizontal(id="agents-header", classes="hidden"):
                    yield Static("", id="agents-fleet-status")
                with Horizontal(id="agents-content"):
                    with Vertical(id="agent-list-container"):
                        yield AgentList(id="agent-list-panel")
                    with Vertical(id="agent-detail-container"):
                        yield AgentDetail(id="agent-detail-panel")
                        yield TabQuickStart(
                            tab="agents",
                            id="agent-quickstart-panel",
                            classes="hidden",
                        )
            with Horizontal(id="axe-view", classes=axe_classes):
                with Vertical(id="bgcmd-list-container"):
                    yield BgCmdList(id="bgcmd-list-panel")
                with Vertical(id="axe-container"):
                    yield AxeInfoPanel(id="axe-info-panel")
                    yield AxeDashboard(id="axe-dashboard")
        yield LinkRail(id="link-rail")
        yield KeybindingFooter(id="keybinding-footer")

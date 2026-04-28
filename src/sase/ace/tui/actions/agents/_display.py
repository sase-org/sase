"""Agent display and refresh methods for the ace TUI app.

Top-level orchestration: holds the panel-index cache, the public refresh
entry points (``_refresh_agents_display`` and friends), and aggregates
:class:`._display_panels._PanelsMixin` and
:class:`._display_detail._DetailMixin` into the single
:class:`AgentDisplayMixin` consumed by :mod:`._core`.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_group_fold import AgentGroupFoldRegistry
    from ...models.agent_panel_index import AgentPanelIndex
    from ...models.agent_panels import AgentPanelGroup

from ...models.agent_groups import GroupingMode
from ...util.debounce import DetailPanelDebouncer
from ...util.trace import tui_trace
from ._display_detail import DetailMixin
from ._display_helpers import _MAIN_PANEL_ID, TabName, panel_widget_id
from ._display_panels import PanelsMixin
from ._loading import DISMISSABLE_STATUSES

log = logging.getLogger(__name__)

# Tests import the legacy private alias from this module — keep it.
_panel_widget_id = panel_widget_id

# Re-exports for backward compatibility with callers/tests that import
# these names directly from ``_display``.
__all__ = ["AgentDisplayMixin", "TabName", "_MAIN_PANEL_ID", "_panel_widget_id"]


class AgentDisplayMixin(PanelsMixin, DetailMixin):
    """Mixin providing agent display and refresh methods.

    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    current_idx: int
    current_attempt_number: int | None
    current_tab: TabName
    refresh_interval: int
    _agents: list[Agent]
    _fold_counts: dict[str, tuple[int, int]]
    _agent_search_query: str

    # Debouncer for j/k navigation detail panel updates
    _agent_detail_debouncer: DetailPanelDebouncer

    _marked_agents: set[tuple[AgentType, str, str | None]]
    _entry_jump_mode_active: bool
    _entry_jump_index_to_hint: dict[int, str]
    # Banner-target inverse map; agents-tab jump mode populates this when
    # the user presses ``'`` and ``_jump_candidate_targets`` includes any
    # collapsed banners.
    _entry_jump_banner_to_hint: dict[tuple[Any, int, tuple[str, ...]], str]

    # Group fold + tag-driven panel collection (see startup.py).
    _group_fold_registry: AgentGroupFoldRegistry
    _grouping_mode: GroupingMode
    _current_group_key: tuple[str, ...] | None
    _panel_group: AgentPanelGroup

    # Countdown for refresh
    _countdown_remaining: int

    # Phase 2 j/k cache (initialized in StartupMixin._init_app_state).
    _nav_stops_cache: tuple[Any, ...] | None
    _panel_keys_cache: tuple[Any, ...] | None
    # Phase 4 panel index cache: keyed on ``self._agents`` identity so a
    # single agents-list ref reuses the same panels / non-child indices /
    # completed count across every refresh path.
    _agent_panel_index_cache: tuple[Any, AgentPanelIndex] | None

    def _invalidate_agent_panel_cache(self) -> None:
        """Clear panel-derived caches after in-place agent mutations."""
        if hasattr(self, "_agent_panel_index_cache"):
            self._agent_panel_index_cache = None
        if hasattr(self, "_panel_keys_cache"):
            self._panel_keys_cache = None
        if hasattr(self, "_nav_stops_cache"):
            self._nav_stops_cache = None

    def _refresh_tab_bar_agent_counts(self) -> None:
        """Recompute and push agent counts onto the tab bar.

        Mirrors the count math in :func:`_loading_finalize.finalize_agent_list`
        so a fast-path in-memory removal can keep the tab bar fresh
        without going through the full finalize pipeline.
        """
        from textual.css.query import NoMatches

        from ...widgets import TabBar

        try:
            tab_bar = self.query_one("#tab-bar", TabBar)  # type: ignore[attr-defined]
        except NoMatches:
            return

        manual_running = sum(
            1
            for a in self._agents
            if a.status not in DISMISSABLE_STATUSES and not a.is_workflow_child
        )
        if getattr(self, "_has_always_visible", False):
            hidden_running = sum(
                1
                for a in getattr(self, "_hideable_agents", [])
                if a.status not in DISMISSABLE_STATUSES and not a.is_workflow_child
            )
        else:
            hidden_running = 0
        done_visible = sum(
            1
            for a in self._agents
            if a.status in DISMISSABLE_STATUSES and not a.is_workflow_child
        )
        tab_bar.update_agents_count(
            manual_running,
            hidden_running,
            show_hidden=not getattr(self, "hide_non_run_agents", False),
            done_count=done_visible,
        )

    def _agent_panel_index(self) -> AgentPanelIndex:
        """Memoized :class:`AgentPanelIndex` keyed on the agents-list ref.

        ``self._agents`` is replaced wholesale by the loading / refilter
        paths so ``is`` identity is a sufficient invalidation signal.
        Every panel-aware refresh path (highlights, widgets, info panel,
        single-row patch) reads from this index so the agents list is
        scanned at most once per refresh cycle.
        """
        from ...models.agent_panel_index import build_agent_panel_index

        cached = getattr(self, "_agent_panel_index_cache", None)
        if cached is not None and cached[0] is self._agents:
            return cached[1]
        index = build_agent_panel_index(
            self._agents, dismissable_statuses=DISMISSABLE_STATUSES
        )
        self._agent_panel_index_cache = (self._agents, index)
        # Keep the legacy ``_panel_keys_cache`` populated so callers that
        # still go through ``_panel_keys_per_agent`` (tree builder, banner
        # math) share the same per-agent key list as the panel index.
        self._panel_keys_cache = (self._agents, index.keys_per_agent)
        return index

    def _panel_keys_per_agent(self) -> list:
        """Memoized :func:`panel_key_per_agent` keyed on the agents list."""
        return self._agent_panel_index().keys_per_agent

    def _refresh_agents_display(
        self, *, list_changed: bool = False, defer_detail: bool = False
    ) -> None:
        """Refresh the agents tab display.

        Args:
            list_changed: If True, the agent list has changed and needs a full
                rebuild (called from _load_agents). If False, only the selection
                index moved (j/k navigation) — skip the expensive OptionList
                clear-and-rebuild.
        """
        with tui_trace(
            "agents.refresh_display",
            agents=len(self._agents),
            list_changed=bool(list_changed),
            defer_detail=bool(defer_detail),
        ):
            self._refresh_agents_display_impl(
                list_changed=list_changed, defer_detail=defer_detail
            )

    def _refresh_agents_display_impl(
        self, *, list_changed: bool = False, defer_detail: bool = False
    ) -> None:
        started = time.perf_counter()
        list_started = started
        # Cancel any pending debounced detail update — full refresh supersedes
        self._agent_detail_debouncer.cancel()

        from textual.css.query import NoMatches

        from ...widgets import AgentDetail, KeybindingFooter

        try:
            agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
            footer_widget = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
        except NoMatches:
            log.debug("agents display refresh skipped: widget tree unavailable")
            return

        if list_changed:
            # Drop any marks pointing at identities that no longer exist.
            self._prune_stale_marked_agents()  # type: ignore[attr-defined]
            self._sync_panel_group()
            jump_hints = (
                dict(self._entry_jump_index_to_hint)
                if self._entry_jump_mode_active
                else None
            )
            banner_jump_hints = (
                dict(self._entry_jump_banner_to_hint)
                if self._entry_jump_mode_active
                else None
            )

            self._refresh_panel_widgets(
                jump_hints=jump_hints,
                banner_jump_hints=banner_jump_hints,
            )
            log.debug(
                "agents display refresh list phase: elapsed=%.3fs agents=%d",
                time.perf_counter() - list_started,
                len(self._agents),
            )
        else:
            self._refresh_panel_highlights()

        self._update_agents_info_panel()
        if defer_detail:
            self._agent_detail_debouncer.schedule(self._fire_debounced_detail_update)
            log.debug(
                "agents display refresh deferred detail: elapsed=%.3fs",
                time.perf_counter() - started,
            )
            return

        detail_started = time.perf_counter()
        self._apply_agent_detail_update(agent_detail, footer_widget)
        log.debug(
            "agents display refresh detail phase: elapsed=%.3fs total=%.3fs",
            time.perf_counter() - detail_started,
            time.perf_counter() - started,
        )

    def _refresh_agents_display_debounced(self) -> None:
        """Debounced refresh for j/k navigation on the agents tab.

        Two-phase: the immediate phase updates list highlight, info panel,
        and the detail prompt header for the freshly-selected agent. The
        debounced phase fires after the j/k burst settles and runs the
        expensive file/thinking/diff workers — only for the final selection.
        """
        with tui_trace("agents.refresh_debounced", agents=len(self._agents)):
            self._refresh_panel_highlights()
            self._update_agents_info_panel()
            self._apply_agent_detail_immediate()
            self._agent_detail_debouncer.schedule(self._fire_debounced_detail_update)

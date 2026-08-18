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
    from ...models.agent_panels import AgentPanelGroup, PanelKey
    from ..navigation.jump_hints import BannerJumpTarget, PanelJumpTarget

from ...models.agent_groups import GroupingMode
from ...util.debounce import DetailPanelDebouncer
from ...util.trace import tui_trace
from ._display_diff import (
    affected_panel_keys,
    build_agent_display_diff,
    changed_same_position_panel_membership_keys,
    diff_touches_workflow_tree,
    panel_keys_for_display,
    rendered_panel_key_by_identity,
)
from ._display_detail import DetailMixin
from ._display_helpers import _MAIN_PANEL_ID, TabName, panel_widget_id
from ._display_panels import PanelsMixin
from ._loading import DISMISSABLE_STATUSES
from ._panel_fold_intent import effective_panel_collapses
from ._refresh_trace import (
    AgentRefreshDisplayCost,
    AgentRefreshFallbackReason,
    record_agents_refresh_trace,
)
from ._neighbors import AgentNeighborMixin

log = logging.getLogger(__name__)

# Tests import the legacy private alias from this module — keep it.
_panel_widget_id = panel_widget_id

# Re-exports for backward compatibility with callers/tests that import
# these names directly from ``_display``.
__all__ = ["AgentDisplayMixin", "TabName", "_MAIN_PANEL_ID", "_panel_widget_id"]


class AgentDisplayMixin(AgentNeighborMixin, PanelsMixin, DetailMixin):
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
    _agent_search_query_seeded: bool

    # Debouncer for j/k navigation detail panel updates
    _agent_detail_debouncer: DetailPanelDebouncer

    _marked_agents: set[tuple[AgentType, str, str | None]]
    _unread_completed_agent_ids: set[tuple[AgentType, str, str | None]]
    _manual_unread_agent_ids: set[tuple[AgentType, str, str | None]]
    _entry_jump_mode_active: bool
    _entry_jump_index_to_hint: dict[int, str]
    # Banner-target inverse map; agents-tab jump mode populates this when
    # the user presses ``'`` and ``_jump_candidate_targets`` includes any
    # collapsed banners.
    _entry_jump_banner_to_hint: dict[BannerJumpTarget, str]
    _entry_jump_panel_to_hint: dict[PanelJumpTarget, str]

    # Group fold + tribe-driven panel collection (see startup.py).
    _group_fold_registry: AgentGroupFoldRegistry
    _grouping_mode: GroupingMode
    _current_group_key: tuple[str, ...] | None
    _panel_group: AgentPanelGroup
    _agent_panels_grouped: bool
    _collapsed_panel_keys: set[PanelKey]

    # Countdown for refresh
    _countdown_remaining: int

    # Phase 2 j/k cache (initialized in StartupMixin._init_app_state).
    _nav_stops_cache: tuple[Any, ...] | None
    _panel_keys_cache: tuple[Any, ...] | None
    # Phase 4 panel index cache: keyed on ``self._agents`` identity so a
    # single agents-list ref reuses the same panels / non-child indices /
    # completed count across every refresh path.
    _agent_panel_index_cache: tuple[Any, bool, AgentPanelIndex] | None
    _agent_neighbor_index_cache: tuple[Any, ...] | None
    _unread_jump_candidates_cache: tuple[Any, Any] | None

    def _invalidate_agent_panel_cache(self) -> None:
        """Clear panel-derived caches after in-place agent mutations."""
        if hasattr(self, "_agent_panel_index_cache"):
            self._agent_panel_index_cache = None
        if hasattr(self, "_agent_neighbor_index_cache"):
            self._agent_neighbor_index_cache = None
        if hasattr(self, "_agent_info_metrics_cache"):
            self._agent_info_metrics_cache = None
        if hasattr(self, "_panel_keys_cache"):
            self._panel_keys_cache = None
        if hasattr(self, "_nav_stops_cache"):
            self._nav_stops_cache = None
        if hasattr(self, "_unread_jump_candidates_cache"):
            self._unread_jump_candidates_cache = None

    def _snap_focus_after_agents_fold_restore(self) -> None:
        """Re-anchor once after restored folds hide the selected agent row."""
        if not getattr(self, "_agents_fold_restore_needs_focus_snap", False):
            return
        self._agents_fold_restore_needs_focus_snap = False  # type: ignore[attr-defined]
        snap = getattr(self, "_snap_focus_after_group_fold_change", None)
        if callable(snap):
            snap()

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
        merge_tribe_panels = getattr(self, "_agent_panels_grouped", False)
        if (
            cached is not None
            and cached[0] is self._agents
            and cached[1] == merge_tribe_panels
        ):
            return cached[2]
        index = build_agent_panel_index(
            self._agents,
            dismissable_statuses=DISMISSABLE_STATUSES,
            merge_tribe_panels=merge_tribe_panels,
        )
        self._agent_panel_index_cache = (self._agents, merge_tribe_panels, index)
        # Keep the legacy ``_panel_keys_cache`` populated so callers that
        # still go through ``_panel_keys_per_agent`` (tree builder, banner
        # math) share the same per-agent key list as the panel index.
        self._panel_keys_cache = (
            self._agents,
            merge_tribe_panels,
            index.keys_per_agent,
        )
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
        source = getattr(self, "_agents_refresh_active_source", "unknown")
        display_cost: AgentRefreshDisplayCost | None = (
            "display_full_rebuild" if list_changed else None
        )
        if display_cost is not None:
            record_agents_refresh_trace(
                self,
                stage="display",
                source=source,
                display_cost=display_cost,
                agents=len(self._agents),
                defer_detail=defer_detail,
            )
        with tui_trace(
            "agents.refresh_display",
            agents=len(self._agents),
            list_changed=bool(list_changed),
            defer_detail=bool(defer_detail),
            source=source,
            display_cost=display_cost,
        ):
            self._refresh_agents_display_impl(
                list_changed=list_changed, defer_detail=defer_detail
            )

    def _record_display_full_rebuild_fallback(
        self,
        reason: AgentRefreshFallbackReason,
        *,
        count: int | None = None,
    ) -> None:
        record_agents_refresh_trace(
            self,
            stage="display_fallback",
            source=getattr(self, "_agents_refresh_active_source", "unknown"),
            display_cost="display_full_rebuild",
            fallback_reason=reason,
            count=count,
        )

    def _refresh_agents_display_after_finalize(
        self,
        *,
        previous_agents: list[Agent] | None,
        defer_detail: bool = False,
    ) -> None:
        """Refresh finalized agent display, using a narrow diff when safe."""
        if previous_agents is not None and self._try_refresh_agents_display_incremental(
            previous_agents,
            defer_detail=defer_detail,
        ):
            return
        self._refresh_agents_display(list_changed=True, defer_detail=defer_detail)

    def _try_refresh_agents_display_incremental(
        self,
        previous_agents: list[Agent],
        *,
        defer_detail: bool,
    ) -> bool:
        """Patch/rebuild affected panels after a finalized list replacement."""
        if self.current_tab != "agents":
            return False
        if not previous_agents and self._agents:
            return False
        if getattr(self, "_agent_search_query", ""):
            self._record_display_full_rebuild_fallback("active_search")
            return False
        if (
            getattr(self, "_grouping_mode", GroupingMode.STANDARD)
            is not GroupingMode.STANDARD
        ):
            self._record_display_full_rebuild_fallback("unsupported_grouping")
            return False
        if not self._agent_display_widgets_match_grouping_mode():
            self._record_display_full_rebuild_fallback("stale_grouping_mode")
            return False

        merge_tribe_panels = getattr(self, "_agent_panels_grouped", False)
        collapsed_panel_keys = effective_panel_collapses(self)
        if not self._agent_display_widgets_have_previous_rows(previous_agents):
            return False

        old_panel_keys = tuple(getattr(self._panel_group, "panel_keys", ()))
        if (
            panel_keys_for_display(
                previous_agents,
                merge_tribe_panels=merge_tribe_panels,
                collapsed_panel_keys=collapsed_panel_keys,
            )
            != old_panel_keys
        ):
            self._record_display_full_rebuild_fallback("panel_membership_change")
            return False

        next_panel_keys = panel_keys_for_display(
            self._agents,
            merge_tribe_panels=merge_tribe_panels,
            collapsed_panel_keys=collapsed_panel_keys,
        )
        if next_panel_keys != old_panel_keys:
            self._record_display_full_rebuild_fallback("panel_membership_change")
            return False

        diff = build_agent_display_diff(previous_agents, self._agents)
        if diff.duplicate_identity:
            self._record_display_full_rebuild_fallback("panel_membership_change")
            return False
        if diff_touches_workflow_tree(diff, previous_agents, self._agents):
            self._record_display_full_rebuild_fallback("workflow_tree_change")
            return False

        with tui_trace(
            "agents.refresh_display_incremental",
            agents=len(self._agents),
            previous_agents=len(previous_agents),
            changed=len(diff.changed_same_position),
            removed=len(diff.removed_identities),
            added=len(diff.added_indices),
            moved=len(diff.moved_identities),
            defer_detail=bool(defer_detail),
        ):
            return self._try_refresh_agents_display_incremental_impl(
                previous_agents,
                diff=diff,
                defer_detail=defer_detail,
                merge_tribe_panels=merge_tribe_panels,
            )

    def _agent_display_widgets_match_grouping_mode(self) -> bool:
        """Return True when every rendered ``AgentList`` matches the app mode.

        The incremental refresh path patches and re-highlights existing rows
        in place, so it is only safe when the widget trees already on screen
        were built under the app's currently-active grouping mode. After a
        grouping cycle (e.g. ``BY_STATUS -> STANDARD``) the agent identities
        can be unchanged while the widgets still hold the previous mode's
        banners; patching them would leave stale status buckets under a
        project-mode label. When the widgets disagree with
        ``self._grouping_mode`` we force the full rebuild path instead.
        """
        from textual.css.query import NoMatches

        from ...widgets import AgentList

        active_mode = getattr(self, "_grouping_mode", GroupingMode.STANDARD)
        try:
            container = self.query_one("#agent-list-container")  # type: ignore[attr-defined]
        except NoMatches:
            return True
        try:
            widgets = list(
                container.query(AgentList).results(AgentList)  # type: ignore[attr-defined]
            )
        except (AttributeError, NoMatches):
            widgets = [
                widget
                for widget in getattr(container, "children", [])
                if isinstance(widget, AgentList)
            ]
        return all(
            getattr(widget, "_grouping_mode", GroupingMode.STANDARD) is active_mode
            for widget in widgets
        )

    def _agent_display_widgets_have_previous_rows(
        self,
        previous_agents: list[Agent],
    ) -> bool:
        """Return True when the current widgets have a prior rendered list."""
        from textual.css.query import NoMatches

        from ...models.agent_panels import agent_is_rendered_in_agents_panel
        from ...widgets import AgentList

        if not any(
            agent_is_rendered_in_agents_panel(agent) for agent in previous_agents
        ):
            return True
        try:
            container = self.query_one("#agent-list-container")  # type: ignore[attr-defined]
        except NoMatches:
            return False
        try:
            widgets = list(
                container.query(AgentList).results(AgentList)  # type: ignore[attr-defined]
            )
        except (AttributeError, NoMatches):
            widgets = [
                widget
                for widget in getattr(container, "children", [])
                if isinstance(widget, AgentList)
            ]
        return any(int(getattr(widget, "option_count", 0)) > 0 for widget in widgets)

    def _try_refresh_agents_display_incremental_impl(
        self,
        previous_agents: list[Agent],
        *,
        diff: Any,
        defer_detail: bool,
        merge_tribe_panels: bool,
    ) -> bool:
        sync_artifact_layout = getattr(self, "_sync_artifact_file_viewer_layout", None)
        if callable(sync_artifact_layout):
            sync_artifact_layout()
        self._agent_detail_debouncer.cancel()

        from textual.css.query import NoMatches

        from ...widgets import AgentDetail, KeybindingFooter

        try:
            agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
            footer_widget = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
        except NoMatches:
            self._record_display_full_rebuild_fallback("panel_membership_change")
            return False

        prune = getattr(self, "_prune_stale_marked_agents", None)
        if callable(prune):
            prune()
        self._sync_panel_group()
        self._snap_focus_after_agents_fold_restore()

        affected_keys = affected_panel_keys(
            diff,
            previous_agents,
            self._agents,
            merge_tribe_panels=merge_tribe_panels,
        )
        panel_rebuild_keys: set[Any] = set()
        panel_rebuild_keys.update(
            changed_same_position_panel_membership_keys(
                diff,
                previous_agents,
                self._agents,
                merge_tribe_panels=merge_tribe_panels,
            )
        )
        if diff.has_collection_changes:
            panel_rebuild_keys.update(affected_keys)

        if diff.removed_identities and not self._try_remove_agent_rows(
            set(diff.removed_identities)
        ):
            return False

        current_keys = rendered_panel_key_by_identity(
            self._agents,
            merge_tribe_panels=merge_tribe_panels,
        )
        for idx in diff.changed_same_position:
            agent = self._agents[idx]
            if current_keys.get(agent.identity) in panel_rebuild_keys:
                continue
            if not self._try_patch_agent_row(agent):
                return False

        if panel_rebuild_keys:
            if not self._refresh_affected_panel_widgets(panel_rebuild_keys):
                self._record_display_full_rebuild_fallback(
                    "panel_membership_change",
                    count=len(panel_rebuild_keys),
                )
                return False
            self._record_display_patch_trace(
                display_cost="display_panel_rebuild",
                count=len(panel_rebuild_keys),
            )

        self._reapply_panel_heights()
        self._refresh_panel_highlights()
        self._update_agents_info_panel()
        if defer_detail:
            if self._sync_agents_onboarding(
                agent_detail=agent_detail, footer_widget=footer_widget
            ):
                return True
            if self._apply_tribe_summary(
                agent_detail,
                footer_widget,
                cheap=True,
            ):
                self._agent_detail_debouncer.schedule(
                    self._fire_debounced_detail_update
                )
                return True
            self._agent_detail_debouncer.schedule(self._fire_debounced_detail_update)
            return True

        self._apply_agent_detail_update(agent_detail, footer_widget)
        return True

    def _refresh_agents_display_impl(
        self, *, list_changed: bool = False, defer_detail: bool = False
    ) -> None:
        started = time.perf_counter()
        list_started = started
        sync_artifact_layout = getattr(self, "_sync_artifact_file_viewer_layout", None)
        if callable(sync_artifact_layout):
            sync_artifact_layout()
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
            self._snap_focus_after_agents_fold_restore()
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
            panel_jump_hints = (
                dict(self._entry_jump_panel_to_hint)
                if self._entry_jump_mode_active
                else None
            )
            if not self._entry_jump_mode_active and getattr(
                self, "_panel_fold_hint_mode_active", False
            ):
                (
                    jump_hints,
                    banner_jump_hints,
                ) = self._panel_fold_hint_display_maps()  # type: ignore[attr-defined]
                panel_jump_hints = None

            self._refresh_panel_widgets(
                jump_hints=jump_hints,
                banner_jump_hints=banner_jump_hints,
                panel_jump_hints=panel_jump_hints,
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
            if self._sync_agents_onboarding(
                agent_detail=agent_detail, footer_widget=footer_widget
            ):
                log.debug(
                    "agents display refresh onboarding detail: elapsed=%.3fs",
                    time.perf_counter() - started,
                )
                return
            if self._apply_tribe_summary(
                agent_detail,
                footer_widget,
                cheap=True,
            ):
                self._agent_detail_debouncer.schedule(
                    self._fire_debounced_detail_update
                )
                log.debug(
                    "agents display refresh tribe summary: elapsed=%.3fs",
                    time.perf_counter() - started,
                )
                return
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
        expensive file/tools/diff workers — only for the final selection.
        """
        with tui_trace("agents.refresh_debounced", agents=len(self._agents)):
            self._refresh_panel_highlights()
            self._update_agents_info_panel()
            if self._apply_agent_detail_immediate():
                self._agent_detail_debouncer.cancel()
            else:
                self._agent_detail_debouncer.schedule(
                    self._fire_debounced_detail_update
                )

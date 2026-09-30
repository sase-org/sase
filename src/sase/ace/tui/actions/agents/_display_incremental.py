"""Incremental (diff-based) refresh for the agent display mixin."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_panels import PanelKey

from ...models.agent_groups import GroupingMode
from ...util.debounce import DetailPanelDebouncer
from ...util.trace import tui_trace
from ._display_diff import (
    PanelRebuildScope,
    affected_panel_keys,
    build_agent_display_diff,
    changed_same_position_panel_membership_keys,
    panel_rebuild_scope,
    rendered_panel_key_by_identity,
)
from ._display_helpers import TabName, panel_widget_id_for_key, panel_widget_is_retiring
from ._loading import DISMISSABLE_STATUSES
from ._paint_log import record_agents_paint_frame
from ._refresh_trace import (
    AgentRefreshFallbackReason,
    record_agents_refresh_trace,
    take_display_outcome,
)


class AgentDisplayIncrementalMixin:
    """Narrow diff refresh after a finalized list replacement."""

    current_tab: TabName
    _agents: list[Agent]
    _agent_search_query: str
    _agent_display_last_search_query: str
    _grouping_mode: GroupingMode
    _agent_panels_grouped: bool
    _agent_detail_debouncer: DetailPanelDebouncer

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

    def _record_display_panel_rebuild_fallback(
        self,
        reason: AgentRefreshFallbackReason,
        key: PanelKey,
    ) -> None:
        """Name the one panel a whole-roster predicate sends to a rebuild."""
        record_agents_refresh_trace(
            self,
            stage="display_fallback",
            source=getattr(self, "_agents_refresh_active_source", "unknown"),
            display_cost="display_panel_rebuild",
            fallback_reason=reason,
            panel=panel_widget_id_for_key(key),
        )

    def _refresh_agents_display_after_finalize(
        self,
        *,
        previous_agents: list[Agent] | None,
        defer_detail: bool = False,
    ) -> None:
        """Refresh finalized agent display, using a narrow diff when safe."""
        # Costs noted before this refresh started belong to no frame.
        take_display_outcome(self)
        current_search_query = getattr(self, "_agent_search_query", "") or ""
        if previous_agents is not None and self._try_refresh_agents_display_incremental(
            previous_agents,
            defer_detail=defer_detail,
        ):
            self._agent_display_last_search_query = current_search_query
            return
        self._refresh_agents_display(  # type: ignore[attr-defined]
            list_changed=True, defer_detail=defer_detail
        )
        self._agent_display_last_search_query = current_search_query

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
        current_search_query = getattr(self, "_agent_search_query", "") or ""
        last_search_query = getattr(
            self,
            "_agent_display_last_search_query",
            current_search_query,
        )
        if current_search_query != last_search_query:
            self._record_display_full_rebuild_fallback("search_query_changed")
            return False
        grouping_mode = getattr(self, "_grouping_mode", GroupingMode.STANDARD)
        if grouping_mode not in {
            GroupingMode.STANDARD,
            GroupingMode.BY_STATUS,
            GroupingMode.BY_MACHINE,
        }:
            self._record_display_full_rebuild_fallback("unsupported_grouping")
            return False
        if not self._agent_display_widgets_match_grouping_mode():
            self._record_display_full_rebuild_fallback("stale_grouping_mode")
            return False

        merge_tribe_panels = getattr(self, "_agent_panels_grouped", False)
        if not self._agent_display_widgets_have_previous_rows(previous_agents):
            return False

        diff = build_agent_display_diff(previous_agents, self._agents)
        scope = self._panel_rebuild_scope(
            previous_agents,
            diff,
            grouping_mode=grouping_mode,
            merge_tribe_panels=merge_tribe_panels,
        )
        for key, reason in scope.reasons:
            self._record_display_panel_rebuild_fallback(reason, key)

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
            completed = self._try_refresh_agents_display_incremental_impl(
                previous_agents,
                diff=diff,
                scope=scope,
                defer_detail=defer_detail,
                merge_tribe_panels=merge_tribe_panels,
            )
        if completed:
            record_agents_paint_frame(self, kind="incremental")
        return completed

    def _panel_rebuild_scope(
        self,
        previous_agents: list[Agent],
        diff: Any,
        *,
        grouping_mode: GroupingMode,
        merge_tribe_panels: bool,
    ) -> PanelRebuildScope:
        """Return the panels a roster change must rebuild rather than patch.

        A change that touches no panel structure leaves the scope empty and the
        apply on the cheap patch path. Otherwise only the panels the change
        concerns are named, so a sibling panel keeps its widget untouched.
        """
        if not diff.has_changes:
            return PanelRebuildScope()
        from ...models.agent_panel_index import build_agent_panel_index

        previous_index = build_agent_panel_index(
            previous_agents,
            dismissable_statuses=DISMISSABLE_STATUSES,
            merge_tribe_panels=merge_tribe_panels,
        )
        return panel_rebuild_scope(
            diff,
            previous_agents,
            self._agents,
            previous_index=previous_index,
            next_index=self._agent_panel_index(),  # type: ignore[attr-defined]
            by_status=grouping_mode is GroupingMode.BY_STATUS,
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
            if not panel_widget_is_retiring(widget)
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
        return any(
            int(getattr(widget, "option_count", 0)) > 0
            for widget in widgets
            if not panel_widget_is_retiring(widget)
        )

    def _try_refresh_agents_display_incremental_impl(
        self,
        previous_agents: list[Agent],
        *,
        diff: Any,
        scope: PanelRebuildScope,
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
        reconciled_retired = self._sync_panel_group() or set()  # type: ignore[attr-defined]
        self._snap_focus_after_agents_fold_restore()  # type: ignore[attr-defined]

        group_fold_stale = self._group_fold_stale_panel_keys()  # type: ignore[attr-defined]
        for key in sorted(group_fold_stale, key=lambda k: panel_widget_id_for_key(k)):
            self._record_display_panel_rebuild_fallback("group_fold_change", key)

        affected_keys = affected_panel_keys(
            diff,
            previous_agents,
            self._agents,
            merge_tribe_panels=merge_tribe_panels,
        )
        # Panels a whole-roster predicate concerns are rebuilt whole: never
        # patched row by row, and never given an in-place insert.
        # Fold-stale panels join the same forced set so the in-place
        # row-insert shortcut is ruled out for them as well.
        forced_rebuild_keys: set[Any] = set(scope.keys) | set(group_fold_stale)
        panel_rebuild_keys: set[Any] = set(forced_rebuild_keys)
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
        if reconciled_retired:
            # A key retired by the sync-time reconcile may belong to a panel
            # that was already a zero-row strip: no diff entry names it, so
            # name it for rebuild and let the widget sync unmount it in this
            # frame (recorded as display_panel_remove) instead of lingering.
            panel_rebuild_keys.update(reconciled_retired)

        removed_in_place = set(diff.removed_identities) - scope.rebuilt_removals
        if removed_in_place and not self._try_remove_agent_rows(  # type: ignore[attr-defined]
            removed_in_place
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
            if not self._try_patch_agent_row(  # type: ignore[attr-defined]
                agent, refresh_info=False
            ):
                return False

        if panel_rebuild_keys:
            # A panel whose rows only gained plain nodes takes an in-place row
            # insert; the rest are rebuilt.
            inserted_keys: set[Any] = set()
            if not self._refresh_affected_panel_widgets(  # type: ignore[attr-defined]
                panel_rebuild_keys,
                inserted_keys=inserted_keys,
                rebuild_only_keys=forced_rebuild_keys,
            ):
                self._record_display_full_rebuild_fallback(
                    "panel_membership_change",
                    count=len(panel_rebuild_keys),
                )
                return False
            rebuilt_keys = panel_rebuild_keys - inserted_keys
            if rebuilt_keys:
                self._record_display_patch_trace(  # type: ignore[attr-defined]
                    display_cost="display_panel_rebuild",
                    count=len(rebuilt_keys),
                )

        self._reapply_panel_heights()  # type: ignore[attr-defined]
        self._refresh_panel_highlights()  # type: ignore[attr-defined]
        self._update_agents_info_panel()  # type: ignore[attr-defined]
        update_agents_header = getattr(self, "_update_agents_header", None)
        if callable(update_agents_header):
            update_agents_header()
        if defer_detail:
            if self._sync_agents_onboarding(  # type: ignore[attr-defined]
                agent_detail=agent_detail, footer_widget=footer_widget
            ):
                return True
            if self._apply_tribe_summary(  # type: ignore[attr-defined]
                agent_detail,
                footer_widget,
                cheap=True,
            ):
                self._agent_detail_debouncer.schedule(
                    self._fire_debounced_detail_update  # type: ignore[attr-defined]
                )
                return True
            self._agent_detail_debouncer.schedule(
                self._fire_debounced_detail_update  # type: ignore[attr-defined]
            )
            return True

        self._apply_agent_detail_update(agent_detail, footer_widget)  # type: ignore[attr-defined]
        return True


__all__ = ["AgentDisplayIncrementalMixin"]

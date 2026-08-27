"""Reactive selection and tab watchers for :class:`AceApp`."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .artifact_tabs import ArtifactsSubTab, FilesSubTab
from .artifacts_description import ArtifactsDescriptionMode
from .artifacts_split import ArtifactsSplitMode
from .tab_order import ARTIFACTS_TAB, TabName
from .widgets import ArtifactsView, TabBar

if TYPE_CHECKING:
    from .actions.navigation._types import BannerJumpTarget, PanelJumpTarget


class AppWatchersMixin:
    """Respond to top-level selection and tab state changes."""

    def watch_current_idx(self: Any, old_idx: int, new_idx: int) -> None:
        """React to current_idx changes."""
        if old_idx != new_idx:
            if (
                self.current_tab == ARTIFACTS_TAB
                and self.current_artifacts_subtab == "patches"
            ):
                self._refresh_patches_display_debounced()
            elif self.current_tab == "agents":
                self._refresh_agents_display_debounced()
            elif self.current_tab == "axe":
                self._refresh_axe_display_debounced()
            refresh_link_rail = getattr(self, "refresh_link_rail", None)
            if callable(refresh_link_rail):
                refresh_link_rail()
            if self._jk_perf is not None:
                self.call_after_refresh(self._jk_perf.mark_painted)

    def watch_current_tab(
        self: Any,
        old_tab: TabName,
        new_tab: TabName,
    ) -> None:
        """React to tab changes by showing/hiding views."""
        if old_tab == new_tab:
            return

        cancel_member_jump = getattr(self, "_cancel_member_jump_pending", None)
        if callable(cancel_member_jump):
            cancel_member_jump(refresh_footer=False)

        from .util.trace import set_trace_context

        set_trace_context(current_tab=new_tab)

        if new_tab == "axe" or (
            new_tab == ARTIFACTS_TAB and self.current_artifacts_subtab != "patches"
        ):
            self._fold_mode_active = False

        # Cancel pending detail-panel work for the tab we're leaving. The new
        # tab redraws fresh, so deferred work would land in a hidden view.
        if old_tab == "agents":
            if getattr(self, "_agent_hint_render_identity", None) is not None:
                self._remove_hint_input_bar(refresh=False)
            self._exit_agent_metadata_search_for_context_change()
            self._agent_detail_debouncer.cancel()
            self._expanded_panel_focus = False
        elif old_tab == "axe":
            self._axe_detail_debouncer.cancel()
        elif old_tab == ARTIFACTS_TAB and self.current_artifacts_subtab == "patches":
            self._patch_detail_debouncer.cancel()

        if old_tab == "agents" and getattr(self, "_panel_fold_hint_mode_active", False):
            self._teardown_panel_fold_hint_mode(refresh_titles=False)

        # Tab changes always cancel adaptive entry-jump mode.
        self._cancel_non_pr_artifacts_jump_mode()
        self._entry_jump_mode_active = False
        self._entry_jump_hint_to_target: dict[str, object] = {}
        self._entry_jump_pending_prefix = ""
        self._entry_jump_hint_to_index: dict[str, int] = {}
        self._entry_jump_index_to_hint: dict[int, str] = {}
        self._entry_jump_hint_to_banner: dict[str, BannerJumpTarget] = {}
        self._entry_jump_banner_to_hint: dict[BannerJumpTarget, str] = {}
        self._entry_jump_hint_to_panel: dict[str, PanelJumpTarget] = {}
        self._entry_jump_panel_to_hint: dict[PanelJumpTarget, str] = {}
        self._entry_jump_hint_to_patch_banner: dict[str, tuple[str, ...]] = {}
        self._entry_jump_patch_banner_to_hint: dict[tuple[str, ...], str] = {}

        tab_bar = self.query_one("#tab-bar", TabBar)
        tab_bar.update_tab(new_tab)

        patches_view = self.query_one("#artifacts-view", ArtifactsView)
        agents_view = self.query_one("#agents-view")
        axe_view = self.query_one("#axe-view")

        if old_tab == ARTIFACTS_TAB:
            patches_view.deactivate_current()

        if new_tab == ARTIFACTS_TAB:
            patches_view.remove_class("hidden")
            patches_view.disabled = False
            agents_view.add_class("hidden")
            agents_view.disabled = True
            axe_view.add_class("hidden")
            axe_view.disabled = True
            patches_view.activate_current()
            self._sync_active_artifacts_entry_state()
        elif new_tab == "agents":
            patches_view.add_class("hidden")
            patches_view.disabled = True
            agents_view.remove_class("hidden")
            agents_view.disabled = False
            axe_view.add_class("hidden")
            axe_view.disabled = True
            self._sync_artifact_file_viewer_layout()
            # During mount, on_mount schedules the initial async load. On a
            # later tab switch, show cached data immediately and only re-fetch
            # when there is pending work to consume.
            if not self._mounting:
                self._refilter_agents()
                if getattr(self, "_dirty_agents", False) and not getattr(
                    self, "_agents_loading", False
                ):
                    if hasattr(self, "_schedule_agents_async_refresh"):
                        self._schedule_agents_async_refresh(source="tab_switch")
        else:  # axe
            patches_view.add_class("hidden")
            patches_view.disabled = True
            agents_view.add_class("hidden")
            agents_view.disabled = True
            axe_view.remove_class("hidden")
            axe_view.disabled = False
            self._refresh_axe_display()
            self._schedule_axe_async_refresh()

        # Refresh an open tab-scoped help panel with the new context.
        from .modals import HelpModal

        screen = self.screen
        if isinstance(screen, HelpModal):
            if new_tab == "agents":
                self._prepare_agents_help_guide_state()
            pane_id = getattr(self, "current_artifacts_pane_key", "patches")
            query_context = getattr(self, "_query_history_help_context", None)
            if callable(query_context):
                active_query, query_history, query_history_enabled = query_context()
            else:
                active_query = self.canonical_query_string
                query_history = None
                query_history_enabled = False
            screen.refresh_for_tab(
                new_tab,
                active_query,
                registry=self._keymap_registry,
                saved_queries={
                    slot: record.canonical
                    for slot, record in self._saved_queries.get(pane_id, {}).items()
                },
                query_history=query_history,
                query_history_enabled=query_history_enabled,
                pane_id=pane_id,
                agents_launch_targets_available=(
                    self._agents_onboarding_launch_targets_available
                ),
                agents_plugins_installed=self._agents_onboarding_plugins_installed,
            )
        refresh_link_rail = getattr(self, "refresh_link_rail", None)
        if callable(refresh_link_rail):
            refresh_link_rail()

    def watch_current_artifacts_subtab(
        self: Any,
        old_subtab: ArtifactsSubTab,
        new_subtab: ArtifactsSubTab,
    ) -> None:
        """Switch Artifacts panes and preserve PR detail/refresh isolation."""
        if old_subtab == new_subtab:
            return
        if new_subtab != "patches":
            self._fold_mode_active = False
        if self._entry_jump_mode_active:
            self._exit_entry_jump_mode()
        else:
            self._cancel_non_pr_artifacts_jump_mode()
        try:
            view = self.query_one("#artifacts-view", ArtifactsView)
        except Exception:
            return
        if old_subtab == "patches":
            self._patch_detail_debouncer.cancel()
        view.switch_to(new_subtab)
        if self.current_tab != ARTIFACTS_TAB:
            return
        self._sync_active_artifacts_entry_state()
        refresh_link_rail = getattr(self, "refresh_link_rail", None)
        if callable(refresh_link_rail):
            refresh_link_rail()
        from .modals import HelpModal

        screen = self.screen
        if isinstance(screen, HelpModal):
            pane_id = getattr(self, "current_artifacts_pane_key", "patches")
            query_context = getattr(self, "_query_history_help_context", None)
            if callable(query_context):
                active_query, query_history, query_history_enabled = query_context()
            else:
                active_query = self.canonical_query_string
                query_history = None
                query_history_enabled = False
            screen.refresh_for_tab(
                self.current_tab,
                active_query,
                registry=self._keymap_registry,
                saved_queries={
                    slot: record.canonical
                    for slot, record in self._saved_queries.get(pane_id, {}).items()
                },
                query_history=query_history,
                query_history_enabled=query_history_enabled,
                pane_id=pane_id,
                agents_launch_targets_available=(
                    self._agents_onboarding_launch_targets_available
                ),
                agents_plugins_installed=self._agents_onboarding_plugins_installed,
            )

    def watch_artifacts_split_mode(
        self: Any,
        old_mode: ArtifactsSplitMode,
        new_mode: ArtifactsSplitMode,
    ) -> None:
        """Apply the shared Artifacts split and refresh the Patch width cap."""

        if old_mode == new_mode:
            return
        try:
            view = self.query_one("#artifacts-view", ArtifactsView)
        except Exception:
            return
        view.apply_split_mode(new_mode)
        self._apply_patch_list_width()

    def watch_artifacts_description_mode(
        self: Any,
        old_mode: ArtifactsDescriptionMode,
        new_mode: ArtifactsDescriptionMode,
    ) -> None:
        """Apply the shared pane-brief description mode."""

        if old_mode == new_mode:
            return
        try:
            view = self.query_one("#artifacts-view", ArtifactsView)
        except Exception:
            return
        view.apply_description_mode(new_mode)

    def watch_current_files_subtab(
        self: Any,
        old_subtab: FilesSubTab,
        new_subtab: FilesSubTab,
    ) -> None:
        """Compatibility watcher for the retired nested Files panes."""
        del old_subtab, new_subtab

"""Mount-time setup helpers for the ACE TUI."""

from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger(__name__)


class StartupMountMixin:
    """Mixin for ``on_mount`` and mount-adjacent UI state helpers."""

    _stall_watchdog: Any

    def on_mount(self: Any) -> None:
        """Set up the app synchronously and defer slow reads until first paint."""
        import asyncio

        from ..widgets import (
            AgentDetail,
            AgentInfoPanel,
            ArtifactsView,
            PatchDetail,
            PatchFilterBar,
            PatchInfoPanel,
            PatchList,
            KeybindingFooter,
            RelationPanel,
            TabBar,
        )

        self._mounting = True
        try:
            self._mark_startup_on_mount()

            from ..util.trace import set_trace_context

            set_trace_context(current_tab=self.current_tab)

            # Wire keymap registry to widgets.
            footer = self.query_one("#keybinding-footer", KeybindingFooter)
            footer.set_keymap_registry(self._keymap_registry)
            tab_bar = self.query_one("#tab-bar", TabBar)
            tab_bar.set_keymap_registry(self._keymap_registry)
            tab_bar.update_tab(self.current_tab)
            artifacts_view = self.query_one("#artifacts-view", ArtifactsView)
            artifacts_view.set_keymap_registry(self._keymap_registry)
            # The Stitches pane was composed with its fully merged startup
            # query. Shared scope setup must not overwrite that visible token.
            # A current-project seed arrives later from the async inventory
            # and only fills in when ``commits.filters.project`` is still None.
            artifacts_view.set_project_scope(
                self.artifacts_project_scope,
                update_commits=False,
            )
            self.query_one("#artifacts-view").disabled = self.current_tab != "artifacts"
            self.query_one("#agents-view").disabled = self.current_tab != "agents"
            self.query_one("#axe-view").disabled = self.current_tab != "axe"
            if self.current_tab == "artifacts":
                # The view's mount hook owns lifecycle activation; share the
                # same footer/scope entry behavior as top-level navigation.
                self._sync_active_artifacts_entry_state()
            else:
                self.set_timer(0.01, self._focus_startup_visible_tab)
            if self._commits_default_query_diagnostic is not None:
                self.notify(
                    self._commits_default_query_diagnostic,
                    severity="warning",
                    timeout=8,
                )
            info_panel = self.query_one("#agent-info-panel", AgentInfoPanel)
            info_panel.set_keymap_registry(self._keymap_registry)
            try:
                cs_info_panel = self.query_one("#info-panel", PatchInfoPanel)
                cs_info_panel.set_keymap_registry(self._keymap_registry)
            except Exception:
                log.debug("Patch info panel keymap wiring skipped: widget not found")

            # Cache stable widget refs so hot paths skip repeat ``query_one``
            # walks. Wrapped in try/except so a missing widget never blocks
            # mount; callers fall back to ``query_one`` when a ref is unset.
            self._w_footer = footer
            self._w_tab_bar = tab_bar
            self._w_agent_info_panel = info_panel
            for attr, selector, cls in (
                ("_w_patch_list", "#list-panel", PatchList),
                ("_w_patch_detail", "#detail-panel", PatchDetail),
                (
                    "_w_relation_panel",
                    "#patches-relation-panel",
                    RelationPanel,
                ),
                ("_w_patch_info_panel", "#info-panel", PatchInfoPanel),
                ("_w_patch_filter_bar", "#patch-filter-bar", PatchFilterBar),
                ("_w_agent_detail", "#agent-detail-panel", AgentDetail),
            ):
                try:
                    setattr(self, attr, self.query_one(selector, cls))
                except Exception:
                    log.debug("widget ref cache skipped: %s not found", selector)

            self._apply_startup_loading_state()
            self.call_after_refresh(self._start_post_mount_background_loads)
            start_proc_reconciler = getattr(self, "_start_proc_reconciler", None)
            if callable(start_proc_reconciler):
                start_proc_reconciler()

            from ..util.stall_watchdog import (
                start_event_loop_stall_watchdog,
                subscribe_watchdog_to_suspend_signals,
            )

            self._stall_watchdog = start_event_loop_stall_watchdog(
                asyncio.get_running_loop(),
                app=self,
                context_provider=self._tui_stall_context,
            )
            self._stall_watchdog_suspend_signals_wired = (
                subscribe_watchdog_to_suspend_signals(self, self._stall_watchdog)
            )
            self._last_input_mono = time.monotonic()

            if self.refresh_interval > 0:
                self._countdown_remaining = self.refresh_interval
                countdown_tick = self._on_countdown_tick
                auto_refresh = self._on_auto_refresh
                self._countdown_timer = self.set_interval(
                    1, countdown_tick, name="countdown"
                )
                self._refresh_timer = self.set_interval(
                    self.refresh_interval, auto_refresh, name="auto-refresh"
                )

        finally:
            self._mounting = False

    def _focus_startup_visible_tab(self: Any) -> None:
        """Keep hidden startup panes from retaining keyboard focus."""
        if self.current_tab == "agents":
            selector = "#agent-list-panel"
        elif self.current_tab == "axe":
            selector = "#bgcmd-list-panel"
        else:
            return
        try:
            self.query_one(selector).focus()
        except Exception:
            log.debug("startup focus normalization skipped: %s not found", selector)

    def _tui_stall_context(self: Any) -> dict[str, Any]:
        """Return side-effect-free context for the stall watchdog thread."""
        now_mono = time.monotonic()
        last_keypress_age_s: float | None = None
        last_input_mono = getattr(self, "_last_input_mono", 0.0)
        if last_input_mono > 0.0:
            last_keypress_age_s = max(0.0, now_mono - last_input_mono)
        return {
            "current_tab": self.current_tab,
            "current_idx": self.current_idx,
            "current_attempt_number": self._current_attempt_number,
            "last_action": getattr(self, "_last_input_action", None),
            "last_keypress_age_s": (
                None if last_keypress_age_s is None else round(last_keypress_age_s, 3)
            ),
        }

    def _maybe_end_startup_stopwatch(self: Any) -> None:
        """End the startup stopwatch once the initially visible tab is ready.

        Deliberately visible-surface based, not "every hidden tab is ready":
        a future hidden-tab feature must not be able to silently regress the
        startup stopwatch for every mode by adding a third surface that has
        to finish loading first. ``_startup_visible_surface_ready`` (from
        ``StartupTelemetryMixin``) is the single source of truth for which
        tab's readiness gates this.
        """
        if not self._startup_visible_surface_ready():
            return
        try:
            from ..widgets import KeybindingFooter

            self.query_one(
                "#keybinding-footer", KeybindingFooter
            ).end_startup_stopwatch()
        except Exception:
            pass

    def _apply_startup_loading_state(self: Any) -> None:
        """Mark async-loaded panels as loading so the user sees spinners.

        Flips ``.loading`` on the two AgentList widgets and the AxeDashboard
        (driving Textual's built-in LoadingIndicator), and switches the
        Agents tab label plus info panels into their dim-ellipsis state.
        The flags are cleared once the first async load completes.
        """
        from ..widgets import (
            AgentInfoPanel,
            AgentList,
            AxeDashboard,
            AxeInfoPanel,
        )

        if not self._agents_first_load_done:
            try:
                self.query_one("#agent-list-panel", AgentList).loading = True
            except Exception:
                pass
            try:
                self.query_one("#agent-info-panel", AgentInfoPanel).set_loading(True)
            except Exception:
                pass

        if not self._axe_first_load_done:
            try:
                self.query_one("#axe-dashboard", AxeDashboard).loading = True
            except Exception:
                pass
            try:
                self.query_one("#axe-info-panel", AxeInfoPanel).set_loading(True)
            except Exception:
                pass

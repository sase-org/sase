"""Mount-time setup helpers for the ACE TUI."""

from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger(__name__)


class StartupMountMixin:
    """Mixin for ``on_mount`` and mount-adjacent UI state helpers."""

    _stall_watchdog: Any

    async def on_mount(self: Any) -> None:
        """Set up the app on mount.

        Async so each disk read can ``await asyncio.to_thread(...)``
        between applying to widgets - the event loop stays free between
        helpers so the ``KeybindingFooter`` startup stopwatch can tick at
        ~10Hz through the multi-second startup gap.
        """
        import asyncio

        from ..widgets import (
            AgentDetail,
            AgentInfoPanel,
            AncestorsChildrenPanel,
            AxeInfoPanel,
            ArtifactsView,
            ChangeSpecDetail,
            ChangeSpecInfoPanel,
            ChangeSpecList,
            KeybindingFooter,
            SearchQueryPanel,
            TabBar,
        )

        self._mounting = True
        try:
            from ..util.trace import set_trace_context

            set_trace_context(current_tab=self.current_tab)

            # Wire keymap registry to widgets.
            footer = self.query_one("#keybinding-footer", KeybindingFooter)
            footer.set_keymap_registry(self._keymap_registry)
            tab_bar = self.query_one("#tab-bar", TabBar)
            tab_bar.set_keymap_registry(self._keymap_registry)
            tab_bar.update_tab(self.current_tab)
            artifacts_view = self.query_one("#changespecs-view", ArtifactsView)
            artifacts_view.set_keymap_registry(self._keymap_registry)
            artifacts_view.set_project_scope(self.artifacts_project_scope)
            info_panel = self.query_one("#agent-info-panel", AgentInfoPanel)
            info_panel.set_keymap_registry(self._keymap_registry)
            try:
                cs_info_panel = self.query_one("#info-panel", ChangeSpecInfoPanel)
                cs_info_panel.set_keymap_registry(self._keymap_registry)
            except Exception:
                log.debug(
                    "ChangeSpec info panel keymap wiring skipped: widget not found"
                )
            try:
                axe_info_panel = self.query_one("#axe-info-panel", AxeInfoPanel)
                axe_info_panel.set_keymap_registry(self._keymap_registry)
            except Exception:
                log.debug("AXE info panel keymap wiring skipped: widget not found")

            # Cache stable widget refs so hot paths skip repeat ``query_one``
            # walks. Wrapped in try/except so a missing widget never blocks
            # mount; callers fall back to ``query_one`` when a ref is unset.
            self._w_footer = footer
            self._w_tab_bar = tab_bar
            self._w_agent_info_panel = info_panel
            for attr, selector, cls in (
                ("_w_changespec_list", "#list-panel", ChangeSpecList),
                ("_w_changespec_detail", "#detail-panel", ChangeSpecDetail),
                (
                    "_w_ancestors_children",
                    "#ancestors-children-panel",
                    AncestorsChildrenPanel,
                ),
                ("_w_changespec_info_panel", "#info-panel", ChangeSpecInfoPanel),
                ("_w_search_query_panel", "#search-query-panel", SearchQueryPanel),
                ("_w_agent_detail", "#agent-detail-panel", AgentDetail),
            ):
                try:
                    setattr(self, attr, self.query_one(selector, cls))
                except Exception:
                    log.debug("widget ref cache skipped: %s not found", selector)

            notif_state = await asyncio.to_thread(self._read_notifications_for_startup)
            self._initialize_agent_tracking(notif_state)

            stash_counts = await asyncio.to_thread(self._read_prompt_stash_counts)
            self._apply_prompt_stash_counts(*stash_counts)

            all_cs = await asyncio.to_thread(self._read_changespecs_from_disk)
            self._apply_changespecs(all_cs)

            last_name = await asyncio.to_thread(self._read_last_selection_name)
            self._restore_last_selection(last_name)
            await asyncio.to_thread(self._save_current_query)

            self._apply_startup_loading_state()
            self.call_after_refresh(self._start_post_mount_background_loads)

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

            # Best-effort title refinement. Runs last (after first paint is
            # already scheduled) and off-thread because resolving a
            # git-derived dev version blocks on git subprocesses for editable
            # installs. Wheel installs typically resolve to the same string
            # and see no visible change; a ``None`` result keeps the instant
            # ``__version__``-based title from ``__init__``.
            from ..util.app_version import (
                format_app_title,
                initial_app_version,
                resolved_app_version,
            )

            version = await asyncio.to_thread(resolved_app_version)
            if version and version != initial_app_version():
                self.title = format_app_title(version)
        finally:
            self._mounting = False

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
            "last_keypress_age_s": (
                None if last_keypress_age_s is None else round(last_keypress_age_s, 3)
            ),
        }

    def _maybe_end_startup_stopwatch(self: Any) -> None:
        """End startup stopwatch once both async startup surfaces are loaded."""
        if not (self._agents_first_load_done and self._axe_first_load_done):
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

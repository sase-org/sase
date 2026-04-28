"""Startup/mount mixin for the ace TUI app.

Houses the ``on_mount`` handler and its post-mount helpers. The bulky
``_init_app_state`` method that runs from ``AceApp.__init__`` lives in
``_state_init.py`` to keep both files under the per-file line budget;
``StartupMixin`` inherits it transparently.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Literal, cast

from textual.timer import Timer

from ...query.types import QueryExpr
from ..activity_log import ActivityLog
from ..util.fs_watcher import ArtifactWatcher
from ..util.nav_gate import NavigationGate
from ._state_init import StateInitMixin

if TYPE_CHECKING:
    from .navigation._types import JumpAllResult

log = logging.getLogger(__name__)

TabName = Literal["changespecs", "agents", "axe"]


class StartupMixin(StateInitMixin):
    """Mixin providing app state initialization and mount-time setup."""

    # Attributes set by ``_init_app_state`` and referenced from other mixins.
    query_string: str
    parsed_query: QueryExpr
    refresh_interval: int
    theme: str
    _current_idx: int
    _current_attempt_number: int | None
    _auto_start_axe: bool
    _restart_axe: bool
    _mounting: bool
    _agents_first_load_done: bool
    _axe_first_load_done: bool
    _refresh_timer: Timer | None
    _countdown_timer: Timer | None
    _countdown_remaining: int
    _activity_log: ActivityLog
    _last_activity_time: float
    _last_activity_flush: float
    _pinned_idle: bool
    _post_mount_background_loads_started: bool
    _jump_all_last_position: JumpAllResult | None
    _nav_gate: NavigationGate
    _fs_watcher: ArtifactWatcher | None
    _w_changespec_list: Any
    _w_changespec_detail: Any
    _w_ancestors_children: Any
    _w_changespec_info_panel: Any
    _w_footer: Any
    _w_search_query_panel: Any
    _w_agent_detail: Any
    _w_agent_info_panel: Any
    _w_tab_bar: Any
    _saved_queries: dict[str, str]
    _dirty_changespecs: bool
    _dirty_agents: bool
    _dirty_axe: bool
    _last_full_sanity_refresh: float
    _user_snippets: dict[str, str]
    _snippets_cache: dict[str, str] | None

    def get_snippets(self) -> dict[str, str]:
        """Return the merged xprompt + user snippet registry, building on demand.

        First call walks disk-backed xprompt definitions to materialize the
        combined map; subsequent calls reuse the cached dict. The widgets
        that need snippets (prompt text-area, help modal) call this rather
        than reading ``_snippets`` directly so cold startup never pays the
        scan unless the user opens the snippet entry surface.
        """
        cached = getattr(self, "_snippets_cache", None)
        if cached is not None:
            return cached
        from sase.xprompt.snippet_bridge import get_xprompt_snippets

        merged = get_xprompt_snippets()
        merged.update(self._user_snippets)
        self._snippets_cache = merged
        return merged

    def _invalidate_saved_queries_cache(self) -> None:
        """Reload ``_saved_queries`` from disk after a save/delete.

        Called by the actions that mutate saved-query slots (save / delete
        keymap and the help modal). The hot render path (``SearchQueryPanel``)
        only touches the cached dict, so this is the lone refill site.
        """
        from ...saved_queries import load_saved_queries

        self._saved_queries = load_saved_queries()

    async def on_mount(self) -> None:
        """Set up the app on mount.

        Async so each disk read can ``await asyncio.to_thread(...)``
        between applying to widgets — the event loop stays free between
        helpers so the ``KeybindingFooter`` startup stopwatch can tick at
        ~10Hz through the multi-second startup gap.
        """
        import asyncio

        from ..widgets import (
            AgentDetail,
            AgentInfoPanel,
            AncestorsChildrenPanel,
            ChangeSpecDetail,
            ChangeSpecInfoPanel,
            ChangeSpecList,
            InactiveIndicator,
            KeybindingFooter,
            SearchQueryPanel,
            TabBar,
        )

        self._mounting = True
        try:
            # Wire keymap registry to widgets
            footer = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
            footer.set_keymap_registry(self._keymap_registry)
            tab_bar = self.query_one("#tab-bar", TabBar)  # type: ignore[attr-defined]
            tab_bar.set_keymap_registry(self._keymap_registry)
            info_panel = self.query_one("#agent-info-panel", AgentInfoPanel)  # type: ignore[attr-defined]
            info_panel.set_keymap_registry(self._keymap_registry)
            try:
                cs_info_panel = self.query_one(  # type: ignore[attr-defined]
                    "#info-panel", ChangeSpecInfoPanel
                )
                cs_info_panel.set_keymap_registry(self._keymap_registry)
            except Exception:
                log.debug("CL info panel keymap wiring skipped: widget not found")

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
                    setattr(self, attr, self.query_one(selector, cls))  # type: ignore[attr-defined]
                except Exception:
                    log.debug("widget ref cache skipped: %s not found", selector)

            # Initialize agent tracking for completion notifications
            notif_state = await asyncio.to_thread(
                self._read_notifications_for_startup  # type: ignore[attr-defined]
            )
            self._initialize_agent_tracking(notif_state)  # type: ignore[attr-defined]

            # Load initial changespecs with the startup query
            all_cs = await asyncio.to_thread(self._read_changespecs_from_disk)  # type: ignore[attr-defined]
            self._apply_changespecs(all_cs)  # type: ignore[attr-defined]

            # If no results, try saved queries as fallback; if none work, open
            # the Agents tab instead
            if not self.changespecs:  # type: ignore[attr-defined]
                if not await self._try_startup_fallback_async():  # type: ignore[attr-defined]
                    self.current_tab = "agents"  # type: ignore[assignment,attr-defined]

            last_name = await asyncio.to_thread(self._read_last_selection_name)  # type: ignore[attr-defined]
            self._restore_last_selection(last_name)  # type: ignore[attr-defined]
            await asyncio.to_thread(self._save_current_query)  # type: ignore[attr-defined]

            # Show loading indicators on panels that populate asynchronously
            # so users see pulsing spinners / dim ellipses instead of
            # "loaded, empty" state during the ~3.5s gap before first data.
            self._apply_startup_loading_state()

            # Defer startup background loads until after first paint.
            # The launcher schedules agents and axe tasks independently so
            # the AXE startup path is never blocked by a slow agent load.
            self.call_after_refresh(self._start_post_mount_background_loads)  # type: ignore[attr-defined]

            # Write initial activity timestamp, idle state, and PID file.
            # If pinned idle was active in the previous session, restore it.
            from sase.ace.tui_activity import (
                read_pinned_idle,
                write_activity_timestamp,
                write_idle_state,
                write_last_keypress,
                write_tui_pid,
            )

            from ..activity_log import ActivityEventType

            write_tui_pid()
            self._activity_log.record(ActivityEventType.SESSION_START)
            if read_pinned_idle():
                self._pinned_idle = True
                if hasattr(self, "_last_activity_time"):
                    del self._last_activity_time
                write_activity_timestamp(0)
                write_idle_state(True)
                indicator = self.query_one("#inactive-indicator", InactiveIndicator)  # type: ignore[attr-defined]
                indicator.set_idle(True, pinned=True)
                self._activity_log.record(ActivityEventType.IDLE_RESTORED)
            else:
                self._last_activity_time = time.monotonic()
                self._last_activity_flush = time.monotonic()
                now = time.time()
                write_activity_timestamp(now)
                write_last_keypress(now)
                write_idle_state(False)

            # Set up auto-refresh timer if enabled
            if self.refresh_interval > 0:
                self._countdown_remaining = self.refresh_interval
                countdown_tick = self._on_countdown_tick  # type: ignore[attr-defined]
                auto_refresh = self._on_auto_refresh  # type: ignore[attr-defined]
                self._countdown_timer = self.set_interval(  # type: ignore[attr-defined]
                    1, countdown_tick, name="countdown"
                )
                self._refresh_timer = self.set_interval(  # type: ignore[attr-defined]
                    self.refresh_interval, auto_refresh, name="auto-refresh"
                )
        finally:
            self._mounting = False

    def _start_post_mount_background_loads(self) -> None:
        """Launch post-mount startup loads once, without serial dependency."""
        if self._post_mount_background_loads_started:
            return
        self._post_mount_background_loads_started = True
        try:
            self.run_worker(  # type: ignore[attr-defined]
                cast(Any, self._run_agents_async_refresh),  # type: ignore[attr-defined]
                thread=False,
                exclusive=False,
                group="startup-loads",
            )
        except Exception:
            log.exception("Failed to schedule startup agent refresh")
        try:
            self.run_worker(  # type: ignore[attr-defined]
                cast(Any, self._run_axe_startup_init),  # type: ignore[attr-defined]
                thread=False,
                exclusive=False,
                group="startup-loads",
            )
        except Exception:
            log.exception("Failed to schedule startup axe init")
        try:
            self._start_artifact_watcher()
        except Exception:
            log.exception("Failed to start artifact inotify watcher")

    def _start_artifact_watcher(self) -> None:
        """Spin up an inotify watcher on ``~/.sase/projects/`` if supported.

        Falls back silently when inotify is unavailable; the auto-refresh
        timer remains the polling safety net in that case.
        """
        from pathlib import Path

        if self._fs_watcher is not None:
            return
        projects_dir = Path.home() / ".sase" / "projects"
        if not projects_dir.exists():
            return
        # Watch each project's artifacts dir directly.  inotify on a
        # parent dir only fires for direct-child events, so watching
        # ``projects/`` would miss writes inside ``projects/<p>/artifacts/``.
        watch_paths: list[Path] = []
        for project_dir in projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            artifacts_dir = project_dir / "artifacts"
            if artifacts_dir.is_dir():
                watch_paths.append(artifacts_dir)
            # Project files (.gp) live directly in ``project_dir``;
            # watching the dir picks up RUNNING-field updates.
            watch_paths.append(project_dir)
        if not watch_paths:
            return
        watcher = ArtifactWatcher(
            watch_paths,
            on_change=self._on_artifact_change,  # type: ignore[attr-defined]
            schedule_callback=self.call_from_thread,  # type: ignore[attr-defined]
        )
        if watcher.start():
            self._fs_watcher = watcher

    def _stop_artifact_watcher(self) -> None:
        """Tear down the inotify watcher on quit."""
        watcher = self._fs_watcher
        if watcher is None:
            return
        self._fs_watcher = None
        try:
            watcher.stop()
        except Exception:
            log.exception("Failed to stop artifact watcher cleanly")

    def _maybe_end_startup_stopwatch(self) -> None:
        """End startup stopwatch once both async startup surfaces are loaded."""
        if not (self._agents_first_load_done and self._axe_first_load_done):
            return
        try:
            from ..widgets import KeybindingFooter

            self.query_one(  # type: ignore[attr-defined]
                "#keybinding-footer", KeybindingFooter
            ).end_startup_stopwatch()
        except Exception:
            pass

    def _apply_startup_loading_state(self) -> None:
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
            TabBar,
        )

        if not self._agents_first_load_done:
            try:
                self.query_one("#agent-list-panel", AgentList).loading = True  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                tab_bar = self.query_one("#tab-bar", TabBar)  # type: ignore[attr-defined]
                tab_bar.update_agents_count(0, 0, show_hidden=False, loading=True)
            except Exception:
                pass
            try:
                self.query_one("#agent-info-panel", AgentInfoPanel).set_loading(True)  # type: ignore[attr-defined]
            except Exception:
                pass

        if not self._axe_first_load_done:
            try:
                self.query_one("#axe-dashboard", AxeDashboard).loading = True  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                self.query_one("#axe-info-panel", AxeInfoPanel).set_loading(True)  # type: ignore[attr-defined]
            except Exception:
                pass

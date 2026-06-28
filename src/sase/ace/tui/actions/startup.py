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

from sase.core.paths import sase_projects_dir, sase_subdir

from ...query.types import QueryExpr
from ..activity_log import ActivityLog
from ..util.fs_watcher import ArtifactWatcher
from ..util.nav_gate import NavigationGate
from ._state_init import StateInitMixin

if TYPE_CHECKING:
    from .navigation._types import JumpAllResult
    from ..prompt_catalog import PromptCatalogSnapshot
    from ..widgets.prompt_completion import PromptCompletionSettings
    from ..widgets.xprompt_arg_assist import XPromptAssistEntry

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
    _stall_watchdog: Any
    _stall_watchdog_suspend_signals_wired: bool
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
    _dirty_notifications: bool
    _last_full_sanity_refresh: float
    _user_snippets: dict[str, str]
    _snippets_cache: dict[str, str] | None
    _prompt_catalog: PromptCatalogSnapshot | None
    _prompt_catalog_generation: int
    _prompt_catalog_rebuild_in_flight: bool
    _prompt_catalog_rebuild_pending: bool
    _prompt_catalog_rebuild_pending_force: bool
    _prompt_catalog_projects: set[str | None]
    _prompt_catalog_token_check_last_mono: float
    _prompt_source_watcher: ArtifactWatcher | None
    _prompt_source_watcher_active: bool
    _prompt_source_watched_projects: set[str | None]
    _prompt_source_debounce_timer: Timer | None
    _prompt_completion_settings: PromptCompletionSettings

    def get_snippets(self) -> dict[str, str]:
        """Return the memory-only xprompt + user snippet registry."""
        cached = getattr(self, "_snippets_cache", None)
        if cached is not None:
            self._schedule_prompt_catalog_token_fallback_check()
            return cached
        self._schedule_prompt_catalog_rebuild(reason="snippet_cache_miss")
        return self._user_snippets

    def get_prompt_completion_settings(self) -> PromptCompletionSettings:
        """Return parsed prompt completion behavior settings."""
        return self._prompt_completion_settings

    def get_prompt_catalog_assist_entries(
        self,
        project: str | None,
        *,
        schedule: bool = True,
    ) -> list[XPromptAssistEntry] | None:
        """Return memory-only xprompt assist entries for *project* if warm."""
        self._ensure_prompt_catalog_project(project)
        catalog = self._prompt_catalog
        if catalog is not None:
            entries = catalog.assist_entries_by_project.get(project)
            if entries is not None:
                self._schedule_prompt_catalog_token_fallback_check()
                return list(entries)
            if project is not None:
                fallback = catalog.assist_entries_by_project.get(None)
                if fallback is not None:
                    if schedule:
                        self._schedule_prompt_catalog_rebuild(
                            reason="assist_project_miss"
                        )
                    return list(fallback)
        if schedule:
            self._schedule_prompt_catalog_rebuild(reason="assist_cache_miss")
        return None

    def warm_prompt_catalog_project(self, project: str | None) -> None:
        """Schedule an off-thread catalog warm for *project*."""
        self._ensure_prompt_catalog_project(project)
        self._schedule_prompt_catalog_token_fallback_check()
        catalog = self._prompt_catalog
        if (
            catalog is not None
            and project in catalog.assist_entries_by_project
            and self._snippets_cache is not None
        ):
            return
        self._schedule_prompt_catalog_rebuild(reason="assist_warm")

    def _ensure_prompt_catalog_project(self, project: str | None) -> None:
        """Track requested project catalogs and expand watches when needed."""
        if project in self._prompt_catalog_projects:
            return
        self._prompt_catalog_projects.add(project)
        if self._prompt_source_watcher is not None:
            self._restart_prompt_source_watcher()

    def _schedule_prompt_catalog_token_fallback_check(self) -> None:
        """Schedule a throttled token check when no watcher is active."""
        if self._prompt_source_watcher_active:
            return
        now = time.monotonic()
        if now - self._prompt_catalog_token_check_last_mono < 1.0:
            return
        self._prompt_catalog_token_check_last_mono = now
        self._schedule_prompt_catalog_rebuild(reason="token_fallback")

    def _schedule_prompt_catalog_rebuild(
        self,
        *,
        reason: str,
        force: bool = False,
    ) -> None:
        """Schedule a prompt catalog rebuild with last-request-wins coalescing."""
        del reason
        self._prompt_catalog_projects.add(None)
        if self._prompt_catalog_rebuild_in_flight:
            self._prompt_catalog_rebuild_pending = True
            self._prompt_catalog_rebuild_pending_force = (
                self._prompt_catalog_rebuild_pending_force or force
            )
            return

        self._prompt_catalog_rebuild_in_flight = True
        self._prompt_catalog_rebuild_pending = False
        self._prompt_catalog_rebuild_pending_force = False
        generation = self._prompt_catalog_generation
        projects = frozenset(self._prompt_catalog_projects)
        previous_token = (
            None
            if force or self._prompt_catalog is None
            else self._prompt_catalog.source_token
        )

        async def run_rebuild() -> None:
            await self._run_prompt_catalog_rebuild(
                generation,
                projects,
                previous_token,
            )

        try:
            self.run_worker(  # type: ignore[attr-defined]
                cast(Any, run_rebuild),
                name=f"prompt-catalog:{generation}",
                group="prompt-catalog",
                exclusive=False,
            )
        except Exception:
            self._prompt_catalog_rebuild_in_flight = False
            log.exception("Failed to schedule prompt catalog rebuild")

    async def _run_prompt_catalog_rebuild(
        self,
        generation: int,
        projects: frozenset[str | None],
        previous_source_token: tuple[Any, ...] | None,
    ) -> None:
        """Build the prompt catalog off-thread and apply it on the UI task."""
        import asyncio

        from ..prompt_catalog import build_prompt_catalog_snapshot

        snapshot = None
        try:
            snapshot = await asyncio.to_thread(
                build_prompt_catalog_snapshot,
                generation=generation,
                projects=projects,
                previous_source_token=previous_source_token,
            )
        except Exception:
            log.exception("Prompt catalog rebuild failed")
            try:
                self.notify(  # type: ignore[attr-defined]
                    "Failed to reload snippets/xprompts; keeping previous catalog",
                    severity="warning",
                    timeout=8,
                )
            except Exception:
                pass
        finally:
            self._prompt_catalog_rebuild_in_flight = False

        if snapshot is not None:
            self._apply_prompt_catalog_snapshot(snapshot)

        if self._prompt_catalog_rebuild_pending:
            pending_force = self._prompt_catalog_rebuild_pending_force
            self._prompt_catalog_rebuild_pending = False
            self._prompt_catalog_rebuild_pending_force = False
            self._schedule_prompt_catalog_rebuild(
                reason="prompt_catalog_pending",
                force=pending_force,
            )

    def _apply_prompt_catalog_snapshot(
        self,
        snapshot: PromptCatalogSnapshot,
    ) -> None:
        """Publish a freshly-built prompt catalog snapshot."""
        if snapshot.generation != self._prompt_catalog_generation:
            return
        self._prompt_catalog = snapshot
        self._snippets_cache = dict(snapshot.snippets)
        self._refresh_visible_prompt_catalog_surfaces()

    def _refresh_visible_prompt_catalog_surfaces(self) -> None:
        """Refresh currently-mounted prompt completion/hint surfaces."""
        try:
            from ..widgets.prompt_text_area import PromptTextArea

            text_areas = list(self.query(PromptTextArea))  # type: ignore[attr-defined]
        except Exception:
            return
        for text_area in text_areas:
            if not getattr(text_area, "is_mounted", False):
                continue
            try:
                if getattr(text_area, "_file_completion_active", False) and str(
                    getattr(text_area, "_completion_kind", "")
                ).startswith("xprompt"):
                    text_area._refresh_file_completion_from_cursor()
                if getattr(text_area, "_active_xprompt_arg_hint", None) is not None:
                    text_area._refresh_xprompt_arg_hint_from_cursor()
                text_area._on_prompt_completion_context_changed()
            except Exception:
                log.debug("Failed to refresh prompt catalog surface", exc_info=True)

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
            from ..util.trace import set_trace_context

            set_trace_context(current_tab=self.current_tab)  # type: ignore[attr-defined]

            # Wire keymap registry to widgets
            footer = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
            footer.set_keymap_registry(self._keymap_registry)
            tab_bar = self.query_one("#tab-bar", TabBar)  # type: ignore[attr-defined]
            tab_bar.set_keymap_registry(self._keymap_registry)
            tab_bar.update_tab(self.current_tab)  # type: ignore[attr-defined]
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

            # Seed the prompt-stash badge from disk (kept off the paint path).
            stash_counts = await asyncio.to_thread(
                self._read_prompt_stash_counts  # type: ignore[attr-defined]
            )
            self._apply_prompt_stash_counts(*stash_counts)  # type: ignore[attr-defined]

            # Load initial changespecs with the startup query
            all_cs = await asyncio.to_thread(self._read_changespecs_from_disk)  # type: ignore[attr-defined]
            self._apply_changespecs(all_cs)  # type: ignore[attr-defined]

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
            from ..util.stall_watchdog import (
                start_event_loop_stall_watchdog,
                subscribe_watchdog_to_suspend_signals,
            )

            self._stall_watchdog = start_event_loop_stall_watchdog(
                asyncio.get_running_loop(),
                context_provider=self._tui_stall_context,
            )
            # Global safety net: pause the watchdog across every intentional
            # ``suspend()`` terminal handoff so editors/viewers are not logged
            # as generic event-loop freezes. The external-tool helper falls
            # back to manual pausing when this hookup is unavailable.
            self._stall_watchdog_suspend_signals_wired = (
                subscribe_watchdog_to_suspend_signals(self, self._stall_watchdog)
            )
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
        """Launch post-mount startup loads once after first paint."""
        if self._post_mount_background_loads_started:
            return
        self._post_mount_background_loads_started = True
        dismissed_index_callback = self._schedule_dismissed_index_startup_sync
        try:
            self._agents_refresh_pending_callbacks.append(  # type: ignore[attr-defined]
                dismissed_index_callback
            )
            self._agents_refresh_scheduled_source = "startup"  # type: ignore[attr-defined]
            self.run_worker(  # type: ignore[attr-defined]
                cast(Any, self._run_agent_index_startup_prepare_and_refresh),
                thread=False,
                exclusive=False,
                group="startup-loads",
            )
        except Exception:
            try:
                self._agents_refresh_pending_callbacks.remove(  # type: ignore[attr-defined]
                    dismissed_index_callback
                )
            except ValueError:
                pass
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
        start_prompt_source_watcher = getattr(
            self, "_start_prompt_source_watcher", None
        )
        if callable(start_prompt_source_watcher):
            try:
                start_prompt_source_watcher()
            except Exception:
                log.exception("Failed to start prompt-source inotify watcher")
        schedule_prompt_catalog_rebuild = getattr(
            self, "_schedule_prompt_catalog_rebuild", None
        )
        if callable(schedule_prompt_catalog_rebuild):
            try:
                schedule_prompt_catalog_rebuild(reason="startup_warm")
            except Exception:
                log.exception("Failed to schedule prompt catalog warm")
        try:
            self._schedule_startup_update_toast_check()  # type: ignore[attr-defined]
        except Exception:
            log.debug("Failed to schedule startup update toast", exc_info=True)

    async def _run_agent_index_startup_prepare_and_refresh(self) -> None:
        """Refresh stale index projections before the first agents query."""
        try:
            await self._run_agent_index_startup_prepare()
        finally:
            await self._run_agents_async_refresh()  # type: ignore[attr-defined]

    async def _run_agent_index_startup_prepare(self) -> None:
        """Run cheap pre-query index maintenance off the first-paint path."""
        import asyncio

        from sase.core.agent_artifact_index_lifecycle import (
            refresh_agent_artifact_index_if_schema_stale,
        )
        from sase.core.agent_scan_wire import AGENT_ARTIFACT_INDEX_SCHEMA_VERSION

        try:
            report = await asyncio.to_thread(
                refresh_agent_artifact_index_if_schema_stale
            )
        except Exception:
            log.exception("Startup artifact-index schema refresh failed")
            return
        if report.refreshed:
            log.info(
                "rebuilt stale agent artifact index: schema %s -> %s, rows=%s",
                report.stored_schema_version,
                AGENT_ARTIFACT_INDEX_SCHEMA_VERSION,
                report.rows_indexed,
            )

    def _schedule_dismissed_index_startup_sync(self) -> None:
        """Schedule dismissed-index maintenance after startup agents load."""
        try:
            self.run_worker(  # type: ignore[attr-defined]
                cast(Any, self._run_dismissed_index_startup_sync),
                thread=False,
                exclusive=False,
                group="startup-loads",
            )
        except Exception:
            log.exception("Failed to schedule startup dismissed-index sync")

    async def _run_dismissed_index_startup_sync(self) -> None:
        """Run dismissed-projection index maintenance off the paint path.

        ``_init_app_state`` only captures the cheap in-memory dismissed
        state; the artifact-index sync — O(archive) on signature drift and
        unbounded when the index is corrupt — runs here in a thread so
        first paint never waits on it. A projection rewrite means
        dismissed visibility may have drifted out-of-band since the last
        session, so nudge an agents refresh to reconcile shortly after
        first paint; a heal additionally gets a user-visible notification.
        """
        import asyncio

        from sase.core.agent_artifact_index_lifecycle import (
            DismissedProjectionSyncReport,
            sync_dismissed_agent_artifact_index_report,
        )

        # Snapshot on the UI thread: dismiss/revive actions may mutate
        # ``_dismissed_agents`` while the worker thread iterates it.
        dismissed_snapshot = set(self._dismissed_agents)  # type: ignore[attr-defined]
        try:
            report: DismissedProjectionSyncReport = await asyncio.to_thread(
                sync_dismissed_agent_artifact_index_report,
                dismissed_snapshot,
            )
        except Exception:
            log.exception("Startup dismissed-index sync failed")
            return
        self._artifact_index_maintenance_last_mono = time.monotonic()  # type: ignore[attr-defined]
        if report.healed:
            quarantined = report.quarantined_path
            suffix = f" (old copy: {quarantined.name})" if quarantined else ""
            self.notify(  # type: ignore[attr-defined]
                f"Agent artifact index was corrupt; rebuilt it{suffix}",
                severity="warning",
                timeout=10,
            )
        if report.changed:
            self._schedule_agents_async_refresh(  # type: ignore[attr-defined]
                source="dismissed_index_sync"
            )

    def _start_artifact_watcher(self) -> None:
        """Spin up an inotify watcher on ``~/.sase/projects/`` if supported.

        Falls back silently when inotify is unavailable; the auto-refresh
        timer remains the polling safety net in that case.
        """
        from pathlib import Path

        if self._fs_watcher is not None:
            return
        projects_dir = sase_projects_dir()
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
            # Project spec files live directly in ``project_dir``;
            # watching the dir picks up RUNNING-field updates.
            watch_paths.append(project_dir)
        beads_dir = Path.cwd() / "sdd" / "beads"
        if beads_dir.is_dir():
            watch_paths.append(beads_dir)
        notifications_dir = sase_subdir("notifications")
        if notifications_dir.is_dir():
            watch_paths.append(notifications_dir)
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

    def _start_prompt_source_watcher(self) -> None:
        """Spin up an inotify watcher on editable prompt/snippet sources."""
        if self._prompt_source_watcher is not None:
            return
        from ..prompt_catalog import prompt_source_watch_paths

        watch_paths = prompt_source_watch_paths(self._prompt_catalog_projects)
        if not watch_paths:
            self._prompt_source_watcher_active = False
            return
        watcher = ArtifactWatcher(
            watch_paths,
            on_change=self._on_prompt_source_change,
            schedule_callback=self.call_from_thread,  # type: ignore[attr-defined]
        )
        if watcher.start():
            self._prompt_source_watcher = watcher
            self._prompt_source_watcher_active = True
            self._prompt_source_watched_projects = set(self._prompt_catalog_projects)
        else:
            self._prompt_source_watcher_active = False

    def _restart_prompt_source_watcher(self) -> None:
        """Restart prompt watcher after the requested project set grows."""
        self._stop_prompt_source_watcher()
        self._start_prompt_source_watcher()

    def _stop_prompt_source_watcher(self) -> None:
        """Tear down the prompt-source inotify watcher on quit."""
        timer = self._prompt_source_debounce_timer
        if timer is not None:
            timer.stop()
            self._prompt_source_debounce_timer = None
        watcher = self._prompt_source_watcher
        self._prompt_source_watcher = None
        self._prompt_source_watcher_active = False
        self._prompt_source_watched_projects = set()
        if watcher is None:
            return
        try:
            watcher.stop()
        except Exception:
            log.exception("Failed to stop prompt-source watcher cleanly")

    def _on_prompt_source_change(self, changed_paths: tuple[Any, ...]) -> None:
        """Debounced callback for editable prompt/snippet source changes."""
        from pathlib import Path

        from ..prompt_catalog import (
            PROMPT_SOURCE_DEBOUNCE_S,
            prompt_source_change_is_relevant,
        )

        paths = tuple(Path(path) for path in changed_paths)
        if not prompt_source_change_is_relevant(paths, self._prompt_catalog_projects):
            return
        timer = self._prompt_source_debounce_timer
        if timer is not None:
            timer.stop()
        self._prompt_source_debounce_timer = self.set_timer(  # type: ignore[attr-defined]
            PROMPT_SOURCE_DEBOUNCE_S,
            self._fire_prompt_source_debounce,
            name="prompt-source-debounce",
        )

    def _fire_prompt_source_debounce(self) -> None:
        """Start one coalesced prompt catalog rebuild after source changes."""
        self._prompt_source_debounce_timer = None
        self._prompt_catalog_generation += 1
        self._schedule_prompt_catalog_rebuild(reason="prompt_source_change")

    def _tui_stall_context(self) -> dict[str, Any]:
        """Return side-effect-free context for the stall watchdog thread."""
        now_mono = time.monotonic()
        last_keypress_age_s: float | None = None
        if hasattr(self, "_last_activity_time"):
            last_keypress_age_s = max(0.0, now_mono - self._last_activity_time)
        current_state = self._activity_log.current_state()
        return {
            "current_tab": self.current_tab,  # type: ignore[attr-defined]
            "current_idx": self.current_idx,  # type: ignore[attr-defined]
            "current_attempt_number": self._current_attempt_number,
            "last_keypress_age_s": (
                None if last_keypress_age_s is None else round(last_keypress_age_s, 3)
            ),
            "activity_state": None
            if current_state is None
            else current_state.event.value,
        }

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
        )

        if not self._agents_first_load_done:
            try:
                self.query_one("#agent-list-panel", AgentList).loading = True  # type: ignore[attr-defined]
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

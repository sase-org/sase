"""Auto-refresh timer handling for ACE TUI event refreshes."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from sase.feature_flags import FeatureFlag, current_flags

from .._debug_leaks import debug_leaks_enabled, log_leak_snapshot
from ..agents._notification_utils import request_notification_agents_refresh
from ...util.pump_tasks import spawn_pump_free_task
from ...util.trace import tui_trace
from ._artifact_paths import agent_has_live_file_panel
from ._constants import (
    AGENTS_LOAD_MIN_INTERVAL_SECONDS,
    FULL_SANITY_REFRESH_SECONDS,
)
from ._helpers import callable_accepts_kwarg
from ._sdd_paths import cached_sdd_beads_dir
from ._surface_tokens import (
    SurfaceTokenRoots,
    SurfaceTokenSnapshot,
    live_surface_token_roots,
    probe_surface_tokens,
    surface_token_drifted,
)
from ._watcher import EventWatcherRefreshMixin


class EventAutoRefreshMixin(EventWatcherRefreshMixin):
    """Mixin for auto-refresh and lightweight live-file updates."""

    def _refresh_selected_agent_file_panel(self) -> bool:
        """Refresh only the selected agent's file panel when it is safe to do so."""
        if self.current_tab != "agents":
            return False
        if getattr(self, "current_attempt_number", None) is not None:
            return False

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None or not agent_has_live_file_panel(agent):
            return False

        from textual.css.query import NoMatches

        from ...widgets import AgentDetail

        try:
            agent_detail = self.query_one(  # type: ignore[attr-defined]
                "#agent-detail-panel", AgentDetail
            )
        except NoMatches:
            return False

        if getattr(agent_detail, "panel_mode_label", "file") != "file":
            return False

        agent_detail.refresh_current_file(agent)
        return True

    def _on_auto_refresh(self) -> None:
        """Timer-facing sync callback that launches a pump-free refresh.

        When the user is mid-burst on j/k the refresh defers itself for the
        remainder of the navigation window plus a small overshoot.  A new
        ``set_timer`` call schedules a single retry; if the user is *still*
        navigating when that fires, the same gate will defer it again.

        Phase 7: when the inotify watcher is active each surface's refresh
        is gated on its dirty flag; flags clear after the refresh runs.
        Token probes additionally skip unchanged surfaces when
        ``ace_refresh_tokens`` is enabled. Every sanity interval we ignore
        those gates and run a full reconcile to recover from missed events.
        """
        self._countdown_remaining = self.refresh_interval
        if self._nav_gate.is_navigating():
            if getattr(self, "_auto_refresh_deferred", False):
                return
            self._auto_refresh_deferred = True
            delay = self._nav_gate.time_until_idle() + 0.05
            self.set_timer(delay, self._retry_auto_refresh)  # type: ignore[attr-defined]
            return
        if self._prompt_input_active():
            return
        if getattr(self, "_auto_refresh_running", False):
            self._auto_refresh_pending = True
            return
        if getattr(self, "_auto_refresh_scheduled", False):
            return
        self._auto_refresh_scheduled = True
        self._spawn_auto_refresh_task()

    def _retry_auto_refresh(self) -> None:
        """Navigation-gate timer callback that only invokes the sync spawner."""
        self._auto_refresh_deferred = False
        self._on_auto_refresh()

    def _spawn_auto_refresh_task(self) -> None:
        """Run auto-refresh without making Textual's message pump await it."""
        task = spawn_pump_free_task(
            self,
            self._run_auto_refresh(),
            name="sase-auto-refresh",
            registry_attr="_pump_free_async_tasks",
        )
        if task is None:
            self._auto_refresh_scheduled = False

    async def _run_auto_refresh(self) -> None:
        """Run one guarded refresh and coalesce a trailing timer tick."""
        self._auto_refresh_scheduled = False
        if getattr(self, "_auto_refresh_running", False):
            self._auto_refresh_pending = True
            return
        self._auto_refresh_running = True
        try:
            await self._run_auto_refresh_body()
        finally:
            self._auto_refresh_running = False
            if getattr(self, "_auto_refresh_pending", False):
                self._auto_refresh_pending = False
                self._on_auto_refresh()

    def _probe_surface_tokens(self) -> SurfaceTokenSnapshot:
        """Collect metadata-only tokens for every ACE refresh surface."""
        roots: SurfaceTokenRoots = live_surface_token_roots(
            beads_dir=cached_sdd_beads_dir(self)
        )
        return probe_surface_tokens(roots)

    def _accept_surface_token(
        self,
        surface: str,
        snapshot: SurfaceTokenSnapshot | None,
    ) -> None:
        """Record *surface*'s probed token after a successful load."""
        if snapshot is None:
            return
        token = snapshot.token_for(surface)
        if token.indeterminate:
            return
        tokens = getattr(self, "_last_completed_surface_tokens", None)
        if tokens is None:
            self._last_completed_surface_tokens = {}
            tokens = self._last_completed_surface_tokens
        tokens[surface] = token

    def _surface_token_drifted(
        self,
        snapshot: SurfaceTokenSnapshot | None,
        surface: str,
    ) -> bool:
        if snapshot is None:
            return True
        last = getattr(self, "_last_completed_surface_tokens", {}).get(surface)
        return surface_token_drifted(snapshot.token_for(surface), last)

    async def _run_auto_refresh_body(self) -> None:
        """Refresh dirty surfaces; always called from a pump-free task."""
        reloaded: list[str] = []
        axe_file_opens = 0
        with tui_trace("refresh.auto_tick") as extra:
            try:
                axe_file_opens = await self._run_auto_refresh_surfaces(reloaded)
            finally:
                extra["surfaces_reloaded"] = len(reloaded)
                extra["surfaces"] = ",".join(reloaded)
                extra["axe_file_opens"] = axe_file_opens

    async def _run_auto_refresh_surfaces(self, reloaded: list[str]) -> int:
        """Run one auto-refresh pass, appending reloaded surface names."""
        axe_file_opens = 0
        watcher_active = self._watcher_active()
        now_mono = time.monotonic()
        sanity_interval = float(
            getattr(self, "sanity_refresh_interval", FULL_SANITY_REFRESH_SECONDS)
        )
        sanity_due = (
            now_mono - getattr(self, "_last_full_sanity_refresh", 0.0)
            >= sanity_interval
        )
        tokens_enabled = current_flags().enabled(FeatureFlag.ace_refresh_tokens)
        current_tokens: SurfaceTokenSnapshot | None = None
        if tokens_enabled:
            current_tokens = await asyncio.to_thread(self._probe_surface_tokens)

        def _should_refresh(flag_name: str, surface: str) -> bool:
            if sanity_due:
                return True
            if not tokens_enabled:
                if not watcher_active:
                    return True
                return bool(getattr(self, flag_name, True))
            if watcher_active and bool(getattr(self, flag_name, True)):
                return True
            return self._surface_token_drifted(current_tokens, surface)

        # Always poll axe status regardless of tab (for STARTING/STOPPING
        # transitions) — but skip the disk poll on idle ticks when the
        # watcher is active and nothing about axe has changed.
        if _should_refresh("_dirty_axe", "axe"):
            run_axe_refresh = getattr(self, "_run_axe_status_refresh", None)
            axe_full = sanity_due or self.current_tab == "axe"
            if callable(run_axe_refresh):
                if not getattr(
                    self, "_axe_status_refresh_running", False
                ) and not getattr(
                    self,
                    "_axe_status_refresh_scheduled",
                    False,
                ):
                    if callable_accepts_kwarg(
                        run_axe_refresh, "include_full_snapshots"
                    ):
                        if callable_accepts_kwarg(
                            run_axe_refresh, "tail_all_chop_logs"
                        ):
                            refreshed = await run_axe_refresh(
                                include_full_snapshots=axe_full,
                                tail_all_chop_logs=sanity_due,
                            )
                        else:
                            refreshed = await run_axe_refresh(
                                include_full_snapshots=axe_full,
                            )
                    else:
                        refreshed = await run_axe_refresh()
                    if refreshed:
                        self._dirty_axe = False
                        self._accept_surface_token("axe", current_tokens)
                        reloaded.append("axe")
                        axe_file_opens = self._axe_collector_file_opens()
            else:
                # Narrow EventAutoRefreshMixin test doubles do not include the
                # AXE loader mixin; production always takes the guarded path.
                load_axe = self._load_axe_status_async  # type: ignore[attr-defined]
                if callable_accepts_kwarg(load_axe, "include_full_snapshots"):
                    if callable_accepts_kwarg(load_axe, "tail_all_chop_logs"):
                        await load_axe(
                            include_full_snapshots=axe_full,
                            tail_all_chop_logs=sanity_due,
                        )
                    else:
                        await load_axe(include_full_snapshots=axe_full)
                else:
                    await load_axe()
                self._dirty_axe = False
                self._accept_surface_token("axe", current_tokens)
                reloaded.append("axe")
                axe_file_opens = self._axe_collector_file_opens()

        queued_agent_artifact_dirs = tuple(
            getattr(self, "_dirty_agent_artifact_dirs", ())
        )
        agent_delta_ready = (
            watcher_active
            and bool(queued_agent_artifact_dirs)
            and getattr(self, "_dirty_agent_artifact_fallback_reason", None) is None
        )
        agents_due = _should_refresh("_dirty_agents", "agents") or agent_delta_ready
        # Tab-gate: broad (expensive) agent loads are deferred until the
        # user is actually looking at the Agents tab, or the sanity-floor
        # escape hatch below fires. A queued, bounded exact artifact-delta
        # request is cheap and independent of which tab is on screen, so
        # it stays live off-tab -- that is what lets completion/unread
        # state converge promptly while the user is on Artifacts or Axe
        # instead of waiting for a tab switch or the sanity reconcile.
        if (
            agents_due
            and not sanity_due
            and not agent_delta_ready
            and self.current_tab != "agents"
        ):
            agents_due = False
        # Debounce: floor the auto-refresh tick to one load per window
        # regardless of how often inotify re-arms ``_dirty_agents``.
        # Leaves the dirty flag set so the next eligible tick retries.
        if agents_due and not sanity_due:
            since_last = now_mono - getattr(self, "_last_agents_load_mono", 0.0)
            if since_last < AGENTS_LOAD_MIN_INTERVAL_SECONDS:
                agents_due = False
        # Notification polling is its own surface so an idle tick (no
        # new notifications) skips the on-disk snapshot read. The
        # gating mirrors the other surfaces: poll on every tick when
        # the watcher is inactive, otherwise wait for inotify to set
        # the dirty flag or the sanity-refresh window to elapse.
        new_agent_notification = False
        if _should_refresh("_dirty_notifications", "notifications"):
            new_agent_notification = bool(
                await self._poll_agent_completions()  # type: ignore[attr-defined]
            )
            self._dirty_notifications = False
            self._accept_surface_token("notifications", current_tokens)
            reloaded.append("notifications")

        # Skip patch/agent refresh if the user is in a transient input
        # mode (hint bar or similar is active).
        if getattr(self, "_hint_mode_active", False):
            return axe_file_opens
        if getattr(self, "_entry_jump_mode_active", False):
            return axe_file_opens
        if getattr(self, "_panel_fold_hint_mode_active", False):
            return axe_file_opens
        if getattr(self, "_accept_mode_active", False):
            return axe_file_opens

        # Skip if a background agent load is already in progress
        if self._agents_loading:
            return axe_file_opens

        # Notification-triggered targeting resolves against the newly
        # observed completions (roster first, then raw_suffix) and is
        # safe off-tab as an exact delta. Suppress it only when this tick
        # actually runs a broad/full agents load; a tick that consumes a
        # bounded delta for unrelated dirs must still reconcile the
        # notified agent. Unresolvable completions stay tab-gated so they
        # cannot start an off-tab Tier 1 load.
        fallback_reason = getattr(self, "_dirty_agent_artifact_fallback_reason", None)
        can_consume_delta = (
            watcher_active
            and not sanity_due
            and fallback_reason is None
            and bool(queued_agent_artifact_dirs)
        )
        ran_broad_agents_load = False
        if agents_due:
            if can_consume_delta and self._consume_agent_artifact_delta_refresh(
                source="watcher"
            ):
                self._dirty_agents = False
                self._last_agents_load_mono = time.monotonic()
                self._accept_surface_token("agents", current_tokens)
                reloaded.append("agents")
            elif not sanity_due and self.current_tab != "agents":
                # Broad loads stay tab-gated. An off-tab delta that could
                # not be applied (e.g. the delta consumer failed) leaves
                # the dirty state in place for the next Agents-tab entry
                # or sanity pass instead of escalating to a broad load.
                pass
            else:
                ran_broad_agents_load = True
                if fallback_reason is not None:
                    self._record_agent_artifact_delta_fallback(
                        fallback_reason,
                        source="auto_refresh",
                    )
                self._agents_loading = True
                try:
                    load_agents_async = self._load_agents_async  # type: ignore[attr-defined]
                    kwargs: dict[str, Any] = {}
                    if callable_accepts_kwarg(load_agents_async, "source"):
                        kwargs["source"] = "auto_refresh"
                    await load_agents_async(**kwargs)
                finally:
                    self._agents_loading = False
                    self._last_agents_load_mono = time.monotonic()
                    self._clear_agent_artifact_delta_state()
                self._dirty_agents = False
                self._accept_surface_token("agents", current_tokens)
                reloaded.append("agents")
        elif not new_agent_notification:
            self._refresh_selected_agent_file_panel()

        if new_agent_notification and not ran_broad_agents_load:
            request_notification_agents_refresh(
                self,
                notifications=getattr(self, "_last_new_completion_notifications", None),
                allow_broad_fallback=self.current_tab == "agents",
            )

        if (
            self.current_tab == "artifacts"
            and getattr(self, "current_artifacts_subtab", "patches") == "patches"
            and _should_refresh("_dirty_patches", "patches")
        ):
            run_patches_refresh = getattr(
                self,
                "_run_patches_async_refresh",
                None,
            )
            if callable(run_patches_refresh):
                if not getattr(self, "_patches_loading", False) and not getattr(
                    self,
                    "_patches_refresh_scheduled",
                    False,
                ):
                    await run_patches_refresh()
                    self._dirty_patches = False
                    self._accept_surface_token("patches", current_tokens)
                    reloaded.append("patches")
            else:
                # Narrow EventAutoRefreshMixin test doubles do not include the
                # Patch loader mixin; production uses its overlap guard.
                await self._reload_and_reposition_async()  # type: ignore[attr-defined]
                self._dirty_patches = False
                self._accept_surface_token("patches", current_tokens)
                reloaded.append("patches")
        elif (
            self.current_tab == "artifacts"
            and getattr(self, "current_artifacts_subtab", "patches") != "patches"
        ):
            self._request_active_artifacts_refresh()  # type: ignore[attr-defined]

        if sanity_due:
            self._last_full_sanity_refresh = now_mono

        if debug_leaks_enabled():
            log_leak_snapshot(self, source="auto_refresh")
        return axe_file_opens

    def _axe_collector_file_opens(self) -> int:
        """Return this tick's axe-collector file-open count, if a cache exists."""
        cache = getattr(self, "_axe_status_read_cache", None)
        if cache is None:
            return 0
        stats = getattr(cache, "stats", None)
        opens = getattr(stats, "file_opens", 0)
        if isinstance(opens, int) and not isinstance(opens, bool):
            return int(opens)
        return 0

    def action_debug_leak_snapshot(self) -> None:
        """One-shot leak snapshot keybind gated by ``SASE_ACE_DEBUG_LEAKS=1``.

        Logs the snapshot and surfaces the headline counts via the
        Textual notification toast so the snapshot is visible without
        digging through the log file.
        """
        if not debug_leaks_enabled():
            return
        snapshot = log_leak_snapshot(self, source="keybind")
        message = (
            f"artifact_cache={snapshot['artifact_page_cache']} "
            f"watches={snapshot['fs_watcher_watches']} "
            f"dismissed={snapshot['dismissed_agent_objects']} "
            f"agents={snapshot['agents_with_children']} "
            f"tasks={snapshot['pending_asyncio_tasks']} "
            f"fds={snapshot['open_fds']}"
        )
        try:
            self.notify(message, title="leak snapshot", timeout=10)  # type: ignore[attr-defined]
        except Exception:
            pass

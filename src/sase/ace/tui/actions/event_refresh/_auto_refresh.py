"""Auto-refresh timer handling for ACE TUI event refreshes."""

from __future__ import annotations

import time
from typing import Any

from .._debug_leaks import debug_leaks_enabled, log_leak_snapshot
from ..agents._notification_utils import request_notification_agents_refresh
from ._artifact_paths import agent_has_live_file_panel
from ._constants import (
    AGENTS_LOAD_MIN_INTERVAL_SECONDS,
    FULL_SANITY_REFRESH_SECONDS,
)
from ._helpers import callable_accepts_kwarg
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

    async def _on_auto_refresh(self) -> None:
        """Auto-refresh handler called by timer.

        When the user is mid-burst on j/k the refresh defers itself for the
        remainder of the navigation window plus a small overshoot.  A new
        ``set_timer`` call schedules a single retry; if the user is *still*
        navigating when that fires, the same gate will defer it again.

        Phase 7: when the inotify watcher is active each surface's refresh
        is gated on its dirty flag; flags clear after the refresh runs.
        Every ``FULL_SANITY_REFRESH_SECONDS`` we ignore the gate and run
        a full reconcile to recover from any missed events.
        """
        if self._nav_gate.is_navigating():
            delay = self._nav_gate.time_until_idle() + 0.05
            self.set_timer(delay, self._on_auto_refresh)  # type: ignore[attr-defined]
            return

        self._countdown_remaining = self.refresh_interval
        if self._prompt_input_active():
            return

        watcher_active = self._watcher_active()
        now_mono = time.monotonic()
        sanity_due = (
            now_mono - getattr(self, "_last_full_sanity_refresh", 0.0)
            >= FULL_SANITY_REFRESH_SECONDS
        )

        def _should_refresh(flag_name: str) -> bool:
            if not watcher_active or sanity_due:
                return True
            return bool(getattr(self, flag_name, True))

        # Always poll axe status regardless of tab (for STARTING/STOPPING
        # transitions) — but skip the disk poll on idle ticks when the
        # watcher is active and nothing about axe has changed.
        if _should_refresh("_dirty_axe"):
            await self._load_axe_status_async()  # type: ignore[attr-defined]
            self._dirty_axe = False

        queued_agent_artifact_dirs = tuple(
            getattr(self, "_dirty_agent_artifact_dirs", ())
        )
        agent_delta_due = (
            watcher_active
            and bool(queued_agent_artifact_dirs)
            and getattr(self, "_dirty_agent_artifact_fallback_reason", None) is None
        )
        agents_due = _should_refresh("_dirty_agents") or agent_delta_due
        # Tab-gate: when the watcher is the source of truth, only pay
        # for the (expensive) agent load while the user is actually
        # looking at the agents tab. The sanity-floor escape hatch
        # below keeps things converging even if the user lives on a
        # different tab forever and we missed an inotify event.
        if agents_due and not sanity_due and self.current_tab != "agents":
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
        if _should_refresh("_dirty_notifications"):
            new_agent_notification = bool(
                await self._poll_agent_completions()  # type: ignore[attr-defined]
            )
            self._dirty_notifications = False

        # Skip changespec/agent refresh if the user is in a transient input
        # mode (hint bar or similar is active).
        if getattr(self, "_hint_mode_active", False):
            return
        if getattr(self, "_entry_jump_mode_active", False):
            return
        if getattr(self, "_accept_mode_active", False):
            return

        # Skip if a background agent load is already in progress
        if self._agents_loading:
            return

        if new_agent_notification and self.current_tab == "agents" and not agents_due:
            request_notification_agents_refresh(self)

        if agents_due:
            fallback_reason = getattr(
                self, "_dirty_agent_artifact_fallback_reason", None
            )
            if (
                watcher_active
                and not sanity_due
                and fallback_reason is None
                and queued_agent_artifact_dirs
                and self._consume_agent_artifact_delta_refresh(source="watcher")
            ):
                self._dirty_agents = False
                self._last_agents_load_mono = time.monotonic()
            else:
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
        elif watcher_active and not new_agent_notification:
            self._refresh_selected_agent_file_panel()

        if (
            self.current_tab == "changespecs"
            and getattr(self, "current_artifacts_subtab", "prs") == "prs"
            and _should_refresh("_dirty_changespecs")
        ):
            await self._reload_and_reposition_async()  # type: ignore[attr-defined]
            self._dirty_changespecs = False
        elif (
            self.current_tab == "changespecs"
            and getattr(self, "current_artifacts_subtab", "prs") != "prs"
        ):
            self._request_active_artifacts_refresh()  # type: ignore[attr-defined]

        if sanity_due:
            self._last_full_sanity_refresh = now_mono

        if debug_leaks_enabled():
            log_leak_snapshot(self, source="auto_refresh")

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

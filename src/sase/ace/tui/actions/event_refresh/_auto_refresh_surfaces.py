"""Dirty-surface execution for TUI auto-refresh."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from sase.feature_flags import FeatureFlag, current_flags

from .._debug_leaks import debug_leaks_enabled, log_leak_snapshot
from ..agents._notification_utils import request_notification_agents_refresh
from ...util.trace import tui_trace
from ._artifact_paths import agent_has_live_file_panel
from ._auto_refresh_attention import EventAutoRefreshAttentionMixin
from ._auto_refresh_tokens import EventAutoRefreshTokenMixin
from ._constants import (
    AGENTS_LOAD_MIN_INTERVAL_SECONDS,
    FULL_SANITY_REFRESH_SECONDS,
)
from ._freshness import note_surface_refreshed
from ._helpers import callable_accepts_kwarg
from ._surface_tokens import SurfaceTokenSnapshot
from ._watcher import EventWatcherRefreshMixin


class EventAutoRefreshSurfacesMixin(
    EventAutoRefreshAttentionMixin,
    EventAutoRefreshTokenMixin,
    EventWatcherRefreshMixin,
):
    """Mixin for auto-refresh surface selection and loading."""

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

        if not agent_detail.is_file_visible():
            return False

        agent_detail.refresh_current_file(agent)
        return True

    async def _run_auto_refresh_body(self) -> None:
        """Refresh dirty surfaces; always called from a pump-free task."""
        reloaded: list[str] = []
        axe_file_opens = 0
        attention_counters: dict[str, Any] = {
            "fleet_attention_cache_polls": 0,
            "fleet_attention_network_polls": 0,
            "fleet_attention_network_due": 0,
            "fleet_attention_network_scheduled": 0,
            "fleet_attention_cache_scheduled": 0,
            "fleet_attention_skipped": 0,
            "fleet_attention_changed": 0,
            "fleet_attention_errors": 0,
            "fleet_attention_duration_ms": 0.0,
            "fleet_attention_coalesced_requests": 0,
            "fleet_attention_poll_batches": 0,
            "fleet_attention_modes": "",
            "fleet_attention_outcome": "",
        }
        completed_attention_counters = getattr(
            self,
            "_consume_fleet_attention_inventory_completed_counters",
            None,
        )
        if callable(completed_attention_counters):
            attention_counters.update(completed_attention_counters())
        else:
            counters = getattr(
                self,
                "_fleet_attention_inventory_completed_counters",
                None,
            )
            if isinstance(counters, dict):
                attention_counters.update(counters)
                self._fleet_attention_inventory_completed_counters = {}  # type: ignore[attr-defined]
        with tui_trace("refresh.auto_tick") as extra:
            try:
                axe_file_opens = await self._run_auto_refresh_surfaces(
                    reloaded,
                    attention_counters=attention_counters,
                )
            finally:
                extra["surfaces_reloaded"] = len(reloaded)
                extra["surfaces"] = ",".join(reloaded)
                extra["axe_file_opens"] = axe_file_opens
                extra.update(attention_counters)
                refreshed_at = time.monotonic()
                for surface in reloaded:
                    note_surface_refreshed(self, surface, now=refreshed_at)

    async def _run_auto_refresh_surfaces(
        self,
        reloaded: list[str],
        *,
        attention_counters: dict[str, Any] | None = None,
    ) -> int:
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

        attention_network_scheduled = False
        attention_network_due = getattr(
            self,
            "_fleet_attention_inventory_network_due",
            None,
        )
        schedule_attention_network = getattr(
            self,
            "_schedule_fleet_attention_inventory_network_refresh",
            None,
        )
        if callable(attention_network_due) and callable(schedule_attention_network):
            due = bool(attention_network_due())
            if attention_counters is not None:
                attention_counters["fleet_attention_network_due"] = int(due)
            if due:
                attention_network_scheduled = bool(
                    schedule_attention_network(source="auto_refresh")
                )
                if attention_counters is not None:
                    attention_counters["fleet_attention_network_scheduled"] = int(
                        attention_network_scheduled
                    )
                    if not attention_network_scheduled and getattr(
                        self,
                        "_fleet_attention_inventory_refresh_running",
                        False,
                    ):
                        attention_counters["fleet_attention_skipped"] += 1
        if not attention_network_scheduled:
            attention_cache_scheduled = False
            schedule_attention_cache = getattr(
                self,
                "_schedule_fleet_attention_inventory_cache_refresh",
                None,
            )
            if callable(schedule_attention_cache):
                attention_cache_scheduled = bool(
                    schedule_attention_cache(source="auto_refresh")
                )
            else:
                poll_attention_inventory = getattr(
                    self,
                    "_poll_fleet_attention_inventory",
                    None,
                )
                if callable(poll_attention_inventory):
                    attention_cache_scheduled = (
                        self._schedule_fallback_attention_inventory_poll(
                            poll_attention_inventory,
                            source="auto_refresh",
                            cache_only=True,
                        )
                    )
            if attention_counters is not None:
                attention_counters["fleet_attention_cache_scheduled"] = int(
                    attention_cache_scheduled
                )
                if not attention_cache_scheduled and getattr(
                    self,
                    "_fleet_attention_inventory_refresh_running",
                    False,
                ):
                    attention_counters["fleet_attention_skipped"] += 1

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
        # transitions) -- but skip the disk poll on idle ticks when the
        # watcher is active and nothing about axe has changed.
        if _should_refresh("_dirty_axe", "axe"):
            run_axe_refresh = getattr(self, "_run_axe_status_refresh", None)
            axe_full = sanity_due or self.current_tab == "services"
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
        remote_attention_changed = False
        if remote_attention_changed or _should_refresh(
            "_dirty_notifications", "notifications"
        ):
            new_agent_notification = bool(
                await self._poll_agent_completions()  # type: ignore[attr-defined]
            )
            if remote_attention_changed and not getattr(
                self, "_last_new_completion_notifications", None
            ):
                new_agent_notification = False
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
                fallback_artifact_dirs = (
                    list(queued_agent_artifact_dirs)
                    if fallback_reason is not None
                    else []
                )
                fallback_deleted_artifact_dirs = (
                    list(getattr(self, "_dirty_deleted_agent_artifact_dirs", ()))
                    if fallback_artifact_dirs
                    else []
                )
                fallback_delta_covered = not fallback_artifact_dirs
                self._agents_loading = True
                try:
                    load_agents_async = self._load_agents_async  # type: ignore[attr-defined]
                    kwargs: dict[str, Any] = {}
                    if callable_accepts_kwarg(load_agents_async, "source"):
                        kwargs["source"] = "auto_refresh"
                    await load_agents_async(**kwargs)
                    if fallback_artifact_dirs:
                        load_delta_async = getattr(
                            self,
                            "_load_agent_artifact_delta_async",
                            None,
                        )
                        if callable(load_delta_async):
                            try:
                                fallback_delta_covered = bool(
                                    await load_delta_async(
                                        fallback_artifact_dirs,
                                        source="watcher",
                                        deleted_artifact_dirs=(
                                            fallback_deleted_artifact_dirs
                                        ),
                                    )
                                )
                            except Exception:  # noqa: BLE001 - broad fallback survives.
                                self._record_agent_artifact_delta_fallback(
                                    "delta_read_failure",
                                    source="watcher",
                                )
                        else:
                            self._record_agent_artifact_delta_fallback(
                                "delta_read_failure",
                                source="watcher",
                            )
                finally:
                    self._agents_loading = False
                    self._last_agents_load_mono = time.monotonic()
                    self._clear_agent_artifact_delta_state()
                self._dirty_agents = not fallback_delta_covered
                if fallback_delta_covered:
                    if fallback_artifact_dirs and tokens_enabled:
                        current_tokens = await asyncio.to_thread(
                            self._probe_surface_tokens
                        )
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
            reloaded.append("artifacts")

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

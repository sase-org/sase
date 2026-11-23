"""Dirty-surface execution for TUI auto-refresh."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from .._debug_leaks import debug_leaks_enabled, log_leak_snapshot
from ...util.trace import is_enabled as tui_trace_enabled, tui_trace
from ._artifact_paths import agent_has_live_file_panel
from ._auto_refresh_attention import EventAutoRefreshAttentionMixin
from ._auto_refresh_tokens import EventAutoRefreshTokenMixin
from ._constants import (
    FULL_SANITY_REFRESH_SECONDS,
)
from ._freshness import note_surface_refreshed
from ._watcher import EventWatcherRefreshMixin
from ._auto_refresh_surface_axe import EventAutoRefreshAxeSurfaceMixin
from ._auto_refresh_surface_agents import EventAutoRefreshAgentSurfaceMixin
from ._auto_refresh_surface_patches import EventAutoRefreshPatchSurfaceMixin


class EventAutoRefreshSurfacesMixin(
    EventAutoRefreshAxeSurfaceMixin,
    EventAutoRefreshAgentSurfaceMixin,
    EventAutoRefreshPatchSurfaceMixin,
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
        refresh_counters: dict[str, Any] | None = {} if tui_trace_enabled() else None
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
                    refresh_counters=refresh_counters,
                )
            finally:
                sample_watcher_stats = getattr(
                    self,
                    "_sample_watcher_stats_for_trace",
                    None,
                )
                if callable(sample_watcher_stats):
                    sample_watcher_stats()
                extra["surfaces_reloaded"] = len(reloaded)
                extra["surfaces"] = ",".join(reloaded)
                extra["axe_file_opens"] = axe_file_opens
                extra.update(attention_counters)
                if refresh_counters is not None:
                    refresh_counters["token_unknown_surfaces"] = sorted(
                        set(refresh_counters.get("token_unknown_surfaces", ()))
                    )
                    refresh_counters["raw_token_changed_surfaces"] = sorted(
                        refresh_counters.get("token_change_kinds", {})
                    )
                    extra.update(refresh_counters)
                refreshed_at = time.monotonic()
                for surface in reloaded:
                    note_surface_refreshed(self, surface, now=refreshed_at)

    async def _run_auto_refresh_surfaces(
        self,
        reloaded: list[str],
        *,
        attention_counters: dict[str, Any] | None = None,
        refresh_counters: dict[str, Any] | None = None,
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
        if refresh_counters is not None:
            refresh_counters.update(
                {
                    "sanity_due": sanity_due,
                    "watcher_active": watcher_active,
                    "surface_reasons": {},
                    "surface_outcomes": dict.fromkeys(
                        ("axe", "agents", "notifications", "patches"), "skipped"
                    ),
                    "token_change_kinds": {},
                }
            )

        def _record_reason(surface: str, reason: str) -> None:
            if refresh_counters is not None:
                refresh_counters["surface_reasons"][surface] = reason

        def _refresh_reason(
            surface: str,
            *,
            flag_name: str | None = None,
            use_watcher_dirty: bool = True,
        ) -> str:
            consumer_drifted = False
            if refresh_counters is not None:
                consumer_drifted = self._surface_token_consumer_drifted(
                    current_tokens,
                    surface,
                )
                refresh_counters.setdefault("consumer_token_drifted", {})[surface] = (
                    consumer_drifted
                )
                if consumer_drifted:
                    consumer_kinds = self._surface_token_change_kinds(
                        current_tokens,
                        surface,
                    )
                    refresh_counters.setdefault("consumer_token_change_kinds", {})[
                        surface
                    ] = list(consumer_kinds)
                    if consumer_kinds == ("unknown",):
                        refresh_counters.setdefault(
                            "token_unknown_surfaces", []
                        ).append(surface)
            if refresh_counters is not None and self._surface_token_raw_drifted(
                current_tokens,
                surface,
            ):
                raw_kinds = self._surface_token_change_kinds(
                    current_tokens,
                    surface,
                    consumed_only=False,
                )
                refresh_counters["token_change_kinds"][surface] = list(raw_kinds)
            if sanity_due:
                reason = "sanity"
            elif (
                use_watcher_dirty
                and watcher_active
                and flag_name is not None
                and bool(getattr(self, flag_name, True))
            ):
                reason = "watcher_dirty"
            else:
                drifted = (
                    consumer_drifted
                    if refresh_counters is not None
                    else self._surface_token_drifted(current_tokens, surface)
                )
                if drifted:
                    kinds = self._surface_token_change_kinds(current_tokens, surface)
                    reason = "token_unknown" if kinds == ("unknown",) else "token_drift"
                else:
                    reason = "unchanged"
            _record_reason(surface, reason)
            return reason

        current_tokens = await asyncio.to_thread(self._probe_surface_tokens)
        # Hidden startup work holds axe collects, sanity/broad Agents
        # loads, and Patch reloads. Cheap stat-only token probes above
        # still run so the first post-release tick has a baseline for
        # every surface except Agents, whose baseline is the pre-load
        # probe accepted when the startup Agents load succeeds.
        if not getattr(self, "_startup_deferred_loads_released", True):
            self._accept_startup_hold_surface_tokens(current_tokens)
            if refresh_counters is not None:
                refresh_counters["startup_hold"] = True
            return axe_file_opens

        if refresh_counters is not None:
            refresh_counters["startup_hold"] = False

        from sase.project_display_names import (
            project_display_snapshot_is_warm,
            refresh_project_display_snapshot,
        )

        # A cold cache populates on the next normal load anyway, so only a
        # genuine change under a previously loaded map dirties surfaces.
        _labels_were_warm = project_display_snapshot_is_warm(None)
        try:
            project_labels_changed = await asyncio.to_thread(
                refresh_project_display_snapshot
            )
        except Exception:  # noqa: BLE001 - labels stay stale; next tick retries.
            project_labels_changed = False
        project_labels_changed = bool(project_labels_changed and _labels_were_warm)
        if project_labels_changed:
            if hasattr(self, "_dirty_agents"):
                self._dirty_agents = True
            if hasattr(self, "_dirty_patches"):
                self._dirty_patches = True

        # Revalidate the cached provider source against the committed
        # generation. Enumeration stays in the publication worker.
        schedule_artifacts = getattr(
            self,
            "_schedule_artifacts_provider_discovery_if_source_changed",
            None,
        )
        if callable(schedule_artifacts):
            try:
                schedule_artifacts()
            except Exception:
                pass

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
            return _refresh_reason(surface, flag_name=flag_name) != "unchanged"

        axe_file_opens = await self._refresh_auto_refresh_axe_surface(
            current_tokens,
            sanity_due=sanity_due,
            refresh_counters=refresh_counters,
            reloaded=reloaded,
            refresh_reason=_refresh_reason,
        )

        should_continue = await self._refresh_auto_refresh_agent_surfaces(
            current_tokens,
            watcher_active=watcher_active,
            sanity_due=sanity_due,
            now_mono=now_mono,
            project_labels_changed=project_labels_changed,
            refresh_counters=refresh_counters,
            reloaded=reloaded,
            should_refresh=_should_refresh,
            record_reason=_record_reason,
        )
        if not should_continue:
            return axe_file_opens

        await self._refresh_auto_refresh_patch_surface(
            current_tokens,
            refresh_counters=refresh_counters,
            reloaded=reloaded,
            should_refresh=_should_refresh,
        )

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

"""Agents and notification work for TUI auto-refresh."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from ..agents._notification_utils import request_notification_agents_refresh
from ._constants import AGENTS_LOAD_MIN_INTERVAL_SECONDS
from ._helpers import callable_accepts_kwarg


class EventAutoRefreshAgentSurfaceMixin:
    """Refresh Agents and completion notifications during an auto-refresh pass."""

    async def _refresh_auto_refresh_agent_surfaces(
        self: Any,
        current_tokens: Any,
        *,
        watcher_active: bool,
        sanity_due: bool,
        now_mono: float,
        project_labels_changed: bool,
        refresh_counters: dict[str, Any] | None,
        reloaded: list[str],
        should_refresh: Callable[[str, str], bool],
        record_reason: Callable[[str, str], None],
    ) -> bool:
        """Refresh agent state; return whether the pass should reach Patches."""
        queued_agent_artifact_dirs = tuple(
            getattr(self, "_dirty_agent_artifact_dirs", ())
        )
        agent_delta_ready = (
            watcher_active
            and bool(queued_agent_artifact_dirs)
            and getattr(self, "_dirty_agent_artifact_fallback_reason", None) is None
        )
        agents_due = (
            should_refresh("_dirty_agents", "agents")
            or agent_delta_ready
            or project_labels_changed
        )
        if project_labels_changed and refresh_counters is not None:
            refresh_counters["surface_reasons"]["agents"] = "project_labels_changed"
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
            record_reason("agents", "tab_gated")
        # Debounce: floor the auto-refresh tick to one load per window
        # regardless of how often inotify re-arms ``_dirty_agents``.
        # Leaves the dirty flag set so the next eligible tick retries.
        if agents_due and not sanity_due:
            since_last = now_mono - getattr(self, "_last_agents_load_mono", 0.0)
            if since_last < AGENTS_LOAD_MIN_INTERVAL_SECONDS:
                agents_due = False
                record_reason("agents", "debounced")
        # Notification polling is its own surface so an idle tick (no
        # new notifications) skips the on-disk snapshot read. The
        # gating mirrors the other surfaces: poll on every tick when
        # the watcher is inactive, otherwise wait for inotify to set
        # the dirty flag or the sanity-refresh window to elapse.
        new_agent_notification = False
        remote_attention_changed = False
        if remote_attention_changed or should_refresh(
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
            if refresh_counters is not None:
                refresh_counters["surface_outcomes"]["notifications"] = (
                    "applied_changed" if new_agent_notification else "read_unchanged"
                )
        elif refresh_counters is not None:
            refresh_counters["surface_outcomes"]["notifications"] = "skipped"

        # An arrival observed by this tick's own poll must still queue its
        # exact delta even when the tick returns early below. The request
        # only queues behind the in-flight load.
        def _request_tick_arrival_delta() -> None:
            if not new_agent_notification:
                return
            request_notification_agents_refresh(
                self,
                notifications=getattr(self, "_last_new_completion_notifications", None),
                allow_broad_fallback=self.current_tab == "agents",
            )

        # Skip patch/agent refresh if the user is in a transient input
        # mode (hint bar or similar is active).
        if getattr(self, "_hint_mode_active", False):
            if refresh_counters is not None:
                refresh_counters["activity_gate"] = "hint"
            _request_tick_arrival_delta()
            return False
        if getattr(self, "_entry_jump_mode_active", False):
            if refresh_counters is not None:
                refresh_counters["activity_gate"] = "entry_jump"
            _request_tick_arrival_delta()
            return False
        if getattr(self, "_panel_fold_hint_mode_active", False):
            if refresh_counters is not None:
                refresh_counters["activity_gate"] = "panel_fold_hint"
            _request_tick_arrival_delta()
            return False
        if getattr(self, "_accept_mode_active", False):
            if refresh_counters is not None:
                refresh_counters["activity_gate"] = "accept"
            _request_tick_arrival_delta()
            return False

        # Skip if a background agent load is already in progress
        if self._agents_loading:
            if refresh_counters is not None:
                refresh_counters["activity_gate"] = "agents_loading"
                refresh_counters["surface_outcomes"].setdefault("agents", "skipped")
            _request_tick_arrival_delta()
            return False

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
                if refresh_counters is not None:
                    refresh_counters["agent_load_kind"] = "exact_delta"
                    refresh_counters["agent_load_reason"] = "watcher_delta"
                    refresh_counters["surface_outcomes"]["agents"] = "applied_changed"
                self._dirty_agents = False
                self._last_agents_load_mono = time.monotonic()
                self._accept_surface_token("agents", current_tokens)
                reloaded.append("agents")
            elif not sanity_due and self.current_tab != "agents":
                # Broad loads stay tab-gated. An off-tab delta that could
                # not be applied (e.g. the delta consumer failed) leaves
                # the dirty state in place for the next Agents-tab entry
                # or sanity pass instead of escalating to a broad load.
                if refresh_counters is not None:
                    refresh_counters["surface_reasons"]["agents"] = (
                        "delta_unavailable_off_tab"
                    )
                    refresh_counters["surface_outcomes"]["agents"] = "skipped"
            else:
                ran_broad_agents_load = True
                if refresh_counters is not None:
                    refresh_counters["agent_load_kind"] = "broad"
                    refresh_counters["agent_load_reason"] = (
                        fallback_reason
                        or refresh_counters.get("surface_reasons", {}).get(
                            "agents", "auto_refresh"
                        )
                    )
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
                    load_applied = await load_agents_async(**kwargs)
                    if refresh_counters is not None:
                        refresh_counters["surface_outcomes"]["agents"] = (
                            "applied_changed"
                            if load_applied is not False
                            else "skipped"
                        )
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
                    if fallback_artifact_dirs:
                        current_tokens = await asyncio.to_thread(
                            self._probe_surface_tokens
                        )
                    self._accept_surface_token("agents", current_tokens)
                reloaded.append("agents")
        else:
            if refresh_counters is not None:
                refresh_counters["surface_outcomes"]["agents"] = "skipped"
            if not new_agent_notification:
                self._refresh_selected_agent_file_panel()

        if new_agent_notification and not ran_broad_agents_load:
            request_notification_agents_refresh(
                self,
                notifications=getattr(self, "_last_new_completion_notifications", None),
                allow_broad_fallback=self.current_tab == "agents",
            )

        return True

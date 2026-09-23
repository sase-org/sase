"""Startup background-load orchestration for sase's TUI."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

log = logging.getLogger(__name__)

_STARTUP_DEFERRED_FALLBACK_SECONDS = 3.0

if TYPE_CHECKING:
    from textual.timer import Timer


class StartupLoadsCoreMixin:
    """Mixin orchestrating post-mount startup loads and deferred release."""

    _startup_deferred_release_reason: str | None
    _startup_deferred_fallback_timer: Timer | None

    def _start_post_mount_background_loads(self: Any) -> None:
        """Launch startup loads with the initially visible surface first."""
        self._mark_startup_first_paint()
        if self._post_mount_background_loads_started:
            return
        self._post_mount_background_loads_started = True
        self._start_post_first_paint_services()
        self._arm_startup_deferred_fallback()
        self._start_immediate_startup_loads()

        initial_tab = getattr(self, "_startup_initial_tab", None) or getattr(
            self, "current_tab", None
        )
        if initial_tab == "agents":
            self._start_startup_agents_surface()
        elif initial_tab == "services":
            self._start_startup_axe_surface()
        else:
            # Artifacts is composed synchronously. Its mount-state disk reads
            # remain worker-backed, but they are not a hidden async surface gate.
            self._schedule_deferred_mount_state_loads()
            self._maybe_end_startup_stopwatch()

    def _start_immediate_startup_loads(self: Any) -> None:
        """Start small/edge-sensitive startup work before the visible load."""
        self._warm_project_tag_catalog_at_startup()
        self._schedule_mount_notification_state_loads()
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

    def _arm_startup_deferred_fallback(self: Any) -> None:
        """Arm the bounded release that prevents hidden startup starvation."""
        if getattr(self, "_startup_deferred_fallback_timer", None) is not None:
            return
        try:
            self._startup_deferred_fallback_timer = self.set_timer(
                _STARTUP_DEFERRED_FALLBACK_SECONDS,
                self._release_startup_deferred_loads_from_fallback,
                name="startup-deferred-fallback",
            )
        except Exception:
            log.exception("Failed to arm startup deferred-load fallback")
            self._release_startup_deferred_loads(reason="fallback_schedule_failed")

    def _cancel_startup_deferred_fallback(self: Any) -> None:
        """Stop the bounded fallback timer after normal release or teardown."""
        timer = getattr(self, "_startup_deferred_fallback_timer", None)
        self._startup_deferred_fallback_timer = None
        if timer is None:
            return
        try:
            timer.stop()
        except Exception:
            log.debug("Failed to stop startup deferred fallback timer", exc_info=True)

    def _release_startup_deferred_loads_from_fallback(self: Any) -> None:
        """Timer callback that releases deferred work without marking ready."""
        self._startup_deferred_fallback_timer = None
        self._release_startup_deferred_loads(reason="fallback")

    def _release_startup_deferred_loads(self: Any, *, reason: str) -> bool:
        """Release every hidden-surface and maintenance startup task once."""
        if getattr(self, "_startup_deferred_loads_released", False):
            return False
        self._startup_deferred_loads_released = True
        self._startup_deferred_release_reason = reason
        self._cancel_startup_deferred_fallback()
        self._schedule_deferred_mount_state_loads()
        self._start_startup_agents_surface()
        self._start_startup_axe_surface()
        self._schedule_deferred_startup_maintenance(reason=reason)
        self._flush_deferred_agents_post_roster_work(reason=reason)
        self._flush_deferred_monitor_reconcile()
        return True

    def _maybe_start_startup_surface_for_tab(self: Any, tab: str) -> bool:
        """Start a hidden startup surface early after a user tab switch."""
        if not getattr(self, "_post_mount_background_loads_started", False):
            return False
        if tab == "agents" and not getattr(self, "_agents_first_load_done", False):
            return self._start_startup_agents_surface()
        if tab == "services" and not getattr(self, "_axe_first_load_done", False):
            return self._start_startup_axe_surface()
        return False

    def _schedule_mount_notification_state_loads(self: Any) -> None:
        """Seed unread notification state without waiting on other disk reads."""
        if getattr(self, "_mount_notification_state_load_started", False):
            return
        self._mount_notification_state_load_started = True
        try:
            self.run_worker(
                cast(Any, self._run_mount_notification_state_loads),
                thread=False,
                exclusive=False,
                group="startup-loads",
            )
        except Exception:
            self._mount_notification_state_load_done = True
            self._maybe_mark_mount_state_loads_done()
            log.exception("Failed to schedule startup notification state load")

    def _schedule_deferred_mount_state_loads(self: Any) -> None:
        """Schedule mount-state reads that are not needed before visible-ready."""
        if getattr(self, "_mount_deferred_state_load_started", False):
            return
        self._mount_deferred_state_load_started = True
        try:
            self.run_worker(
                cast(Any, self._run_deferred_mount_state_loads),
                thread=False,
                exclusive=False,
                group="startup-loads",
            )
        except Exception:
            self._mount_deferred_state_load_done = True
            self._maybe_mark_mount_state_loads_done()
            log.exception("Failed to schedule deferred mount state loads")

    def _maybe_mark_mount_state_loads_done(self: Any) -> None:
        """Preserve ``_mount_state_loads_done`` as the whole-state signal."""
        if getattr(self, "_mount_state_loads_done", False):
            return
        if not getattr(self, "_mount_notification_state_load_done", False):
            return
        if not getattr(self, "_mount_deferred_state_load_done", False):
            return
        self._mount_state_loads_done = True

    def _start_startup_agents_surface(self: Any) -> bool:
        """Start the Agents first meaningful load through its existing worker."""
        if getattr(self, "_agents_first_load_done", False):
            return False
        if getattr(self, "_startup_agents_surface_started", False):
            return False
        if (
            getattr(self, "_agents_loading", False)
            or getattr(self, "_agents_refresh_scheduled", False)
            or getattr(self, "_agents_artifact_delta_scheduled", None) is not None
        ):
            self._startup_agents_surface_started = True
            return False
        try:
            self._schedule_agents_fold_state_load()
        except Exception:
            log.exception("Failed to start Agents fold state load")
        dismissed_index_callback = self._schedule_dismissed_index_startup_sync
        try:
            self._agents_refresh_pending_callbacks.append(dismissed_index_callback)
            self._agents_refresh_scheduled_source = "startup"
            self.run_worker(
                cast(Any, self._run_agent_index_startup_prepare_and_refresh),
                thread=False,
                exclusive=False,
                group="startup-loads",
            )
            self._startup_agents_surface_started = True
            return True
        except Exception:
            try:
                self._agents_refresh_pending_callbacks.remove(dismissed_index_callback)
            except ValueError:
                pass
            log.exception("Failed to schedule startup agent refresh")
            return False

    def _start_startup_axe_surface(self: Any) -> bool:
        """Start the Axe first meaningful load through its startup worker."""
        if getattr(self, "_axe_first_load_done", False):
            return False
        if getattr(self, "_startup_axe_surface_started", False):
            return False
        if getattr(self, "_axe_status_refresh_running", False) or getattr(
            self, "_axe_status_refresh_scheduled", False
        ):
            self._startup_axe_surface_started = True
            return False
        try:
            self.run_worker(
                cast(Any, self._run_axe_startup_init),
                thread=False,
                exclusive=False,
                group="startup-loads",
            )
            self._startup_axe_surface_started = True
            return True
        except Exception:
            log.exception("Failed to schedule startup axe init")
            return False

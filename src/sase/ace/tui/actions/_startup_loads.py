"""Post-mount startup background-load helpers."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, cast

log = logging.getLogger(__name__)

_STARTUP_DEFERRED_FALLBACK_SECONDS = 3.0

if TYPE_CHECKING:
    from textual.timer import Timer


class StartupLoadsMixin:
    """Mixin for startup data loading and deferred index maintenance."""

    _startup_deferred_release_reason: str | None
    _startup_deferred_fallback_timer: Timer | None

    def _maybe_show_keymap_unification_toast(self: Any) -> None:
        """Show the sase-m6.9 ``y``/``R`` flip notice once, ever."""
        from .._keymap_unification_notice import (
            has_shown_keymap_unification_notice,
            mark_keymap_unification_notice_shown,
        )

        if has_shown_keymap_unification_notice():
            return
        mark_keymap_unification_notice_shown()
        self.notify(
            "Patch keys changed: 'y' now copies the @patch: reference and "
            "'R' refreshes (every Artifacts pane agrees on this now). "
            "Rewind moved to '!R', PR-origin to '!o'. Press '?' for the "
            "full keymap.",
            title="Artifacts keymap unified",
            severity="information",
            timeout=15.0,
        )

    def _invalidate_saved_queries_cache(self: Any) -> None:
        """Reload the active pane's ``_saved_queries`` bucket after a mutation.

        Called by the actions that mutate saved-query slots (save / delete
        keymap and the help modal). The hot render path (Patch filter display)
        only touches the cached dict, so this is the lone refill site.
        """
        from ...saved_queries import load_saved_queries

        pane_id = getattr(self, "current_artifacts_pane_key", "patches")
        self._saved_queries[pane_id] = load_saved_queries(pane_id)
        sync_onboarding = getattr(self, "_sync_patches_onboarding", None)
        if callable(sync_onboarding):
            showing_onboarding = sync_onboarding()
            if (
                not showing_onboarding
                and getattr(self, "current_tab", None) == "artifacts"
            ):
                refresh_display = getattr(self, "_refresh_display", None)
                if callable(refresh_display):
                    refresh_display()

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

    def _schedule_deferred_startup_maintenance(self: Any, *, reason: str) -> None:
        """Start hidden warmups and maintenance after visible-ready/fallback."""
        schedule_proc_shell_prune = getattr(
            self, "_schedule_dismissed_proc_shells_startup_prune", None
        )
        if callable(schedule_proc_shell_prune):
            try:
                schedule_proc_shell_prune()
            except Exception:
                log.exception("Failed to schedule startup dismissed-proc-shell prune")
        schedule_prompt_catalog_rebuild = getattr(
            self, "_schedule_prompt_catalog_rebuild", None
        )
        if callable(schedule_prompt_catalog_rebuild):
            try:
                schedule_prompt_catalog_rebuild(reason="startup_warm")
            except Exception:
                log.exception("Failed to schedule prompt catalog warm")
        just_updated = False
        try:
            just_updated = self._maybe_show_post_update_toast()
        except Exception:
            log.debug("Failed to show post-update toast", exc_info=True)
        try:
            self._schedule_startup_update_toast_check()
        except Exception:
            log.debug("Failed to schedule startup update toast", exc_info=True)
        if just_updated:
            try:
                self._maybe_show_keymap_unification_toast()
            except Exception:
                log.debug("Failed to show keymap unification toast", exc_info=True)
        try:
            schedule_usage_refresh = getattr(
                self, "_schedule_usage_refresh_fallback", None
            )
            if callable(schedule_usage_refresh):
                schedule_usage_refresh()
        except Exception:
            log.debug("Failed to schedule usage-refresh fallback", exc_info=True)
        schedule_link_index = getattr(self, "_schedule_link_index_refresh", None)
        if callable(schedule_link_index):
            try:
                schedule_link_index(source=f"startup_{reason}")
            except Exception:
                log.debug("Failed to schedule startup link index", exc_info=True)

    def _schedule_agents_post_roster_startup_work(
        self: Any,
        *,
        source: str,
    ) -> None:
        """Route post-roster warmups through the startup coordinator."""
        if not getattr(self, "_startup_deferred_loads_released", True):
            self._startup_deferred_post_roster_warmups_pending = True
            self._startup_deferred_post_roster_warmups_source = source
            return
        self._startup_deferred_post_roster_warmups_pending = False
        self._startup_deferred_post_roster_warmups_source = source
        self._run_agents_post_roster_warmups(source=source)

    def _flush_deferred_agents_post_roster_work(self: Any, *, reason: str) -> None:
        """Run queued post-roster warmups once deferred startup work is released."""
        source = getattr(
            self,
            "_startup_deferred_post_roster_warmups_source",
            f"startup_{reason}",
        )
        if not getattr(self, "_startup_deferred_post_roster_warmups_pending", False):
            source = f"startup_{reason}"
        self._schedule_agents_post_roster_startup_work(source=source)

    def _run_agents_post_roster_warmups(self: Any, *, source: str) -> None:
        """Schedule existing coalesced post-roster Agents warmups."""
        try:
            self._schedule_live_hint_refresh(source=source)
        except Exception:
            log.debug("Failed to schedule live-hint warmup", exc_info=True)
        try:
            self._schedule_bead_confirmation_warmup(source=source)
        except Exception:
            log.debug("Failed to schedule bead warmup", exc_info=True)
        schedule_family_preview_warmup = getattr(
            self,
            "_schedule_family_plan_preview_warmup",
            None,
        )
        if callable(schedule_family_preview_warmup) and hasattr(
            self,
            "_family_preview_scan_running",
        ):
            try:
                schedule_family_preview_warmup(source=source)
            except Exception:
                log.debug("Failed to schedule family-preview warmup", exc_info=True)
        try:
            self._schedule_diff_badge_classification(source=source)
        except Exception:
            log.debug("Failed to schedule diff-badge warmup", exc_info=True)

    def _flush_deferred_monitor_reconcile(self: Any) -> None:
        """Run a monitor reconcile request that arrived before deferred release."""
        if not getattr(self, "_startup_deferred_monitor_reconcile_pending", False):
            return
        self._startup_deferred_monitor_reconcile_pending = False
        source = getattr(
            self,
            "_startup_deferred_monitor_reconcile_source",
            "startup_deferred",
        )
        schedule = getattr(self, "_schedule_monitor_reconcile", None)
        if callable(schedule):
            schedule(source=source)

    async def _run_mount_notification_state_loads(self: Any) -> None:
        """Load startup notification state before unrelated mount-state reads."""
        import asyncio

        try:
            notif_state = await asyncio.to_thread(self._read_notifications_for_startup)
            self._initialize_agent_tracking(notif_state)
            # Seed existing unread IDs first so startup does not replay old
            # alerts, then reconcile overdue snoozes and arm the nearest
            # deadline independently of the general refresh setting.
            self._schedule_notification_poll(source="startup")
        finally:
            self._mount_notification_state_load_done = True
            self._maybe_mark_mount_state_loads_done()

    async def _run_deferred_mount_state_loads(self: Any) -> None:
        """Load deferred mount-time disk state off the App message pump."""
        import asyncio

        try:
            stash_counts = await asyncio.to_thread(self._read_prompt_stash_counts)
            self._apply_prompt_stash_counts(*stash_counts)

            if not getattr(self, "_patches_first_load_done", False):
                all_cs = await asyncio.to_thread(self._read_patches_from_disk)
                self._apply_patches(all_cs)

            last_name = await asyncio.to_thread(self._read_last_selection_name)
            self._restore_last_selection(last_name)
            await asyncio.to_thread(self._save_startup_query)

            # Resolving a git-derived dev version can block on subprocesses for
            # editable installs. Wheel installs usually keep the instant title.
            from ..util.app_version import (
                format_app_title,
                initial_app_version,
                resolved_app_version,
            )

            version = await asyncio.to_thread(resolved_app_version)
            if version and version != initial_app_version():
                self.title = format_app_title(version)
        finally:
            self._mount_deferred_state_load_done = True
            self._maybe_mark_mount_state_loads_done()

    async def _run_agent_index_startup_prepare_and_refresh(self: Any) -> None:
        """Paint from a bounded scan before rebuilding a stale index."""
        import asyncio

        from sase.core.agent_artifact_index_lifecycle import (
            read_agent_artifact_index_schema_status,
        )

        try:
            status = await asyncio.to_thread(read_agent_artifact_index_schema_status)
        except Exception:
            log.exception("Startup artifact-index schema check failed")
            await self._run_agents_async_refresh()
            return

        if not status.stale:
            await self._run_agents_async_refresh()
            return

        self._artifact_index_schema_rebuild_in_flight = True
        self._artifact_index_schema_bypass = True
        index_ready = False
        try:
            try:
                # The bypass makes this first load take the bounded source-scan
                # branch directly instead of waiting behind the rebuild lock.
                await self._run_agents_async_refresh()
            finally:
                # This coroutine is already a post-mount worker. Keeping the
                # rebuild here makes first paint independent while preserving
                # one reliable completion path for the follow-up refresh.
                index_ready = await self._run_agent_index_startup_prepare()
        finally:
            self._artifact_index_schema_rebuild_in_flight = False
            if index_ready:
                self._artifact_index_schema_bypass = False

        if index_ready:
            self._schedule_agents_async_refresh(
                source="index_schema_rebuilt",
                on_complete=self._resume_startup_index_work_after_schema_rebuild,
            )
            return

        # Keep bypassing the stale index for this session. The bounded first
        # load remains interactive; a quiet-time Tier 2 scan can restore full
        # history without opening the stale index.
        self._agents_history_reconcile_pending = True
        self._agents_history_reconcile_armed_mono = time.monotonic()
        try:
            self.notify(
                "Agent artifact index schema rebuild failed; using a bounded scan",
                severity="warning",
                timeout=10,
            )
        except Exception:
            log.debug("Failed to show schema-rebuild warning", exc_info=True)

    async def _run_agent_index_startup_prepare(self: Any) -> bool:
        """Make a known-stale index safe to query after the first agents paint."""
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
            return False
        if report.refreshed:
            log.info(
                "rebuilt stale agent artifact index: schema %s -> %s, rows=%s",
                report.stored_schema_version,
                AGENT_ARTIFACT_INDEX_SCHEMA_VERSION,
                report.rows_indexed,
            )
        return bool(
            report.refreshed
            or (
                report.checked
                and report.stored_schema_version is not None
                and report.stored_schema_version >= AGENT_ARTIFACT_INDEX_SCHEMA_VERSION
            )
        )

    def _resume_startup_index_work_after_schema_rebuild(self: Any) -> None:
        """Resume index consumers only after the rebuilt index was queried."""
        if self._dismissed_index_sync_pending_after_schema_rebuild:
            self._dismissed_index_sync_pending_after_schema_rebuild = False
            self._schedule_dismissed_index_startup_sync()
        resume_maintenance = getattr(
            self, "_resume_artifact_index_maintenance_after_schema_rebuild", None
        )
        if callable(resume_maintenance):
            resume_maintenance()

    def _schedule_dismissed_index_startup_sync(self: Any) -> None:
        """Schedule dismissed-index maintenance after startup agents load."""
        if getattr(self, "_artifact_index_schema_bypass", False):
            self._dismissed_index_sync_pending_after_schema_rebuild = True
            return
        try:
            self.run_worker(
                cast(Any, self._run_dismissed_index_startup_sync),
                thread=False,
                exclusive=False,
                group="startup-loads",
            )
        except Exception:
            log.exception("Failed to schedule startup dismissed-index sync")

    async def _run_dismissed_index_startup_sync(self: Any) -> None:
        """Run dismissed-projection index maintenance off the paint path.

        ``_init_app_state`` only captures the cheap in-memory dismissed
        state; the artifact-index sync - O(archive) on signature drift and
        unbounded when the index is corrupt - runs here in a thread so
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

        dismissed_snapshot = set(self._dismissed_agents)
        try:
            report: DismissedProjectionSyncReport = await asyncio.to_thread(
                sync_dismissed_agent_artifact_index_report,
                dismissed_snapshot,
            )
        except Exception:
            log.exception("Startup dismissed-index sync failed")
            return
        self._artifact_index_maintenance_last_mono = time.monotonic()
        if report.healed:
            quarantined = report.quarantined_path
            suffix = f" (old copy: {quarantined.name})" if quarantined else ""
            self.notify(
                f"Agent artifact index was corrupt; rebuilt it{suffix}",
                severity="warning",
                timeout=10,
            )
        if report.changed:
            self._schedule_agents_async_refresh(source="dismissed_index_sync")

    def _schedule_dismissed_proc_shells_startup_prune(self: Any) -> None:
        """Schedule dismissed-proc-shell retention prune after first paint."""
        try:
            self.run_worker(
                cast(Any, self._run_dismissed_proc_shells_startup_prune),
                thread=False,
                exclusive=False,
                group="startup-loads",
            )
        except Exception:
            log.exception("Failed to schedule startup dismissed-proc-shell prune")

    async def _run_dismissed_proc_shells_startup_prune(self: Any) -> None:
        """Bound the dismissed-proc-shell set to ids still in the proc store.

        ``_init_app_state`` only loads the JSON; intersecting with ``read_procs()``
        is store I/O and must not run before first paint.
        """
        import asyncio

        from sase.ace.dismissed_proc_shells import prune_dismissed_proc_shells
        from sase.procs import read_procs

        before = set(getattr(self, "_dismissed_proc_shells", ()))

        def _prune() -> set[str]:
            live_ids = {proc.proc_id for proc in read_procs()}
            return prune_dismissed_proc_shells(live_ids)

        try:
            pruned = await asyncio.to_thread(_prune)
        except Exception:
            log.exception("Startup dismissed-proc-shell prune failed")
            return
        added_during = set(getattr(self, "_dismissed_proc_shells", ())) - before
        self._dismissed_proc_shells = pruned | added_during

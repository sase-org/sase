"""Post-mount startup background-load helpers."""

from __future__ import annotations

import logging
import time
from typing import Any, cast

log = logging.getLogger(__name__)


class StartupLoadsMixin:
    """Mixin for startup data loading and deferred index maintenance."""

    def _invalidate_saved_queries_cache(self: Any) -> None:
        """Reload ``_saved_queries`` from disk after a save/delete.

        Called by the actions that mutate saved-query slots (save / delete
        keymap and the help modal). The hot render path (``SearchQueryPanel``)
        only touches the cached dict, so this is the lone refill site.
        """
        from ...saved_queries import load_saved_queries

        self._saved_queries = load_saved_queries()
        sync_onboarding = getattr(self, "_sync_changespecs_onboarding", None)
        if callable(sync_onboarding):
            showing_onboarding = sync_onboarding()
            if (
                not showing_onboarding
                and getattr(self, "current_tab", None) == "changespecs"
            ):
                refresh_display = getattr(self, "_refresh_display", None)
                if callable(refresh_display):
                    refresh_display()

    def _start_post_mount_background_loads(self: Any) -> None:
        """Launch post-mount startup loads once after first paint."""
        if self._post_mount_background_loads_started:
            return
        self._post_mount_background_loads_started = True
        # Independent, non-gating one-shot: its worker performs both bounded
        # file I/O and JSON decoding off-thread. Agents/AXE startup proceeds
        # immediately whether this is fast, slow, missing, or malformed.
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
        except Exception:
            try:
                self._agents_refresh_pending_callbacks.remove(dismissed_index_callback)
            except ValueError:
                pass
            log.exception("Failed to schedule startup agent refresh")
        try:
            self.run_worker(
                cast(Any, self._run_axe_startup_init),
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
            self._maybe_show_post_update_toast()
        except Exception:
            log.debug("Failed to show post-update toast", exc_info=True)
        try:
            self._schedule_startup_update_toast_check()
        except Exception:
            log.debug("Failed to schedule startup update toast", exc_info=True)

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

"""Deferred startup maintenance helpers for sase's TUI."""

from __future__ import annotations

import logging
from typing import Any, cast

log = logging.getLogger(__name__)


class StartupLoadsMaintenanceMixin:
    """Mixin for deferred maintenance, post-roster warmups, and prunes."""

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

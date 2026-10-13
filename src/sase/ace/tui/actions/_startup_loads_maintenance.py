"""Deferred startup maintenance helpers for sase's TUI."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, cast

from ..util.pump_tasks import spawn_pump_free_task

log = logging.getLogger(__name__)

#: Cap on waiting for one CPU-heavy maintenance step to finish.
_STARTUP_MAINTENANCE_STEP_CAP_SECONDS = 20.0
#: Poll interval while waiting for in-flight work or user activity.
_STARTUP_MAINTENANCE_POLL_SECONDS = 0.05

#: First-open prompt-bar modules pre-imported during deferred startup
#: maintenance (phase ``post-open-quiet``). Importing them at idle, after
#: first paint, keeps the first ``<space>`` from paying their import cost on
#: the key-to-paint path. Entries must stay import-side-effect free; each is
#: attempted independently so one failure never breaks startup.
PROMPT_BAR_FIRST_MOUNT_MODULES: tuple[str, ...] = (
    "sase.ace.tui.widgets.prompt_input_bar",
    "sase.dispatch.machine_catalog",
    "sase.ace.tui.agent_tabs_launch_view",
    "sase.macro.directive_edit",
    "sase.ace.tui.agent_tabs_settings",
    "sase.ace.tui.widgets.agent_tab_strip",
    "sase.ace.tui.models.agent_tab_descriptors",
    "sase.ace.tui.modals.launch_tab_picker_modal",
    "sase.ace.tui.actions.agents._agent_tabs_catalog",
)


class StartupLoadsMaintenanceMixin:
    """Mixin for deferred maintenance, post-roster warmups, and prunes."""

    def _maybe_show_agent_decks_toast(self: Any) -> None:
        """Show the agent data decks cut-over notice once, ever."""
        from .._agent_decks_notice import (
            has_shown_agent_decks_notice,
            mark_agent_decks_notice_shown,
        )

        if has_shown_agent_decks_notice():
            return
        mark_agent_decks_notice_shown()
        self.notify(
            "The Agents detail column now shows agent data decks (Main, Files, "
            "Tools) made of cards. Ctrl+J/K move between cards, Ctrl+N/P between "
            "decks, \\ and | split panels, Ctrl+F moves focus, Ctrl+S toggles "
            "the node rail, and Z zooms in place. The p view picker is retired. "
            "Press '?' for the full keymap.",
            title="Agents tab uses decks and cards",
            severity="information",
            timeout=15.0,
        )

    def _maybe_show_artifacts_agent_pane_toast(self: Any) -> None:
        """Show the Artifacts Agent pane retirement notice once, ever."""
        from .._artifact_tab_model import artifacts_agent_pane_retired
        from .._artifacts_agent_pane_notice import (
            has_shown_artifacts_agent_pane_notice,
            mark_artifacts_agent_pane_notice_shown,
        )

        if has_shown_artifacts_agent_pane_notice():
            return
        if not artifacts_agent_pane_retired():
            return
        mark_artifacts_agent_pane_notice_shown()
        self.notify(
            "Agent history moved to the Agents tab · ,a opens the Archive",
            title="Artifacts Agent pane retired",
            severity="information",
            timeout=15.0,
        )

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
        """Start hidden warmups and maintenance after visible-ready/fallback.

        Cheap or I/O-only items start immediately. CPU-heavy jobs run one
        at a time on a pump-free chain so they cannot starve the Agents
        loader through the GIL.
        """
        schedule_named_proc_prune = getattr(
            self, "_schedule_dismissed_named_procs_startup_prune", None
        )
        if callable(schedule_named_proc_prune):
            try:
                schedule_named_proc_prune()
            except Exception:
                log.exception("Failed to schedule startup dismissed-named-proc prune")
        just_updated = False
        try:
            just_updated = self._maybe_show_post_update_toast()
        except Exception:
            log.debug("Failed to show post-update toast", exc_info=True)
        try:
            self._schedule_update_attempts_refresh()
        except Exception:
            log.debug("Failed to schedule update attempts refresh", exc_info=True)
        if just_updated:
            try:
                self._maybe_show_keymap_unification_toast()
            except Exception:
                log.debug("Failed to show keymap unification toast", exc_info=True)
            try:
                self._maybe_show_agent_decks_toast()
            except Exception:
                log.debug("Failed to show agent decks toast", exc_info=True)
            try:
                self._maybe_show_artifacts_agent_pane_toast()
            except Exception:
                log.debug("Failed to show artifacts agent pane toast", exc_info=True)
        if getattr(self, "_startup_maintenance_chain_started", False):
            return
        self._startup_maintenance_chain_started = True
        task = spawn_pump_free_task(
            self,
            self._run_deferred_startup_maintenance_chain(reason=reason),
            name="sase-startup-maintenance",
            registry_attr="_pump_free_async_tasks",
        )
        if task is None:
            self._startup_maintenance_chain_started = False

    async def _run_deferred_startup_maintenance_chain(
        self: Any, *, reason: str
    ) -> None:
        """Run CPU-heavy startup maintenance jobs one at a time."""
        import asyncio

        steps: tuple[tuple[str, Callable[[], Any]], ...] = (
            ("prompt_catalog", self._run_startup_maintenance_prompt_catalog),
            ("link_index", lambda: self._run_startup_maintenance_link_index(reason)),
            ("update_toast", self._run_startup_maintenance_update_toast),
            ("usage_refresh", self._run_startup_maintenance_usage_refresh),
            ("prompt_bar_import", self._run_startup_maintenance_prompt_bar_import),
        )
        for name, step in steps:
            try:
                await self._yield_startup_maintenance_for_activity()
                await step()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.debug(
                    "Startup maintenance step %s failed",
                    name,
                    exc_info=True,
                )

    def _startup_maintenance_activity_busy(self: Any) -> bool:
        """Return True while navigation or prompt input should yield the chain."""
        nav = getattr(self, "_nav_gate", None)
        is_navigating = getattr(nav, "is_navigating", None) if nav is not None else None
        if callable(is_navigating) and is_navigating():
            return True
        prompt_fn = getattr(self, "_prompt_input_active", None)
        return bool(callable(prompt_fn) and prompt_fn())

    async def _yield_startup_maintenance_for_activity(self: Any) -> None:
        """Wait while the user is navigating or typing in the prompt."""
        import asyncio

        while self._startup_maintenance_activity_busy():
            await asyncio.sleep(_STARTUP_MAINTENANCE_POLL_SECONDS)

    async def _wait_startup_maintenance_while(
        self: Any, predicate: Callable[[], bool]
    ) -> None:
        """Wait until *predicate* is false, or the per-step cap elapses."""
        import asyncio
        import time

        deadline = time.monotonic() + _STARTUP_MAINTENANCE_STEP_CAP_SECONDS
        while predicate() and time.monotonic() < deadline:
            await self._yield_startup_maintenance_for_activity()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(_STARTUP_MAINTENANCE_POLL_SECONDS, remaining))

    async def _run_startup_maintenance_prompt_catalog(self: Any) -> None:
        """Warm the prompt catalog, or wait if a rebuild is already in flight."""
        in_flight = bool(getattr(self, "_prompt_catalog_rebuild_in_flight", False))
        fresh = getattr(self, "_prompt_catalog", None) is not None
        if not in_flight and not fresh:
            schedule = getattr(self, "_schedule_prompt_catalog_rebuild", None)
            if callable(schedule):
                try:
                    schedule(reason="startup_warm")
                except Exception:
                    log.exception("Failed to schedule prompt catalog warm")
        await self._wait_startup_maintenance_while(
            lambda: bool(getattr(self, "_prompt_catalog_rebuild_in_flight", False))
        )

    async def _run_startup_maintenance_link_index(self: Any, reason: str) -> None:
        """Refresh the app-wide link index, or wait if a build is in flight."""
        loading = bool(getattr(self, "_link_index_loading", False))
        fresh = getattr(self, "_link_index", None) is not None
        if not loading and not fresh:
            schedule = getattr(self, "_schedule_link_index_refresh", None)
            if callable(schedule):
                try:
                    schedule(source=f"startup_{reason}")
                except Exception:
                    log.debug("Failed to schedule startup link index", exc_info=True)
        await self._wait_startup_maintenance_while(
            lambda: bool(getattr(self, "_link_index_loading", False))
        )

    async def _run_startup_maintenance_update_toast(self: Any) -> None:
        """Run the startup update-status check, or wait if one is in flight."""
        in_flight = bool(getattr(self, "_automatic_update_check_in_flight", False))
        already = getattr(self, "_automatic_update_check_timer", None) is not None
        if not in_flight and not already:
            try:
                self._schedule_startup_update_toast_check()
            except Exception:
                log.debug("Failed to schedule startup update toast", exc_info=True)
        await self._wait_startup_maintenance_while(
            lambda: bool(getattr(self, "_automatic_update_check_in_flight", False))
        )

    async def _run_startup_maintenance_usage_refresh(self: Any) -> None:
        """Start the usage-refresh fallback and wait for its first request."""
        if not getattr(self, "_usage_refresh_fallback_started", False):
            schedule = getattr(self, "_schedule_usage_refresh_fallback", None)
            if callable(schedule):
                try:
                    schedule()
                except Exception:
                    log.debug(
                        "Failed to schedule usage-refresh fallback", exc_info=True
                    )
        await self._wait_startup_maintenance_while(
            lambda: (
                bool(getattr(self, "_usage_refresh_fallback_started", False))
                and not bool(
                    getattr(self, "_usage_refresh_fallback_first_request_done", False)
                )
            )
        )

    async def _run_startup_maintenance_prompt_bar_import(self: Any) -> None:
        """Pre-import first-open prompt-bar modules, or wait if already warming."""
        in_flight = bool(getattr(self, "_prompt_bar_import_warm_in_flight", False))
        fresh = bool(getattr(self, "_prompt_bar_import_warm_done", False))
        if not in_flight and not fresh:
            try:
                self._schedule_prompt_bar_import_warm()
            except Exception:
                log.debug("Failed to schedule prompt-bar import warm", exc_info=True)
        await self._wait_startup_maintenance_while(
            lambda: bool(getattr(self, "_prompt_bar_import_warm_in_flight", False))
        )

    def _schedule_prompt_bar_import_warm(self: Any) -> None:
        """Pre-import first-open prompt-bar modules off the event loop."""
        if getattr(self, "_prompt_bar_import_warm_done", False) or getattr(
            self, "_prompt_bar_import_warm_in_flight", False
        ):
            return
        self._prompt_bar_import_warm_in_flight = True
        try:
            self.run_worker(
                cast(Any, self._run_prompt_bar_import_warm),
                name="prompt-bar-import-warm",
                group="startup-loads",
                exclusive=False,
                thread=True,
            )
        except Exception:
            self._prompt_bar_import_warm_in_flight = False
            log.debug("Failed to schedule prompt-bar import warm", exc_info=True)

    def _run_prompt_bar_import_warm(self: Any) -> None:
        """Import :data:`PROMPT_BAR_FIRST_MOUNT_MODULES` into ``sys.modules``."""
        import importlib

        try:
            for name in PROMPT_BAR_FIRST_MOUNT_MODULES:
                try:
                    importlib.import_module(name)
                except Exception:
                    log.debug(
                        "Prompt-bar import warm failed for %s", name, exc_info=True
                    )
        finally:
            self._prompt_bar_import_warm_in_flight = False
            self._prompt_bar_import_warm_done = True

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
        schedule_agent_session_preview_warmup = getattr(
            self,
            "_schedule_agent_session_plan_preview_warmup",
            None,
        )
        if callable(schedule_agent_session_preview_warmup) and hasattr(
            self,
            "_agent_session_preview_scan_running",
        ):
            try:
                schedule_agent_session_preview_warmup(source=source)
            except Exception:
                log.debug("Failed to schedule session-preview warmup", exc_info=True)
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

    def _schedule_dismissed_named_procs_startup_prune(self: Any) -> None:
        """Schedule dismissed-named-proc retention prune after first paint."""
        try:
            self.run_worker(
                cast(Any, self._run_dismissed_named_procs_startup_prune),
                thread=False,
                exclusive=False,
                group="startup-loads",
            )
        except Exception:
            log.exception("Failed to schedule startup dismissed-named-proc prune")

    async def _run_dismissed_named_procs_startup_prune(self: Any) -> None:
        """Bound the dismissed-named-proc set to ids still in the proc store.

        ``_init_app_state`` only loads the JSON; intersecting with ``read_procs()``
        is store I/O and must not run before first paint.
        """
        import asyncio

        from sase.ace.dismissed_procs import prune_dismissed_procs
        from sase.procs import read_procs

        before = set(getattr(self, "_dismissed_named_procs", ()))

        def _prune() -> set[str]:
            live_ids = {proc.proc_id for proc in read_procs()}
            return prune_dismissed_procs(live_ids)

        try:
            pruned = await asyncio.to_thread(_prune)
        except Exception:
            log.exception("Startup dismissed-named-proc prune failed")
            return
        added_during = set(getattr(self, "_dismissed_named_procs", ())) - before
        self._dismissed_named_procs = pruned | added_during

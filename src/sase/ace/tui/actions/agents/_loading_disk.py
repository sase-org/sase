"""Disk-loading entry points for :class:`AgentLoadingMixin`."""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from . import _loading_helpers
from ._loading_compute import (
    _CLEANED_ARTIFACT_DIRS,
    compute_apply_loaded_agents,
    compute_loader_cleanup,
)
from ._loading_state import AgentLoadingStateMixin

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_loader import AgentLoadState

log = logging.getLogger(__name__)


def _resolve_load_agents_from_disk_with_state() -> Callable[..., Any]:
    """Resolve through the public facade so existing monkeypatches still work."""
    facade = sys.modules.get(f"{__package__}._loading")
    loader = getattr(
        facade,
        "load_agents_from_disk_with_state",
        _loading_helpers.load_agents_from_disk_with_state,
    )
    return cast(Callable[..., Any], loader)


class AgentLoadingDiskMixin(AgentLoadingStateMixin):
    """Methods that read agent state from disk and prepare apply snapshots."""

    def _merge_external_dismissals(self) -> None:
        """Union on-disk dismissed-agent identities into the in-memory set.

        External processes (Telegram kill, ``sase agents kill``, gchat) write
        to ``~/.sase/dismissed_agents.json`` directly via
        :func:`sase.agent.running.kill_named_agent`. Without this merge a
        long-lived TUI would never observe those entries on its next refresh
        and would re-classify the killed agent as FAILED.

        Only unions in new entries — never drops in-memory entries that
        haven't been flushed to disk yet (the optimistic kill flow updates
        memory first and persists asynchronously).
        """
        from ....dismissed_agents import load_dismissed_agents

        try:
            on_disk = load_dismissed_agents()
        except Exception:
            return
        new_external = on_disk - self._dismissed_agents
        if new_external:
            self._dismissed_agents.update(new_external)

    def _load_agents(self, *, full_history: bool = False) -> None:
        """Load agents from all sources.

        Args:
            full_history: When True, force a Tier 2 (full-history) source
                scan rather than letting the artifact index gate visibility.
                Used by deliberate user actions (e.g. revive) that need to
                surface artifacts the persistent index may not yet know
                about.
        """
        from ....changespec import find_all_changespecs_cached

        on_agents_tab = self.current_tab == "agents"

        selected_identity: tuple[AgentType, str, str | None] | None = None
        if on_agents_tab and self._agents and 0 <= self.current_idx < len(self._agents):
            selected_identity = self._agents[self.current_idx].identity
        elif not on_agents_tab:
            # Off-tab rebuild: fall back to the saved identity so the next
            # tab switch back lands on the previously selected agent rather
            # than whatever drifted into ``_agents_last_idx``'s slot.
            selected_identity = getattr(self, "_agents_last_identity", None)

        self._merge_external_dismissals()
        dismissed_snapshot = set(self._dismissed_agents)
        changespec_snapshot = find_all_changespecs_cached()
        load_result = _resolve_load_agents_from_disk_with_state()(
            dismissed_snapshot,
            changespec_snapshot=changespec_snapshot,
            full_history=full_history or bool(getattr(self, "_agent_search_query", "")),
        )
        self._apply_loaded_agents(
            load_result.all_agents,
            load_result.dismissed_from_loader,
            on_agents_tab,
            selected_identity,
            load_state=load_result.load_state,
        )

    async def _load_agents_async(self, *, full_history: bool = False) -> None:
        """Load agents with disk IO and pure-data filtering off the UI thread.

        Phase 2 of the post-launch j/k lag fix: the dismissed-set filter,
        auto-dismiss detection, axe-spawned marking, and always-visible/
        hideable categorization are computed in a worker thread via
        :func:`_compute_apply_loaded_agents`, leaving the UI thread to
        merge the prepared snapshot back into ``self`` and refresh widgets.
        Per-auto-dismiss disk writes (one ``save_dismissed_agents`` call per
        identity in the legacy path) collapse to a single batched flush.
        """
        import asyncio

        from ....changespec import find_all_changespecs_cached

        self._merge_external_dismissals()
        dismissed_snapshot = set(self._dismissed_agents)
        changespec_snapshot = await asyncio.to_thread(find_all_changespecs_cached)
        disk_start = time.perf_counter()
        load_result = await asyncio.to_thread(
            _resolve_load_agents_from_disk_with_state(),
            dismissed_snapshot,
            changespec_snapshot=changespec_snapshot,
            full_history=full_history or bool(getattr(self, "_agent_search_query", "")),
        )
        all_agents = load_result.all_agents
        dismissed_from_loader = load_result.dismissed_from_loader
        disk_elapsed = time.perf_counter() - disk_start
        log.debug(
            "agents async load: disk=%.3fs agents=%d dismissed=%d tier=%s source=%s complete=%s",
            disk_elapsed,
            len(all_agents),
            len(dismissed_from_loader),
            load_result.load_state.tier,
            load_result.load_state.artifact_source,
            load_result.load_state.complete_history,
        )
        cleanup_start = time.perf_counter()
        orphaned, cleaned_dirs = await asyncio.to_thread(
            compute_loader_cleanup, dismissed_snapshot, dismissed_from_loader
        )
        if orphaned:
            self._dismissed_agents -= orphaned
        if cleaned_dirs:
            _CLEANED_ARTIFACT_DIRS.update(cleaned_dirs)
        log.debug(
            "agents async load: cleanup=%.3fs orphaned=%d cleaned=%d",
            time.perf_counter() - cleanup_start,
            len(orphaned),
            len(cleaned_dirs),
        )

        # Capture current state AFTER the await — the user may have navigated
        # (j/k) or switched tabs while disk I/O was in flight.
        on_agents_tab = self.current_tab == "agents"
        selected_identity: tuple[AgentType, str, str | None] | None = None
        if on_agents_tab and self._agents and 0 <= self.current_idx < len(self._agents):
            selected_identity = self._agents[self.current_idx].identity
        elif not on_agents_tab:
            selected_identity = getattr(self, "_agents_last_identity", None)

        prep_start = time.perf_counter()
        # Bind the worker function to a local so ``to_thread`` doesn't see
        # the bare module-level reference on its own line — pyvision's
        # multi-line-import heuristic flags ``<name>,`` as an import
        # continuation, which would force this private helper public for
        # no semantic reason.
        prep_worker = compute_apply_loaded_agents
        prep = await asyncio.to_thread(
            prep_worker,
            all_agents,
            dismissed_from_loader,
            set(self._dismissed_agents),
            bool(self.hide_non_run_agents),
        )
        log.debug("agents async load: prep=%.3fs", time.perf_counter() - prep_start)

        apply_start = time.perf_counter()
        # ``orphaned`` was already subtracted from ``self._dismissed_agents``
        # above; pass ``persist_dismissed=True`` so the prep-time deltas
        # (recovered + auto-dismissed) and the cleanup-time orphan removal
        # are flushed to disk in a single ``save_dismissed_agents`` call.
        self._apply_loaded_agents_prepared(
            prep,
            on_agents_tab=on_agents_tab,
            selected_identity=selected_identity,
            load_state=load_result.load_state,
            persist_dismissed_changes=bool(orphaned)
            or bool(prep.recovered_bundle_identities)
            or bool(prep.auto_dismissed_identities),
        )
        log.debug("agents async load: apply=%.3fs", time.perf_counter() - apply_start)

    def _apply_loaded_agents(
        self,
        all_agents: list[Agent],
        dismissed_from_loader: list[Agent],
        on_agents_tab: bool,
        selected_identity: tuple[AgentType, str, str | None] | None,
        load_state: AgentLoadState | None = None,
    ) -> None:
        """Apply loaded agent data to app state (main thread only).

        Sync entry point used by :meth:`_load_agents` and tests. The async
        path (:meth:`_load_agents_async`) computes the prepared data via
        :func:`_compute_apply_loaded_agents` in a worker thread and then
        calls :meth:`_apply_loaded_agents_prepared` directly.
        """
        # Sync callers (tests and explicit _load_agents paths) own the
        # cleanup pass — the async path runs it in
        # ``_load_agents_async``.  Skipping when ``_agents_loading`` is True
        # preserves that split.
        if not self._agents_loading:
            orphaned, cleaned_dirs = compute_loader_cleanup(
                set(self._dismissed_agents), dismissed_from_loader
            )
            if orphaned:
                self._dismissed_agents -= orphaned
            if cleaned_dirs:
                _CLEANED_ARTIFACT_DIRS.update(cleaned_dirs)
        else:
            orphaned = set()

        prep = compute_apply_loaded_agents(
            all_agents,
            dismissed_from_loader,
            set(self._dismissed_agents),
            bool(self.hide_non_run_agents),
        )
        self._apply_loaded_agents_prepared(
            prep,
            on_agents_tab=on_agents_tab,
            selected_identity=selected_identity,
            load_state=load_state,
            persist_dismissed_changes=bool(orphaned)
            or bool(prep.recovered_bundle_identities)
            or bool(prep.auto_dismissed_identities),
        )

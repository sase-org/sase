"""Disk-loading entry points for :class:`AgentLoadingMixin`."""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from . import _loading_helpers
from ._loading_compute import (
    _CLEANED_ARTIFACT_DIRS,
    attach_finalize_plan_to_boundary,
    compute_apply_loaded_agents,
    compute_loader_cleanup,
    prepare_loaded_agents_worker_boundary,
)
from ._loading_state import AgentLoadingStateMixin
from ._refresh_trace import (
    classify_agents_data_cost,
    normalize_refresh_source,
    record_agents_refresh_trace,
)
from ...util.trace import tui_trace

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_content_search import AgentContentSearchIndex
    from ...models.agent_loader import AgentLoadState

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ExternalDismissalMergeResult:
    file_signature: tuple[int, int] | None
    on_disk_identities: set[tuple[AgentType, str, str | None]]
    new_external_identities: set[tuple[AgentType, str, str | None]]


def _resolve_load_agents_from_disk_with_state() -> Callable[..., Any]:
    """Resolve through the public facade so existing monkeypatches still work."""
    facade = sys.modules.get(f"{__package__}._loading")
    loader = getattr(
        facade,
        "load_agents_from_disk_with_state",
        _loading_helpers.load_agents_from_disk_with_state,
    )
    return cast(Callable[..., Any], loader)


def _compute_external_dismissal_merge(
    *,
    cached_signature: tuple[int, int] | None,
    cached_on_disk_identities: set[tuple[AgentType, str, str | None]],
    cache_initialized: bool,
    dismissed_snapshot: set[tuple[AgentType, str, str | None]],
) -> _ExternalDismissalMergeResult | None:
    from ....dismissed_agents import (
        dismissed_agents_file_signature,
        load_dismissed_agents,
    )

    file_signature = dismissed_agents_file_signature()
    if cache_initialized and file_signature == cached_signature:
        return None

    try:
        on_disk = load_dismissed_agents()
    except Exception:
        return None

    if cache_initialized:
        new_external = on_disk - cached_on_disk_identities
    else:
        new_external = on_disk - dismissed_snapshot

    return _ExternalDismissalMergeResult(
        file_signature=file_signature,
        on_disk_identities=set(on_disk),
        new_external_identities=new_external,
    )


class AgentLoadingDiskMixin(AgentLoadingStateMixin):
    """Methods that read agent state from disk and prepare apply snapshots."""

    def _prepare_agent_content_search_index_sync(
        self,
        agents: list[Agent],
    ) -> AgentContentSearchIndex | None:
        """Build a content index outside finalization for sync load callers."""
        if not getattr(self, "_agent_search_query", ""):
            self._agent_content_search_index = None
            return None
        for agent in agents:
            _loading_helpers.hydrate_agent_attempt_history(agent)
        worker_cache = self._agent_content_search_cache.fork()
        index = worker_cache.build_index(agents)
        self._agent_content_search_cache.merge(worker_cache)
        self._agent_content_search_index = index
        return index

    async def _prepare_agent_content_search_index_async(
        self,
        agents: list[Agent],
    ) -> AgentContentSearchIndex | None:
        """Build a content index in a worker thread for async load callers."""
        import asyncio

        if not getattr(self, "_agent_search_query", ""):
            self._agent_content_search_index = None
            return None

        def hydrate_attempts() -> None:
            for agent in agents:
                _loading_helpers.hydrate_agent_attempt_history(agent)

        await asyncio.to_thread(hydrate_attempts)
        worker_cache = self._agent_content_search_cache.fork()
        index = await asyncio.to_thread(worker_cache.build_index, agents)
        if not getattr(self, "_agent_search_query", ""):
            return None
        self._agent_content_search_cache.merge(worker_cache)
        self._agent_content_search_index = index
        return index

    def _external_dismissal_merge_result(
        self,
        dismissed_snapshot: set[tuple[AgentType, str, str | None]],
    ) -> _ExternalDismissalMergeResult | None:
        return _compute_external_dismissal_merge(
            cached_signature=getattr(self, "_dismissed_agents_disk_signature", None),
            cached_on_disk_identities=set(
                getattr(self, "_dismissed_agents_disk_identities", set())
            ),
            cache_initialized=bool(
                getattr(self, "_dismissed_agents_disk_signature_initialized", False)
            ),
            dismissed_snapshot=dismissed_snapshot,
        )

    def _apply_external_dismissal_merge(
        self, result: _ExternalDismissalMergeResult | None
    ) -> None:
        if result is None:
            return
        self._dismissed_agents_disk_signature = result.file_signature
        self._dismissed_agents_disk_identities = set(result.on_disk_identities)
        self._dismissed_agents_disk_signature_initialized = True
        if result.new_external_identities:
            self._dismissed_agents.update(result.new_external_identities)

    def _merge_external_dismissals(self) -> None:
        """Union on-disk dismissed-agent identities into the in-memory set.

        External processes (Telegram kill, ``sase agent kill``, gchat) write
        to ``~/.sase/dismissed_agents.json`` directly via
        :func:`sase.agent.running.kill_named_agent`. Without this merge a
        long-lived TUI would never observe those entries on its next refresh
        and would re-classify the killed agent as FAILED.

        Only unions in new entries — never drops in-memory entries that
        haven't been flushed to disk yet (the optimistic kill flow updates
        memory first and persists asynchronously).
        """
        result = self._external_dismissal_merge_result(set(self._dismissed_agents))
        self._apply_external_dismissal_merge(result)

    def _load_agents(
        self, *, full_history: bool = False, source: str = "sync_load"
    ) -> None:
        """Load agents from all sources.

        Args:
            full_history: When True, force a Tier 2 (full-history) source
                scan rather than letting the artifact index gate visibility.
                Used by deliberate user actions (e.g. revive) that need to
                surface artifacts the persistent index may not yet know
                about.
        """
        from ....changespec import find_all_changespecs_cached

        source = normalize_refresh_source(source)
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
        changespec_snapshot = find_all_changespecs_cached(include_states="all")
        load_result = _resolve_load_agents_from_disk_with_state()(
            dismissed_snapshot,
            changespec_snapshot=changespec_snapshot,
            full_history=full_history,
            use_artifact_index=not getattr(
                self, "_artifact_index_schema_bypass", False
            ),
            source=source,
        )
        data_cost = classify_agents_data_cost(
            full_history=full_history,
            load_state=load_result.load_state,
        )
        record_agents_refresh_trace(
            self,
            stage="data_loaded",
            source=source,
            data_cost=data_cost,
            full_history=full_history,
            agents=len(load_result.all_agents),
            dismissed=len(load_result.dismissed_from_loader),
            load_tier=load_result.load_state.tier,
            artifact_source=load_result.load_state.artifact_source,
            complete_history=load_result.load_state.complete_history,
        )
        from ...repro.capture import record_agents_tab_loader_result

        record_agents_tab_loader_result(
            self,
            load_state=load_result.load_state,
            agents=load_result.all_agents,
            dismissed_from_loader=load_result.dismissed_from_loader,
            on_agents_tab=on_agents_tab,
            selected_identity=selected_identity,
            source="sync_load",
        )
        previous_active_source = getattr(
            self, "_agents_refresh_active_source", "unknown"
        )
        installed_active_source = previous_active_source == "unknown"
        if installed_active_source:
            self._agents_refresh_active_source = source
        try:
            self._apply_loaded_agents(
                load_result.all_agents,
                load_result.dismissed_from_loader,
                on_agents_tab,
                selected_identity,
                load_state=load_result.load_state,
            )
        finally:
            if installed_active_source:
                self._agents_refresh_active_source = previous_active_source

    async def _load_agents_async(
        self, *, full_history: bool = False, source: str = "unknown"
    ) -> None:
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

        source = normalize_refresh_source(source)
        merge_result = await asyncio.to_thread(
            self._external_dismissal_merge_result, set(self._dismissed_agents)
        )
        self._apply_external_dismissal_merge(merge_result)
        dismissed_snapshot = set(self._dismissed_agents)
        changespec_snapshot = await asyncio.to_thread(
            find_all_changespecs_cached,
            include_states="all",
        )
        disk_start = time.perf_counter()
        load_result = await asyncio.to_thread(
            _resolve_load_agents_from_disk_with_state(),
            dismissed_snapshot,
            changespec_snapshot=changespec_snapshot,
            full_history=full_history,
            use_artifact_index=not getattr(
                self, "_artifact_index_schema_bypass", False
            ),
            source=source,
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
        data_cost = classify_agents_data_cost(
            full_history=full_history,
            load_state=load_result.load_state,
        )
        record_agents_refresh_trace(
            self,
            stage="data_loaded",
            source=source,
            data_cost=data_cost,
            full_history=full_history,
            agents=len(all_agents),
            dismissed=len(dismissed_from_loader),
            disk_ms=disk_elapsed * 1000.0,
            load_tier=load_result.load_state.tier,
            artifact_source=load_result.load_state.artifact_source,
            complete_history=load_result.load_state.complete_history,
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

        from ...repro.capture import record_agents_tab_loader_result

        record_agents_tab_loader_result(
            self,
            load_state=load_result.load_state,
            agents=all_agents,
            dismissed_from_loader=dismissed_from_loader,
            on_agents_tab=on_agents_tab,
            selected_identity=selected_identity,
            source="async_load",
        )

        worker_snapshot = self._make_prepared_apply_snapshot(
            on_agents_tab=on_agents_tab,
            selected_identity=selected_identity,
            load_state=load_result.load_state,
        )

        prep_start = time.perf_counter()
        boundary_worker = prepare_loaded_agents_worker_boundary
        with tui_trace(
            "agents.worker_prep",
            agents=len(all_agents),
            dismissed=len(dismissed_from_loader),
        ):
            boundary = await asyncio.to_thread(
                boundary_worker,
                all_agents,
                dismissed_from_loader,
                set(self._dismissed_agents),
                bool(self.hide_non_run_agents),
                worker_snapshot,
            )
        prep = boundary.prep
        content_index = await self._prepare_agent_content_search_index_async(
            boundary.fold.unfiltered_agents
        )
        with tui_trace(
            "agents.finalize_plan",
            visible=len(boundary.fold.visible_agents),
        ):
            boundary = await asyncio.to_thread(
                attach_finalize_plan_to_boundary,
                boundary,
                worker_snapshot,
                content_index=content_index,
            )
        log.debug("agents async load: prep=%.3fs", time.perf_counter() - prep_start)

        apply_start = time.perf_counter()
        # ``orphaned`` was already subtracted from ``self._dismissed_agents``
        # above; pass ``persist_dismissed=True`` so the prep-time deltas
        # (recovered + auto-dismissed) and the cleanup-time orphan removal
        # are flushed to disk in a single ``save_dismissed_agents`` call.
        previous_active_source = getattr(
            self, "_agents_refresh_active_source", "unknown"
        )
        installed_active_source = previous_active_source == "unknown"
        if installed_active_source:
            self._agents_refresh_active_source = source
        try:
            self._apply_loaded_agents_prepared(
                prep,
                on_agents_tab=on_agents_tab,
                selected_identity=selected_identity,
                load_state=load_result.load_state,
                persist_dismissed_changes=bool(orphaned)
                or bool(prep.recovered_bundle_identities)
                or bool(prep.auto_dismissed_identities),
                dismissed_changes_include_removals=bool(orphaned),
                incomplete_merge_already_applied=True,
                precomputed_boundary=boundary,
                precomputed_fold_levels=worker_snapshot.fold_levels,
            )
        finally:
            if installed_active_source:
                self._agents_refresh_active_source = previous_active_source
        log.debug("agents async load: apply=%.3fs", time.perf_counter() - apply_start)

    async def _load_agent_artifact_delta_async(
        self,
        artifact_dirs: list[Path],
        *,
        source: str = "unknown",
        deleted_artifact_dirs: list[Path] | None = None,
    ) -> bool:
        """Load and apply a bounded exact-artifact delta.

        Returns False when the exact scan could not cover every requested
        artifact dir and the caller should fall back to a broad refresh.
        """
        import asyncio

        from ....changespec import find_all_changespecs_cached

        source = normalize_refresh_source(source)
        merge_result = await asyncio.to_thread(
            self._external_dismissal_merge_result, set(self._dismissed_agents)
        )
        self._apply_external_dismissal_merge(merge_result)
        dismissed_snapshot = set(self._dismissed_agents)
        changespec_snapshot = await asyncio.to_thread(
            find_all_changespecs_cached,
            include_states="all",
        )
        disk_start = time.perf_counter()
        load_result = await asyncio.to_thread(
            _loading_helpers.load_agent_artifact_delta_from_disk_with_state,
            dismissed_snapshot,
            artifact_dirs,
            changespec_snapshot=changespec_snapshot,
            source=source,
            update_index=not getattr(self, "_artifact_index_schema_bypass", False),
            deleted_artifact_dirs=deleted_artifact_dirs or (),
        )
        all_agents = load_result.all_agents
        dismissed_from_loader = load_result.dismissed_from_loader
        disk_elapsed = time.perf_counter() - disk_start
        data_cost = classify_agents_data_cost(artifact_delta=True)
        record_agents_refresh_trace(
            self,
            stage="data_loaded",
            source=source,
            data_cost=data_cost,
            agents=len(all_agents),
            dismissed=len(dismissed_from_loader),
            disk_ms=disk_elapsed * 1000.0,
            load_tier=load_result.load_state.tier,
            artifact_source=load_result.load_state.artifact_source,
            complete_history=load_result.load_state.complete_history,
        )
        if load_result.load_state.repair_recommended:
            record_agents_refresh_trace(
                self,
                stage="fallback",
                source=source,
                data_cost=data_cost,
                fallback_reason="missing_artifact_dir",
            )
            return False

        cleanup_start = time.perf_counter()
        orphaned, cleaned_dirs = await asyncio.to_thread(
            compute_loader_cleanup, dismissed_snapshot, dismissed_from_loader
        )
        if orphaned:
            self._dismissed_agents -= orphaned
        if cleaned_dirs:
            _CLEANED_ARTIFACT_DIRS.update(cleaned_dirs)
        log.debug(
            "agents artifact delta load: cleanup=%.3fs orphaned=%d cleaned=%d",
            time.perf_counter() - cleanup_start,
            len(orphaned),
            len(cleaned_dirs),
        )

        on_agents_tab = self.current_tab == "agents"
        selected_identity: tuple[AgentType, str, str | None] | None = None
        if on_agents_tab and self._agents and 0 <= self.current_idx < len(self._agents):
            selected_identity = self._agents[self.current_idx].identity
        elif not on_agents_tab:
            selected_identity = getattr(self, "_agents_last_identity", None)

        from ...repro.capture import record_agents_tab_loader_result

        record_agents_tab_loader_result(
            self,
            load_state=load_result.load_state,
            agents=all_agents,
            dismissed_from_loader=dismissed_from_loader,
            on_agents_tab=on_agents_tab,
            selected_identity=selected_identity,
            source="artifact_delta_load",
        )

        worker_snapshot = self._make_prepared_apply_snapshot(
            on_agents_tab=on_agents_tab,
            selected_identity=selected_identity,
            load_state=load_result.load_state,
        )

        prep_start = time.perf_counter()
        boundary = await asyncio.to_thread(
            prepare_loaded_agents_worker_boundary,
            all_agents,
            dismissed_from_loader,
            set(self._dismissed_agents),
            bool(self.hide_non_run_agents),
            worker_snapshot,
        )
        content_index = await self._prepare_agent_content_search_index_async(
            boundary.fold.unfiltered_agents
        )
        boundary = await asyncio.to_thread(
            attach_finalize_plan_to_boundary,
            boundary,
            worker_snapshot,
            content_index=content_index,
        )
        log.debug(
            "agents artifact delta load: prep=%.3fs",
            time.perf_counter() - prep_start,
        )

        previous_active_source = getattr(
            self, "_agents_refresh_active_source", "unknown"
        )
        installed_active_source = previous_active_source == "unknown"
        if installed_active_source:
            self._agents_refresh_active_source = source
        try:
            self._apply_loaded_agents_prepared(
                boundary.prep,
                on_agents_tab=on_agents_tab,
                selected_identity=selected_identity,
                load_state=load_result.load_state,
                persist_dismissed_changes=bool(orphaned)
                or bool(boundary.prep.recovered_bundle_identities)
                or bool(boundary.prep.auto_dismissed_identities),
                dismissed_changes_include_removals=bool(orphaned),
                incomplete_merge_already_applied=True,
                precomputed_boundary=boundary,
                precomputed_fold_levels=worker_snapshot.fold_levels,
            )
        finally:
            if installed_active_source:
                self._agents_refresh_active_source = previous_active_source
        return True

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

        with tui_trace(
            "agents.worker_prep",
            agents=len(all_agents),
            dismissed=len(dismissed_from_loader),
        ):
            prep = compute_apply_loaded_agents(
                all_agents,
                dismissed_from_loader,
                set(self._dismissed_agents),
                bool(self.hide_non_run_agents),
            )
        self._prepare_agent_content_search_index_sync(prep.filtered_agents)
        self._apply_loaded_agents_prepared(
            prep,
            on_agents_tab=on_agents_tab,
            selected_identity=selected_identity,
            load_state=load_state,
            persist_dismissed_changes=bool(orphaned)
            or bool(prep.recovered_bundle_identities)
            or bool(prep.auto_dismissed_identities),
            dismissed_changes_include_removals=bool(orphaned),
        )

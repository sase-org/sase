"""Full agent disk-load orchestration for :class:`AgentLoadingDiskMixin`."""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from typing import TYPE_CHECKING, Literal

from ...util.trace import tui_trace
from ._loading_compute import (
    attach_finalize_plan_to_boundary,
    prepare_loaded_agents_worker_boundary,
)
from ._loading_disk_io import disk_load_with_optional_current_project
from ._loading_disk_viewport import (
    AgentLoadingDiskViewportMixin,
    agent_load_query_is_stale,
    agents_viewport_for_load,
    agents_viewport_request_key,
    reschedule_stale_agent_query_load,
)
from ._refresh_trace import (
    classify_agents_data_cost,
    normalize_refresh_source,
    record_agents_refresh_trace,
)

if TYPE_CHECKING:
    from ...models.agent import AgentType

log = logging.getLogger(__name__)


class AgentLoadingDiskFullMixin(AgentLoadingDiskViewportMixin):
    """Synchronous and asynchronous full-history agent disk loads."""

    def _load_agents(
        self,
        *,
        full_history: bool = False,
        source: str = "sync_load",
        index_freshness: Literal["revalidate", "cached"] = "cached",
    ) -> None:
        """Load agents from all sources.

        Args:
            full_history: When True, force a Tier 2 (full-history) source
                scan rather than letting the artifact index gate visibility.
                Used by deliberate user actions (e.g. revive) that need to
                surface artifacts the persistent index may not yet know
                about.
        """
        from ....patch import find_all_patches_cached
        from sase.config.core import get_max_running_agents

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
        patch_snapshot = find_all_patches_cached(include_states="all")
        need_seed = self._should_seed_agent_search_query()
        current_project = None
        if need_seed:
            from sase.current_project import resolve_current_project

            current_project = resolve_current_project()
            self._maybe_seed_agent_search_query(current_project)
        search_query = getattr(self, "_agent_search_query", "") or ""
        viewport = agents_viewport_for_load(self)
        load_result, _ = disk_load_with_optional_current_project(
            dismissed_snapshot,
            resolve_current=False,
            patch_snapshot=patch_snapshot,
            full_history=full_history,
            use_artifact_index=not getattr(
                self, "_artifact_index_schema_bypass", False
            ),
            index_freshness=index_freshness,
            search_query=search_query,
            viewport=viewport,
            source=source,
        )
        self._agents_provider_snapshot = getattr(load_result, "provider_snapshot", None)
        self._agents_viewport_last_requested_limit = (
            load_result.load_state.requested_limit or 0
        )
        dismissed_bundle_snapshot = set(
            getattr(load_result, "dismissed_bundle_identities", set())
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
                effective_runner_limit=get_max_running_agents(),
                dismissed_bundle_snapshot=dismissed_bundle_snapshot,
            )
        finally:
            if installed_active_source:
                self._agents_refresh_active_source = previous_active_source
        self._schedule_monitor_reconcile(source=source)

    async def _load_agents_async(
        self,
        *,
        full_history: bool = False,
        source: str = "unknown",
        index_freshness: Literal["revalidate", "cached"] = "cached",
        full_history_reason: str | None = None,
    ) -> bool:
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

        from ....patch import find_all_patches_cached

        source = normalize_refresh_source(source)
        capacity_generation = int(getattr(self, "_agents_capacity_generation", 0))
        complete_prefix = bool(
            getattr(self, "_agents_refresh_active_prefix_completion", False)
        )
        merge_result = await asyncio.to_thread(
            self._external_dismissal_merge_result, set(self._dismissed_agents)
        )
        self._apply_external_dismissal_merge(merge_result)
        dismissed_snapshot = set(self._dismissed_agents)
        patch_snapshot = await asyncio.to_thread(
            find_all_patches_cached,
            include_states="all",
        )
        disk_start = time.perf_counter()
        restore_query = getattr(self, "_restore_agents_query_once", None)
        if callable(restore_query):
            await restore_query()
        need_seed = self._should_seed_agent_search_query()
        if need_seed:
            from sase.current_project import resolve_current_project

            current_project = await asyncio.to_thread(resolve_current_project)
            self._maybe_seed_agent_search_query(current_project)
        search_query = getattr(self, "_agent_search_query", "") or ""
        viewport = agents_viewport_for_load(self)
        request_key = agents_viewport_request_key(search_query, viewport)
        load_result, _ = await asyncio.to_thread(
            disk_load_with_optional_current_project,
            dismissed_snapshot,
            resolve_current=False,
            patch_snapshot=patch_snapshot,
            full_history=full_history,
            use_artifact_index=not getattr(
                self, "_artifact_index_schema_bypass", False
            ),
            index_freshness=index_freshness,
            search_query=search_query,
            viewport=viewport,
            source=source,
        )
        if agent_load_query_is_stale(self, load_result.load_state):
            reschedule_stale_agent_query_load(
                self,
                source=source,
                full_history=full_history,
                full_history_reason=full_history_reason,
                index_freshness=index_freshness,
                complete_prefix=complete_prefix,
            )
            return False
        if load_result.load_state.bounded_prefix:
            current_query = getattr(self, "_agent_search_query", "") or ""
            current_viewport = agents_viewport_for_load(self)
            current_key = agents_viewport_request_key(current_query, current_viewport)
            if current_key != request_key:
                reschedule_stale_agent_query_load(
                    self,
                    source=source,
                    full_history=full_history,
                    full_history_reason=full_history_reason,
                    index_freshness=index_freshness,
                    complete_prefix=complete_prefix,
                )
                return False
        self._agents_provider_snapshot = getattr(load_result, "provider_snapshot", None)
        self._agents_viewport_last_requested_limit = (
            load_result.load_state.requested_limit or 0
        )
        dismissed_bundle_snapshot = set(
            getattr(load_result, "dismissed_bundle_identities", set())
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
        # Capture current state AFTER the await; the user may have navigated
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
        worker_snapshot = replace(
            worker_snapshot,
            capacity_generation=capacity_generation,
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
                dismissed_bundle_snapshot=dismissed_bundle_snapshot,
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
        if agent_load_query_is_stale(self, load_result.load_state):
            reschedule_stale_agent_query_load(
                self,
                source=source,
                full_history=full_history,
                full_history_reason=full_history_reason,
                index_freshness=index_freshness,
                complete_prefix=complete_prefix,
            )
            return False
        prep_elapsed = time.perf_counter() - prep_start
        log.debug("agents async load: prep=%.3fs", prep_elapsed)

        apply_start = time.perf_counter()
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
                persist_dismissed_changes=bool(prep.recovered_bundle_identities)
                or bool(prep.auto_dismissed_identities),
                incomplete_merge_already_applied=True,
                precomputed_boundary=boundary,
                precomputed_fold_levels=worker_snapshot.fold_levels,
            )
        finally:
            if installed_active_source:
                self._agents_refresh_active_source = previous_active_source
        apply_elapsed = time.perf_counter() - apply_start
        log.debug("agents async load: apply=%.3fs", apply_elapsed)
        self._schedule_loader_cleanup(
            dismissed_snapshot,
            dismissed_from_loader,
            source=source,
            load_kind="full",
        )
        self._schedule_monitor_reconcile(source=source)
        self._record_slow_loader_stages(
            source=source,
            load_kind="full",
            stages={
                "disk": disk_elapsed,
                "prep": prep_elapsed,
                "apply": apply_elapsed,
            },
            agents=len(all_agents),
            dismissed=len(dismissed_from_loader),
        )
        return True

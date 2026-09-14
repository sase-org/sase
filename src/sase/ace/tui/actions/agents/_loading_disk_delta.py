"""Artifact-delta disk-load orchestration for :class:`AgentLoadingDiskMixin`."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from . import _loading_helpers
from ._loading_compute import (
    attach_finalize_plan_to_boundary,
    prepare_loaded_agents_worker_boundary,
)
from ._loading_state import AgentLoadingStateMixin
from ._refresh_trace import (
    classify_agents_data_cost,
    normalize_refresh_source,
    record_agents_refresh_trace,
)

if TYPE_CHECKING:
    from ...models.agent import AgentType

log = logging.getLogger(__name__)


class AgentLoadingDiskDeltaMixin(AgentLoadingStateMixin):
    """Exact-artifact delta disk loads."""

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

        from ....patch import find_all_patches_cached

        source = normalize_refresh_source(source)
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
        load_result = await asyncio.to_thread(
            _loading_helpers.load_agent_artifact_delta_from_disk_with_state,
            dismissed_snapshot,
            artifact_dirs,
            patch_snapshot=patch_snapshot,
            source=source,
            update_index=not getattr(self, "_artifact_index_schema_bypass", False),
            deleted_artifact_dirs=deleted_artifact_dirs or (),
        )
        dismissed_bundle_snapshot = set(
            getattr(load_result, "dismissed_bundle_identities", set())
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
            dismissed_bundle_snapshot=dismissed_bundle_snapshot,
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
        prep_elapsed = time.perf_counter() - prep_start
        log.debug("agents artifact delta load: prep=%.3fs", prep_elapsed)

        apply_start = time.perf_counter()
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
                persist_dismissed_changes=bool(
                    boundary.prep.recovered_bundle_identities
                )
                or bool(boundary.prep.auto_dismissed_identities),
                incomplete_merge_already_applied=True,
                precomputed_boundary=boundary,
                precomputed_fold_levels=worker_snapshot.fold_levels,
            )
        finally:
            if installed_active_source:
                self._agents_refresh_active_source = previous_active_source
        apply_elapsed = time.perf_counter() - apply_start
        log.debug("agents artifact delta load: apply=%.3fs", apply_elapsed)
        self._schedule_loader_cleanup(
            dismissed_snapshot,
            dismissed_from_loader,
            source=source,
            load_kind="artifact_delta",
        )
        self._schedule_monitor_reconcile(source=source)
        self._record_slow_loader_stages(
            source=source,
            load_kind="artifact_delta",
            stages={
                "disk": disk_elapsed,
                "prep": prep_elapsed,
                "apply": apply_elapsed,
            },
            agents=len(all_agents),
            dismissed=len(dismissed_from_loader),
        )
        return True

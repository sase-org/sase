"""Disk-loading entry points for :class:`AgentLoadingMixin`.

Shared indexing, dismissal, cleanup, and telemetry support lives in
:mod:`._loading_disk_support`.
"""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from ...util.trace import tui_trace
from . import _loading_helpers
from ._loading_compute import (
    attach_finalize_plan_to_boundary,
    compute_loader_cleanup as compute_loader_cleanup,
    prepare_loaded_agents_worker_boundary,
)
from ._loading_disk_support import (
    AgentLoadingDiskSupportMixin,
    compute_external_dismissal_merge as _compute_external_dismissal_merge,
    ExternalDismissalMergeResult as _ExternalDismissalMergeResult,
)
from ._refresh_trace import (
    classify_agents_data_cost,
    normalize_refresh_source,
    record_agents_refresh_trace,
)

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


class AgentLoadingDiskMixin(AgentLoadingDiskSupportMixin):
    """Methods that read agent state from disk and prepare apply snapshots."""

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
                effective_runner_limit=get_max_running_agents(),
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

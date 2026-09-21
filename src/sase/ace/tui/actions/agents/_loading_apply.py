"""UI-thread apply helpers for loaded agent snapshots.

:class:`AgentLoadingApplyMixin` is the facade the rest of the loading mixins
(and tests) import. It owns the prepared-apply orchestration; the snapshot
capture and finalize-plan selection live in :mod:`._loading_apply_snapshot`,
the incomplete-load and index-repair handling in
:mod:`._loading_apply_incomplete`, and the shared history-query predicates in
:mod:`._loading_apply_history`.
"""

from __future__ import annotations

import time
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from ...models.agent import AgentType
from ...util.trace import tui_trace
from ._loading_apply_history import (
    has_complete_history_for_load_query,
    history_query_key_for_load,
    should_arm_full_history_reconcile,
)
from ._loading_apply_incomplete import AgentLoadingApplyIncompleteMixin
from ._loading_apply_snapshot import AgentLoadingApplySnapshotMixin
from ._loading_compute import (
    PreparedApplyBoundary,
    PreparedApplyData,
    prepare_loaded_agents_apply_boundary,
    project_and_fold_rosters,
    rebase_prepared_apply_boundary_on_proc_projection,
)
from ._dismiss_memory import trim_dismissed_agent_objects
from ._loading_diff_badges import carry_over_diff_badges
from ._loading_live_hints import carry_over_live_hints
from ._live_watch_coverage import rearm_live_agent_watch_coverage
from ._refresh_trace import classify_agents_data_cost, record_agents_refresh_trace

if TYPE_CHECKING:
    from ...models.agent_loader import AgentLoadState
    from ...models.fold_state import FoldLevel


class AgentLoadingApplyMixin(
    AgentLoadingApplySnapshotMixin,
    AgentLoadingApplyIncompleteMixin,
):
    """Methods that merge prepared agent data back into app state."""

    def _apply_loaded_agents_prepared(
        self,
        prep: PreparedApplyData,
        *,
        on_agents_tab: bool,
        selected_identity: tuple[AgentType, str, str | None] | None,
        load_state: AgentLoadState | None = None,
        persist_dismissed_changes: bool,
        dismissed_changes_include_removals: bool = False,
        incomplete_merge_already_applied: bool = False,
        precomputed_boundary: PreparedApplyBoundary | None = None,
        precomputed_fold_levels: dict[str, FoldLevel] | None = None,
        effective_runner_limit: float | None = None,
    ) -> None:
        """UI-thread step that folds prepared filter output into ``self``.

        Updates the dismissed set with the recovered-bundle and
        auto-dismiss deltas, persists the merged set in a *single*
        :func:`save_dismissed_agents` call (replaces the old per-agent
        write loop), then drops the prepared agent list onto
        ``self._agents`` and runs the finalize pipeline. The fold filter,
        query evaluation, status overrides, registry GC, tab-bar update,
        and panel refresh all happen in :meth:`_finalize_agent_list` on
        this thread.
        """
        source = getattr(self, "_agents_refresh_active_source", "unknown")
        data_cost = classify_agents_data_cost(load_state=load_state)
        with tui_trace(
            "agents.apply_loaded_agents_prepared",
            agents=len(prep.filtered_agents),
            complete=getattr(load_state, "complete_history", None),
            source=source,
            data_cost=data_cost,
            proc_generation=int(getattr(self, "_proc_generation", 0)),
        ) as extra:
            self._apply_loaded_agents_prepared_inner(
                prep,
                on_agents_tab=on_agents_tab,
                selected_identity=selected_identity,
                load_state=load_state,
                persist_dismissed_changes=persist_dismissed_changes,
                dismissed_changes_include_removals=dismissed_changes_include_removals,
                incomplete_merge_already_applied=incomplete_merge_already_applied,
                precomputed_boundary=precomputed_boundary,
                precomputed_fold_levels=precomputed_fold_levels,
                effective_runner_limit=effective_runner_limit,
                trace_extra=extra,
            )
            extra["proc_generation"] = int(getattr(self, "_proc_generation", 0))
            extra["proc_shell_count"] = sum(
                1
                for agent in getattr(self, "_agents_with_children", [])
                if getattr(agent, "is_proc_shell", False)
            )

    def _apply_loaded_agents_prepared_inner(
        self,
        prep: PreparedApplyData,
        *,
        on_agents_tab: bool,
        selected_identity: tuple[AgentType, str, str | None] | None,
        load_state: AgentLoadState | None = None,
        persist_dismissed_changes: bool,
        dismissed_changes_include_removals: bool = False,
        incomplete_merge_already_applied: bool = False,
        precomputed_boundary: PreparedApplyBoundary | None = None,
        precomputed_fold_levels: dict[str, FoldLevel] | None = None,
        effective_runner_limit: float | None = None,
        trace_extra: dict[str, Any] | None = None,
    ) -> None:
        """Implementation for the traced prepared-apply UI continuation."""
        # Capture the pre-mutation visible-row anchor for the neighbor
        # fallback when the selected identity is gone. Cheap: reuses the
        # cached nav stops when they are already cached.
        prior_pos: int | None = None
        if on_agents_tab:
            capture = getattr(self, "_capture_focused_visible_pos", None)
            if callable(capture):
                try:
                    prior_pos = capture()
                except Exception:
                    prior_pos = None
        first_agents_load = not self._agents_first_load_done
        if first_agents_load:
            self._agents_first_load_done = True
            try:
                from ._display_helpers import first_agent_list_widget

                widget = first_agent_list_widget(self)
                if widget is not None:
                    widget.loading = False
            except Exception:
                pass

        added_identities = (
            set(prep.recovered_bundle_identities) | prep.auto_dismissed_identities
        )
        if prep.recovered_bundle_identities:
            self._dismissed_agents.update(prep.recovered_bundle_identities)
        if prep.auto_dismissed_identities:
            self._dismissed_agents.update(prep.auto_dismissed_identities)
        if persist_dismissed_changes:
            from ....dismissed_agents import save_dismissed_agents

            if save_dismissed_agents(self._dismissed_agents):
                self._schedule_artifact_index_maintenance(
                    dismissed=set(self._dismissed_agents),
                    added=added_identities or None,
                    force=dismissed_changes_include_removals,
                    source="apply",
                )
            else:
                record_agents_refresh_trace(
                    self,
                    stage="fallback",
                    source=getattr(self, "_agents_refresh_active_source", "unknown"),
                    data_cost=classify_agents_data_cost(load_state=load_state),
                    fallback_reason="persistence_error",
                )

        self._note_empty_incomplete_apply_ignored(load_state)

        preserved_revived = self._preserve_revived_agents_for_incomplete_load(
            prep, load_state
        )
        if not incomplete_merge_already_applied:
            with tui_trace(
                "agents.incomplete_load_merge",
                incoming=len(prep.filtered_agents),
                cached=len(getattr(self, "_agents_with_children", [])),
                complete=getattr(load_state, "complete_history", None),
            ):
                self._merge_incomplete_load_after_complete_history(prep, load_state)

        boundary = None
        if (
            precomputed_boundary is not None
            and incomplete_merge_already_applied
            and not preserved_revived
        ):
            fold_manager = getattr(self, "_fold_manager", None)
            snapshot_fold = getattr(fold_manager, "snapshot", None)
            current_fold_levels = snapshot_fold() if callable(snapshot_fold) else None
            if current_fold_levels == precomputed_fold_levels:
                boundary = precomputed_boundary

        current_capacity_generation = int(
            getattr(self, "_agents_capacity_generation", 0)
        )
        capacity_inputs_stale = (
            precomputed_boundary is not None
            and precomputed_boundary.capacity_generation < current_capacity_generation
        )

        if boundary is None:
            boundary_limit: float | None = (
                float(effective_runner_limit)
                if effective_runner_limit is not None and not capacity_inputs_stale
                else None
            )
            if (
                boundary_limit is None
                and precomputed_boundary is not None
                and not capacity_inputs_stale
            ):
                precomputed_limit = precomputed_boundary.runner_capacity.effective_limit
                if precomputed_limit > 0:
                    boundary_limit = precomputed_limit
            snapshot = self._make_prepared_apply_snapshot(
                on_agents_tab=on_agents_tab,
                selected_identity=selected_identity,
                load_state=load_state,
            )
            boundary = prepare_loaded_agents_apply_boundary(
                prep,
                snapshot,
                merge_incomplete=False,
                effective_runner_limit=boundary_limit,
            )
        live_proc_generation = int(getattr(self, "_proc_generation", 0))
        if live_proc_generation != boundary.proc_generation:
            live_snapshot = self._make_prepared_apply_snapshot(
                on_agents_tab=on_agents_tab,
                selected_identity=selected_identity,
                load_state=load_state,
            )
            boundary = rebase_prepared_apply_boundary_on_proc_projection(
                boundary,
                live_snapshot,
            )
        prep = boundary.prep

        history_query_key = history_query_key_for_load(self, load_state)
        history_complete_for_query = has_complete_history_for_load_query(
            self,
            load_state,
        )

        if load_state is not None and load_state.complete_history:
            self._agents_complete_history_query_key = history_query_key
            self._agents_seen_complete_history = True
            self._agents_history_reconcile_pending = False
            from ..event_refresh._freshness import note_surface_refreshed

            note_surface_refreshed(self, "agents_full_history")
        elif not history_complete_for_query:
            # The latch belongs to the query that produced complete history,
            # not to whatever roster was applied last: an incomplete load for
            # a different query key must disarm it even when the applied key
            # is unset or already matches this load. The reconcile-arming
            # check above uses this same latch-key comparison, so the two
            # stay consistent.
            self._agents_complete_history_query_key = None
            self._agents_seen_complete_history = False
        self._agents_applied_query_key = history_query_key
        self._agent_load_state = load_state
        schema_rebuild_in_flight = bool(
            getattr(self, "_artifact_index_schema_rebuild_in_flight", False)
        )
        if not schema_rebuild_in_flight:
            self._maybe_notify_agent_index_repair(load_state)
        # Defer the Tier 2 full-history reconcile only for repair/fallback
        # states. A healthy Tier 1 load can be archive-incomplete while still
        # complete for the visible inbox, so ordinary startup/lifecycle
        # refreshes must not prime the next normal refresh into Tier 2.
        if (
            not schema_rebuild_in_flight
            and should_arm_full_history_reconcile(
                load_state,
                history_complete_for_query=history_complete_for_query,
            )
            and not getattr(self, "_agents_history_reconcile_pending", False)
        ):
            self._agents_history_reconcile_pending = True
            self._agents_history_reconcile_armed_mono = time.monotonic()

        self._dismissed_agent_objects = trim_dismissed_agent_objects(
            prep.dismissed_agent_objects
        )
        self._has_always_visible = prep.has_always_visible
        self._hidden_count = prep.hidden_count
        self._hideable_agents = prep.hideable_agents
        previous_agents_with_children = list(getattr(self, "_agents_with_children", []))
        previous_agents = list(self._agents)
        previous_capacity = getattr(self, "_agent_runner_capacity", None)
        previous_capacity_generation = int(
            getattr(self, "_agents_capacity_applied_generation", 0)
        )
        bump_capacity = getattr(self, "_bump_agents_capacity_generation", None)
        if callable(bump_capacity):
            roster_capacity_generation = int(bump_capacity())
        else:
            roster_capacity_generation = (
                int(getattr(self, "_agents_capacity_generation", 0)) + 1
            )
            self._agents_capacity_generation = roster_capacity_generation
        if capacity_inputs_stale and previous_capacity is not None:
            self._agent_runner_capacity = previous_capacity
            self._agents_capacity_applied_generation = previous_capacity_generation
        else:
            boundary = replace(
                boundary,
                capacity_generation=roster_capacity_generation,
            )
            self._agent_runner_capacity = boundary.runner_capacity
            self._agents_capacity_applied_generation = roster_capacity_generation
        self._agents_capacity_with_children = list(
            boundary.prep.capacity_agents or boundary.fold.local_unfiltered_agents
        )
        unfiltered_agents = boundary.fold.unfiltered_agents
        visible_agents = boundary.fold.visible_agents
        fold_counts = boundary.fold.fold_counts
        # The boundary was projected from the fleet rows its snapshot captured.
        # Publish its rows (the ones the finalize plan was computed over) while
        # those are still the app's fleet rows; a fleet refresh in between
        # replaces them, and the live roster is derived again the same way.
        live_fleet_rows = self._fleet_rows_for_prepared_snapshot()
        roster_moved = len(live_fleet_rows) != len(boundary.fleet_source_rows) or any(
            live is not source
            for live, source in zip(
                live_fleet_rows, boundary.fleet_source_rows, strict=False
            )
        )
        if roster_moved:
            snapshot_fold = getattr(
                getattr(self, "_fold_manager", None), "snapshot", None
            )
            unfiltered_agents, visible_agents, fold_counts = project_and_fold_rosters(
                boundary.fold.local_unfiltered_agents,
                live_fleet_rows,
                snapshot_fold() if callable(snapshot_fold) else None,
            )
        self._agents_local_with_children = list(  # type: ignore[attr-defined]
            boundary.fold.local_unfiltered_agents
        )
        self._agents_local_visible = list(boundary.fold.local_visible_agents)  # type: ignore[attr-defined]
        self._agents_with_children = unfiltered_agents
        rearm_live_agent_watch_coverage(self)
        self._agents = visible_agents
        if capacity_inputs_stale:
            schedule_capacity_refresh = getattr(
                self,
                "_schedule_agents_capacity_refresh_from_roster",
                None,
            )
            if callable(schedule_capacity_refresh):
                schedule_capacity_refresh(source="apply_stale_capacity")
        carry_over_live_hints(
            [*previous_agents_with_children, *previous_agents],
            [*self._agents_with_children, *self._agents],
        )
        carry_over_diff_badges(
            [*previous_agents_with_children, *previous_agents],
            [*self._agents_with_children, *self._agents],
        )
        self._fold_counts = fold_counts

        finalize_plan = self._select_finalize_plan(
            boundary.finalize,
            on_agents_tab=on_agents_tab,
            selected_identity=selected_identity,
            roster_moved=roster_moved,
            trace_extra=trace_extra,
        )
        if first_agents_load:
            debouncer = getattr(self, "_agent_detail_debouncer", None)
            if debouncer is not None:
                debouncer.cancel()
        # _panel_navigation_stops() is keyed on the agents-list identity,
        # so after the roster replacement above it rebuilds from the new
        # roster when _restore_focus_after_removal runs; no explicit cache
        # invalidation is needed here.
        self._finalize_agent_list(
            on_agents_tab,
            selected_identity,
            save_unfiltered=False,
            fold_filter_already_applied=True,
            prior_pos=prior_pos,
            precomputed_plan=finalize_plan,
            previous_agents=previous_agents,
        )
        if first_agents_load:
            # Keep the info panel's loading treatment until the coherent row,
            # capacity, and metric snapshot has been installed and rendered.
            from ...widgets import AgentInfoPanel

            try:
                info_panel = self.query_one(  # type: ignore[attr-defined]
                    "#agent-info-panel", AgentInfoPanel
                )
                info_panel.set_loading(False)
            except Exception:
                pass
            self._mark_startup_agents_ready()  # type: ignore[attr-defined]
            self._maybe_end_startup_stopwatch()  # type: ignore[attr-defined]
        from ...repro.capture import record_agents_tab_app_projection

        record_agents_tab_app_projection(
            self,
            load_state=load_state,
            source="apply",
        )

        schedule_post_roster_work = getattr(
            self,
            "_schedule_agents_post_roster_startup_work",
            None,
        )
        if callable(schedule_post_roster_work):
            schedule_post_roster_work(source="apply")
        else:
            self._schedule_live_hint_refresh(source="apply")  # type: ignore[attr-defined]
            self._schedule_bead_confirmation_warmup(source="apply")  # type: ignore[attr-defined]
            schedule_family_preview_warmup = getattr(
                self,
                "_schedule_family_plan_preview_warmup",
                None,
            )
            if callable(schedule_family_preview_warmup) and hasattr(
                self,
                "_family_preview_scan_running",
            ):
                schedule_family_preview_warmup(source="apply")
            self._schedule_diff_badge_classification(source="apply")  # type: ignore[attr-defined]

        arm_index_revalidate = getattr(
            self,
            "_arm_tier1_index_revalidate_reconcile",
            None,
        )
        if callable(arm_index_revalidate):
            arm_index_revalidate(
                load_state,
                source=getattr(self, "_agents_refresh_active_source", "unknown"),
            )
        arm_prefix_completion = getattr(
            self,
            "_arm_startup_prefix_completion",
            None,
        )
        if callable(arm_prefix_completion):
            arm_prefix_completion(
                load_state,
                source=getattr(self, "_agents_refresh_active_source", "unknown"),
            )

        schedule_fleet_refresh = getattr(self, "_schedule_agents_fleet_refresh", None)
        if callable(schedule_fleet_refresh):
            schedule_fleet_refresh(source="apply")

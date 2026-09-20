"""UI-thread apply helpers for loaded agent snapshots."""

from __future__ import annotations

import time
from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast

from ...models.agent import AgentType
from ...util.trace import trace_event, tui_trace
from ._loading_compute import (
    PreparedApplyBoundary,
    PreparedApplyData,
    PreparedApplySelectionInputs,
    PreparedApplySnapshot,
    PreparedFinalizePlan,
    make_finalize_stale_token,
    merge_incomplete_load_after_complete_history,
    prepare_loaded_agents_apply_boundary,
    project_and_fold_rosters,
    rebase_prepared_apply_boundary_on_proc_projection,
)
from ._dismiss_memory import trim_dismissed_agent_objects
from ._loading_diff_badges import carry_over_diff_badges
from ._loading_helpers import is_always_visible, roster_identities
from ._loading_live_hints import carry_over_live_hints
from ._loading_state import AgentLoadingStateMixin
from ._live_watch_coverage import rearm_live_agent_watch_coverage
from ._refresh_trace import classify_agents_data_cost, record_agents_refresh_trace

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_loader import AgentLoadState
    from ...models.agent_live_query_engine import AgentsHistoryQueryKey
    from ...models.fold_state import FoldLevel


def _note_finalize_plan_outcome(
    trace_extra: dict[str, Any] | None,
    outcome: str,
    discard_reason: str | None = None,
) -> None:
    """Record whether the worker finalize plan was ``applied`` on the apply span."""
    if trace_extra is None:
        return
    trace_extra["finalize_plan"] = outcome
    if discard_reason is not None:
        trace_extra["finalize_plan_discard_reason"] = discard_reason


def _agent_index_repair_notice(load_state: AgentLoadState | None) -> str | None:
    """Return the operator-facing repair notice for a load state."""
    if load_state is None or not load_state.repair_recommended:
        return None
    reason = load_state.repair_reason or "unknown"
    return (
        f"Agent index repair recommended: {reason}. "
        "Run `sase agent index status --json`, then `sase agent index gc`."
    )


def _history_query_key_for_load(
    app: object,
    load_state: AgentLoadState | None,
) -> AgentsHistoryQueryKey:
    """Return the committed-query key that the incoming load covers."""

    load_key = getattr(load_state, "history_query_key", None)
    if load_key is not None:
        return cast("AgentsHistoryQueryKey", load_key)
    from ...models.agent_live_query_engine import agents_history_query_key

    return agents_history_query_key(getattr(app, "_agent_search_query", "") or "")


def _has_complete_history_for_load_query(
    app: object,
    load_state: AgentLoadState | None,
) -> bool:
    """Return whether cached full history belongs to this load's query key."""

    complete_key = getattr(app, "_agents_complete_history_query_key", None)
    if complete_key is None:
        # Compatibility for tests and older in-memory app fakes that set the
        # historical boolean directly without the keyed latch.
        return bool(getattr(app, "_agents_seen_complete_history", False))
    return complete_key == _history_query_key_for_load(app, load_state)


def _cache_query_matches_load(
    app: object,
    load_state: AgentLoadState | None,
) -> bool:
    """Return whether the cached roster was applied under this load's query."""

    applied_key = getattr(app, "_agents_applied_query_key", None)
    if applied_key is None:
        return True
    return applied_key == _history_query_key_for_load(app, load_state)


def _should_arm_full_history_reconcile(
    load_state: AgentLoadState | None,
    *,
    history_complete_for_query: bool = False,
) -> bool:
    """Return whether this load state should arm a deferred Tier 2 reconcile."""
    if load_state is None or not load_state.needs_full_history_reconcile:
        return False
    if load_state.repair_recommended:
        return True
    if load_state.query_incomplete:
        return not history_complete_for_query
    return not load_state.complete_visible_inbox and not load_state.used_artifact_index


class AgentLoadingApplyMixin(AgentLoadingStateMixin):
    """Methods that merge prepared agent data back into app state."""

    def _preserve_revived_agents_for_incomplete_load(
        self,
        prep: PreparedApplyData,
        load_state: AgentLoadState | None,
    ) -> bool:
        """Keep revived historical agents visible until Tier 2 reconciles."""
        revived_suffixes = getattr(self, "_revived_agent_raw_suffixes", None)
        if not revived_suffixes:
            return False

        loaded_suffixes = {
            agent.raw_suffix
            for agent in prep.filtered_agents
            if agent.raw_suffix is not None
        }
        if load_state is not None and load_state.complete_history:
            revived_suffixes.difference_update(loaded_suffixes)
            return False
        if load_state is None or load_state.complete_history:
            return False

        missing_suffixes = revived_suffixes - loaded_suffixes
        if not missing_suffixes:
            return False

        dismissed_suffixes = {
            raw_suffix
            for _, _, raw_suffix in self._dismissed_agents
            if raw_suffix is not None
        }
        missing_suffixes -= dismissed_suffixes
        if not missing_suffixes:
            return False

        existing_identities = {agent.identity for agent in prep.filtered_agents}
        preserved: list[Agent] = []
        preserved_suffixes: set[str] = set()
        for agent in self._agents_with_children:
            if agent.raw_suffix not in missing_suffixes:
                continue
            if agent.identity in existing_identities:
                continue
            if agent.identity in self._dismissed_agents:
                continue
            preserved.append(agent)
            existing_identities.add(agent.identity)
            if agent.raw_suffix is not None:
                preserved_suffixes.add(agent.raw_suffix)

        # Fall back to the dismissed-bundle cache for revived suffixes that
        # never landed in ``_agents_with_children`` (e.g. long-dismissed
        # bundles revived from the archive). The revive flow hydrates those
        # bundle agents into ``_dismissed_agent_objects`` before calling the
        # loader, so the data is on hand for first-paint visibility.
        remaining_suffixes = missing_suffixes - preserved_suffixes
        if remaining_suffixes:
            for agent in self._dismissed_agent_objects:
                if agent.raw_suffix not in remaining_suffixes:
                    continue
                if agent.identity in existing_identities:
                    continue
                if agent.identity in self._dismissed_agents:
                    continue
                preserved.append(agent)
                existing_identities.add(agent.identity)

        if not preserved:
            return False

        prep.filtered_agents = [*prep.filtered_agents, *preserved]
        prep.has_always_visible = any(
            is_always_visible(a) for a in prep.filtered_agents
        )
        prep.hideable_agents = [
            agent for agent in prep.filtered_agents if not is_always_visible(agent)
        ]
        return True

    def _make_prepared_apply_snapshot(
        self,
        *,
        on_agents_tab: bool,
        selected_identity: tuple[AgentType, str, str | None] | None,
        load_state: AgentLoadState | None,
    ) -> PreparedApplySnapshot:
        """Capture UI-owned state for the pure prepared-apply boundary.

        This is a cheap identity capture: agent lists are shallow-copied.
        Worker mutation must go through :func:`own_prepared_apply_snapshot`.
        """
        from ...models.agent_groups import GroupingMode

        fold_manager = getattr(self, "_fold_manager", None)
        snapshot_fold = getattr(fold_manager, "snapshot", None)
        fold_levels = cast(
            "dict[str, FoldLevel] | None",
            snapshot_fold() if callable(snapshot_fold) else None,
        )
        prior_visual_row: int | None
        if on_agents_tab:
            prior_visual_row = self.current_idx
        else:
            prior_visual_row = getattr(self, "_agents_last_idx", None)
        grouping_mode = getattr(self, "_grouping_mode", None)
        if grouping_mode is None:
            grouping_mode = GroupingMode.STANDARD
        from ..._proc_observer_models import ProcProjection

        compose = getattr(self, "_effective_proc_projection", None)
        proc_projection: ProcProjection | None
        if callable(compose):
            captured = compose()
            proc_projection = (
                captured if isinstance(captured, ProcProjection) else ProcProjection()
            )
        else:
            captured = getattr(self, "_proc_projection", None)
            proc_projection = captured if isinstance(captured, ProcProjection) else None

        return PreparedApplySnapshot(
            cached_agents_with_children=list(
                getattr(self, "_agents_with_children", [])
            ),
            dismissed_agents=set(getattr(self, "_dismissed_agents", set())),
            agents_seen_complete_history=_has_complete_history_for_load_query(
                self,
                load_state,
            ),
            hide_non_run_agents=bool(self.hide_non_run_agents),
            load_state=load_state,
            fold_levels=fold_levels,
            selection=PreparedApplySelectionInputs(
                on_agents_tab=on_agents_tab,
                selected_identity=selected_identity,
                prior_visual_row=prior_visual_row,
            ),
            capacity_agents_with_children=list(
                getattr(
                    self,
                    "_agents_capacity_with_children",
                    getattr(self, "_agents_with_children", []),
                )
            ),
            agent_search_query=getattr(self, "_agent_search_query", "") or "",
            agent_query_cache=getattr(self, "_agent_query_cache", None),
            agent_status_overrides=dict(getattr(self, "_agent_status_overrides", {})),
            grouping_mode=grouping_mode,
            agent_panels_grouped=bool(getattr(self, "_agent_panels_grouped", False)),
            capacity_generation=int(getattr(self, "_agents_capacity_generation", 0)),
            unread_agent_ids=frozenset(
                getattr(self, "_unread_completed_agent_ids", ()) or ()
            ),
            proc_projection=proc_projection,
            proc_generation=int(getattr(self, "_proc_generation", 0)),
            dismissed_proc_shells=frozenset(
                getattr(self, "_dismissed_proc_shells", ()) or ()
            ),
            cache_query_matches=_cache_query_matches_load(self, load_state),
            fleet_rows=self._fleet_rows_for_prepared_snapshot(),
        )

    def _fleet_rows_for_prepared_snapshot(self) -> tuple[Agent, ...]:
        """Return the fleet rows a load's roster is widened with when published.

        Runs on the UI thread because reconciling dispatch provisionals mutates
        ``_agents_dispatch_provisional_rows``.
        """
        fleet_rows = list(getattr(self, "_agents_fleet_rows", ()) or ())
        with_provisionals = getattr(
            self, "_fleet_rows_with_dispatch_provisionals", None
        )
        if callable(with_provisionals):
            fleet_rows = list(with_provisionals(fleet_rows))
        return tuple(fleet_rows)

    def _select_finalize_plan(
        self,
        precomputed: PreparedFinalizePlan | None,
        *,
        on_agents_tab: bool,
        selected_identity: tuple[AgentType, str, str | None] | None,
        roster_moved: bool = False,
        trace_extra: dict[str, Any] | None = None,
    ) -> PreparedFinalizePlan | None:
        """Return the worker plan if it still describes what is being published.

        The plan is discarded — and the finalize pipeline recomputes the
        query filter, status overrides, selection math, and group keys on
        the UI thread — when either:

        * any captured input (selection, fold snapshot, query,
          status-override set, grouping mode, or hide flag) has drifted since
          the worker ran (``stale_token``); or
        * the rows the plan was computed over are not the roster about to be
          published (``roster_fingerprint``). The token cannot see this: it
          compares mutable UI state, and a plan over a different row set
          (for example a local-only roster before the fleet projection
          widened it) would otherwise silently replace ``self._agents``.

        Call after ``self._agents`` holds the roster being published.
        *roster_moved* says that roster was re-derived because the fleet rows
        changed after the plan's rows were projected, which the identity
        fingerprint alone cannot see (same identities, newer row content).
        *trace_extra*, when given, receives ``finalize_plan`` and, on a
        discard, ``finalize_plan_discard_reason``.
        """
        if precomputed is None:
            _note_finalize_plan_outcome(trace_extra, "absent")
            return None
        if roster_moved:
            _note_finalize_plan_outcome(trace_extra, "discarded", "roster_fingerprint")
            return None
        current_snapshot = self._make_prepared_apply_snapshot(
            on_agents_tab=on_agents_tab,
            selected_identity=selected_identity,
            load_state=getattr(self, "_agent_load_state", None),
        )
        current_token = make_finalize_stale_token(current_snapshot)
        if current_token != precomputed.stale_token:
            _note_finalize_plan_outcome(trace_extra, "discarded", "stale_token")
            return None
        if precomputed.input_row_identities != roster_identities(self._agents):
            _note_finalize_plan_outcome(trace_extra, "discarded", "roster_fingerprint")
            return None
        _note_finalize_plan_outcome(trace_extra, "applied")
        return precomputed

    def _merge_incomplete_load_after_complete_history(
        self,
        prep: PreparedApplyData,
        load_state: AgentLoadState | None,
    ) -> None:
        """Compatibility hook for the incomplete Tier 1 merge step."""
        merge_incomplete_load_after_complete_history(
            prep,
            self._make_prepared_apply_snapshot(
                on_agents_tab=False,
                selected_identity=None,
                load_state=load_state,
            ),
        )

    def _note_empty_incomplete_apply_ignored(
        self,
        load_state: AgentLoadState | None,
    ) -> None:
        """Trace a same-query bounded zero that the merge keeps out of the cache.

        The bounded zero patches over the cache instead of replacing it; one
        revalidated load then confirms whether the rows really are gone.
        """
        if load_state is None or load_state.returned_count != 0:
            self._agents_empty_ignored_revalidated = False
            return
        if (
            load_state.complete_history
            or not load_state.bounded_prefix
            or not getattr(self, "_agents_with_children", None)
            or not _cache_query_matches_load(self, load_state)
        ):
            return
        trace_event(
            "agents.empty_incomplete_apply_ignored",
            reason="empty_incomplete_apply_ignored",
            cached=len(self._agents_with_children),
            history_query_key=repr(_history_query_key_for_load(self, load_state)),
            has_more=load_state.has_more,
        )
        if getattr(self, "_agents_empty_ignored_revalidated", False):
            return
        self._agents_empty_ignored_revalidated = True
        cast("Any", self)._schedule_agents_async_refresh(
            source="empty_incomplete_revalidate",
            revalidate_index=True,
        )

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

        history_query_key = _history_query_key_for_load(self, load_state)
        history_complete_for_query = _has_complete_history_for_load_query(
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
            and _should_arm_full_history_reconcile(
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
        self._finalize_agent_list(
            on_agents_tab,
            selected_identity,
            save_unfiltered=False,
            fold_filter_already_applied=True,
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

    def _maybe_notify_agent_index_repair(
        self, load_state: AgentLoadState | None
    ) -> None:
        """Show a one-shot visible repair notice when Tier 1 diagnostics ask."""
        notice = _agent_index_repair_notice(load_state)
        if notice is None:
            self._agents_index_repair_notice_key = None
            return
        key = (
            load_state.repair_reason if load_state is not None else None,
            load_state.index_error if load_state is not None else None,
        )
        if key == getattr(self, "_agents_index_repair_notice_key", None):
            return
        self._agents_index_repair_notice_key = key
        self.notify(notice, severity="warning")  # type: ignore[attr-defined]

"""UI-thread apply helpers for loaded agent snapshots."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, cast

from ...models.agent import AgentType
from ...util.trace import tui_trace
from ._loading_compute import (
    PreparedApplyBoundary,
    PreparedApplyData,
    PreparedApplySelectionInputs,
    PreparedApplySnapshot,
    PreparedFinalizePlan,
    make_finalize_stale_token,
    merge_incomplete_load_after_complete_history,
    prepare_loaded_agents_apply_boundary,
)
from ._dismiss_memory import trim_dismissed_agent_objects
from ._loading_diff_badges import carry_over_diff_badges
from ._loading_helpers import is_always_visible
from ._loading_live_hints import carry_over_live_hints
from ._loading_state import AgentLoadingStateMixin
from ._live_watch_coverage import rearm_live_agent_watch_coverage
from ._refresh_trace import classify_agents_data_cost, record_agents_refresh_trace

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_loader import AgentLoadState
    from ...models.fold_state import FoldLevel


def _agent_index_repair_notice(load_state: AgentLoadState | None) -> str | None:
    """Return the operator-facing repair notice for a load state."""
    if load_state is None or not load_state.repair_recommended:
        return None
    reason = load_state.repair_reason or "unknown"
    return (
        f"Agent index repair recommended: {reason}. "
        "Run `sase agent index status --json`, then `sase agent index gc`."
    )


def _should_arm_full_history_reconcile(load_state: AgentLoadState | None) -> bool:
    """Return whether this load state should arm a deferred Tier 2 reconcile."""
    if load_state is None or not load_state.needs_full_history_reconcile:
        return False
    if load_state.repair_recommended:
        return True
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
        """Capture UI-owned state for the pure prepared-apply boundary."""
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
        return PreparedApplySnapshot(
            cached_agents_with_children=list(
                getattr(self, "_agents_with_children", [])
            ),
            dismissed_agents=set(getattr(self, "_dismissed_agents", set())),
            agents_seen_complete_history=bool(
                getattr(self, "_agents_seen_complete_history", False)
            ),
            hide_non_run_agents=bool(self.hide_non_run_agents),
            load_state=load_state,
            fold_levels=fold_levels,
            selection=PreparedApplySelectionInputs(
                on_agents_tab=on_agents_tab,
                selected_identity=selected_identity,
                prior_visual_row=prior_visual_row,
            ),
            agent_search_query=getattr(self, "_agent_search_query", "") or "",
            agent_query_cache=getattr(self, "_agent_query_cache", None),
            agent_status_overrides=dict(getattr(self, "_agent_status_overrides", {})),
            grouping_mode=grouping_mode,
            agent_panels_grouped=bool(getattr(self, "_agent_panels_grouped", False)),
        )

    def _select_finalize_plan(
        self,
        precomputed: PreparedFinalizePlan | None,
        *,
        on_agents_tab: bool,
        selected_identity: tuple[AgentType, str, str | None] | None,
    ) -> PreparedFinalizePlan | None:
        """Return the worker plan if its stale token still matches UI state.

        The plan is discarded — and the finalize pipeline recomputes the
        query filter, status overrides, selection math, and group keys on
        the UI thread — whenever any captured input (selection, fold
        snapshot, query, status-override set, grouping mode, or hide
        flag) has drifted since the worker ran.
        """
        if precomputed is None:
            return None
        current_snapshot = self._make_prepared_apply_snapshot(
            on_agents_tab=on_agents_tab,
            selected_identity=selected_identity,
            load_state=getattr(self, "_agent_load_state", None),
        )
        current_token = make_finalize_stale_token(current_snapshot)
        if current_token == precomputed.stale_token:
            return precomputed
        return None

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
        effective_runner_limit: int | None = None,
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
        ):
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
        effective_runner_limit: int | None = None,
    ) -> None:
        """Implementation for the traced prepared-apply UI continuation."""
        first_agents_load = not self._agents_first_load_done
        if first_agents_load:
            self._agents_first_load_done = True
            from ...widgets import AgentList

            try:
                self.query_one("#agent-list-panel", AgentList).loading = False  # type: ignore[attr-defined]
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

        if boundary is None:
            boundary_limit = effective_runner_limit
            if boundary_limit is None and precomputed_boundary is not None:
                precomputed_limit = precomputed_boundary.runner_capacity.effective_limit
                if precomputed_limit > 0:
                    boundary_limit = precomputed_limit
            boundary = prepare_loaded_agents_apply_boundary(
                prep,
                self._make_prepared_apply_snapshot(
                    on_agents_tab=on_agents_tab,
                    selected_identity=selected_identity,
                    load_state=load_state,
                ),
                merge_incomplete=False,
                effective_runner_limit=boundary_limit,
            )
        prep = boundary.prep

        if load_state is not None and load_state.complete_history:
            self._agents_seen_complete_history = True
            self._agents_history_reconcile_pending = False
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
            and _should_arm_full_history_reconcile(load_state)
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
        self._agent_runner_capacity = boundary.runner_capacity
        self._agents_with_children = boundary.fold.unfiltered_agents
        rearm_live_agent_watch_coverage(self)
        self._agents = boundary.fold.visible_agents
        carry_over_live_hints(
            [*previous_agents_with_children, *previous_agents],
            [*self._agents_with_children, *self._agents],
        )
        carry_over_diff_badges(
            [*previous_agents_with_children, *previous_agents],
            [*self._agents_with_children, *self._agents],
        )
        self._fold_counts = boundary.fold.fold_counts

        finalize_plan = self._select_finalize_plan(
            boundary.finalize,
            on_agents_tab=on_agents_tab,
            selected_identity=selected_identity,
        )
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
            self._maybe_end_startup_stopwatch()  # type: ignore[attr-defined]
            self._mark_startup_agents_ready()  # type: ignore[attr-defined]
        from ...repro.capture import record_agents_tab_app_projection

        record_agents_tab_app_projection(
            self,
            load_state=load_state,
            source="apply",
        )

        sync_proc_shells = getattr(
            self, "_sync_proc_shell_agents_from_projection", None
        )
        if callable(sync_proc_shells):
            sync_proc_shells()

        # Live workspace pencil hints for active rows without a persisted
        # diff_path are computed off the loader path. Schedule the deferred,
        # coalesced background scan now that the agent list is finalized; it
        # no-ops cheaply when there are no active candidates.
        self._schedule_live_hint_refresh(source="apply")  # type: ignore[attr-defined]

        # Confirmed-bead glyph/field can only render from a warm cache, so
        # confirm visible bead candidates off the event loop now that the list
        # has painted; it no-ops cheaply when no visible row has an unconfirmed
        # candidate.
        self._schedule_bead_confirmation_warmup(source="apply")  # type: ignore[attr-defined]

        # Family completion previews resolve plan/bead context off the render
        # path. The warmed cache feeds the next prompt-target completion menu.
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

        # Persisted diff-badge classification reads every referenced diff
        # file, so it is deferred off the loader path the same way; it
        # no-ops cheaply when every visible row is already classified.
        self._schedule_diff_badge_classification(source="apply")  # type: ignore[attr-defined]

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

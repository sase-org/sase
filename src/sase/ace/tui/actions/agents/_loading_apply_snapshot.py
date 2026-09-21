"""Prepared-apply snapshot capture and finalize-plan selection."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from ._loading_apply_history import (
    cache_query_matches_load,
    has_complete_history_for_load_query,
)
from ._loading_compute import (
    PreparedApplySelectionInputs,
    PreparedApplySnapshot,
    PreparedFinalizePlan,
    make_finalize_stale_token,
)
from ._loading_helpers import roster_identities
from ._loading_state import AgentLoadingStateMixin

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_loader import AgentLoadState
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


class AgentLoadingApplySnapshotMixin(AgentLoadingStateMixin):
    """Methods that capture UI state for the pure prepared-apply boundary."""

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
            agents_seen_complete_history=has_complete_history_for_load_query(
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
            cache_query_matches=cache_query_matches_load(self, load_state),
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

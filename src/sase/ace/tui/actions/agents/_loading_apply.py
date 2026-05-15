"""UI-thread apply helpers for loaded agent snapshots."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...models.agent import AgentType
from ...util.trace import tui_trace
from ._loading_compute import (
    PreparedApplyBoundary,
    PreparedApplyData,
    PreparedApplySelectionInputs,
    PreparedApplySnapshot,
    merge_incomplete_load_after_complete_history,
    prepare_loaded_agents_apply_boundary,
)
from ._loading_helpers import is_always_visible
from ._loading_state import AgentLoadingStateMixin

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_loader import AgentLoadState
    from ...models.fold_state import FoldLevel


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
        fold_manager = getattr(self, "_fold_manager", None)
        snapshot_fold = getattr(fold_manager, "snapshot", None)
        fold_levels = snapshot_fold() if callable(snapshot_fold) else None
        prior_visual_row: int | None
        if on_agents_tab:
            prior_visual_row = self.current_idx
        else:
            prior_visual_row = getattr(self, "_agents_last_idx", None)
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
        )

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
        incomplete_merge_already_applied: bool = False,
        precomputed_boundary: PreparedApplyBoundary | None = None,
        precomputed_fold_levels: dict[str, FoldLevel] | None = None,
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
        with tui_trace(
            "agents.apply_loaded_agents_prepared",
            agents=len(prep.filtered_agents),
            complete=getattr(load_state, "complete_history", None),
        ):
            self._apply_loaded_agents_prepared_inner(
                prep,
                on_agents_tab=on_agents_tab,
                selected_identity=selected_identity,
                load_state=load_state,
                persist_dismissed_changes=persist_dismissed_changes,
                incomplete_merge_already_applied=incomplete_merge_already_applied,
                precomputed_boundary=precomputed_boundary,
                precomputed_fold_levels=precomputed_fold_levels,
            )

    def _apply_loaded_agents_prepared_inner(
        self,
        prep: PreparedApplyData,
        *,
        on_agents_tab: bool,
        selected_identity: tuple[AgentType, str, str | None] | None,
        load_state: AgentLoadState | None = None,
        persist_dismissed_changes: bool,
        incomplete_merge_already_applied: bool = False,
        precomputed_boundary: PreparedApplyBoundary | None = None,
        precomputed_fold_levels: dict[str, FoldLevel] | None = None,
    ) -> None:
        """Implementation for the traced prepared-apply UI continuation."""
        # Clear the startup loading indicators (spinner on list panels,
        # dim ellipsis on tab label / info panel) on the first completed
        # load. Safe to call every refresh -- flag stays True and the
        # widget setters are idempotent.
        if not self._agents_first_load_done:
            self._agents_first_load_done = True
            from ...widgets import AgentInfoPanel, AgentList

            try:
                self.query_one("#agent-list-panel", AgentList).loading = False  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                info_panel = self.query_one(  # type: ignore[attr-defined]
                    "#agent-info-panel", AgentInfoPanel
                )
                info_panel.set_loading(False)
            except Exception:
                pass
            self._maybe_end_startup_stopwatch()  # type: ignore[attr-defined]

        if prep.recovered_bundle_identities:
            self._dismissed_agents.update(prep.recovered_bundle_identities)
        if prep.auto_dismissed_identities:
            self._dismissed_agents.update(prep.auto_dismissed_identities)
        if persist_dismissed_changes:
            from ....dismissed_agents import save_dismissed_agents

            save_dismissed_agents(self._dismissed_agents)

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
            boundary = prepare_loaded_agents_apply_boundary(
                prep,
                self._make_prepared_apply_snapshot(
                    on_agents_tab=on_agents_tab,
                    selected_identity=selected_identity,
                    load_state=load_state,
                ),
                merge_incomplete=False,
            )
        prep = boundary.prep

        if load_state is not None and load_state.complete_history:
            self._agents_seen_complete_history = True
        self._agent_load_state = load_state
        if (
            load_state is not None
            and load_state.needs_full_history_reconcile
            and not getattr(self, "_agents_refresh_pending_full_history", False)
            and not getattr(self, "_agents_refresh_scheduled_full_history", False)
        ):
            self._agents_refresh_pending = True
            self._agents_refresh_pending_full_history = True

        self._dismissed_agent_objects = prep.dismissed_agent_objects
        self._has_always_visible = prep.has_always_visible
        self._hidden_count = prep.hidden_count
        self._hideable_agents = prep.hideable_agents
        self._agents_with_children = boundary.fold.unfiltered_agents
        self._agents = boundary.fold.visible_agents
        self._fold_counts = boundary.fold.fold_counts

        self._finalize_agent_list(
            on_agents_tab,
            selected_identity,
            save_unfiltered=False,
            fold_filter_already_applied=True,
        )
        from ...repro.capture import record_agents_tab_app_projection

        record_agents_tab_app_projection(
            self,
            load_state=load_state,
            source="apply",
        )

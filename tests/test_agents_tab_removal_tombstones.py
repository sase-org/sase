"""Regression coverage for session-local Agents-tab removal tombstones."""

from __future__ import annotations

from dataclasses import replace

from sase.ace.tui.actions.agents._loading_compute import (
    PreparedApplyData,
    compute_apply_loaded_agents,
    merge_incomplete_load_after_complete_history,
    prepare_loaded_agents_apply_boundary,
)
from sase.ace.tui.actions.agents._fleet_projection import AgentFleetProjectionMixin
from sase.ace.tui.actions.agents._removal_tombstones import (
    AgentRemovalTombstonesMixin,
    ExplicitRemovalSnapshot,
    filter_explicitly_removed,
)
from sase.ace.tui.models.agent import AgentType

from tests._agents_tab_incomplete_merge_helpers import _incomplete_tier1_snapshot
from tests._agents_tab_query_helpers import FakeAgentApp, _make_agent


class _TombstoneApplyApp(AgentRemovalTombstonesMixin, FakeAgentApp):
    def __init__(self) -> None:
        super().__init__()
        self._explicit_removals = set()
        self._explicit_removal_suffixes = set()
        self._explicit_removal_cl_suffixes = set()
        self._agents_removal_generation = 0
        self._agents_local_with_children = []
        self._agents_local_visible = []
        self._agents_fleet_rows = []
        self._agents_capacity_with_children = []
        self._agents_capacity_generation = 0
        self._agents_capacity_applied_generation = 0
        self._agent_runner_capacity = None
        self._proc_generation = 0
        self._agents_first_load_done = True


class _TombstoneFleetApp(AgentRemovalTombstonesMixin, AgentFleetProjectionMixin):
    def __init__(self, agent: object) -> None:
        self.current_tab = "changespecs"
        self.current_idx = 0
        self._agents = [agent]
        self._agents_with_children = [agent]
        self._agents_local_with_children = [agent]
        self._agents_local_visible = [agent]
        self._agents_fleet_rows = []
        self._agents_dispatch_provisional_rows = {}
        self._agents_fleet_applied_projection_signature = None
        self._agents_refresh_active_source = "unknown"
        self._explicit_removals = set()
        self._explicit_removal_suffixes = set()
        self._explicit_removal_cl_suffixes = set()
        self._agents_removal_generation = 0

    def _fleet_rows_with_dispatch_provisionals(
        self, rows: list[object]
    ) -> list[object]:
        return rows

    def _finalize_agent_list(self, *_args: object, **_kwargs: object) -> None:
        pass

    def _update_agents_header(self) -> None:
        pass


def _live_agent(*, cl_name: str = "work", suffix: str = "20260924093000"):
    agent = _make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name=cl_name,
        raw_suffix=suffix,
        status="RETRYING",
    )
    agent.runner_is_live = True
    return agent


def test_tombstoned_live_row_is_filtered_and_retained_for_revive() -> None:
    agent = _live_agent()
    removals = ExplicitRemovalSnapshot.from_identities({agent.identity})

    prep = compute_apply_loaded_agents(
        all_agents=[agent],
        dismissed_from_loader=[],
        dismissed_snapshot={agent.identity},
        hide_non_run_agents=False,
        explicit_removals=removals,
    )

    assert prep.filtered_agents == []
    assert prep.dismissed_agent_objects == [agent]


def test_untombstoned_live_retry_still_beats_stale_dismissal() -> None:
    agent = _live_agent()

    prep = compute_apply_loaded_agents(
        all_agents=[agent],
        dismissed_from_loader=[],
        dismissed_snapshot={agent.identity},
        hide_non_run_agents=False,
    )

    assert prep.filtered_agents == [agent]


def test_tombstone_matches_running_relabel_and_drops_empty_clan() -> None:
    killed = _live_agent(cl_name="alpha", suffix="20260924093100")
    relabeled = _live_agent(cl_name="alpha", suffix=killed.raw_suffix or "")
    relabeled.agent_type = AgentType.RUNNING
    unknown = _live_agent(cl_name="unknown", suffix=killed.raw_suffix or "")
    unknown.agent_type = AgentType.RUNNING

    filtered = filter_explicitly_removed(
        [relabeled, unknown],
        ExplicitRemovalSnapshot.from_identities({killed.identity}),
    )

    assert filtered == []


def test_tier1_merge_honors_tombstone_before_live_runner_exemption() -> None:
    cached = _live_agent()
    prep = PreparedApplyData(
        filtered_agents=[],
        has_always_visible=False,
        hidden_count=0,
        hideable_agents=[],
        dismissed_agent_objects=[],
    )
    snapshot = replace(
        _incomplete_tier1_snapshot([cached]),
        explicit_removals=ExplicitRemovalSnapshot.from_identities({cached.identity}),
    )

    merge_incomplete_load_after_complete_history(prep, snapshot)

    assert prep.filtered_agents == []


def test_apply_rechecks_removal_recorded_after_worker_boundary() -> None:
    app = _TombstoneApplyApp()
    agent = _live_agent()
    prep = PreparedApplyData(
        filtered_agents=[agent],
        has_always_visible=True,
        hidden_count=0,
        hideable_agents=[],
        dismissed_agent_objects=[],
    )
    boundary = prepare_loaded_agents_apply_boundary(
        prep,
        app._make_prepared_apply_snapshot(
            on_agents_tab=False, selected_identity=None, load_state=None
        ),
    )
    app.record_explicit_removals({agent.identity})

    app._apply_loaded_agents_prepared(
        prep,
        on_agents_tab=False,
        selected_identity=None,
        load_state=None,
        persist_dismissed_changes=False,
        incomplete_merge_already_applied=True,
        precomputed_boundary=boundary,
        precomputed_fold_levels=app._fold_manager.snapshot(),
    )

    assert app._agents_with_children == []
    assert app._agents == []


def _apply_after_removal(
    app: _TombstoneApplyApp,
    agent: Agent,
    *,
    move_proc_generation: bool = False,
    stale_fold_levels: bool = False,
) -> None:
    """Prepare a worker boundary, remove *agent*, then apply the stale boundary."""
    prep = PreparedApplyData(
        filtered_agents=[agent],
        has_always_visible=True,
        hidden_count=0,
        hideable_agents=[],
        dismissed_agent_objects=[],
    )
    boundary = prepare_loaded_agents_apply_boundary(
        prep,
        app._make_prepared_apply_snapshot(
            on_agents_tab=False, selected_identity=None, load_state=None
        ),
    )
    app.record_explicit_removals({agent.identity})
    app._dismissed_agents.add(agent.identity)
    if move_proc_generation:
        app._proc_generation += 1
    fold_levels = app._fold_manager.snapshot()

    app._apply_loaded_agents_prepared(
        prep,
        on_agents_tab=False,
        selected_identity=None,
        load_state=None,
        persist_dismissed_changes=False,
        incomplete_merge_already_applied=True,
        precomputed_boundary=boundary,
        precomputed_fold_levels={"stale": fold_levels}
        if stale_fold_levels
        else fold_levels,
    )


def test_apply_recheck_survives_a_proc_projection_rebase() -> None:
    """A proc-generation move between prep and apply rebases the worker boundary.

    The rebase only swaps proc-shell rows; its local roster is still the one the
    worker prepared before the removal, so it must keep the worker's removal
    provenance or the recheck compares the live generation with itself.
    """
    app = _TombstoneApplyApp()
    agent = _live_agent()

    _apply_after_removal(app, agent, move_proc_generation=True)

    assert app._agents_with_children == []
    assert app._agents == []
    assert app._agents_local_with_children == []


def test_apply_recheck_survives_a_fold_level_rebuild() -> None:
    """Changed fold levels rebuild the boundary from the same stale prepared roster."""
    app = _TombstoneApplyApp()
    agent = _live_agent()

    _apply_after_removal(app, agent, stale_fold_levels=True)

    assert app._agents_with_children == []
    assert app._agents == []
    assert app._agents_local_with_children == []


def test_fleet_reprojection_cannot_resurrect_a_tombstoned_local_row() -> None:
    agent = _live_agent()
    app = _TombstoneFleetApp(agent)
    app.record_explicit_removals({agent.identity})

    app._reproject_agents_from_current_mode(source="fleet_refresh")

    assert app._agents_with_children == []
    assert app._agents == []

"""Authoritative report tests for the machine-capacity report feed."""

from __future__ import annotations

from sase.ace.tui.actions.agents._loading_compute import (
    PreparedApplyData,
    PreparedApplySelectionInputs,
    PreparedApplySnapshot,
    prepare_loaded_agents_apply_boundary,
)
from sase.ace.tui.actions.agents._loading_filter import AgentLoadingFilterMixin
from sase.ace.tui.models.agent_runner_slots import refresh_runner_slot_context
from tests.ace.tui._machine_capacity_report_feed_helpers import make_agent, make_report


def test_authoritative_report_drives_header_and_waiter_context_without_roster() -> None:
    waiter = make_agent(
        "filtered-waiter",
        slot_requested_at="2026-10-27T10:00:00Z",
        artifacts_dir="/tmp/project/artifacts/waiter",
    )
    raw = make_report(
        waiters=(
            {
                "artifact_dir": waiter.artifacts_dir,
                "queue_position": 3,
                "slot_requested_at": "2026-10-27T10:00:00Z",
                "requested_weight": 1.0,
                "priority": 0,
                "eligible": False,
                "admission_limit": 4.0,
                "blockers": [{"code": "insufficient-capacity"}],
            },
        )
    )

    capacity = refresh_runner_slot_context(
        [waiter],
        raw_snapshot=raw.raw_snapshot,
        report=raw,
    )
    filtered = refresh_runner_slot_context(
        [],
        raw_snapshot=raw.raw_snapshot,
        report=raw,
    )

    assert capacity.source == "authoritative"
    assert capacity.occupied_capacity == 5.0
    assert capacity.slots_in_use == 6
    assert capacity.occupied_capacity == filtered.occupied_capacity
    assert capacity.holders[0].label == "verify-monitor"
    assert any(
        holder.label == "wait-monitor" and holder.weight == 0
        for holder in capacity.holders
    )
    assert waiter.status == "QUEUED"
    assert waiter.runner_slot_queue_position == 3
    assert waiter.runner_capacity_blockers == ({"code": "insufficient-capacity"},)


def test_each_roster_apply_uses_the_latest_report_and_keeps_an_estimate_witness() -> (
    None
):
    waiter = make_agent(
        "filtered-waiter",
        slot_requested_at="2026-10-27T10:00:00Z",
        artifacts_dir="/tmp/project/artifacts/waiter",
    )
    report = make_report(
        waiters=(
            {
                "artifact_dir": waiter.artifacts_dir,
                "queue_position": 2,
                "slot_requested_at": "2026-10-27T10:00:00Z",
                "requested_weight": 1.0,
                "priority": 0,
                "eligible": False,
                "admission_limit": 4.0,
                "blockers": [{"code": "insufficient-capacity"}],
            },
        )
    )
    prep = PreparedApplyData(
        filtered_agents=[waiter],
        has_always_visible=True,
        hidden_count=0,
        hideable_agents=[waiter],
        dismissed_agent_objects=[],
        capacity_agents=[waiter],
    )
    snapshot = PreparedApplySnapshot(
        cached_agents_with_children=[],
        dismissed_agents=set(),
        agents_seen_complete_history=False,
        hide_non_run_agents=False,
        load_state=None,
        fold_levels={},
        selection=PreparedApplySelectionInputs(
            on_agents_tab=False,
            selected_identity=None,
            prior_visual_row=None,
        ),
        capacity_report=report,
    )

    boundary = prepare_loaded_agents_apply_boundary(
        prep,
        snapshot,
        merge_incomplete=False,
        effective_runner_limit=8,
        graphs_owned=True,
    )

    assert boundary.runner_capacity.source == "authoritative"
    assert boundary.runner_capacity.occupied_capacity == 5.0
    assert boundary.runner_capacity_estimate.source == "estimate"
    assert boundary.prep.filtered_agents[0].status == "QUEUED"
    assert boundary.prep.filtered_agents[0].runner_slot_queue_position == 2


def test_report_refresh_copies_queue_context_to_live_rows_and_patches_them() -> None:
    live = make_agent("waiter", status="WAITING")
    updated = make_agent(
        "waiter",
        status="QUEUED",
        runner_slots_in_use=6,
        runner_occupied_capacity=5.0,
        runner_effective_limit=8.0,
        runner_slot_queue_position=2,
        runner_slot_queue_size=1,
        runner_capacity_blockers=({"code": "insufficient-capacity"},),
    )

    class _App:
        current_tab = "agents"
        _agents = [live]
        _agents_with_children = [live]
        _agents_capacity_with_children = [live]
        _agents_query_result = [live]
        patched: list[object] = []

        def _try_patch_agent_row(
            self,
            row: object,
            *,
            refresh_info: bool,
            refresh_title: bool,
        ) -> bool:
            del refresh_info, refresh_title
            self.patched.append(row)
            return True

    app = _App()
    AgentLoadingFilterMixin._apply_agents_capacity_row_updates(app, [updated])

    assert live.status == "QUEUED"
    assert live.runner_slot_queue_position == 2
    assert live.runner_capacity_blockers == ({"code": "insufficient-capacity"},)
    assert app.patched == [live]

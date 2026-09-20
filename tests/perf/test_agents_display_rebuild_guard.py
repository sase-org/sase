"""Perf guards for Agents-tab display refreshes."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from sase.ace.tui.actions.agents._fleet_dispatch_launches import (
    AgentFleetDispatchLaunchMixin,
)
from sase.ace.tui.actions.agents._fleet_projection import AgentFleetProjectionMixin
from sase.ace.tui.actions.agents._loading_compute import (
    attach_finalize_plan_to_boundary,
    prepare_loaded_agents_worker_boundary,
)
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.util import trace

from tests._agents_tab_graph_isolation_helpers import (
    clan_container,
    clan_graph,
    delta_load_state,
    row_prefix,
)
from tests._agents_tab_query_helpers import FakeAgentApp
from sase.ace.tui.actions.agents._display_helpers import panel_widget_id_for_key
from tests.ace.tui._agent_display_diff_helpers import (
    _DisplayDiffApp,
    _agent,
    _display_costs,
    _widget_sel,
)


def test_unchanged_active_search_finalize_does_not_rebuild_panels(
    monkeypatch: Any,
) -> None:
    """An unchanged visible set under a stable search must stay on the patch path."""
    agent = _agent("alpha", tribe="epic", suffix="a1", status="RUNNING")
    app = _DisplayDiffApp([agent], monkeypatch)
    widget = app._widgets[_widget_sel("epic")]
    app._agent_search_query = "tribe:epic"
    app._agent_display_last_search_query = "tribe:epic"
    widget.update_list_calls = 0

    app._agents = [agent]
    app._refresh_agents_display_after_finalize(
        previous_agents=[agent],
        defer_detail=True,
    )

    assert widget.update_list_calls == 0
    assert app.full_rebuilds == 0
    assert "display_full_rebuild" not in _display_costs(app)
    assert [
        record.fallback_reason
        for record in app._agents_refresh_trace_records
        if record.fallback_reason == "active_search"
    ] == []


def test_by_status_unchanged_membership_finalize_does_not_rebuild_panels(
    monkeypatch: Any,
) -> None:
    """BY_STATUS with a stable visible set must stay on the patch path."""
    old_agent = _agent("alpha", tribe="epic", suffix="a1", status="RUNNING")
    new_agent = replace(old_agent, activity="still running")
    app = _DisplayDiffApp([old_agent], monkeypatch)
    app._grouping_mode = GroupingMode.BY_STATUS
    app._refresh_panel_widgets(jump_hints=None)
    widget = app._widgets[_widget_sel("epic")]
    app._agent_search_query = "tribe:epic"
    app._agent_display_last_search_query = "tribe:epic"
    widget.update_list_calls = 0
    app._agents_refresh_trace_records.clear()

    app._agents = [new_agent]
    app._refresh_agents_display_after_finalize(
        previous_agents=[old_agent],
        defer_detail=True,
    )

    assert widget.update_list_calls == 0
    assert app.full_rebuilds == 0
    assert "row_patch" in _display_costs(app)
    assert "display_full_rebuild" not in _display_costs(app)
    assert [
        record.fallback_reason
        for record in app._agents_refresh_trace_records
        if record.fallback_reason == "unsupported_grouping"
    ] == []


def test_by_status_live_churn_keeps_tribe_panels_on_incremental_path(
    monkeypatch: Any,
) -> None:
    """Stable BY_STATUS churn must not remount tribe panels under a live query."""
    epic = _agent("epic-worker", tribe="epic", suffix="e1", status="RUNNING")
    review = _agent("review-worker", tribe="review", suffix="r1", status="RUNNING")
    app = _DisplayDiffApp([epic, review], monkeypatch)
    app._grouping_mode = GroupingMode.BY_STATUS
    app._refresh_panel_widgets(jump_hints=None)
    app._agent_search_query = "status:RUNNING"
    app._agent_display_last_search_query = "status:RUNNING"
    epic_widget = app._widgets[_widget_sel("epic")]
    review_widget = app._widgets[_widget_sel("review")]
    epic_widget.update_list_calls = 0
    review_widget.update_list_calls = 0
    app._agents_refresh_trace_records.clear()

    previous = [epic, review]
    for tick in range(3):
        next_agents = [
            replace(previous[0], activity=f"epic tick {tick}"),
            replace(previous[1], activity=f"review tick {tick}"),
        ]
        app._agents = next_agents
        app._refresh_agents_display_after_finalize(
            previous_agents=previous,
            defer_detail=True,
        )
        previous = next_agents

    assert app._widgets[_widget_sel("epic")] is epic_widget
    assert app._widgets[_widget_sel("review")] is review_widget
    assert epic_widget.update_list_calls == 0
    assert review_widget.update_list_calls == 0
    assert epic_widget._agents[0].activity == "epic tick 2"
    assert review_widget._agents[0].activity == "review tick 2"
    assert app.full_rebuilds == 0
    costs = _display_costs(app)
    assert "row_patch" in costs
    assert "display_panel_rebuild" not in costs
    assert "display_full_rebuild" not in costs
    fallback_reasons = {
        record.fallback_reason
        for record in app._agents_refresh_trace_records
        if record.fallback_reason is not None
    }
    assert "unsupported_grouping" not in fallback_reasons
    assert "active_search" not in fallback_reasons
    assert "status_membership_change" not in fallback_reasons


def test_by_status_stable_clan_refresh_keeps_epic_panel(
    monkeypatch: Any,
) -> None:
    """Unchanged BY_STATUS clan membership must patch in place, not remount."""
    live = clan_graph()
    container = clan_container(live)
    live_prefix = row_prefix(container)
    loader = FakeAgentApp()
    loader._agents_with_children = live
    loader._agents = list(live)
    loader._agents_seen_complete_history = True
    snapshot = loader._make_prepared_apply_snapshot(
        on_agents_tab=True,
        selected_identity=container.identity,
        load_state=delta_load_state(),
    )
    boundary = prepare_loaded_agents_worker_boundary(
        [],
        [],
        set(),
        False,
        snapshot,
    )
    assert row_prefix(container) == live_prefix
    next_agents = list(boundary.fold.unfiltered_agents)

    app = _DisplayDiffApp(live, monkeypatch)
    app._grouping_mode = GroupingMode.BY_STATUS
    app._refresh_panel_widgets(jump_hints=None)
    widget = app._widgets[_widget_sel("epic")]
    app._agent_search_query = "NOT machine:apollo"
    app._agent_display_last_search_query = "NOT machine:apollo"
    widget.update_list_calls = 0
    app._agents_refresh_trace_records.clear()
    previous_widget = widget

    app._agents = next_agents
    app.current_idx = 0
    app._refresh_agents_display_after_finalize(
        previous_agents=live,
        defer_detail=True,
    )

    assert app._widgets[_widget_sel("epic")] is previous_widget
    assert widget.update_list_calls == 0
    assert app.full_rebuilds == 0
    costs = _display_costs(app)
    assert "display_full_rebuild" not in costs
    published = clan_container(next_agents)
    assert row_prefix(published) == live_prefix
    fallback_reasons = {
        record.fallback_reason
        for record in app._agents_refresh_trace_records
        if record.fallback_reason is not None
    }
    assert "unsupported_grouping" not in fallback_reasons
    assert "status_membership_change" not in fallback_reasons


def test_sibling_tribe_insert_and_remove_keeps_epic_widget_identity(
    monkeypatch: Any,
) -> None:
    """Adding/removing chop must not remount or blank the epic AgentList."""
    epic = _agent("epic-worker", tribe="epic", suffix="e1", status="RUNNING")
    review = _agent("review-worker", tribe="review", suffix="r1", status="RUNNING")
    chop = _agent("chop-worker", tribe="chop", suffix="c1", status="RUNNING")
    app = _DisplayDiffApp([epic, review], monkeypatch)
    epic_widget = app._widgets[_widget_sel("epic")]
    review_widget = app._widgets[_widget_sel("review")]
    epic_widget.update_list_calls = 0
    review_widget.update_list_calls = 0
    app._agents_refresh_trace_records.clear()
    epic_counts: list[int] = [int(getattr(epic_widget, "option_count", 0))]

    app._agents = [epic, review, chop]
    app._refresh_agents_display_after_finalize(
        previous_agents=[epic, review],
        defer_detail=True,
    )
    epic_counts.append(int(getattr(epic_widget, "option_count", 0)))

    app._agents = [epic, review]
    app._refresh_agents_display_after_finalize(
        previous_agents=[epic, review, chop],
        defer_detail=True,
    )
    epic_counts.append(int(getattr(epic_widget, "option_count", 0)))

    assert app._widgets[_widget_sel("epic")] is epic_widget
    assert app._widgets[_widget_sel("review")] is review_widget
    assert epic_widget.update_list_calls == 0
    assert review_widget.update_list_calls == 0
    assert all(count > 0 for count in epic_counts)
    assert app.full_rebuilds == 0
    costs = _display_costs(app)
    assert "display_full_rebuild" not in costs
    assert "display_panel_insert" in costs


def test_standing_query_sibling_row_remove_leaves_epic_untouched(
    monkeypatch: Any,
) -> None:
    """A standing filter plus sibling identity removal stays incremental."""
    epic = _agent("epic-worker", tribe="epic", suffix="e1", status="RUNNING")
    review_one = _agent("review-one", tribe="review", suffix="r1", status="RUNNING")
    review_two = _agent("review-two", tribe="review", suffix="r2", status="RUNNING")
    app = _DisplayDiffApp([epic, review_one, review_two], monkeypatch)
    app._grouping_mode = GroupingMode.BY_STATUS
    app._refresh_panel_widgets(jump_hints=None)
    app._agent_search_query = "NOT machine:apollo"
    app._agent_display_last_search_query = "NOT machine:apollo"
    epic_widget = app._widgets[_widget_sel("epic")]
    review_widget = app._widgets[_widget_sel("review")]
    epic_widget.update_list_calls = 0
    review_widget.update_list_calls = 0
    app._agents_refresh_trace_records.clear()

    app._agents = [epic, review_one]
    app._refresh_agents_display_after_finalize(
        previous_agents=[epic, review_one, review_two],
        defer_detail=True,
    )

    assert app._widgets[_widget_sel("epic")] is epic_widget
    assert epic_widget.update_list_calls == 0
    assert app.full_rebuilds == 0
    costs = _display_costs(app)
    assert "row_remove" in costs
    assert "display_full_rebuild" not in costs
    fallback_reasons = {
        record.fallback_reason
        for record in app._agents_refresh_trace_records
        if record.fallback_reason is not None
    }
    assert "active_search" not in fallback_reasons


def test_empty_incomplete_apply_keeps_session_sticky_epic_widget(
    monkeypatch: Any,
) -> None:
    """An emptied roster must not unmount a tribe already mounted this session."""
    epic = _agent("epic-worker", tribe="epic", suffix="e1", status="RUNNING")
    review = _agent("review-worker", tribe="review", suffix="r1", status="RUNNING")
    app = _DisplayDiffApp([epic, review], monkeypatch)
    app._agent_search_query = "NOT machine:apollo"
    app._agent_display_last_search_query = "NOT machine:apollo"
    app._remember_session_mounted_occupancy()
    epic_widget = app._widgets[_widget_sel("epic")]
    app._agents_refresh_trace_records.clear()

    app._agents = []
    app._refresh_agents_display_after_finalize(
        previous_agents=[epic, review],
        defer_detail=True,
    )

    assert app._widgets[_widget_sel("epic")] is epic_widget
    assert epic_widget in app._container.children


class _ApplyDisplayApp(
    AgentFleetProjectionMixin,
    AgentFleetDispatchLaunchMixin,
    _DisplayDiffApp,
    FakeAgentApp,
):
    """Display harness that can also drive a prepared disk apply end to end."""

    def __init__(self, agents: list[Any], monkeypatch: Any) -> None:
        FakeAgentApp.__init__(self)
        _DisplayDiffApp.__init__(self, agents, monkeypatch)
        self._agents_fleet_rows: list[Any] = []
        self._agents_dispatch_provisional_rows: dict[str, Any] = {}
        self._agents_local_with_children: list[Any] = []
        self._agents_local_visible: list[Any] = []


def test_plan_apply_with_fleet_epic_rows_keeps_epic_widget_and_panel_count(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    """A full apply that uses its finalize plan must not blank the fleet's tribe.

    The plan used to be computed over the local-only roster and installed after
    the fleet projection widened it, so an apply that survived its stale token
    republished one panel and remounted ``@epic`` on the next fleet refresh.
    """
    log = tmp_path / "trace.jsonl"
    monkeypatch.setenv("SASE_TUI_TRACE", "1")
    monkeypatch.setenv("SASE_TUI_TRACE_PATH", str(log))
    local = _agent("local-worker", tribe="tale", suffix="20260920090000")
    fleet = _agent("fleet-epic", tribe="epic", suffix="apollo:fleet-epic")
    fleet.fleet_origin_alias = "apollo"
    app = _ApplyDisplayApp([local, fleet], monkeypatch)
    app._agents_fleet_rows = [fleet]
    app._agents_with_children = [local, fleet]
    app._agents_local_with_children = [local]
    app._agents_local_visible = [local]
    epic_widget = app._widgets[_widget_sel("epic")]
    app._agents_refresh_trace_records.clear()
    assert app._panel_group.panel_keys == ["epic", "tale"]

    snapshot = app._make_prepared_apply_snapshot(
        on_agents_tab=True,
        selected_identity=local.identity,
        load_state=None,
    )
    boundary = prepare_loaded_agents_worker_boundary(
        [local], [], set(), False, snapshot
    )
    boundary = attach_finalize_plan_to_boundary(boundary, snapshot, content_index=None)
    app._apply_loaded_agents_prepared(
        boundary.prep,
        on_agents_tab=True,
        selected_identity=local.identity,
        load_state=None,
        persist_dismissed_changes=False,
        incomplete_merge_already_applied=True,
        precomputed_boundary=boundary,
        precomputed_fold_levels=snapshot.fold_levels,
    )

    trace._flush_trace_writes()
    spans = [json.loads(line) for line in log.read_text().splitlines() if line]
    (apply_span,) = [
        span
        for span in spans
        if span.get("span") == "agents.apply_loaded_agents_prepared"
    ]
    # Without this the guard would pass vacuously through the inline path.
    assert apply_span["finalize_plan"] == "applied"
    panel_spans = [
        span for span in spans if span.get("span") == "agents.refresh_panel_widgets"
    ]
    assert panel_spans
    for span in panel_spans:
        assert span["panels"] == 2
        assert span["panel_widget_ids"] == [
            panel_widget_id_for_key("epic"),
            panel_widget_id_for_key("tale"),
        ]
    assert app._panel_group.panel_keys == ["epic", "tale"]
    assert app._widgets[_widget_sel("epic")] is epic_widget
    assert epic_widget in app._container.children
    assert app.full_rebuilds == 0
    assert "display_full_rebuild" not in _display_costs(app)
    assert "display_panel_remove" not in _display_costs(app)


def test_apply_with_collapsed_epic_clan_keeps_epic_widget_and_panel_count(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    """A tribe panel made of collapsed clan containers survives every apply.

    The live regression behind the ``2 -> 1 -> 2`` panel dips: the apply folded
    the roster and then projected it, and the clan projection rebuilds a
    container only from the member rows it still sees, so a collapsed clan's
    container (and the whole ``@epic`` panel) vanished until the next fleet
    refresh rebuilt the roster.
    """
    log = tmp_path / "trace.jsonl"
    monkeypatch.setenv("SASE_TUI_TRACE", "1")
    monkeypatch.setenv("SASE_TUI_TRACE_PATH", str(log))
    graph = clan_graph()
    container = clan_container(graph)
    members = [agent for agent in graph if not agent.is_clan_container]
    fleet = _agent("fleet-review", tribe="review", suffix="apollo:fleet-review")
    fleet.fleet_origin_alias = "apollo"
    app = _ApplyDisplayApp([container, fleet], monkeypatch)
    app._agents_fleet_rows = [fleet]
    app._agents_with_children = [*graph, fleet]
    app._agents_local_with_children = list(graph)
    epic_widget = app._widgets[_widget_sel("epic")]
    app._agents_refresh_trace_records.clear()
    assert app._panel_group.panel_keys == ["epic", "review"]

    snapshot = app._make_prepared_apply_snapshot(
        on_agents_tab=True,
        selected_identity=container.identity,
        load_state=None,
    )
    boundary = prepare_loaded_agents_worker_boundary(
        members, [], set(), False, snapshot
    )
    boundary = attach_finalize_plan_to_boundary(boundary, snapshot, content_index=None)
    app._apply_loaded_agents_prepared(
        boundary.prep,
        on_agents_tab=True,
        selected_identity=container.identity,
        load_state=None,
        persist_dismissed_changes=False,
        incomplete_merge_already_applied=True,
        precomputed_boundary=boundary,
        precomputed_fold_levels=snapshot.fold_levels,
    )

    trace._flush_trace_writes()
    spans = [json.loads(line) for line in log.read_text().splitlines() if line]
    (apply_span,) = [
        span
        for span in spans
        if span.get("span") == "agents.apply_loaded_agents_prepared"
    ]
    assert apply_span["finalize_plan"] == "applied"
    panel_spans = [
        span for span in spans if span.get("span") == "agents.refresh_panel_widgets"
    ]
    assert panel_spans
    for span in panel_spans:
        assert span["panels"] == 2
        assert panel_widget_id_for_key("epic") in span["panel_widget_ids"]
    assert clan_container(app._agents).identity == container.identity
    assert app._widgets[_widget_sel("epic")] is epic_widget
    assert epic_widget in app._container.children
    assert app.full_rebuilds == 0
    assert "display_panel_remove" not in _display_costs(app)

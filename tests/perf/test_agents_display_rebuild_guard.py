"""Perf guards for Agents-tab display refreshes."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from sase.ace.tui.actions.agents._loading_compute import (
    prepare_loaded_agents_worker_boundary,
)
from sase.ace.tui.models.agent_groups import GroupingMode

from tests._agents_tab_graph_isolation_helpers import (
    clan_container,
    clan_graph,
    delta_load_state,
    row_prefix,
)
from tests._agents_tab_query_helpers import FakeAgentApp
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

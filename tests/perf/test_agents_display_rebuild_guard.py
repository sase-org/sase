"""Perf guards for Agents-tab display refreshes."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from sase.ace.tui.models.agent_groups import GroupingMode

from tests.ace.tui._agent_display_diff_helpers import (
    _DisplayDiffApp,
    _agent,
    _display_costs,
)


def test_unchanged_active_search_finalize_does_not_rebuild_panels(
    monkeypatch: Any,
) -> None:
    """An unchanged visible set under a stable search must stay on the patch path."""
    agent = _agent("alpha", tribe="epic", suffix="a1", status="RUNNING")
    app = _DisplayDiffApp([agent], monkeypatch)
    widget = app._widgets["#agent-list-panel"]
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
    widget = app._widgets["#agent-list-panel"]
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

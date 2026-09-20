"""Collapsed panels record the grouping mode they painted under."""

from __future__ import annotations

from typing import Any

from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.widgets.agent_list import AgentList

from ._agent_display_diff_helpers import (
    _DisplayDiffApp,
    _agent,
    _display_costs,
    _widget_sel,
)


def _three_panel_by_status_app(monkeypatch: Any) -> tuple[_DisplayDiffApp, list[Any]]:
    """Two expanded panels plus a collapsed ``job`` panel under BY_STATUS."""
    agents = [
        _agent("default-one", tribe=None, suffix="d1"),
        _agent("epic-one", tribe="epic", suffix="e1"),
        _agent("job-one", tribe="job", suffix="j1"),
    ]
    app = _DisplayDiffApp(agents, monkeypatch, collapsed_panel_keys={"job"})
    app._grouping_mode = GroupingMode.BY_STATUS
    app._refresh_panel_widgets(jump_hints=None)
    return app, agents


def _fallbacks(app: _DisplayDiffApp) -> list[str | None]:
    return [record.fallback_reason for record in app._agents_refresh_trace_records]


def _refresh(app: _DisplayDiffApp, previous: list[Any], current: list[Any]) -> None:
    app._agents_refresh_trace_records.clear()
    app._agents = current
    app._refresh_agents_display_after_finalize(
        previous_agents=previous,
        defer_detail=True,
    )


def test_collapsed_panel_records_grouping_mode(monkeypatch: Any) -> None:
    app, _agents = _three_panel_by_status_app(monkeypatch)
    job = app._widgets[_widget_sel("job")]

    assert job._panel_collapsed is True
    assert job._grouping_mode is GroupingMode.BY_STATUS
    assert app._agent_display_widgets_match_grouping_mode() is True


def test_collapsed_sibling_keeps_changed_apply_incremental(monkeypatch: Any) -> None:
    app, agents = _three_panel_by_status_app(monkeypatch)
    added = _agent("epic-two", tribe="epic", suffix="e2")

    _refresh(app, agents, [*agents, added])

    assert "stale_grouping_mode" not in _fallbacks(app)
    assert "display_full_rebuild" not in _display_costs(app)
    assert app.full_rebuilds == 0


def test_collapsed_sibling_keeps_unchanged_apply_incremental(monkeypatch: Any) -> None:
    app, agents = _three_panel_by_status_app(monkeypatch)

    _refresh(app, agents, list(agents))

    assert "stale_grouping_mode" not in _fallbacks(app)
    assert "display_full_rebuild" not in _display_costs(app)
    assert app.full_rebuilds == 0


def test_unchanged_apply_repaints_no_panel(monkeypatch: Any) -> None:
    app, agents = _three_panel_by_status_app(monkeypatch)
    widgets = list(app._container.children)
    del agents
    collapse_calls = 0
    original = AgentList.render_collapsed

    def counted(self: AgentList, *, grouping_mode: GroupingMode) -> None:
        nonlocal collapse_calls
        collapse_calls += 1
        original(self, grouping_mode=grouping_mode)

    monkeypatch.setattr(AgentList, "render_collapsed", counted)
    before = {w.id: w.update_list_calls for w in widgets}

    app._refresh_panel_widgets(jump_hints=None)

    assert collapse_calls == 0
    assert {w.id: w.update_list_calls for w in widgets} == before


def test_grouping_cycle_with_collapsed_panel_still_forces_rebuild(
    monkeypatch: Any,
) -> None:
    app, _agents = _three_panel_by_status_app(monkeypatch)

    app._grouping_mode = GroupingMode.STANDARD

    # The expanded panels still hold BY_STATUS banners, so the guard must fail.
    assert app._agent_display_widgets_match_grouping_mode() is False


def test_collapsed_panel_that_expands_paints_under_current_mode(
    monkeypatch: Any,
) -> None:
    app, agents = _three_panel_by_status_app(monkeypatch)
    job = app._widgets[_widget_sel("job")]

    app._collapsed_panel_keys.clear()
    app._expanded_panel_keys = {"job"}
    app._refresh_panel_widgets(jump_hints=None)

    assert job._panel_collapsed is False
    assert job._grouping_mode is GroupingMode.BY_STATUS
    assert job.option_count > 0
    assert app._agent_display_widgets_match_grouping_mode() is True
    del agents


def test_render_collapsed_stores_grouping_mode_on_real_widget() -> None:
    widget = AgentList()

    widget.render_collapsed(grouping_mode=GroupingMode.BY_MACHINE)

    assert widget._panel_collapsed is True
    assert widget._grouping_mode is GroupingMode.BY_MACHINE
    assert widget.option_count == 0

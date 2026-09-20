"""In-place row insert on the Agents-tab incremental display path (sase-142)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from sase.ace.tui.models.agent_groups import GroupingMode

from ._agent_display_diff_helpers import (
    _DisplayDiffApp,
    _agent,
    _display_costs,
    _widget_sel,
)


def _by_status_app(agents: list[Any], monkeypatch: Any) -> _DisplayDiffApp:
    """Return an app whose panels are painted under ``BY_STATUS``, as on the host."""
    app = _DisplayDiffApp(agents, monkeypatch)
    app._grouping_mode = GroupingMode.BY_STATUS
    app._refresh_panel_widgets(jump_hints=None)
    app._agents_refresh_trace_records.clear()
    return app


def _apply(app: _DisplayDiffApp, previous: list[Any], current: list[Any]) -> None:
    app._agents = list(current)
    app._refresh_agents_display_after_finalize(
        previous_agents=list(previous), defer_detail=True
    )


def _fallbacks(app: _DisplayDiffApp) -> list[str | None]:
    return [record.fallback_reason for record in app._agents_refresh_trace_records]


def test_a_plain_node_joining_a_panel_is_inserted_in_place(monkeypatch: Any) -> None:
    one = _agent("apple-one", tribe="apple", suffix="a1")
    two = _agent("apple-two", tribe="apple", suffix="a2")
    arrival = _agent("apple-six", tribe="apple", suffix="a3")
    app = _by_status_app([one, two], monkeypatch)
    widget = app._widgets[_widget_sel("apple")]
    repaints = widget.update_list_calls
    rows = widget.option_count

    _apply(app, [one, two], [one, two, arrival])

    assert widget.update_list_calls == repaints  # not cleared and re-emitted
    assert widget.option_count == rows + 1
    assert [agent.identity for agent in widget._agents] == [
        one.identity,
        two.identity,
        arrival.identity,
    ]
    assert app.full_rebuilds == 0
    costs = _display_costs(app)
    assert "display_row_insert" in costs
    assert "display_panel_rebuild" not in costs
    assert "display_full_rebuild" not in costs
    assert not any(_fallbacks(app))


def test_a_panel_beside_the_arrival_is_left_alone(monkeypatch: Any) -> None:
    apple = _agent("apple-one", tribe="apple", suffix="a1")
    banana = _agent("banana-one", tribe="banana", suffix="b1")
    arrival = _agent("apple-two", tribe="apple", suffix="a2")
    app = _by_status_app([apple, banana], monkeypatch)
    banana_widget = app._widgets[_widget_sel("banana")]
    banana_repaints = banana_widget.update_list_calls

    _apply(app, [apple, banana], [apple, arrival, banana])

    assert banana_widget.update_list_calls == banana_repaints
    assert "display_row_insert" in _display_costs(app)


def test_a_starting_node_that_becomes_rendered_joins_without_a_full_rebuild(
    monkeypatch: Any,
) -> None:
    one = _agent("apple-one", tribe="apple", suffix="a1")
    starting = _agent("apple-two", tribe="apple", suffix="a2", status="STARTING")
    app = _by_status_app([one, starting], monkeypatch)
    widget = app._widgets[_widget_sel("apple")]
    repaints = widget.update_list_calls

    # A STARTING row is not rendered, so its status change to RUNNING moves no
    # row on screen: it is an arrival, not a status-bucket move.
    _apply(app, [one, starting], [one, replace(starting, status="RUNNING")])

    assert widget.update_list_calls == repaints
    assert widget.option_count == 3  # the Running banner and two rows
    assert app.full_rebuilds == 0
    assert "status_membership_change" not in _fallbacks(app)
    assert "display_row_insert" in _display_costs(app)
    assert "display_full_rebuild" not in _display_costs(app)


def test_a_rendered_row_changing_bucket_still_forces_a_full_rebuild(
    monkeypatch: Any,
) -> None:
    running = _agent("apple-one", tribe="apple", suffix="a1")
    other = _agent("apple-two", tribe="apple", suffix="a2")
    app = _by_status_app([running, other], monkeypatch)

    _apply(app, [running, other], [replace(running, status="DONE"), other])

    assert app.full_rebuilds == 1
    assert "status_membership_change" in _fallbacks(app)
    assert "display_full_rebuild" in _display_costs(app)


def test_an_arrival_that_cannot_be_inserted_records_why_and_rebuilds_its_panel(
    monkeypatch: Any,
) -> None:
    one = _agent("apple-one", tribe="apple", suffix="a1")
    wide = _agent("apple-with-a-much-longer-name", tribe="apple", suffix="a2")
    app = _by_status_app([one], monkeypatch)
    widget = app._widgets[_widget_sel("apple")]
    repaints = widget.update_list_calls

    _apply(app, [one], [one, wide])

    assert widget.update_list_calls == repaints + 1
    assert app.full_rebuilds == 0
    attempts = [
        record
        for record in app._agents_refresh_trace_records
        if record.display_cost == "display_row_insert"
    ]
    assert [record.fallback_reason for record in attempts] == ["width_growth"]
    assert "display_panel_rebuild" in _display_costs(app)


def test_only_the_incremental_apply_path_attempts_inserts(monkeypatch: Any) -> None:
    one = _agent("apple-one", tribe="apple", suffix="a1")
    arrival = _agent("apple-two", tribe="apple", suffix="a2")
    app = _by_status_app([one], monkeypatch)
    widget = app._widgets[_widget_sel("apple")]
    repaints = widget.update_list_calls

    # Fold, hint, and full-refresh callers keep their rebuild semantics.
    app._agents = [one, arrival]
    app._sync_panel_group()
    assert app._refresh_affected_panel_widgets({"apple"})

    assert widget.update_list_calls == repaints + 1
    assert "display_row_insert" not in _display_costs(app)

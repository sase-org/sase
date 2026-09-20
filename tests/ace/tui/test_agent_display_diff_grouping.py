"""Grouping-mode refresh paths for finalized Agents-tab display diffs."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any

from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_groups import GroupingMode

from ._agent_display_diff_helpers import (
    _DisplayDiffApp,
    _agent,
    _apply_roster,
    _display_costs,
    _panel_attributions,
    _panel_id,
    _panel_rows,
    _rebuild_scope,
    _widget_sel,
)


def _by_status_app(agents: list[Agent], monkeypatch: Any) -> _DisplayDiffApp:
    """Build a single-panel app rendered under the BY_STATUS bucket tree."""
    app = _DisplayDiffApp(agents, monkeypatch)
    app._grouping_mode = GroupingMode.BY_STATUS
    # Re-render so the widgets carry the BY_STATUS status-bucket tree (and the
    # per-row patch context the row-patch path reads).
    app._refresh_panel_widgets(jump_hints=None)
    app._agents_refresh_trace_records.clear()
    return app


def _by_machine_app(agents: list[Agent], monkeypatch: Any) -> _DisplayDiffApp:
    """Build a single-panel app rendered under the BY_MACHINE bucket tree."""
    app = _DisplayDiffApp(agents, monkeypatch)
    app._grouping_mode = GroupingMode.BY_MACHINE
    app._refresh_panel_widgets(jump_hints=None)
    return app


def _clan_projection(status: str) -> list[Agent]:
    member = _agent("research.member", tribe=None, suffix="member", status=status)
    member.agent_clan = "research"
    member.agent_clan_generation = "20260718120000"
    return project_clan_tree([member])


def test_standard_clan_status_bucket_change_rebuilds_instead_of_patching(
    monkeypatch: Any,
) -> None:
    previous_agents = _clan_projection("RUNNING")
    next_agents = _clan_projection("DONE")
    app = _DisplayDiffApp(previous_agents, monkeypatch)
    app._agents_refresh_trace_records.clear()

    app._agents = next_agents
    app._refresh_agents_display_after_finalize(
        previous_agents=previous_agents,
        defer_detail=True,
    )

    assert app.full_rebuilds == 1
    assert any(
        record.fallback_reason == "clan_member_order_change"
        for record in app._agents_refresh_trace_records
    )
    assert "display_full_rebuild" in _display_costs(app)


def test_standard_clan_badge_only_change_patches_in_place(monkeypatch: Any) -> None:
    projected = _clan_projection("RUNNING")
    app = _DisplayDiffApp(projected, monkeypatch)
    app._agents_refresh_trace_records.clear()
    member = projected[1]

    member.live_file_change_hint = True

    assert app._try_patch_agent_row(member) is True
    assert app.full_rebuilds == 0
    assert app._agents_refresh_trace_records[-1].fallback_reason is None
    assert "row_patch" in _display_costs(app)


def test_by_status_badge_only_change_patches_in_place(monkeypatch: Any) -> None:
    # Regression: a deferred live-hint pencil on a redirected Plan row used to
    # wait for the next full rebuild because BY_STATUS vetoed every row patch.
    agent = _agent("alpha", tribe=None, suffix="a1", status="RUNNING")
    app = _by_status_app([agent], monkeypatch)
    app._agents_refresh_trace_records.clear()

    # Badge-only live-hint flip on the same row keeps it in the Running bucket.
    agent.live_file_change_hint = True
    assert app._try_patch_agent_row(agent) is True

    assert app.full_rebuilds == 0
    costs = _display_costs(app)
    assert "row_patch" in costs
    assert "display_full_rebuild" not in costs
    assert app._agents_refresh_trace_records[-1].fallback_reason is None


def test_by_status_finalize_same_bucket_change_patches_incrementally(
    monkeypatch: Any,
) -> None:
    old_agent = _agent("alpha", tribe=None, suffix="a1", status="RUNNING")
    new_agent = replace(old_agent, activity="still running")
    app = _by_status_app([old_agent], monkeypatch)
    widget = app._widgets["#agent-list-panel"]
    widget.update_list_calls = 0
    app._agents_refresh_trace_records.clear()

    app._agents = [new_agent]
    app._refresh_agents_display_after_finalize(
        previous_agents=[old_agent],
        defer_detail=True,
    )

    assert widget.update_list_calls == 0
    assert widget._agents[0].activity == "still running"
    assert app.full_rebuilds == 0
    costs = _display_costs(app)
    assert "row_patch" in costs
    assert "display_full_rebuild" not in costs
    assert [
        record.fallback_reason
        for record in app._agents_refresh_trace_records
        if record.fallback_reason == "unsupported_grouping"
    ] == []


def test_by_status_finalize_bucket_move_uses_status_membership_fallback(
    monkeypatch: Any,
) -> None:
    old_agent = _agent("alpha", tribe=None, suffix="a1", status="RUNNING")
    new_agent = replace(old_agent, status="DONE")
    app = _by_status_app([old_agent], monkeypatch)
    app._agents_refresh_trace_records.clear()

    app._agents = [new_agent]
    app._refresh_agents_display_after_finalize(
        previous_agents=[old_agent],
        defer_detail=True,
    )

    assert app.full_rebuilds == 0
    assert _panel_attributions(app) == [
        ("agent-list-panel", "status_membership_change")
    ]
    assert "display_panel_rebuild" in _display_costs(app)
    assert "display_full_rebuild" not in _display_costs(app)


def test_by_status_finalize_bucket_appearance_uses_status_membership_fallback(
    monkeypatch: Any,
) -> None:
    running = _agent("alpha", tribe=None, suffix="a1", status="RUNNING")
    done = _agent("beta", tribe=None, suffix="b1", status="DONE")
    app = _by_status_app([running], monkeypatch)
    app._agents_refresh_trace_records.clear()

    app._agents = [running, done]
    app._refresh_agents_display_after_finalize(
        previous_agents=[running],
        defer_detail=True,
    )

    assert app.full_rebuilds == 0
    assert _panel_attributions(app) == [
        ("agent-list-panel", "status_membership_change")
    ]
    assert "display_panel_rebuild" in _display_costs(app)
    assert "display_full_rebuild" not in _display_costs(app)


def test_by_status_finalize_subgroup_collapse_uses_status_membership_fallback(
    monkeypatch: Any,
) -> None:
    first = _agent("alpha.one", tribe=None, suffix="a1", status="RUNNING")
    second = _agent("alpha.two", tribe=None, suffix="a2", status="RUNNING")
    app = _by_status_app([first, second], monkeypatch)
    app._agents_refresh_trace_records.clear()

    app._agents = [first]
    app._refresh_agents_display_after_finalize(
        previous_agents=[first, second],
        defer_detail=True,
    )

    assert app.full_rebuilds == 0
    assert _panel_attributions(app) == [
        ("agent-list-panel", "status_membership_change")
    ]
    assert "display_panel_rebuild" in _display_costs(app)
    assert "display_full_rebuild" not in _display_costs(app)


def test_by_status_status_bucket_move_refuses_row_patch(monkeypatch: Any) -> None:
    old_agent = _agent("alpha", tribe=None, suffix="a1", status="RUNNING")
    app = _by_status_app([old_agent], monkeypatch)
    app._agents_refresh_trace_records.clear()

    new_agent = replace(old_agent, status="DONE")
    app._agents = [new_agent]

    # Running -> Done crosses status buckets, so the in-place patch must refuse
    # and leave the caller to rebuild the affected panel.
    assert app._try_patch_agent_row(new_agent) is False
    assert app._agents_refresh_trace_records[-1].fallback_reason == (
        "status_membership_change"
    )


def test_by_status_launch_anchor_change_refuses_row_patch(monkeypatch: Any) -> None:
    old_agent = _agent("alpha", tribe=None, suffix="a1", status="RUNNING")
    app = _by_status_app([old_agent], monkeypatch)
    app._agents_refresh_trace_records.clear()

    new_agent = replace(
        old_agent,
        start_time=datetime(2026, 6, 8, 12, 1, 0),
    )
    app._agents = [new_agent]

    assert app._try_patch_agent_row(new_agent) is False
    assert app._agents_refresh_trace_records[-1].fallback_reason == (
        "status_membership_change"
    )


def test_by_machine_status_bucket_move_refuses_row_patch(monkeypatch: Any) -> None:
    # A status-bucket crossing change (Running -> Done) moves the row to a
    # different status subgroup, so the strengthened machine_grouping_signature
    # must force a rebuild rather than patch the stale-positioned row in place.
    old_agent = _agent("alpha", tribe=None, suffix="a1", status="RUNNING")
    old_agent.fleet_origin_alias = "apollo"
    new_agent = replace(old_agent, status="DONE")
    app = _by_machine_app([old_agent], monkeypatch)
    app._agents_refresh_trace_records.clear()

    app._agents = [new_agent]

    assert app._try_patch_agent_row(new_agent) is False
    assert app._agents_refresh_trace_records[-1].fallback_reason == (
        "status_membership_change"
    )


def test_by_machine_badge_only_change_patches_in_place(monkeypatch: Any) -> None:
    # A same-bucket, badge-only change (e.g. a deferred live-hint pencil)
    # leaves every machine_grouping_signature field unchanged, so it still
    # patches in place.
    old_agent = _agent("alpha", tribe=None, suffix="a1", status="RUNNING")
    old_agent.fleet_origin_alias = "apollo"
    app = _by_machine_app([old_agent], monkeypatch)
    app._agents_refresh_trace_records.clear()

    old_agent.live_file_change_hint = True
    assert app._try_patch_agent_row(old_agent) is True

    assert app.full_rebuilds == 0
    assert "row_patch" in _display_costs(app)
    assert "display_full_rebuild" not in _display_costs(app)
    assert app._agents_refresh_trace_records[-1].fallback_reason is None


def test_by_machine_origin_move_refuses_row_patch(monkeypatch: Any) -> None:
    old_agent = _agent("alpha", tribe=None, suffix="a1", status="RUNNING")
    old_agent.fleet_origin_alias = "apollo"
    app = _by_machine_app([old_agent], monkeypatch)
    app._agents_refresh_trace_records.clear()

    new_agent = replace(old_agent)
    new_agent.fleet_origin_alias = "zeus"
    app._agents = [new_agent]

    assert app._try_patch_agent_row(new_agent) is False
    assert app._agents_refresh_trace_records[-1].fallback_reason == (
        "status_membership_change"
    )


def test_stale_widget_grouping_mode_falls_back_to_full_rebuild(
    monkeypatch: Any,
) -> None:
    # Reproduces the BY_STATUS -> STANDARD ("by project") cycle: app state
    # advances to STANDARD while the rendered widgets still hold the previous
    # mode's status-bucket tree. Patching those rows in place would leave the
    # stale banners on screen, so the incremental path must defer to a full
    # rebuild instead.
    agent = _agent("alpha", tribe=None, suffix="a1", status="RUNNING")
    app = _DisplayDiffApp([agent], monkeypatch)
    for widget in app._container.children:
        widget._grouping_mode = GroupingMode.BY_STATUS

    assert app._grouping_mode is GroupingMode.STANDARD

    app._agents = [agent]
    app._refresh_agents_display_after_finalize(
        previous_agents=[agent],
        defer_detail=True,
    )

    assert app.full_rebuilds == 1
    assert app._agents_refresh_trace_records[0].fallback_reason == (
        "stale_grouping_mode"
    )
    assert "display_full_rebuild" in _display_costs(app)


# --- panel-scoped rebuilds: only the panel a change concerns is rebuilt ---


def test_a_bucket_move_in_one_panel_leaves_a_sibling_with_no_change_alone(
    monkeypatch: Any,
) -> None:
    apple = _agent("apple-one", tribe="apple", suffix="a1")
    apple_two = _agent("apple-two", tribe="apple", suffix="a2")
    banana = _agent("banana-one", tribe="banana", suffix="b1")
    app = _by_status_app([apple, apple_two, banana], monkeypatch)
    apple_widget = app._widgets[_widget_sel("apple")]
    banana_widget = app._widgets[_widget_sel("banana")]
    apple_repaints = apple_widget.update_list_calls
    banana_repaints = banana_widget.update_list_calls
    banana_rows = banana_widget.option_count

    _apply_roster(
        app,
        [apple, apple_two, banana],
        [replace(apple, status="DONE"), apple_two, banana],
    )

    assert app.full_rebuilds == 0
    assert apple_widget.update_list_calls == apple_repaints + 1
    assert banana_widget.update_list_calls == banana_repaints
    assert banana_widget.option_count == banana_rows
    assert _panel_attributions(app) == [
        (_panel_id("apple"), "status_membership_change")
    ]
    costs = _display_costs(app)
    assert "display_panel_rebuild" in costs
    assert "display_full_rebuild" not in costs


def test_a_bucket_move_beside_a_cosmetic_change_patches_the_sibling_in_place(
    monkeypatch: Any,
) -> None:
    apple = _agent("apple-one", tribe="apple", suffix="a1")
    banana = _agent("banana-one", tribe="banana", suffix="b1")
    app = _by_status_app([apple, banana], monkeypatch)
    banana_widget = app._widgets[_widget_sel("banana")]
    banana_repaints = banana_widget.update_list_calls

    _apply_roster(
        app,
        [apple, banana],
        [replace(apple, status="DONE"), replace(banana, activity="still going")],
    )

    # Before scoping, the whole-roster rebuild repainted the sibling whose row
    # only changed cosmetically; now that row is patched in place.
    assert banana_widget.update_list_calls == banana_repaints
    assert banana_widget._agents[0].activity == "still going"
    costs = _display_costs(app)
    assert "row_patch" in costs
    assert "display_full_rebuild" not in costs
    assert _panel_attributions(app) == [
        (_panel_id("apple"), "status_membership_change")
    ]


def test_a_new_status_bucket_in_one_panel_does_not_name_its_siblings(
    monkeypatch: Any,
) -> None:
    apple = _agent("apple-one", tribe="apple", suffix="a1")
    banana = _agent("banana-one", tribe="banana", suffix="b1")
    arrival = _agent("apple-two", tribe="apple", suffix="a2", status="DONE")
    app = _by_status_app([apple, banana], monkeypatch)
    banana_widget = app._widgets[_widget_sel("banana")]
    banana_repaints = banana_widget.update_list_calls

    _apply_roster(app, [apple, banana], [apple, arrival, banana])

    assert banana_widget.update_list_calls == banana_repaints
    assert _panel_rows(app, "apple") == [apple.identity, arrival.identity]
    assert _panel_attributions(app) == [
        (_panel_id("apple"), "status_membership_change")
    ]
    assert "display_full_rebuild" not in _display_costs(app)


def test_a_bucket_move_in_each_of_two_panels_names_both(monkeypatch: Any) -> None:
    apple = _agent("apple-one", tribe="apple", suffix="a1")
    banana = _agent("banana-one", tribe="banana", suffix="b1")
    cherry = _agent("cherry-one", tribe="cherry", suffix="c1")
    app = _by_status_app([apple, banana, cherry], monkeypatch)
    cherry_widget = app._widgets[_widget_sel("cherry")]
    cherry_repaints = cherry_widget.update_list_calls

    _apply_roster(
        app,
        [apple, banana, cherry],
        [replace(apple, status="DONE"), replace(banana, status="FAILED"), cherry],
    )

    assert cherry_widget.update_list_calls == cherry_repaints
    assert _panel_attributions(app) == [
        (_panel_id("apple"), "status_membership_change"),
        (_panel_id("banana"), "status_membership_change"),
    ]


def test_a_removal_that_drops_a_bucket_rebuilds_only_the_panel_that_lost_it(
    monkeypatch: Any,
) -> None:
    running = _agent("apple-one", tribe="apple", suffix="a1")
    done = _agent("apple-two", tribe="apple", suffix="a2", status="DONE")
    banana = _agent("banana-one", tribe="banana", suffix="b1")
    app = _by_status_app([running, done, banana], monkeypatch)
    apple_widget = app._widgets[_widget_sel("apple")]
    banana_widget = app._widgets[_widget_sel("banana")]
    apple_repaints = apple_widget.update_list_calls
    banana_repaints = banana_widget.update_list_calls

    _apply_roster(app, [running, done, banana], [running, banana])

    # The Done bucket's banner disappears, so the panel is rebuilt from its new
    # slice rather than having its rows removed in place.
    assert app.full_rebuilds == 0
    assert apple_widget.update_list_calls == apple_repaints + 1
    assert banana_widget.update_list_calls == banana_repaints
    assert _panel_rows(app, "apple") == [running.identity]
    assert _panel_attributions(app) == [
        (_panel_id("apple"), "status_membership_change")
    ]
    assert "row_remove" not in _display_costs(app)


def test_a_removal_that_keeps_every_bucket_still_removes_rows_in_place(
    monkeypatch: Any,
) -> None:
    one = _agent("apple-one", tribe="apple", suffix="a1")
    two = _agent("apple-two", tribe="apple", suffix="a2")
    banana = _agent("banana-one", tribe="banana", suffix="b1")
    app = _by_status_app([one, two, banana], monkeypatch)
    apple_widget = app._widgets[_widget_sel("apple")]
    repaints = apple_widget.update_list_calls

    _apply_roster(app, [one, two, banana], [one, banana])

    assert apple_widget.update_list_calls == repaints
    assert _panel_rows(app, "apple") == [one.identity]
    assert _panel_attributions(app) == []
    assert "row_remove" in _display_costs(app)


def test_by_status_attribution_is_skipped_for_other_grouping_modes() -> None:
    apple = _agent("apple-one", tribe="apple", suffix="a1")

    moved = _rebuild_scope([apple], [replace(apple, status="DONE")], by_status=False)
    by_status = _rebuild_scope([apple], [replace(apple, status="DONE")], by_status=True)

    assert moved.reasons == ()
    assert by_status.reasons == (("apple", "status_membership_change"),)


def test_a_starting_node_becoming_rendered_is_an_arrival_not_a_bucket_move() -> None:
    apple = _agent("apple-one", tribe="apple", suffix="a1")
    starting = _agent("apple-two", tribe="apple", suffix="a2", status="STARTING")

    scope = _rebuild_scope(
        [apple, starting], [apple, replace(starting, status="RUNNING")], by_status=True
    )

    assert scope.reasons == ()


def test_removed_identities_in_a_rebuilt_panel_need_no_in_place_removal() -> None:
    running = _agent("apple-one", tribe="apple", suffix="a1")
    done = _agent("apple-two", tribe="apple", suffix="a2", status="DONE")
    banana = _agent("banana-one", tribe="banana", suffix="b1")
    banana_two = _agent("banana-two", tribe="banana", suffix="b2")

    scope = _rebuild_scope(
        [running, done, banana, banana_two], [running, banana], by_status=True
    )

    assert scope.keys == {"apple"}
    assert scope.rebuilt_removals == {done.identity}

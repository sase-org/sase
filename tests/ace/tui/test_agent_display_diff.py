"""Panel refresh paths for finalized Agents-tab display diffs."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from rich.text import Text

from ._agent_display_diff_helpers import (
    _DisplayDiffApp,
    _agent,
    _display_costs,
    _rebuild_scope,
    _widget_sel,
    _workflow_agent,
)


def test_same_position_row_change_patches_without_panel_rebuild(
    monkeypatch: Any,
) -> None:
    old_agent = _agent("alpha", tribe="apple", suffix="a1", status="RUNNING")
    new_agent = replace(old_agent, status="DONE")
    app = _DisplayDiffApp([old_agent], monkeypatch)
    widget = app._widgets[_widget_sel("apple")]

    app._agents = [new_agent]
    app._refresh_agents_display_after_finalize(
        previous_agents=[old_agent],
        defer_detail=True,
    )

    assert widget.update_list_calls == 1
    assert widget._agents[0].status == "DONE"
    assert app.full_rebuilds == 0
    assert "row_patch" in _display_costs(app)
    assert "display_full_rebuild" not in _display_costs(app)
    assert app._agent_detail_debouncer.is_pending


def test_full_refresh_repaints_panel_when_row_content_changes_under_same_identity(
    monkeypatch: Any,
) -> None:
    old_agent = _agent("alpha", tribe="apple", suffix="a1", status="RUNNING")
    new_agent = replace(old_agent, status="DONE")
    assert new_agent.identity == old_agent.identity
    app = _DisplayDiffApp([old_agent], monkeypatch)
    widget = app._widgets[_widget_sel("apple")]

    app._agents = [new_agent]
    app._refresh_panel_widgets(jump_hints=None)

    assert widget.update_list_calls == 2
    assert widget._agents[0].status == "DONE"


def test_full_refresh_repaints_panel_only_when_jump_hints_change(
    monkeypatch: Any,
) -> None:
    agent = _agent("alpha", tribe="apple", suffix="a1", status="RUNNING")
    app = _DisplayDiffApp([agent], monkeypatch)
    widget = app._widgets[_widget_sel("apple")]

    app._refresh_panel_widgets(jump_hints=None)
    assert widget.update_list_calls == 1

    app._refresh_panel_widgets(jump_hints={0: "a"})
    assert widget.update_list_calls == 2
    app._refresh_panel_widgets(jump_hints={0: "a"})
    assert widget.update_list_calls == 2

    app._refresh_panel_widgets(jump_hints=None)
    assert widget.update_list_calls == 3


def test_incremental_row_patch_batch_refreshes_info_panel_once(
    monkeypatch: Any,
) -> None:
    first = _agent("alpha", tribe="apple", suffix="a1", status="RUNNING")
    second = _agent("beta", tribe="apple", suffix="b1", status="RUNNING")
    updated_first = replace(first, status="DONE")
    updated_second = replace(second, status="FAILED")
    app = _DisplayDiffApp([first, second], monkeypatch)
    app.info_updates = 0

    app._agents = [updated_first, updated_second]
    app._refresh_agents_display_after_finalize(
        previous_agents=[first, second],
        defer_detail=True,
    )

    assert app.info_updates == 1
    assert app.full_rebuilds == 0
    assert _display_costs(app).count("row_patch") == 2


def test_unchanged_active_search_uses_incremental_without_panel_rebuild(
    monkeypatch: Any,
) -> None:
    agent = _agent("alpha", tribe="apple", suffix="a1", status="RUNNING")
    app = _DisplayDiffApp([agent], monkeypatch)
    widget = app._widgets[_widget_sel("apple")]
    app._agent_search_query = "status:RUNNING"
    app._agent_display_last_search_query = "status:RUNNING"
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
    assert app._agent_display_last_search_query == "status:RUNNING"


def test_changed_active_search_query_falls_back_to_full_rebuild(
    monkeypatch: Any,
) -> None:
    agent = _agent("alpha", tribe="apple", suffix="a1", status="RUNNING")
    app = _DisplayDiffApp([agent], monkeypatch)
    app._agent_search_query = "status:DONE"
    app._agent_display_last_search_query = "status:RUNNING"

    app._agents = [agent]
    app._refresh_agents_display_after_finalize(
        previous_agents=[agent],
        defer_detail=True,
    )

    assert app.full_rebuilds == 1
    assert [
        record.fallback_reason
        for record in app._agents_refresh_trace_records
        if record.fallback_reason == "search_query_changed"
    ] == ["search_query_changed"]
    assert [
        record.fallback_reason
        for record in app._agents_refresh_trace_records
        if record.fallback_reason == "active_search"
    ] == []
    assert app._agent_display_last_search_query == "status:DONE"


def test_row_patch_refreshes_family_lane_panel_title_without_rebuild(
    monkeypatch: Any,
) -> None:
    # Family-member children no longer carry a left-side title, so the
    # container name has to supply the row-width slack that a suffix patch
    # (unread + pencil) needs.
    planner = _agent(
        "build-family-root",
        tribe="apple",
        suffix="build-plan",
        status="TALE APPROVED",
    )
    planner.agent_family = "build"
    planner.agent_family_role = "root"
    planner.role_suffix = "--plan"
    planner.plan_chain_root = True
    coder = _agent(
        "build--code",
        tribe="apple",
        suffix="build-code",
        status="WORKING TALE",
    )
    coder.parent_timestamp = planner.raw_suffix
    coder.agent_family = "build"
    coder.agent_family_role = "code"
    coder.role_suffix = "--code"
    planner.followup_agents = [coder]
    standalone = _agent(
        "standalone",
        tribe="apple",
        suffix="standalone",
        status="DONE",
    )
    app = _DisplayDiffApp([planner, coder, standalone], monkeypatch)
    widget = app._widgets[_widget_sel("apple")]

    assert Text.from_markup(widget.border_title).plain == "@apple · 2 [R1 D1]"

    app._unread_completed_agent_ids.add(standalone.identity)
    standalone.live_file_change_hint = True
    assert app._try_patch_agent_row(standalone) is True

    assert Text.from_markup(widget.border_title).plain == "@apple · 2 [R1 U1]"
    assert app.full_rebuilds == 0
    assert "row_patch" in _display_costs(app)


def test_collapsed_last_panel_order_still_allows_incremental_row_patch(
    monkeypatch: Any,
) -> None:
    apple = _agent("apple", tribe="apple", suffix="a1", status="RUNNING")
    banana = _agent("banana", tribe="banana", suffix="b1")
    cherry = _agent("cherry", tribe="cherry", suffix="c1")
    updated_apple = replace(apple, status="DONE")
    app = _DisplayDiffApp(
        [apple, banana, cherry],
        monkeypatch,
        collapsed_panel_keys={"banana"},
    )

    assert app._panel_group.panel_keys == ["apple", "cherry", "banana"]

    app._agents = [updated_apple, banana, cherry]
    app._refresh_agents_display_after_finalize(
        previous_agents=[apple, banana, cherry],
        defer_detail=True,
    )

    assert app._panel_group.panel_keys == ["apple", "cherry", "banana"]
    assert app.full_rebuilds == 0
    assert "row_patch" in _display_costs(app)
    assert "display_full_rebuild" not in _display_costs(app)


def test_single_panel_addition_rebuilds_only_affected_panel(monkeypatch: Any) -> None:
    apple = _agent("apple-one", tribe="apple", suffix="a1")
    banana = _agent("banana-one", tribe="banana", suffix="b1")
    added = _agent("apple-two", tribe="apple", suffix="a2")
    app = _DisplayDiffApp([apple, banana], monkeypatch)
    apple_widget = app._widgets[_widget_sel("apple")]
    banana_widget = app._widgets[_widget_sel("banana")]

    app._agents = [apple, added, banana]
    app._refresh_agents_display_after_finalize(
        previous_agents=[apple, banana],
        defer_detail=True,
    )

    assert apple_widget.update_list_calls == 2
    assert banana_widget.update_list_calls == 1
    assert [agent.identity for agent in apple_widget._agents] == [
        apple.identity,
        added.identity,
    ]
    assert app.full_rebuilds == 0
    assert "display_panel_rebuild" in _display_costs(app)
    assert "display_full_rebuild" not in _display_costs(app)


def test_single_panel_removal_removes_then_rebuilds_affected_panel(
    monkeypatch: Any,
) -> None:
    apple_one = _agent("apple-one", tribe="apple", suffix="a1")
    apple_two = _agent("apple-two", tribe="apple", suffix="a2")
    banana = _agent("banana-one", tribe="banana", suffix="b1")
    app = _DisplayDiffApp([apple_one, apple_two, banana], monkeypatch)
    apple_widget = app._widgets[_widget_sel("apple")]
    banana_widget = app._widgets[_widget_sel("banana")]

    app._agents = [apple_one, banana]
    app._refresh_agents_display_after_finalize(
        previous_agents=[apple_one, apple_two, banana],
        defer_detail=True,
    )

    assert apple_widget.update_list_calls == 1
    assert banana_widget.update_list_calls == 1
    assert [agent.identity for agent in apple_widget._agents] == [apple_one.identity]
    assert app.full_rebuilds == 0
    assert "row_remove" in _display_costs(app)


def test_tribe_move_between_existing_panels_rebuilds_source_and_target(
    monkeypatch: Any,
) -> None:
    apple_one = _agent("apple-one", tribe="apple", suffix="a1")
    apple_two = _agent("apple-two", tribe="apple", suffix="a2")
    banana = _agent("banana-one", tribe="banana", suffix="b1")
    moved = replace(apple_one, tribe="banana")
    app = _DisplayDiffApp([apple_one, apple_two, banana], monkeypatch)
    apple_widget = app._widgets[_widget_sel("apple")]
    banana_widget = app._widgets[_widget_sel("banana")]

    app._agents = [moved, apple_two, banana]
    app._refresh_agents_display_after_finalize(
        previous_agents=[apple_one, apple_two, banana],
        defer_detail=True,
    )

    assert apple_widget.update_list_calls == 2
    assert banana_widget.update_list_calls == 2
    assert [agent.identity for agent in apple_widget._agents] == [apple_two.identity]
    assert [agent.identity for agent in banana_widget._agents] == [
        moved.identity,
        banana.identity,
    ]
    assert app.full_rebuilds == 0
    assert "display_panel_rebuild" in _display_costs(app)
    assert "display_full_rebuild" not in _display_costs(app)


def test_merged_panel_tribe_label_change_rebuilds_panel(monkeypatch: Any) -> None:
    old_agent = _agent("alpha", tribe="apple", suffix="a1")
    new_agent = replace(old_agent, tribe="banana")
    app = _DisplayDiffApp([old_agent], monkeypatch, merge_tribe_panels=True)
    widget = app._widgets[_widget_sel(None)]

    app._agents = [new_agent]
    app._refresh_agents_display_after_finalize(
        previous_agents=[old_agent],
        defer_detail=True,
    )

    assert widget.update_list_calls == 2
    assert widget._agents[0].tribe == "banana"
    assert app.full_rebuilds == 0
    assert "display_panel_rebuild" in _display_costs(app)
    assert "row_patch" not in _display_costs(app)


def test_panel_collection_change_inserts_without_full_rebuild(
    monkeypatch: Any,
) -> None:
    apple = _agent("apple-one", tribe="apple", suffix="a1")
    banana = _agent("banana-one", tribe="banana", suffix="b1")
    app = _DisplayDiffApp([apple], monkeypatch)
    apple_widget = app._widgets[_widget_sel("apple")]
    apple_widget.update_list_calls = 0

    app._agents = [apple, banana]
    app._refresh_agents_display_after_finalize(
        previous_agents=[apple],
        defer_detail=True,
    )

    assert app._widgets[_widget_sel("apple")] is apple_widget
    assert apple_widget.update_list_calls == 0
    assert _widget_sel("banana") in app._widgets
    assert app.full_rebuilds == 0
    assert "display_panel_insert" in _display_costs(app)
    assert "display_full_rebuild" not in _display_costs(app)


def test_same_list_falls_back_when_previous_rows_were_not_rendered(
    monkeypatch: Any,
) -> None:
    agent = _agent("alpha", tribe=None, suffix="a1")
    app = _DisplayDiffApp([agent], monkeypatch)
    widget = app._widgets[_widget_sel(None)]
    widget.clear_options()

    app._agents = [agent]
    app._refresh_agents_display_after_finalize(
        previous_agents=[agent],
        defer_detail=True,
    )

    assert app.full_rebuilds == 1
    assert "display_full_rebuild" in _display_costs(app)


# --- whole-roster predicates attribute to the panels they concern ---


def test_a_duplicated_identity_names_the_panels_holding_a_copy() -> None:
    apple = _agent("apple-one", tribe="apple", suffix="a1")
    banana = _agent("banana-one", tribe="banana", suffix="b1")
    cherry = _agent("cherry-one", tribe="cherry", suffix="c1")

    scope = _rebuild_scope(
        [apple, banana, cherry],
        [apple, replace(apple, tribe="banana"), banana, cherry],
    )

    assert scope.reasons == (
        ("apple", "panel_membership_change"),
        ("banana", "panel_membership_change"),
    )


def test_a_repeating_identity_in_both_rosters_still_names_only_its_panel() -> None:
    apple = _agent("apple-one", tribe="apple", suffix="a1")
    banana = _agent("banana-one", tribe="banana", suffix="b1")
    changed = replace(banana, activity="busy")

    scope = _rebuild_scope([apple, apple, banana], [apple, apple, changed])

    assert scope.keys == {"apple"}


def test_an_unchanged_roster_has_an_empty_scope() -> None:
    apple = _agent("apple-one", tribe="apple", suffix="a1")
    flow = _workflow_agent("flow", suffix="wf1", tribe="banana")

    scope = _rebuild_scope([apple, flow], [apple, flow], by_status=True)

    assert scope.reasons == ()
    assert scope.rebuilt_removals == frozenset()

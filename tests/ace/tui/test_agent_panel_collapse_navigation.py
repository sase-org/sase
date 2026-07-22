"""Whole-panel collapse and expansion navigation on the Agents tab."""

from __future__ import annotations

from ._agent_panel_collapse_helpers import (
    AgentPanelCollapseApp,
    make_agent,
    make_four_panel_agents,
    make_multi_panel_agents,
)


def test_h_selects_then_collapses_panel_and_l_expands_then_descends() -> None:
    app = AgentPanelCollapseApp(make_multi_panel_agents(), focused_key="alpha")
    app.current_idx = 2
    registry = app._group_fold_registry.for_panel("alpha")
    registry.collapse(("zeta",))

    app.action_hooks_or_collapse()

    focus = app._resolve_focused_panel()
    assert focus is not None
    assert focus.panel_key == "alpha"
    assert focus.collapsed is False
    assert app._panel_selection_memory["alpha"] == ("agent", 2)
    assert app._collapsed_panel_keys == set()
    assert app.current_attempt_number is None
    assert app._entry_jump_agents_anchor_stack == [("agent", 2, "alpha")]
    assert app.armed_departures == [app._agents[2]]

    app.action_hooks_or_collapse()

    assert app._collapsed_panel_keys == {"alpha"}
    assert app.current_idx == 1
    assert app.current_attempt_number is None
    assert app._current_group_key is None
    assert app._panel_group.panel_keys == [None, "beta", "alpha"]
    assert app._panel_group.focused_key == "alpha"
    assert app._panel_group.focused_idx == 2
    assert app._panel_navigation_stops() == []
    assert app._agents_visible_order() == []
    assert app.refresh_calls == [False, True]

    app.action_expand_or_layout()

    assert app._collapsed_panel_keys == set()
    assert app._resolve_focused_panel() is not None
    assert app.current_idx == 1
    assert app._panel_navigation_stops() == []

    app.action_expand_or_layout()

    assert app._resolve_focused_panel() is None
    assert app.current_idx == 2
    assert app._agents[app.current_idx].agent_name == "render-first"
    assert app._panel_group.panel_keys == [None, "alpha", "beta"]
    assert app._panel_group.focused_key == "alpha"
    assert app._panel_group.focused_idx == 1
    assert registry.is_collapsed(("zeta",)) is True
    assert app.refresh_calls == [False, True, True, False]
    assert app.panel_fold_changes == [("alpha", True), ("alpha", False)]


def test_h_selects_collapses_and_reenters_sole_default_panel() -> None:
    single = AgentPanelCollapseApp([make_agent(name="only", project="one", tribe=None)])

    single.action_hooks_or_collapse()

    focus = single._resolve_focused_panel()
    assert focus is not None
    assert focus.panel_key is None
    assert focus.collapsed is False
    assert single._panel_selection_memory[None] == ("agent", 0)
    assert single._entry_jump_agents_anchor_stack == [("agent", 0, None)]
    assert single.armed_departures == [single._agents[0]]
    assert single._collapsed_panel_keys == set()

    single.action_hooks_or_collapse()

    focus = single._resolve_focused_panel()
    assert focus is not None and focus.collapsed is True
    assert single._collapsed_panel_keys == {None}
    assert single.panel_fold_changes == [(None, True)]

    single.action_expand_or_layout()
    focus = single._resolve_focused_panel()
    assert focus is not None and focus.collapsed is False
    assert single._collapsed_panel_keys == set()
    assert single._panel_selection_memory[None] == ("agent", 0)

    single.action_expand_or_layout()

    assert single._resolve_focused_panel() is None
    assert single.current_idx == 0
    assert single._panel_selection_memory[None] == ("agent", 0)
    assert single.panel_fold_changes == [(None, True), (None, False)]
    assert single.refresh_calls == [False, True, True, False]


def test_h_selects_sole_named_panel_and_saves_reversible_jump_anchor() -> None:
    agent = make_agent(name="only", project="one", tribe="research")
    app = AgentPanelCollapseApp([agent], focused_key="research")

    target = app._resolve_agent_left_navigation_target()
    assert target is not None and target.kind == "tribe"
    app.action_hooks_or_collapse()

    focus = app._resolve_focused_panel()
    assert focus is not None
    assert focus.panel_key == "research"
    assert focus.collapsed is False
    assert app._panel_selection_memory["research"] == ("agent", 0)
    assert app._entry_jump_agents_anchor_stack == [("agent", 0, "research")]

    assert app._restore_agents_jump_anchor() is True
    assert app._resolve_focused_panel() is None
    assert app.current_idx == 0
    assert app._entry_jump_agents_forward_stack() == [("panel", "research")]

    app.action_hooks_or_collapse()
    app.action_hooks_or_collapse()

    focus = app._resolve_focused_panel()
    assert focus is not None and focus.collapsed is True
    assert app._collapsed_panel_keys == {"research"}

    app.action_expand_or_layout()
    app.action_expand_or_layout()

    assert app._resolve_focused_panel() is None
    assert app.current_idx == 0
    assert app._panel_selection_memory["research"] == ("agent", 0)
    assert app.panel_fold_changes == [("research", True), ("research", False)]


def test_h_selects_grouping_banner_in_sole_named_panel() -> None:
    app = AgentPanelCollapseApp(
        [
            make_agent(name="one", project="one", tribe="research"),
            make_agent(name="two", project="two", tribe="research"),
        ],
        focused_key="research",
    )
    banner = app._all_known_group_keys()[0]
    app._group_fold_registry.for_panel("research").collapse(banner)
    app._current_group_key = banner

    assert ("banner", banner) in app._panel_navigation_stops()
    target = app._resolve_agent_left_navigation_target()
    assert target is not None and target.kind == "tribe"
    app.action_hooks_or_collapse()

    focus = app._resolve_focused_panel()
    assert focus is not None and focus.panel_key == "research"
    assert app._panel_selection_memory["research"] == ("banner", banner)


def test_panel_collapse_guards_merged_and_all_collapsed_actions() -> None:
    merged = AgentPanelCollapseApp(make_multi_panel_agents(), merged=True)
    merged.action_hooks_or_collapse()
    assert merged._collapsed_panel_keys == set()
    assert merged.refresh_calls == []

    split = AgentPanelCollapseApp(make_multi_panel_agents(), focused_key="alpha")
    split.action_hooks_or_collapse()
    split.action_hooks_or_collapse()
    split._collapsed_panel_keys.update({None, "beta"})
    split._sync_panel_group()
    split.action_hooks_or_collapse()
    assert split.refresh_calls == [False, True]
    assert split.notifications == ["Panel is already collapsed"]
    split.action_expand_or_layout()
    split.action_expand_or_layout()
    assert split.refresh_calls == [False, True, True, False]


def test_h_from_collapsed_panel_jumps_to_last_expanded_panel() -> None:
    app = AgentPanelCollapseApp(make_four_panel_agents(), focused_key="gamma")
    app._collapsed_panel_keys.update({"beta", "gamma"})
    app._expanded_panel_keys.add("alpha")
    app._sync_panel_group()
    app.current_idx = 4
    app.current_attempt_number = 7
    app._current_group_key = ("stale",)
    app._panel_selection_memory["alpha"] = ("agent", 2)
    app._entry_jump_agents_forward_anchor_stack = [("agent", 0, None)]

    assert app._panel_group.panel_keys == [None, "alpha", "beta", "gamma"]
    assert app._resolve_last_expanded_panel_target() == (1, "alpha")

    app.action_hooks_or_collapse()

    focus = app._resolve_focused_panel()
    assert focus is not None
    assert focus.panel_key == "alpha"
    assert focus.collapsed is False
    assert app._expanded_panel_focus is True
    assert app.current_idx == 2
    assert app.current_attempt_number is None
    assert app._current_group_key is None
    assert app._collapsed_panel_keys == {"beta", "gamma"}
    assert app._expanded_panel_keys == {"alpha"}
    assert app.panel_fold_changes == []
    assert app.refresh_calls == [False]
    assert app.footer_refresh_calls == 1
    assert app.notifications == []
    assert app._entry_jump_agents_anchor_stack == [("panel", "gamma")]
    assert app._entry_jump_agents_forward_anchor_stack == []

    assert app._restore_agents_jump_anchor() is True
    restored = app._resolve_focused_panel()
    assert restored is not None
    assert restored.panel_key == "gamma"
    assert restored.collapsed is True

    app.action_hooks_or_collapse()
    app.action_expand_or_layout()

    assert app._resolve_focused_panel() is None
    assert app._panel_group.focused_key == "alpha"
    assert app.current_idx == 2
    assert app.refresh_calls == [False, False, False]
    assert app.footer_refresh_calls == 2
    assert app.panel_fold_changes == []


def test_h_from_collapsed_panel_accepts_default_as_expanded_destination() -> None:
    app = AgentPanelCollapseApp(make_four_panel_agents(), focused_key="gamma")
    app._collapsed_panel_keys.update({"alpha", "beta", "gamma"})
    app._expanded_panel_keys.add(None)
    app._sync_panel_group()

    assert app._resolve_last_expanded_panel_target() == (0, None)

    app.action_hooks_or_collapse()

    focus = app._resolve_focused_panel()
    assert focus is not None
    assert focus.panel_key is None
    assert focus.collapsed is False
    assert app.current_idx == 0
    assert app._collapsed_panel_keys == {"alpha", "beta", "gamma"}
    assert app._expanded_panel_keys == {None}
    assert app.panel_fold_changes == []
    assert app.refresh_calls == [False]
    assert app.footer_refresh_calls == 1


def test_h_from_collapsed_panel_with_no_expanded_target_is_a_pure_noop() -> None:
    app = AgentPanelCollapseApp(make_four_panel_agents(), focused_key="gamma")
    app._collapsed_panel_keys.update({None, "alpha", "beta", "gamma"})
    app._sync_panel_group()
    app._entry_jump_agents_anchor_stack = [("agent", 0, None)]
    app._entry_jump_agents_forward_anchor_stack = [("agent", 2, "alpha")]
    before = (
        app._panel_group.focused_idx,
        app._panel_group.focused_key,
        app.current_idx,
        app.current_attempt_number,
        app._current_group_key,
        set(app._collapsed_panel_keys),
        set(app._expanded_panel_keys),
        list(app._entry_jump_agents_anchor_stack),
        list(app._entry_jump_agents_forward_anchor_stack),
    )

    assert app._resolve_last_expanded_panel_target() is None

    app.action_hooks_or_collapse()

    after = (
        app._panel_group.focused_idx,
        app._panel_group.focused_key,
        app.current_idx,
        app.current_attempt_number,
        app._current_group_key,
        set(app._collapsed_panel_keys),
        set(app._expanded_panel_keys),
        list(app._entry_jump_agents_anchor_stack),
        list(app._entry_jump_agents_forward_anchor_stack),
    )
    assert after == before
    assert app.notifications == ["Panel is already collapsed"]
    assert app.refresh_calls == []
    assert app.affected_refreshes == []
    assert app.footer_refresh_calls == 0
    assert app.panel_fold_changes == []

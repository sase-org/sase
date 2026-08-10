"""Whole-panel isolation and cycling behavior on the Agents tab."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sase.ace.tui.actions.navigation._basic import BasicNavigationMixin
from sase.ace.tui.models._agent_tree import agent_fold_key, project_clan_tree
from sase.ace.tui.models.fold_state import FoldLevel

from ._agent_panel_collapse_helpers import (
    AgentPanelCollapseApp,
    make_four_panel_agents,
    make_multi_panel_agents,
)


def test_capital_z_expands_selected_panel_and_collapses_every_other_panel() -> None:
    app = AgentPanelCollapseApp(make_multi_panel_agents(), focused_key="alpha")
    app.current_idx = 2
    remembered = ("agent", 2)
    app._panel_selection_memory["alpha"] = remembered
    registry = app._group_fold_registry.for_panel("alpha")
    registry.collapse(("zeta",))
    registry_before = app._group_fold_registry.snapshot()
    app._collapsed_panel_keys.add("alpha")
    app._sync_panel_group()
    app._current_group_key = ("stale",)

    app.action_isolate_panels()

    focus = app._resolve_focused_panel()
    assert focus is not None
    assert focus.panel_key == "alpha"
    assert focus.collapsed is False
    assert app._collapsed_panel_keys == {None, "beta"}
    assert app._panel_group.panel_keys == ["alpha", None, "beta"]
    assert app._panel_group.focused_key == "alpha"
    assert app._panel_group.focused_idx == 0
    assert app.current_idx == 2
    assert app.current_attempt_number is None
    assert app._current_group_key is None
    assert app._panel_selection_memory["alpha"] == remembered
    assert app._group_fold_registry.snapshot() == registry_before
    assert app.refresh_calls == [True]
    assert app.panel_fold_changes == [
        (None, True),
        ("beta", True),
        ("alpha", False),
    ]


def test_capital_z_only_changes_expanded_siblings_then_restores() -> None:
    app = AgentPanelCollapseApp(make_multi_panel_agents(), focused_key="alpha")
    app.current_idx = 2
    app._panel_selection_memory["alpha"] = ("agent", 2)
    app._collapsed_panel_keys.add("beta")
    app._sync_panel_group()
    app._expanded_panel_focus = True

    app.action_isolate_panels()

    assert app._collapsed_panel_keys == {None, "beta"}
    assert app._panel_group.panel_keys == ["alpha", None, "beta"]
    assert app._panel_group.focused_key == "alpha"
    assert app.refresh_calls == [True]
    assert app.panel_fold_changes == [(None, True)]

    app.action_isolate_panels()

    assert app._resolve_focused_panel() is not None
    assert app._collapsed_panel_keys == {"beta"}
    assert app.refresh_calls == [True, True]
    assert app.panel_fold_changes == [(None, True), (None, False)]
    assert app.notifications == ["Restored 1 panel"]


def test_capital_z_can_leave_no_tribe_panel_as_selected_survivor() -> None:
    app = AgentPanelCollapseApp(make_multi_panel_agents(), focused_key=None)
    app._collapsed_panel_keys.add(None)
    app._sync_panel_group()

    app.action_isolate_panels()

    focus = app._resolve_focused_panel()
    assert focus is not None
    assert focus.panel_key is None
    assert focus.collapsed is False
    assert app._collapsed_panel_keys == {"alpha", "beta"}
    assert app._panel_group.panel_keys == [None, "alpha", "beta"]
    assert app._panel_group.focused_key is None
    assert app.refresh_calls == [True]
    assert app.panel_fold_changes == [
        ("alpha", True),
        ("beta", True),
        (None, False),
    ]


def test_capital_h_walks_selected_panel_clans_groups_then_collapses_panel() -> None:
    agents = make_multi_panel_agents()
    clan_member = agents[1]
    clan_member.agent_clan = "toobig-g"
    clan_member.agent_clan_generation = "generation"
    agents = project_clan_tree(agents)
    clan = next(agent for agent in agents if agent.is_clan_container)
    clan_key = agent_fold_key(clan)
    assert clan_key is not None
    render_first = next(agent for agent in agents if agent.agent_name == "render-first")
    app = AgentPanelCollapseApp(agents, focused_key="alpha")
    app._fold_manager.expand(clan_key)
    app.current_idx = agents.index(render_first)
    remembered = ("agent", app.current_idx)
    app._panel_selection_memory["alpha"] = remembered
    app._expanded_panel_focus = True
    registry = app._group_fold_registry.for_panel("alpha")

    clan_target = app._resolve_focused_panel_clan_collapse_target()
    assert clan_target is not None
    assert clan_target.fold_keys == (clan_key,)

    app.action_hooks_or_collapse_all()

    assert app._fold_manager.get(clan_key) is FoldLevel.COLLAPSED
    assert registry.snapshot() == frozenset()
    assert app._resolve_focused_panel() is not None
    assert app.current_idx == agents.index(render_first)
    assert app._panel_selection_memory["alpha"] == remembered
    assert app.refilter_kwargs == [{"refresh_content_index": False}]

    target = app._resolve_focused_panel_group_collapse_target()
    assert target is not None
    assert target.group_key == ("zeta",)

    app.action_hooks_or_collapse_all()

    assert app._collapsed_panel_keys == set()
    assert registry.is_collapsed(("zeta",))
    assert not registry.is_collapsed(("alpha",))
    assert app._resolve_focused_panel() is not None
    assert app.current_idx == agents.index(render_first)
    assert app._panel_selection_memory["alpha"] == remembered
    assert app._panel_isolation_revert is None
    assert app.panel_fold_changes == []
    assert app.refilter_kwargs == [
        {"refresh_content_index": False},
        {"refresh_content_index": False},
    ]
    assert app.group_fold_changes == [("alpha", ("zeta",), True)]

    app.action_hooks_or_collapse_all()

    assert registry.is_collapsed(("alpha",))
    assert app._collapsed_panel_keys == set()
    assert app.group_fold_changes == [
        ("alpha", ("zeta",), True),
        ("alpha", ("alpha",), True),
    ]

    app.action_hooks_or_collapse_all()

    assert app._collapsed_panel_keys == {"alpha"}
    assert app._panel_isolation_revert is None
    assert app.panel_fold_changes == [("alpha", True)]
    assert app.refresh_calls == [True]

    group_state = app._group_fold_registry.snapshot()
    app.action_hooks_or_collapse_all()

    assert app._group_fold_registry.snapshot() == group_state
    assert app.notifications == ["Panel is already collapsed"]


def test_selected_panel_j_and_k_cycle_without_descending() -> None:
    app = AgentPanelCollapseApp(make_multi_panel_agents(), focused_key="alpha")
    app.current_idx = 2
    app._panel_selection_memory["alpha"] = ("agent", 2)
    app._collapsed_panel_keys.add("beta")
    app._sync_panel_group()
    app._expanded_panel_focus = True

    BasicNavigationMixin._navigate_agents_panel(app, 1)

    focus = app._resolve_focused_panel()
    assert focus is not None
    assert focus.panel_key == "beta"
    assert focus.collapsed is True
    assert app._panel_navigation_stops() == []

    BasicNavigationMixin._navigate_agents_panel(app, 1)

    focus = app._resolve_focused_panel()
    assert focus is not None
    assert focus.panel_key is None
    assert focus.collapsed is False

    BasicNavigationMixin._navigate_agents_panel(app, -1)

    focus = app._resolve_focused_panel()
    assert focus is not None
    assert focus.panel_key == "beta"
    assert focus.collapsed is True


def test_escape_from_expanded_panel_restores_remembered_banner() -> None:
    app = AgentPanelCollapseApp(make_multi_panel_agents(), focused_key="alpha")
    banner = ("zeta",)
    app._group_fold_registry.for_panel("alpha").collapse(banner)
    app._panel_selection_memory["alpha"] = ("banner", banner)
    app._expanded_panel_focus = True

    assert app._exit_expanded_panel_focus() is True

    assert app._resolve_focused_panel() is None
    assert app._current_group_key == banner
    assert app.current_idx == 1


def test_panel_switch_skips_collapsed_panel_and_l_reanchors_after_lowercase_j() -> None:
    app = AgentPanelCollapseApp(make_multi_panel_agents(), focused_key=None)
    app._collapsed_panel_keys.add("alpha")
    app._sync_panel_group()

    app.action_focus_next_agent_panel()

    assert app._panel_group.focused_key == "beta"
    assert app.current_idx == 3

    app.action_focus_next_agent_panel()

    assert app._panel_group.focused_key is None
    assert app.current_idx == 0
    assert app._current_group_key is None
    assert app.refresh_calls == [False, False]

    app._expanded_panel_focus = True
    BasicNavigationMixin._navigate_agents_panel(app, -1)
    focus = app._resolve_focused_panel()
    assert focus is not None
    assert focus.panel_key == "alpha"
    assert focus.collapsed is True

    prior = (app.current_idx, app._current_group_key)
    BasicNavigationMixin._navigate_agents_panel(app, 1)
    BasicNavigationMixin._navigate_agents_panel(app, -1)
    assert (app.current_idx, app._current_group_key) == prior

    app.action_expand_or_layout()
    app.action_expand_or_layout()
    assert app.current_idx == 2
    assert app._collapsed_panel_keys == set()
    assert app._panel_group.panel_keys == [None, "alpha", "beta"]
    assert app.refresh_calls == [False, False, False, False, False, True, False]


def test_prev_panel_switch_skips_collapsed_panel_and_lands_on_last_banner() -> None:
    app = AgentPanelCollapseApp(make_multi_panel_agents(), focused_key=None)
    app._collapsed_panel_keys.add("beta")
    app._group_fold_registry.for_panel("alpha").collapse(("zeta",))
    app._sync_panel_group()

    app.action_focus_prev_agent_panel()

    assert app._panel_group.focused_key == "alpha"
    assert app._current_group_key == ("zeta",)
    assert app.current_idx == 1
    assert app._expanded_panel_focus is False


def test_panel_switches_descend_from_collapsed_origin() -> None:
    forward = AgentPanelCollapseApp(make_four_panel_agents(), focused_key="beta")
    forward._collapsed_panel_keys.add("beta")
    forward._sync_panel_group()
    forward._expanded_panel_focus = True

    forward.action_focus_next_agent_panel()

    assert forward._panel_group.focused_key is None
    assert forward.current_idx == 0
    assert forward._current_group_key is None
    assert forward._expanded_panel_focus is False

    reverse = AgentPanelCollapseApp(make_four_panel_agents(), focused_key="beta")
    reverse._collapsed_panel_keys.add("beta")
    reverse._sync_panel_group()
    reverse._expanded_panel_focus = True

    reverse.action_focus_prev_agent_panel()

    assert reverse._panel_group.focused_key == "gamma"
    assert reverse.current_idx == 4
    assert reverse._current_group_key is None
    assert reverse._expanded_panel_focus is False


def test_panel_switch_skips_config_collapsed_panel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.models import tribe_display

    monkeypatch.setattr(
        tribe_display,
        "tribe_display_for",
        lambda key: SimpleNamespace(initially_expanded=key != "alpha"),
    )
    app = AgentPanelCollapseApp(make_multi_panel_agents(), focused_key=None)
    app._sync_panel_group()

    app.action_focus_next_agent_panel()

    assert app._collapsed_panel_keys == set()
    assert app._expanded_panel_keys == set()
    assert app._panel_group.focused_key == "beta"
    assert app.current_idx == 3


def _panel_switch_state(app: AgentPanelCollapseApp) -> tuple[object, ...]:
    return (
        app._panel_group.focused_idx,
        app._panel_group.focused_key,
        app.current_idx,
        app.current_attempt_number,
        app._current_group_key,
        app._expanded_panel_focus,
        list(app._entry_jump_agents_anchor_stack),
        list(app._entry_jump_agents_forward_anchor_stack),
        list(app.refresh_calls),
        list(app.notifications),
    )


def test_panel_switches_are_pure_noops_without_expanded_sibling() -> None:
    app = AgentPanelCollapseApp(make_four_panel_agents(), focused_key="alpha")
    app._collapsed_panel_keys.update({None, "beta", "gamma"})
    app._sync_panel_group()
    app.current_idx = 2
    app._current_group_key = ("stale",)
    app._expanded_panel_focus = True
    app._entry_jump_agents_anchor_stack = [("agent", 0, None)]
    app._entry_jump_agents_forward_anchor_stack = [("agent", 4, "gamma")]
    before = _panel_switch_state(app)

    app.action_focus_next_agent_panel()
    app.action_focus_prev_agent_panel()

    assert _panel_switch_state(app) == before


def test_panel_switches_are_noops_in_merged_layout() -> None:
    app = AgentPanelCollapseApp(make_multi_panel_agents(), merged=True)
    app._expanded_panel_focus = True
    before = _panel_switch_state(app)

    app.action_focus_next_agent_panel()
    app.action_focus_prev_agent_panel()

    assert _panel_switch_state(app) == before

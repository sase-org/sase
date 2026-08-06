"""Fold, group, and panel layers a member jump has to peel back before selecting."""

from __future__ import annotations

from sase.ace.tui.models._agent_tree import agent_fold_key
from sase.ace.tui.models.agent_groups import GroupingMode, build_agent_tree
from sase.ace.tui.models.agent_panels import AgentPanelGroup
from sase.ace.tui.models.agent_tribe_summary import (
    build_agent_tribe_summary_snapshot,
)
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.models.group_fold import GroupFoldRegistry
from sase.ace.tui.widgets.prompt_panel._agent_display_tribe import (
    build_tribe_detail_text,
)

from ._member_jump_navigation_helpers import (
    JumpHarness,
    make_agent,
    make_clan,
    make_jump_map,
)


def test_jump_expands_target_group_and_different_collapsed_panel() -> None:
    complete, container = make_clan(2, mixed_tribes=True)
    members = list(container.runtime_children)
    target = members[1]
    app = JumpHarness(complete, container)
    app._member_jump_maps[container.identity] = make_jump_map(container, members)
    clan_key = agent_fold_key(container)
    assert clan_key is not None

    # Prime the target's rendered panel/group context, collapse those layers,
    # then return to the clan container's collapsed outer fold.
    app._fold_manager.expand(clan_key)
    app._refilter_agents()
    target_idx = next(
        index
        for index, agent in enumerate(app._agents)
        if agent.identity == target.identity
    )
    target_panel_key = app._panel_keys_per_agent()[target_idx]
    target_panel_agents = [
        agent
        for index, agent in enumerate(app._agents)
        if app._panel_keys_per_agent()[index] == target_panel_key
    ]
    local_target_idx = target_panel_agents.index(app._agents[target_idx])
    tree = build_agent_tree(
        target_panel_agents,
        fold_registry=GroupFoldRegistry(),
        mode=GroupingMode.STANDARD,
    )
    target_groups = [
        entry.group.group_key
        for entry in tree
        if entry.kind == "group"
        and entry.group is not None
        and local_target_idx in entry.group.agent_indices
    ]
    registry = app._group_fold_registry.for_panel(target_panel_key)
    registry.collapse_keys(target_groups)
    app._collapsed_panel_keys.add(target_panel_key)
    app._fold_manager.collapse(clan_key)
    app._refilter_agents()
    app.current_idx = next(
        index
        for index, agent in enumerate(app._agents)
        if agent.identity == container.identity
    )

    assert app._handle_member_jump_key("1") is True

    assert app._agents[app.current_idx].identity == target.identity
    assert target_panel_key not in app._collapsed_panel_keys
    assert all(not registry.is_collapsed(key) for key in target_groups)
    assert app.group_fold_changes == [
        (target_panel_key, key, False) for key in target_groups
    ]
    assert app.panel_fold_changes == [(target_panel_key, False)]
    assert app.display_refreshes == [True]


def test_visible_member_jump_skips_refilter_and_structural_refresh() -> None:
    complete, container = make_clan(2)
    members = list(container.runtime_children)
    app = JumpHarness(complete, container)
    app._member_jump_maps[container.identity] = make_jump_map(container, members)
    clan_key = agent_fold_key(container)
    assert clan_key is not None
    app._fold_manager.expand(clan_key)
    app._refilter_agents()
    app.refilter_calls = 0
    app.display_refreshes.clear()
    app.current_idx = next(
        idx
        for idx, agent in enumerate(app._agents)
        if agent.identity == container.identity
    )

    assert app._handle_member_jump_key("1") is True

    assert app._agents[app.current_idx].identity == members[1].identity
    assert app.refilter_calls == 0
    assert app.display_refreshes == []


def test_tribe_member_jump_expands_panel_and_selects_numbered_unit() -> None:
    first = make_agent("first", tribe="epic")
    second = make_agent("second", tribe="epic")
    app = JumpHarness([first, second], first)
    app._collapsed_panel_keys.add("epic")
    app._whole_panel_focus = True
    app._panel_group = AgentPanelGroup.from_agents(
        app._agents,
        focused_key="epic",
        collapsed_panel_keys=app._collapsed_panel_keys,
    )
    snapshot = build_agent_tribe_summary_snapshot(
        "epic",
        [first, second],
        panel_collapsed=True,
    )
    build_tribe_detail_text(
        snapshot,
        fold_level=FoldLevel.COLLAPSED,
        member_jump_map_publisher=lambda jump_map: app._member_jump_maps.__setitem__(
            jump_map.container_identity,
            jump_map,
        ),
    )
    assert app._member_jump_maps[snapshot.container_identity].targets

    assert app._handle_member_jump_key("1") is True

    assert "epic" not in app._collapsed_panel_keys
    assert app._agents[app.current_idx].identity == second.identity
    assert app.panel_fold_changes == [("epic", False)]

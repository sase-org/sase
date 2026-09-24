"""Jump-panel number presses through the real member-jump path."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rich.text import Text

from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent_tribe_summary import AgentPanelFocus
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel._member_roster import (
    MemberJumpMap,
    MemberJumpNumbering,
    MemberRosterEntry,
    append_member_roster,
)
from sase.ace.tui.widgets.renderable_text import renderable_to_text
from tests.ace.tui._member_jump_navigation_helpers import (
    JumpHarness,
    make_agent as make_nav_agent,
    make_family as make_nav_family,
)
from tests.ace.tui.widgets._agent_display_clan_helpers import make_clan_agent


def _press_each_number(
    app: JumpHarness, container: Any, jump_map: MemberJumpMap
) -> None:
    """Press every panel number through the real key path and check landing."""
    from sase.ace.tui.widgets._agent_jump_legend import JumpLegendRenderable

    rendered = renderable_to_text(JumpLegendRenderable(jump_map, mode="collapsed"))
    assert rendered
    for target in jump_map.targets:
        assert target.number in rendered
        assert target.label in rendered
        app.current_idx = next(
            index
            for index, agent in enumerate(app._agents)
            if agent.identity == container.identity
        )
        assert app._handle_member_jump_key(target.number) is True
        landed = app._agents[app.current_idx].identity
        assert landed == target.member_identity, (target.number, landed)
    assert app.notifications == []


def test_panel_numbers_land_through_real_jump_path() -> None:
    complete, root, child = make_nav_family(in_clan=False)
    app = JumpHarness(complete, root)
    entries = (
        MemberRosterEntry(
            identity=child.identity,
            presented_name="alpha--code",
            label="--code",
            kind="agent",
            status="DONE",
            model="m",
            duration="1m",
        ),
    )
    jump_map = append_member_roster(
        Text(),
        container_identity=root.identity,
        entries=entries,
        title="FAMILY SHELLS",
        accent="#00AFFF",
        panel_level=FoldLevel.COLLAPSED,
        numbering=MemberJumpNumbering(total=len(entries)),
    )
    app._member_jump_maps[root.identity] = jump_map
    _press_each_number(app, root, jump_map)


def test_panel_neighbor_number_lands() -> None:
    container = make_nav_agent("foo.plan")
    neighbor = make_nav_agent("foo.code")
    app = JumpHarness([container, neighbor], container)
    app._neighbor_targets[container.identity] = {neighbor.identity}
    entries = (
        MemberRosterEntry(
            identity=neighbor.identity,
            presented_name="foo.code",
            label="foo.code",
            kind="agent",
            status="RUNNING",
            model="m",
            duration="1m",
            target_role="neighbor",
        ),
    )
    jump_map = append_member_roster(
        Text(),
        container_identity=container.identity,
        entries=entries,
        title="NEIGHBORS",
        accent="#00D7AF",
        panel_level=FoldLevel.COLLAPSED,
        numbering=MemberJumpNumbering(total=len(entries)),
    )
    app._member_jump_maps[container.identity] = jump_map
    _press_each_number(app, container, jump_map)


def test_panel_dismissed_number_revives() -> None:
    from sase.ace.tui.widgets._agent_jump_legend import JumpLegendRenderable

    container = make_nav_agent("foo")
    dismissed = make_nav_agent("foo.scratch")
    app = JumpHarness([container], container)
    app._dismissed_agent_objects = [dismissed]
    app._dismissed_agents = {dismissed.identity}
    entries = (
        MemberRosterEntry(
            identity=dismissed.identity,
            presented_name="foo.scratch",
            label="foo.scratch",
            kind="agent",
            status="QUESTION",
            model="m",
            duration="1m",
            is_dismissed=True,
            target_role="dismissed",
        ),
    )
    jump_map = append_member_roster(
        Text(),
        container_identity=container.identity,
        entries=entries,
        title="NEIGHBORS",
        accent="#00D7AF",
        panel_level=FoldLevel.COLLAPSED,
        numbering=MemberJumpNumbering(total=len(entries)),
    )
    app._member_jump_maps[container.identity] = jump_map

    rendered = renderable_to_text(JumpLegendRenderable(jump_map, mode="0"))
    assert rendered and "revive" in rendered

    assert app._handle_member_jump_key("0") is True
    assert app.revived_agents == [dismissed]
    assert app._agents[app.current_idx].identity == container.identity
    assert app.notifications == []


def test_panel_clan_and_tribe_numbers_land() -> None:
    members = [
        make_clan_agent(
            "research.first",
            status="DONE",
            start=datetime(2026, 7, 17, 12, 0, 0),
            stop=datetime(2026, 7, 17, 12, 2, 0),
        ),
        make_clan_agent(
            "research.second",
            status="FAILED",
            start=datetime(2026, 7, 17, 12, 1, 0),
            stop=datetime(2026, 7, 17, 12, 1, 45),
        ),
    ]
    projected = project_clan_tree(members)
    container = next(agent for agent in projected if agent.is_clan_container)
    app = JumpHarness([*projected], container)
    entries = tuple(
        MemberRosterEntry(
            identity=member.identity,
            presented_name=member.agent_name or "member",
            label=f"member-{index}",
            kind="agent",
            status="DONE",
            model="m",
            duration="1m",
        )
        for index, member in enumerate(container.runtime_children)
    )
    jump_map = append_member_roster(
        Text(),
        container_identity=container.identity,
        entries=entries,
        title="CLAN MEMBERS",
        accent="#D75FFF",
        panel_level=FoldLevel.COLLAPSED,
        numbering=MemberJumpNumbering(total=len(entries)),
    )
    app._member_jump_maps[container.identity] = jump_map
    _press_each_number(app, container, jump_map)

    tribe_members = [
        make_nav_agent(f"t.member{index}", tribe="t") for index in range(3)
    ]
    tribe_app = JumpHarness(tribe_members, tribe_members[0])
    focus = AgentPanelFocus(
        panel_key=tribe_app._panel_group.focused_key, collapsed=False
    )

    def _focused_panel() -> AgentPanelFocus:
        return focus

    tribe_app._resolve_focused_panel = _focused_panel  # noqa: SLF001
    tribe_entries = tuple(
        MemberRosterEntry(
            identity=member.identity,
            presented_name=member.agent_name or "member",
            label=f"t-label-{index}",
            kind="agent",
            status="RUNNING",
            model="m",
            duration="1m",
        )
        for index, member in enumerate(tribe_members)
    )
    tribe_map = append_member_roster(
        Text(),
        container_identity=focus.container_identity,
        entries=tribe_entries,
        title="TRIBE MEMBERS",
        accent="#AF87D7",
        panel_level=FoldLevel.COLLAPSED,
        numbering=MemberJumpNumbering(total=len(tribe_entries)),
    )
    tribe_app._member_jump_maps[focus.container_identity] = tribe_map
    from sase.ace.tui.widgets._agent_jump_legend import JumpLegendRenderable

    rendered = renderable_to_text(JumpLegendRenderable(tribe_map, mode="collapsed"))
    assert rendered
    for target in tribe_map.targets:
        assert target.number in rendered
        assert app.notifications == []
        assert tribe_app._handle_member_jump_key(target.number) is True
        assert (
            tribe_app._agents[tribe_app.current_idx].identity == target.member_identity
        )
    assert tribe_app.notifications == []

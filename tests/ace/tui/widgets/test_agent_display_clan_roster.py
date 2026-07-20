"""Clan member roster rendering in the Agents metadata panel."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.widgets.prompt_panel._agent_display_clan import (
    build_clan_detail_text,
)
from tests.ace.tui.widgets._agent_display_clan_helpers import make_clan_agent


def test_clan_members_render_family_aggregate_and_every_member() -> None:
    family_name = "research.writer"
    planner = make_clan_agent(
        f"{family_name}--plan-0",
        status="DONE",
        start=datetime(2026, 7, 17, 12, 0, 0),
        stop=datetime(2026, 7, 17, 12, 1, 0),
        family=family_name,
    )
    coder = make_clan_agent(
        f"{family_name}--code",
        status="DONE",
        start=datetime(2026, 7, 17, 12, 2, 0),
        stop=datetime(2026, 7, 17, 12, 3, 0),
        model="sonnet",
        parent_timestamp=planner.raw_suffix,
        family=family_name,
    )
    planner.runtime_children = [coder]
    container = project_clan_tree([planner, coder])[0]

    jump_maps = []
    detail = build_clan_detail_text(
        container,
        now=datetime(2026, 7, 17, 12, 4, 0),
        member_jump_map_publisher=jump_maps.append,
    )

    assert "Members: 2 agents · 1 family\n" in detail.plain
    members_section = (
        detail.plain.split("▸ ❖ CLAN MEMBERS · 1\n", 1)[1]
        .split(
            "\n" + "─" * 50 + "\n",
            1,
        )[0]
        .split("\n⋯ scanning member data…", 1)[0]
    )
    assert members_section == (
        " 0  .writer · family · ✓ DONE · mixed · 2m\n"
        "    ├─ --plan-0 · agent · ✓ DONE · gpt-5 · 1m\n"
        "    └─ --code · agent · ✓ DONE · sonnet · 1m\n"
    )
    assert len(jump_maps) == 1
    assert tuple(
        (target.number, target.member_identity, target.kind)
        for target in jump_maps[0].targets
    ) == (("0", planner.identity, "family"),)


def test_clan_family_roster_renders_settled_planner_as_done() -> None:
    family_name = "research.writer"
    planner = make_clan_agent(
        f"{family_name}--plan",
        status="TALE APPROVED",
        start=datetime(2026, 7, 17, 12, 0, 0),
        family=family_name,
    )
    coder = make_clan_agent(
        f"{family_name}--code",
        status="WORKING TALE",
        start=datetime(2026, 7, 17, 12, 2, 0),
        parent_timestamp=planner.raw_suffix,
        family=family_name,
    )
    planner.runtime_children = [coder]
    container = project_clan_tree([planner, coder])[0]

    detail = build_clan_detail_text(container)

    assert "--plan · agent · ✓ TALE APPROVED" in detail.plain
    assert "--code · agent · ▶ WORKING TALE" in detail.plain


def test_clan_roster_launch_order_is_stable_while_statuses_churn() -> None:
    first = make_clan_agent(
        "research.first",
        status="RUNNING",
        start=datetime(2026, 7, 17, 12, 0, 0),
    )
    second = make_clan_agent(
        "research.second",
        status="WAITING",
        start=datetime(2026, 7, 17, 12, 1, 0),
    )
    container = project_clan_tree([second, first])[0]

    before_maps = []
    before = build_clan_detail_text(
        container,
        member_jump_map_publisher=before_maps.append,
    ).plain
    first.status = "DONE"
    second.status = "FAILED"
    after_maps = []
    after = build_clan_detail_text(
        container,
        member_jump_map_publisher=after_maps.append,
    ).plain

    assert before.index(" 0  .first") < before.index(" 1  .second")
    assert after.index(" 0  .first") < after.index(" 1  .second")
    assert tuple(target.member_identity for target in before_maps[0].targets) == (
        first.identity,
        second.identity,
    )
    assert before_maps[0].targets == after_maps[0].targets

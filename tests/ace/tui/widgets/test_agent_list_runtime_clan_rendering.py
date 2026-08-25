"""Tests for AgentList live clan runtime suffix rendering."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from sase.ace.tui.widgets.agent_list import AgentList

from .agent_list_runtime_helpers import (
    AgentListHarness,
    agent,
    agent_row_index,
    workflow_child,
)


def _clan_container(*, clan: str = "research", generation: str = "gen-1") -> Agent:
    container = agent(status="RUNNING", raw_suffix="clan-root", cl_name=clan)
    container.is_clan_container = True
    container.agent_clan = clan
    container.agent_clan_generation = generation
    return container


def test_format_agent_option_active_clan_shows_lowest_lane_and_total() -> None:
    clan = _clan_container()
    lane_a = agent(
        status="RUNNING",
        start=datetime(2026, 7, 19, 9, 0, 0),
        run_start=datetime(2026, 7, 19, 9, 0, 0),
        raw_suffix="lane-a",
        cl_name="research.a",
    )
    lane_a.agent_clan = "research"
    lane_a.agent_clan_generation = "gen-1"
    lane_b = agent(
        status="RUNNING",
        start=datetime(2026, 7, 19, 9, 5, 0),
        run_start=datetime(2026, 7, 19, 9, 5, 0),
        raw_suffix="lane-b",
        cl_name="research.b",
    )
    lane_b.agent_clan = "research"
    lane_b.agent_clan_generation = "gen-1"
    clan.runtime_children = [lane_a, lane_b]

    _, suffix, _ = format_agent_option(
        clan,
        0,
        is_selected=False,
        now=datetime(2026, 7, 19, 9, 50, 0),
    )

    assert suffix.plain == "🏃‍♂️ 45m / 50m"


def test_format_agent_option_active_clan_orders_lanes_by_seconds_not_string() -> None:
    clan = _clan_container()
    long_lane = agent(
        status="RUNNING",
        start=datetime(2026, 7, 19, 8, 0, 0),
        run_start=datetime(2026, 7, 19, 8, 0, 0),
        raw_suffix="lane-long",
        cl_name="research.long",
    )
    long_lane.agent_clan = "research"
    long_lane.agent_clan_generation = "gen-1"
    short_lane = agent(
        status="RUNNING",
        start=datetime(2026, 7, 19, 8, 20, 0),
        run_start=datetime(2026, 7, 19, 8, 20, 0),
        raw_suffix="lane-short",
        cl_name="research.short",
    )
    short_lane.agent_clan = "research"
    short_lane.agent_clan_generation = "gen-1"
    clan.runtime_children = [long_lane, short_lane]

    _, suffix, _ = format_agent_option(
        clan,
        0,
        is_selected=False,
        now=datetime(2026, 7, 19, 9, 5, 0),
    )

    # "1h05m" sorts before "45m" lexically even though it is the larger
    # duration -- proving the minimum is taken on elapsed seconds.
    assert suffix.plain == "🏃‍♂️ 45m / 1h05m"


def test_format_agent_option_clan_single_family_lane_matches_family_total() -> None:
    root = agent(
        status="RUNNING",
        start=datetime(2026, 7, 19, 9, 0, 0),
        run_start=datetime(2026, 7, 19, 9, 0, 0),
        raw_suffix="root",
        cl_name="family",
    )
    root.agent_name = "family--0"
    root.agent_family = "family"
    root.agent_family_role = "root"
    root.role_suffix = "--0"
    waiting_child = agent(
        status="WAITING",
        start=datetime(2026, 7, 19, 9, 1, 0),
        run_start=None,
        raw_suffix="waiting",
        cl_name="family--review",
    )
    waiting_child.parent_timestamp = root.raw_suffix
    waiting_child.agent_family = "family"
    waiting_child.agent_family_role = "review"
    waiting_child.role_suffix = "--review"
    root.followup_agents = [waiting_child]

    clan = _clan_container()
    root.agent_clan = "research"
    root.agent_clan_generation = "gen-1"
    clan.runtime_children = [root]

    now = datetime(2026, 7, 19, 9, 3, 5)
    _, family_suffix, _ = format_agent_option(root, 0, is_selected=False, now=now)
    _, clan_suffix, _ = format_agent_option(clan, 0, is_selected=False, now=now)

    assert family_suffix.plain == "🏃‍♂️ 3m05s / 3m05s"
    assert (
        clan_suffix.plain.split(" / ")[0]
        == "🏃‍♂️ " + family_suffix.plain.split(" / ")[1]
    )


def test_format_agent_option_clan_family_lane_contributes_family_total() -> None:
    root = agent(
        agent_type=AgentType.WORKFLOW,
        status="WORKING TALE",
        start=datetime(2026, 7, 19, 9, 0, 0),
        run_start=datetime(2026, 7, 19, 9, 0, 0),
        raw_suffix="root",
        cl_name="family-workflow",
    )
    root.agent_name = "family--plan"
    root.agent_family = "family"
    root.agent_family_role = "root"
    root.plan_chain_root = True
    planner = workflow_child(
        step_type="agent",
        status="DONE",
        start=datetime(2026, 7, 19, 9, 0, 0),
        run_start=datetime(2026, 7, 19, 9, 0, 0),
        plan_times=[datetime(2026, 7, 19, 9, 2, 0)],
        raw_suffix="planner",
        cl_name="plan",
    )
    coder = agent(
        status="RUNNING",
        start=datetime(2026, 7, 19, 9, 4, 0),
        run_start=datetime(2026, 7, 19, 9, 4, 0),
        raw_suffix="coder",
        cl_name="family--code",
    )
    coder.parent_timestamp = root.raw_suffix
    coder.agent_family = "family"
    coder.agent_family_role = "code"
    coder.role_suffix = "--code"
    root.runtime_children = [planner, coder]
    root.followup_agents = [coder]
    root.agent_clan = "research"
    root.agent_clan_generation = "gen-1"

    solo = agent(
        status="RUNNING",
        start=datetime(2026, 7, 19, 9, 0, 0),
        run_start=datetime(2026, 7, 19, 9, 0, 0),
        raw_suffix="solo",
        cl_name="research.solo",
    )
    solo.agent_clan = "research"
    solo.agent_clan_generation = "gen-1"

    clan = _clan_container()
    clan.runtime_children = [root, solo]

    now = datetime(2026, 7, 19, 9, 5, 5)
    _, family_suffix, _ = format_agent_option(root, 0, is_selected=False, now=now)
    _, clan_suffix, _ = format_agent_option(clan, 0, is_selected=False, now=now)

    assert family_suffix.plain == "🏃‍♂️ 1m05s / 3m05s"
    assert clan_suffix.plain == "🏃‍♂️ 3m05s / 5m05s"
    assert "1m05s" not in clan_suffix.plain  # the coder shell's own runtime


def test_format_agent_option_clan_family_lane_falls_back_when_total_is_not_live() -> (
    None
):
    # The family aggregate collapses to an inactive "0s" while a queued-only
    # child sits in runtime_children -- see plan Follow-up 1 ("a family
    # total can collapse to 0s"), tracked as a pre-existing bug in
    # `_aggregate_runtime()`. Re-evaluate this test once that bug is fixed:
    # the family row's own "0s" total pinned below should no longer occur.
    root = agent(
        status="RUNNING",
        start=datetime(2026, 7, 19, 9, 0, 0),
        run_start=datetime(2026, 7, 19, 9, 0, 0),
        raw_suffix="root",
        cl_name="family",
    )
    root.agent_name = "family--0"
    root.agent_family = "family"
    root.agent_family_role = "root"
    queued_child = agent(
        status="WAITING",
        start=datetime(2026, 7, 19, 9, 1, 0),
        run_start=None,
        raw_suffix="queued",
        cl_name="family--review",
    )
    queued_child.parent_timestamp = root.raw_suffix
    queued_child.agent_family = "family"
    queued_child.agent_family_role = "review"
    queued_child.role_suffix = "--review"
    root.runtime_children = [queued_child]
    root.followup_agents = [queued_child]
    root.agent_clan = "research"
    root.agent_clan_generation = "gen-1"

    clan = _clan_container()
    clan.runtime_children = [root]

    now = datetime(2026, 7, 19, 9, 3, 5)
    _, family_suffix, _ = format_agent_option(root, 0, is_selected=False, now=now)
    _, clan_suffix, _ = format_agent_option(clan, 0, is_selected=False, now=now)

    assert family_suffix.plain == "🏃‍♂️ 3m05s / 0s"
    assert " / " in clan_suffix.plain  # never an empty left value
    assert clan_suffix.plain.split(" / ")[0] == "🏃‍♂️ 3m05s"  # never 0s


def test_format_agent_option_clan_ticking_lane_with_no_active_interval_has_no_slash() -> (
    None
):
    clan = _clan_container()
    waiting = agent(
        status="WAITING",
        start=datetime(2026, 7, 19, 9, 0, 0),
        run_start=datetime(2026, 7, 19, 9, 0, 0),
        raw_suffix="waiting",
        cl_name="research.waiting",
    )
    waiting.agent_clan = "research"
    waiting.agent_clan_generation = "gen-1"
    clan.runtime_children = [waiting]

    _, suffix, _ = format_agent_option(
        clan,
        0,
        is_selected=False,
        now=datetime(2026, 7, 19, 9, 5, 0),
    )

    assert suffix.plain == "🏃‍♂️ 5m"
    assert " / " not in suffix.plain


@pytest.mark.asyncio
async def test_patch_active_runtime_rows_advances_clan_lane_and_total() -> None:
    app = AgentListHarness()
    async with app.run_test() as pilot:
        widget = app.query_one(AgentList)
        clan = _clan_container()
        lane_a = agent(
            status="RUNNING",
            start=datetime(2026, 7, 19, 9, 0, 0),
            run_start=datetime(2026, 7, 19, 9, 0, 0),
            raw_suffix="lane-a",
            cl_name="research.a",
        )
        lane_a.agent_clan = "research"
        lane_a.agent_clan_generation = "gen-1"
        clan.runtime_children = [lane_a]

        widget.update_list(
            [clan],
            current_idx=0,
            now=datetime(2026, 7, 19, 9, 5, 3),
        )
        await pilot.pause()

        row = agent_row_index(widget, 0)
        before = widget.get_option_at_index(row).prompt.plain  # type: ignore[union-attr]
        assert before.rstrip().endswith("🏃‍♂️ 5m03s / 5m03s")

        patched = widget.patch_active_runtime_rows(datetime(2026, 7, 19, 9, 5, 8))
        await pilot.pause()

        after = widget.get_option_at_index(row).prompt.plain  # type: ignore[union-attr]
        assert patched == 1
        assert after.rstrip().endswith("🏃‍♂️ 5m08s / 5m08s")


@pytest.mark.asyncio
async def test_clan_runtime_suffix_follows_new_minimum_when_fresh_lane_starts() -> None:
    app = AgentListHarness()
    async with app.run_test() as pilot:
        widget = app.query_one(AgentList)
        clan = _clan_container()
        lane_a = agent(
            status="RUNNING",
            start=datetime(2026, 7, 19, 9, 0, 0),
            run_start=datetime(2026, 7, 19, 9, 0, 0),
            raw_suffix="lane-a",
            cl_name="research.a",
        )
        lane_a.agent_clan = "research"
        lane_a.agent_clan_generation = "gen-1"
        clan.runtime_children = [lane_a]

        widget.update_list(
            [clan],
            current_idx=0,
            now=datetime(2026, 7, 19, 9, 10, 0),
        )
        await pilot.pause()
        row = agent_row_index(widget, 0)
        before = widget.get_option_at_index(row).prompt.plain  # type: ignore[union-attr]
        assert before.rstrip().endswith("🏃‍♂️ 10m / 10m")

        lane_b = agent(
            status="RUNNING",
            start=datetime(2026, 7, 19, 9, 10, 0),
            run_start=datetime(2026, 7, 19, 9, 10, 0),
            raw_suffix="lane-b",
            cl_name="research.b",
        )
        lane_b.agent_clan = "research"
        lane_b.agent_clan_generation = "gen-1"
        clan.runtime_children = [lane_a, lane_b]

        widget.update_list(
            [clan],
            current_idx=0,
            now=datetime(2026, 7, 19, 9, 10, 5),
        )
        await pilot.pause()

        after = widget.get_option_at_index(row).prompt.plain  # type: ignore[union-attr]
        assert after.rstrip().endswith("🏃‍♂️ 5s / 10m05s")

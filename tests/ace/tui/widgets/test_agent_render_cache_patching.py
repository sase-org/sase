"""Tests for AgentList row patching through the render cache path."""

from __future__ import annotations

import pytest
from rich.text import Text

from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.widgets.agent_list import AgentList

from ._agent_render_cache_helpers import (
    AgentListHarness as _Harness,
    agent as _agent,
    agent_row_index as _agent_row_index,
)


def _style_at(text: Text, position: int) -> str | None:
    for span in reversed(text.spans):
        if span.start <= position < span.end:
            return str(span.style)
    return str(text.style) if text.style else None


@pytest.mark.asyncio
async def test_patch_agent_row_replaces_prompt_without_full_rebuild() -> None:
    app = _Harness()
    async with app.run_test() as pilot:
        widget = app.query_one(AgentList)
        a = _agent(approve=False)
        widget.update_list([a], current_idx=0)
        await pilot.pause()
        before_count = widget.option_count
        row = _agent_row_index(widget, 0)
        before_id = widget.get_option_at_index(row).id

        a.approve = True
        ok = widget.patch_agent_row(0)
        await pilot.pause()

        assert ok is True
        # Patch should not change row count or option_id.
        assert widget.option_count == before_count
        assert widget.get_option_at_index(row).id == before_id


@pytest.mark.asyncio
async def test_patch_agent_row_falls_back_when_index_out_of_range() -> None:
    app = _Harness()
    async with app.run_test() as pilot:
        widget = app.query_one(AgentList)
        a = _agent()
        widget.update_list([a], current_idx=0)
        await pilot.pause()
        # Out-of-range index: caller should fall back to a full rebuild.
        assert widget.patch_agent_row(7) is False


@pytest.mark.asyncio
async def test_patch_agent_row_returns_false_when_no_full_render_yet() -> None:
    app = _Harness()
    async with app.run_test() as pilot:
        widget = app.query_one(AgentList)
        # No update_list call -> no per-row context captured. Adding a
        # bare agent without seeding context must trigger fallback.
        widget._agents = [_agent()]
        await pilot.pause()
        assert widget.patch_agent_row(0) is False


@pytest.mark.asyncio
async def test_patch_agent_row_reflects_mark_change() -> None:
    app = _Harness()
    async with app.run_test() as pilot:
        widget = app.query_one(AgentList)
        a = _agent()
        widget.update_list([a], current_idx=0, marked_agents=set())
        await pilot.pause()
        row = _agent_row_index(widget, 0)
        prompt_unmarked = widget.get_option_at_index(row).prompt

        ok = widget.patch_agent_row(0, marked_agents={a.identity})
        await pilot.pause()
        assert ok
        prompt_marked = widget.get_option_at_index(row).prompt
        # The mark glyph "[✓]" appears in the marked render but not the
        # unmarked one, so the cached path must not return the stale Text.
        assert "[✓]" in str(prompt_marked)
        assert "[✓]" not in str(prompt_unmarked)


@pytest.mark.asyncio
async def test_patch_agent_row_reflects_unread_change() -> None:
    app = _Harness()
    async with app.run_test() as pilot:
        widget = app.query_one(AgentList)
        a = _agent()
        widget.update_list([a], current_idx=0, unread_agents={a.identity})
        await pilot.pause()
        row = _agent_row_index(widget, 0)
        prompt_unread = widget.get_option_at_index(row).prompt

        ok = widget.patch_agent_row(0, unread_agents=set())
        await pilot.pause()
        assert ok
        prompt_read = widget.get_option_at_index(row).prompt
        assert "✦" not in str(prompt_unread)
        assert "✅" in str(prompt_unread)
        assert "✦" not in str(prompt_read)
        assert "✅" not in str(prompt_read)


@pytest.mark.asyncio
async def test_patch_family_root_recolors_name_with_first_real_member() -> None:
    app = _Harness()
    async with app.run_test() as pilot:
        widget = app.query_one(AgentList)
        root = _agent(agent_name="demo")
        root.agent_family = "demo"
        root.agent_family_role = "root"
        root.appears_as_agent = True
        synthetic = _agent(
            cl_name="demo--plan",
            agent_name="demo--plan",
            raw_suffix="20260425143001",
        )
        synthetic.is_synthetic_planner = True
        root.followup_agents = [synthetic]

        widget.update_list([root], current_idx=0)
        await pilot.pause()
        row = _agent_row_index(widget, 0)
        prompt_before = widget.get_option_at_index(row).prompt

        root.followup_agents.append(
            _agent(
                cl_name="demo--code",
                agent_name="demo--code",
                raw_suffix="20260425143002",
            )
        )
        assert widget.patch_agent_row(0) is True
        await pilot.pause()
        prompt_after = widget.get_option_at_index(row).prompt

        assert isinstance(prompt_before, Text)
        assert isinstance(prompt_after, Text)
        assert _style_at(prompt_before, prompt_before.plain.rindex("demo")) == "#FFD700"
        assert _style_at(prompt_after, prompt_after.plain.rindex("demo")) == "#00AFFF"


@pytest.mark.asyncio
async def test_patch_clan_row_preserves_latest_panel_context() -> None:
    app = _Harness()
    async with app.run_test() as pilot:
        widget = app.query_one(AgentList)
        clan = _agent(cl_name="research", status="RUNNING")
        clan.is_clan_container = True
        clan.agent_clan = "research"
        clan.clan_tags = ("epic",)

        widget.update_list([clan], current_idx=0, panel_tag="epic")
        await pilot.pause()
        row = _agent_row_index(widget, 0)
        assert "@epic" not in str(widget.get_option_at_index(row).prompt)

        widget.update_list(
            [clan],
            current_idx=0,
            grouping_mode=GroupingMode.BY_STATUS,
            tag_labels=["epic"],
            panel_tag=None,
        )
        await pilot.pause()
        row = _agent_row_index(widget, 0)
        assert str(widget.get_option_at_index(row).prompt).count("@epic") == 1

        clan.status = "DONE"
        assert widget.patch_agent_row(0) is True
        await pilot.pause()
        assert str(widget.get_option_at_index(row).prompt).count("@epic") == 1


@pytest.mark.asyncio
async def test_patch_clan_row_removes_final_unread_chip_without_rebuild() -> None:
    app = _Harness()
    async with app.run_test() as pilot:
        widget = app.query_one(AgentList)
        clan = _agent(cl_name="research", status="DONE", raw_suffix=None)
        clan.is_clan_container = True
        clan.agent_clan = "research"
        clan.agent_clan_generation = "generation"
        member = _agent(cl_name="research.done", status="DONE", raw_suffix="done")
        member.agent_clan = "research"
        member.agent_clan_generation = "generation"
        clan.runtime_children = [member]

        widget.update_list(
            [clan],
            current_idx=0,
            unread_agents={member.identity},
        )
        await pilot.pause()
        row = _agent_row_index(widget, 0)
        assert "[U1]" in str(widget.get_option_at_index(row).prompt)

        assert widget.patch_agent_row(0, unread_agents=set())
        await pilot.pause()

        prompt = str(widget.get_option_at_index(row).prompt)
        assert "[D1]" in prompt
        assert "U1" not in prompt

"""Tests for AgentList row patching through the render cache path."""

from __future__ import annotations

import gc
from datetime import datetime

import pytest
from rich.text import Text

import sase.ace.tui.models.tribe_display as tribe_display
import sase.ace.tui.widgets._agent_list_build_patch_single as patch_single
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.widgets.agent_list import AgentList

from ._agent_render_cache_helpers import (
    AgentListHarness as _Harness,
    agent as _agent,
    agent_row_index as _agent_row_index,
    style_at as _style_at,
)


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
async def test_patch_agent_session_root_recolors_name_with_first_real_member() -> None:
    app = _Harness()
    async with app.run_test() as pilot:
        widget = app.query_one(AgentList)
        root = _agent(agent_name="demo")
        root.agent_session = "demo"
        root.agent_session_role = "root"
        root.appears_as_agent = True

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
        clan.clan_tribes = ("epic",)

        widget.update_list([clan], current_idx=0, panel_tribe="epic")
        await pilot.pause()
        row = _agent_row_index(widget, 0)
        assert "@epic" not in str(widget.get_option_at_index(row).prompt)

        widget.update_list(
            [clan],
            current_idx=0,
            grouping_mode=GroupingMode.BY_STATUS,
            tribe_labels=["epic"],
            panel_tribe=None,
        )
        await pilot.pause()
        row = _agent_row_index(widget, 0)
        assert str(widget.get_option_at_index(row).prompt).count("@epic") == 1

        clan.status = "DONE"
        assert widget.patch_agent_row(0) is True
        await pilot.pause()
        assert str(widget.get_option_at_index(row).prompt).count("@epic") == 1


@pytest.mark.asyncio
async def test_patch_agent_row_keeps_synthesized_default_tribe_label_hidden() -> None:
    app = _Harness()
    async with app.run_test() as pilot:
        widget = app.query_one(AgentList)
        agent = _agent(status="RUNNING")
        widget.update_list(
            [agent],
            current_idx=0,
            tribe_labels=["default"],
        )
        await pilot.pause()
        row = _agent_row_index(widget, 0)
        assert "@default" not in str(widget.get_option_at_index(row).prompt)

        agent.status = "DONE"
        assert widget.patch_agent_row(0) is True
        await pilot.pause()

        patched = str(widget.get_option_at_index(row).prompt)
        assert "@default" not in patched
        assert "DONE" in patched


@pytest.mark.asyncio
async def test_full_rebuild_refreshes_tribe_colors_reused_by_patch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = [1]
    colors = {1: "#123456", 2: "#654321"}
    monkeypatch.setattr(
        tribe_display,
        "load_merged_config",
        lambda: {
            "ace": {
                "tribes": {
                    "epic": {"color": colors[token[0]]},
                }
            }
        },
    )
    monkeypatch.setattr(
        tribe_display,
        "current_config_token",
        lambda: ("patch-tribe-color", token[0]),
    )
    tribe_display._tribe_displays_for_token.cache_clear()

    app = _Harness()
    async with app.run_test() as pilot:
        widget = app.query_one(AgentList)
        agent = _agent()
        widget.update_list(
            [agent],
            current_idx=0,
            tribe_labels=["epic"],
        )
        await pilot.pause()
        row = _agent_row_index(widget, 0)
        first = widget.get_option_at_index(row).prompt
        assert isinstance(first, Text)
        assert _style_at(first, first.plain.index("@epic")) == "bold #123456"

        token[0] = 2
        widget.update_list(
            [agent],
            current_idx=0,
            tribe_labels=["epic"],
        )
        await pilot.pause()
        second = widget.get_option_at_index(row).prompt
        assert isinstance(second, Text)
        assert _style_at(second, second.plain.index("@epic")) == "bold #654321"

        agent.status = "DONE"
        assert widget.patch_agent_row(0) is True
        await pilot.pause()
        patched = widget.get_option_at_index(row).prompt
        assert isinstance(patched, Text)
        assert _style_at(patched, patched.plain.index("@epic")) == "bold #654321"


@pytest.mark.asyncio
async def test_patch_agent_row_skips_replace_when_inputs_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated patches with identical inputs must not rebuild or replace.

    Render-allocation: an unchanged row keeps its Option without calling
    ``replace_option_prompt_at_index``, so repeated no-op patches build no
    Text/Strip trees and leave no cyclic garbage behind.
    """
    app = _Harness()
    async with app.run_test() as pilot:
        widget = app.query_one(AgentList)
        agents = [
            _agent(cl_name=f"demo{i:02d}", raw_suffix=f"2026042514{i:04d}")
            for i in range(5)
        ]
        now = datetime(2026, 4, 25, 14, 0, 0)
        widget.update_list(agents, current_idx=2, now=now)
        await pilot.pause()

        replaces = 0
        orig_replace = AgentList.replace_option_prompt_at_index

        def counting_replace(self: AgentList, index: int, prompt: object) -> object:
            nonlocal replaces
            replaces += 1
            return orig_replace(self, index, prompt)  # type: ignore[arg-type]

        monkeypatch.setattr(
            AgentList, "replace_option_prompt_at_index", counting_replace
        )

        renders = 0
        orig_cached = patch_single.cached_format_agent_option

        def counting_cached(*args: object, **kwargs: object) -> object:
            nonlocal renders
            renders += 1
            return orig_cached(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(patch_single, "cached_format_agent_option", counting_cached)

        assembles = 0
        orig_assemble = patch_single.assemble_padded_option

        def counting_assemble(*args: object, **kwargs: object) -> object:
            nonlocal assembles
            assembles += 1
            return orig_assemble(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(patch_single, "assemble_padded_option", counting_assemble)

        prompts_before = [
            widget.get_option_at_index(_agent_row_index(widget, i)).prompt
            for i in range(5)
        ]
        for i in range(5):
            assert widget.patch_agent_row(i, now=now) is True
        await pilot.pause()

        assert replaces == 0
        assert renders == 0
        assert assembles == 0
        for i in range(5):
            after = widget.get_option_at_index(_agent_row_index(widget, i)).prompt
            assert after is prompts_before[i]

        garbage_before = len(gc.garbage)
        del prompts_before
        gc.collect()
        assert len(gc.garbage) == garbage_before


@pytest.mark.asyncio
async def test_patch_agent_row_repaints_on_visible_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Changed selection, status, style, width, and fleet inputs still repaint."""
    app = _Harness()
    async with app.run_test() as pilot:
        widget = app.query_one(AgentList)
        a = _agent()
        widget.update_list([a], current_idx=0)
        await pilot.pause()
        row = _agent_row_index(widget, 0)

        replaces: list[int] = []
        orig_replace = AgentList.replace_option_prompt_at_index

        def counting_replace(self: AgentList, index: int, prompt: object) -> object:
            replaces.append(index)
            return orig_replace(self, index, prompt)  # type: ignore[arg-type]

        monkeypatch.setattr(
            AgentList, "replace_option_prompt_at_index", counting_replace
        )

        # No-op patch first: nothing to replace (row starts selected).
        assert widget.patch_agent_row(0) is True
        assert replaces == []

        # Selection flip repaints once, then the same selection skips.
        assert widget.patch_agent_row(0, is_selected=False) is True
        assert replaces == [row]
        unselected_prompt = widget.get_option_at_index(row).prompt
        assert widget.patch_agent_row(0, is_selected=False) is True
        assert replaces == [row]
        assert widget.get_option_at_index(row).prompt is unselected_prompt

        # Status change repaints.
        a.status = "RUNNING"
        assert widget.patch_agent_row(0, is_selected=False) is True
        assert replaces == [row, row]

        # Tier-guide (theme/resize chrome) change repaints.
        widget._row_tier_styles[0] = ("bold #FF0000",)
        assert widget.patch_agent_row(0, is_selected=False) is True
        assert replaces == [row, row, row]

        # Fleet input change repaints.
        a.fleet_origin_alias = "apollo"
        assert widget.patch_agent_row(0, is_selected=False) is True
        assert replaces == [row, row, row, row]

        # Target-width change repaints even with identical row inputs.
        widget._target_width += 4
        assert widget.patch_agent_row(0, is_selected=False) is True
        assert replaces == [row, row, row, row, row]


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

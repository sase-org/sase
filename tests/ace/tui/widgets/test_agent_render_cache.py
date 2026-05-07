"""Tests for the per-row render cache and selective patch path.

Phase 3 of sdd/tales/202604/instant_jk_navigation.md (bead sase-u.3).
"""

from __future__ import annotations

from datetime import datetime

import pytest
from textual.app import App

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets._agent_list_rendering import (
    AgentRenderCache,
    agent_render_key,
    cached_format_agent_option,
)
from sase.ace.tui.widgets.agent_list import AgentList


def _agent(
    *,
    cl_name: str = "demo",
    status: str = "DONE",
    approve: bool = False,
    agent_name: str | None = None,
    raw_suffix: str = "20260425143000",
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/p.gp",
        status=status,
        start_time=datetime(2026, 4, 25, 14, 30, 0),
        approve=approve,
        agent_name=agent_name,
        raw_suffix=raw_suffix,
    )


# --- render-key extraction ---------------------------------------------------


def test_render_key_changes_when_approve_flips() -> None:
    a = _agent(approve=False)
    k1 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=None,
    )
    a.approve = True
    k2 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=None,
    )
    assert k1 != k2


def test_render_key_stable_for_unchanged_inputs() -> None:
    a = _agent()
    k1 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=None,
    )
    k2 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=None,
    )
    assert k1 == k2


def test_render_key_changes_when_tag_label_changes() -> None:
    a = _agent()
    k1 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        tag_label="alpha",
        now=None,
    )
    k2 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        tag_label="beta",
        now=None,
    )
    assert k1 != k2


def test_render_key_changes_when_unread_flips() -> None:
    a = _agent()
    k1 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        is_unread=False,
        hint_char=None,
        now=None,
    )
    k2 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        is_unread=True,
        hint_char=None,
        now=None,
    )
    assert k1 != k2


def test_render_key_changes_when_bead_agent_name_changes() -> None:
    a = _agent(agent_name="sase-x.3")
    k1 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=None,
    )
    assert "sase-x.3" in k1

    a.agent_name = "sase-x.land"
    k2 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=None,
    )

    assert "sase-x" in k2
    assert k1 != k2


def test_render_key_changes_across_seconds_for_ticking_parent_status() -> None:
    a = _agent(status="PLAN APPROVED")
    a.runtime_children.append(
        _agent(
            cl_name="demo.code",
            status="RUNNING",
            raw_suffix="20260425143100",
        )
    )

    k1 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=datetime(2026, 4, 25, 14, 30, 1),
    )
    k2 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=datetime(2026, 4, 25, 14, 30, 2),
    )

    assert k1 != k2


def test_render_key_changes_when_plan_runtime_timestamp_changes() -> None:
    a = _agent(status="DONE")

    k1 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=datetime(2026, 4, 25, 14, 30, 1),
    )
    a.plan_times.append(datetime(2026, 4, 25, 14, 35, 0))
    k2 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=datetime(2026, 4, 25, 14, 30, 1),
    )

    assert k1 != k2


def test_render_key_changes_when_code_runtime_timestamp_changes() -> None:
    a = _agent(status="PLAN APPROVED")
    a.plan_times.append(datetime(2026, 4, 25, 14, 35, 0))

    k1 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=datetime(2026, 4, 25, 14, 40, 1),
    )
    a.code_time = datetime(2026, 4, 25, 14, 36, 0)
    k2 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=datetime(2026, 4, 25, 14, 40, 1),
    )

    assert k1 != k2


# --- cache hit / miss --------------------------------------------------------


def test_cached_format_agent_option_reuses_result_on_repeat_call() -> None:
    cache = AgentRenderCache()
    a = _agent()
    parts1 = cached_format_agent_option(cache, a, 0, is_selected=False, now=None)
    parts2 = cached_format_agent_option(cache, a, 0, is_selected=False, now=None)
    # Same identity returned: cache hit reuses the Text triple.
    assert parts1[0] is parts2[0]
    assert parts1[1] is parts2[1]
    assert parts1[2] == parts2[2]


def test_cached_format_agent_option_invalidates_on_field_change() -> None:
    cache = AgentRenderCache()
    a = _agent(approve=False)
    parts_before = cached_format_agent_option(cache, a, 0, is_selected=False, now=None)
    a.approve = True
    parts_after = cached_format_agent_option(cache, a, 0, is_selected=False, now=None)
    # Different cache key → different cached entry → different Text instance.
    assert parts_before[0] is not parts_after[0]


def test_cached_format_agent_option_invalidates_on_unread_change() -> None:
    cache = AgentRenderCache()
    a = _agent()
    parts_before = cached_format_agent_option(
        cache, a, 0, is_selected=False, is_unread=False, now=None
    )
    parts_after = cached_format_agent_option(
        cache, a, 0, is_selected=False, is_unread=True, now=None
    )
    assert parts_before[0] is not parts_after[0]
    assert "✦" not in parts_before[0].plain
    assert "✦" in parts_after[0].plain


def test_invalidate_agent_drops_only_that_identity() -> None:
    cache = AgentRenderCache()
    a = _agent(cl_name="alpha")
    b = _agent(cl_name="beta", raw_suffix="20260425143001")
    cached_format_agent_option(cache, a, 0, is_selected=False, now=None)
    cached_format_agent_option(cache, b, 1, is_selected=False, now=None)
    assert len(cache._agent) == 2
    cache.invalidate_agent(a.identity)
    assert len(cache._agent) == 1
    # Surviving entry belongs to ``b``.
    surviving_key = next(iter(cache._agent))
    assert surviving_key[0] == b.identity


# --- patch_agent_row API -----------------------------------------------------


class _Harness(App):
    """Mount a single AgentList for the patch tests."""

    def compose(self):
        yield AgentList(id="agent-list")


def _agent_row_index(widget: AgentList, agent_idx: int) -> int:
    """Resolve the OptionList row index for ``agent_idx`` in *widget*."""
    return widget._row_index_for_agent(agent_idx)  # type: ignore[return-value]


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
        # No update_list call → no per-row context captured. Adding a
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
        # unmarked one — the cached path must not return the stale Text.
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
        assert "✦" in str(prompt_unread)
        assert "✦" not in str(prompt_read)

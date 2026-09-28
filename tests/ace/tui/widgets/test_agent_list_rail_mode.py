"""Tests for the paint-time rail projection (rail-projection phase).

``AgentList.set_rail`` switches the list into a fixed-width rail density
without rebuilding: Textual keeps routing through ``_get_visual``, so the
override paints rail cells for each existing ``Option``. These tests mount a
tiny app because rail visuals need an active app console.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rich.text import Text
from textual.app import App, ComposeResult
from textual.style import Style

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.widgets._agent_list_render_rail import (
    RAIL_CONTENT_CELLS,
    rail_tooltip_text,
)
from sase.ace.tui.widgets._agent_list_styling import BANNER_ROW
from sase.ace.tui.widgets.agent_list import AgentList

BY_STATUS = GroupingMode.BY_STATUS


def _agent(
    name: str,
    minute: int,
    *,
    status: str = "RUNNING",
    project_file: str = "/repo/proj.sase",
    **fields: Any,
) -> Agent:
    return Agent(
        agent_type=fields.pop("agent_type", AgentType.RUNNING),
        cl_name="demo",
        project_file=project_file,
        status=status,
        start_time=datetime(2026, 4, 25, 12, minute, 0),
        agent_name=name,
        raw_suffix=f"2026042512{minute:02d}00",
        **fields,
    )


class _RailApp(App[None]):
    """Minimal app hosting one agent list."""

    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield AgentList(id="agent-list")


def _agent_cells(widget: AgentList) -> dict[Any, str]:
    """Map agent identity to its current rail cells plain text."""
    cells: dict[Any, str] = {}
    for row, (local_idx, _attempt) in enumerate(widget._row_entries):
        if local_idx == BANNER_ROW:
            continue
        option = widget.get_option_at_index(row)
        text = widget._rail_cells_for_option(option)
        assert text is not None
        cells[widget._agents[local_idx].identity] = text.plain
    return cells


def _assert_group_map_covers_banners(widget: AgentList) -> None:
    """Every non-spacer banner row is in the all-banner rail maps."""
    for row, (local_idx, _attempt) in enumerate(widget._row_entries):
        if local_idx != BANNER_ROW:
            continue
        option = widget.get_option_at_index(row)
        if str(option.id or "").startswith("spacer:"):
            continue
        assert row in widget._group_at_row
        assert row in widget._banner_hint_at_row
        assert row in widget._banner_mark_at_row


async def test_set_rail_keeps_options_highlight_scroll_and_expanded_visuals() -> None:
    """Toggling the rail repaints without rebuilding or touching _visual."""
    app = _RailApp()
    async with app.run_test(size=(60, 20)) as pilot:
        await pilot.pause()
        widget = app.query_one(AgentList)
        agents = [_agent(f"node-{i:02d}", i) for i in range(4)]
        widget.update_list(agents, 1, grouping_mode=BY_STATUS)
        await pilot.pause()

        before = list(widget._options)
        before_visuals = [option._visual for option in before]
        before_highlight = widget.highlighted
        before_scroll = widget.scroll_offset
        before_count = widget.option_count

        widget.set_rail(True)
        await pilot.pause()

        assert widget.option_count == before_count
        assert len(widget._options) == len(before)
        assert all(new is old for new, old in zip(widget._options, before, strict=True))
        assert widget.highlighted == before_highlight
        assert widget.scroll_offset == before_scroll
        # The rail served visuals from its own cache: expanded _visuals kept.
        assert [option._visual for option in widget._options] == before_visuals
        for option in widget._options:
            assert widget._get_visual(option) is not None
        assert [option._visual for option in widget._options] == before_visuals

        # A redundant toggle is a no-op.
        cache = widget._rail_visual_cache
        widget.set_rail(True)
        assert widget._rail_visual_cache is cache

        widget.set_rail(False)
        await pilot.pause()
        assert all(new is old for new, old in zip(widget._options, before, strict=True))
        assert widget.highlighted == before_highlight
        assert [option._visual for option in widget._options] == before_visuals


async def test_rail_rows_are_single_lines_with_six_content_cells() -> None:
    """Every rail row is one line and every cell run is six cells wide."""
    app = _RailApp()
    async with app.run_test(size=(60, 20)) as pilot:
        await pilot.pause()
        widget = app.query_one(AgentList)
        agents = [
            _agent("need-you", 1, status="STOPPED"),
            _agent("failed", 2, status="FAILED"),
            _agent("running", 3, status="RUNNING"),
            _agent("done", 4, status="DONE"),
        ]
        widget.update_list(agents, 0, grouping_mode=BY_STATUS)
        widget.set_rail(True)
        await pilot.pause()

        assert set(widget._line_cache.heights.values()) == {1}
        assert len(widget._line_cache.lines) == widget.option_count
        for option in widget._options:
            text = widget._rail_cells_for_option(option)
            if text is None:
                # Spacers render blank.
                continue
            assert text.cell_len == RAIL_CONTENT_CELLS
        _assert_group_map_covers_banners(widget)


async def test_patch_row_repaints_glyph_in_rail_mode() -> None:
    """A patched status busts the prompt-identity rail cache entry."""
    app = _RailApp()
    async with app.run_test(size=(60, 20)) as pilot:
        await pilot.pause()
        widget = app.query_one(AgentList)
        widget.update_list([_agent("node-00", 0)], 0, grouping_mode=BY_STATUS)
        widget.set_rail(True)
        await pilot.pause()

        row = widget._row_by_agent_idx[0]
        option = widget.get_option_at_index(row)
        before_visual = widget._get_visual(option)
        before_prompt = option.prompt
        assert "▶" in (widget._rail_cells_for_option(option) or Text("")).plain

        widget._agents[0].status = "FAILED"
        assert widget.patch_agent_row(0) is True
        await pilot.pause()

        assert option.prompt is not before_prompt
        after_visual = widget._get_visual(option)
        assert after_visual is not before_visual
        assert "✗" in (widget._rail_cells_for_option(option) or Text("")).plain


async def test_insert_in_rail_mode_keeps_shifted_cells() -> None:
    """In-place inserts repaint shifted rows with correct rail cells."""
    app = _RailApp()
    async with app.run_test(size=(60, 20)) as pilot:
        await pilot.pause()
        widget = app.query_one(AgentList)
        agents = [_agent(f"node-{i:02d}", i) for i in range(4)]
        widget.update_list(agents, 0, grouping_mode=BY_STATUS)
        widget.set_rail(True)
        await pilot.pause()

        before = _agent_cells(widget)
        before_count = widget.option_count

        grown = agents[:2] + [_agent("node-04", 30)] + agents[2:]
        assert widget.try_insert_rows(grown, 0, grouping_mode=BY_STATUS) is True
        await pilot.pause()

        assert widget.option_count == before_count + 1
        after = _agent_cells(widget)
        for identity, plain in before.items():
            assert after[identity] == plain
        assert "▶" in after[_agent("node-04", 30).identity]
        _assert_group_map_covers_banners(widget)


async def test_remove_in_rail_mode_keeps_shifted_cells() -> None:
    """Optimistic removes remap the rail maps with the shifted rows."""
    app = _RailApp()
    async with app.run_test(size=(60, 20)) as pilot:
        await pilot.pause()
        widget = app.query_one(AgentList)
        agents = [_agent(f"node-{i:02d}", i) for i in range(4)]
        widget.update_list(agents, 0, grouping_mode=BY_STATUS)
        widget.set_rail(True)
        await pilot.pause()

        before = _agent_cells(widget)
        before_count = widget.option_count
        removed = agents[1].identity
        del before[removed]

        assert widget.try_remove_rows({removed}) is True
        await pilot.pause()

        assert widget.option_count == before_count - 1
        assert _agent_cells(widget) == before
        _assert_group_map_covers_banners(widget)


async def test_folded_rows_absent_and_counts_match_across_densities() -> None:
    """Folds stay authoritative and the rail never adds or drops rows."""
    app = _RailApp()
    async with app.run_test(size=(60, 20)) as pilot:
        await pilot.pause()
        widget = app.query_one(AgentList)
        registry = AgentGroupFoldRegistry()
        registry.collapse(("projA",))
        widget.update_list(
            [
                _agent("a", 1, project_file="/r/projA/proj.sase"),
                _agent("b", 2, project_file="/r/projB/proj.sase"),
            ],
            1,
            fold_registry=registry,
        )
        await pilot.pause()
        expanded_count = widget.option_count

        widget.set_rail(True)
        await pilot.pause()

        assert widget.option_count == expanded_count
        # The folded projA member has no row in either density.
        assert widget._row_by_agent_idx.keys() == {1}
        # The all-banner map covers the collapsed and the expanded banner.
        assert len(widget._group_at_row) >= 2
        assert set(widget._banner_at_row) < set(widget._group_at_row)
        for option in widget._options:
            assert widget._get_visual(option) is not None


async def test_overflow_subtitle_tracks_scrolling() -> None:
    """The rail subtitle names rows above/below the viewport."""
    app = _RailApp()
    async with app.run_test(size=(40, 12)) as pilot:
        await pilot.pause()
        widget = app.query_one(AgentList)
        agents = [_agent(f"node-{i:02d}", i) for i in range(15)]
        widget.update_list(agents, 0, grouping_mode=BY_STATUS)
        widget.set_rail(True)
        await pilot.pause()

        total = widget.virtual_size.height
        viewport = widget.scrollable_content_region.height
        assert total > viewport

        subtitle = widget.border_subtitle
        plain = subtitle.plain if isinstance(subtitle, Text) else str(subtitle)
        assert "▾" in plain
        assert "▴" not in plain

        widget.scroll_to(y=total - viewport, animate=False)
        await pilot.pause()
        subtitle = widget.border_subtitle
        plain = subtitle.plain if isinstance(subtitle, Text) else str(subtitle)
        assert "▴" in plain

        widget.scroll_to(y=0, animate=False)
        await pilot.pause()
        subtitle = widget.border_subtitle
        plain = subtitle.plain if isinstance(subtitle, Text) else str(subtitle)
        assert "▾" in plain
        assert "▴" not in plain


async def test_rail_hover_sets_tooltip_to_expanded_prompt() -> None:
    """Hovering a rail row shows its full expanded text as a tooltip."""
    from textual.events import Leave

    app = _RailApp()
    async with app.run_test(size=(60, 20)) as pilot:
        await pilot.pause()
        widget = app.query_one(AgentList)
        agents = [_agent(f"node-{i:02d}", i) for i in range(4)]
        widget.update_list(agents, 1, grouping_mode=BY_STATUS)
        widget.set_rail(True)
        await pilot.pause()

        row = next(
            row
            for row, (local_idx, _attempt) in enumerate(widget._row_entries)
            if local_idx != BANNER_ROW
        )
        option = widget.get_option_at_index(row)
        expected = rail_tooltip_text(option.prompt)
        assert expected is not None

        assert widget.tooltip is None
        # Content starts below the 1-cell top border.
        landed = await pilot.hover(AgentList, offset=(2, row + 1))
        await pilot.pause()
        assert landed
        assert widget._mouse_hovering_over == row
        assert widget.tooltip is not None
        assert widget.tooltip.plain == expected.plain

        # Leaving the list and disabling the rail both clear the tooltip.
        widget._on_leave(Leave(widget))
        assert widget.tooltip is None
        await pilot.hover(AgentList, offset=(2, row + 1))
        await pilot.pause()
        assert widget.tooltip is not None
        widget.set_rail(False)
        assert widget.tooltip is None


async def test_textual_routes_update_lines_and_option_render_through_get_visual(
    monkeypatch: Any,
) -> None:
    """Guard: a Textual upgrade that bypasses _get_visual fails loudly."""
    app = _RailApp()
    async with app.run_test(size=(60, 20)) as pilot:
        await pilot.pause()
        widget = app.query_one(AgentList)
        calls = 0
        original = AgentList._get_visual

        def counting(self: AgentList, option: Any) -> Any:
            nonlocal calls
            calls += 1
            return original(self, option)

        monkeypatch.setattr(AgentList, "_get_visual", counting)
        widget.update_list([_agent(f"node-{i:02d}", i) for i in range(3)], 0)
        await pilot.pause()
        assert calls > 0

        widget._clear_caches()
        calls = 0
        widget._update_lines()
        assert calls == widget.option_count

        widget._clear_caches()
        calls = 0
        widget._get_option_render(widget.get_option_at_index(0), Style())
        assert calls >= 1

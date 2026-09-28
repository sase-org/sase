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


async def test_spacer_rows_render_without_rail_fallback_trace(
    monkeypatch: Any,
) -> None:
    """Spacer rows return blank cells directly, never the fallback path."""
    from sase.ace.tui.widgets import _agent_list_rail_mode

    events: list[str] = []
    monkeypatch.setattr(
        _agent_list_rail_mode,
        "trace_event",
        lambda event, **fields: events.append(event),
    )

    app = _RailApp()
    async with app.run_test(size=(60, 20)) as pilot:
        await pilot.pause()
        widget = app.query_one(AgentList)
        agents = [
            _agent("running", 1, status="RUNNING"),
            _agent("done", 2, status="DONE"),
        ]
        widget.update_list(agents, 0, grouping_mode=BY_STATUS)
        widget.set_rail(True)
        await pilot.pause()

        spacer_options = [
            option
            for option in widget._options
            if str(option.id or "").startswith("spacer:")
        ]
        assert spacer_options

        widget._rail_visual_cache.clear()
        for option in widget._options:
            widget._get_visual(option)
        for option in spacer_options:
            text = widget._rail_cells_for_option(option)
            assert text is not None
            assert text.plain == " " * RAIL_CONTENT_CELLS

    assert "widget.agent_list.rail_fallback" not in events


def _named_agent(name: str, minute: int, **fields: Any) -> Agent:
    return _agent(name, minute, **fields)


async def test_anchor_map_depth_stack_and_banner_reset() -> None:
    """Anchor map points children at parents and resets at banners."""
    from sase.ace.tui.widgets._agent_list_styling import BANNER_ROW

    app = _RailApp()
    async with app.run_test(size=(60, 20)) as pilot:
        await pilot.pause()
        widget = app.query_one(AgentList)
        parent = _named_agent("alpha", 1)
        child = _named_agent("alpha.cld", 2, tree_depth=1)
        grandchild = _named_agent("alpha.cld.x", 3, tree_depth=2)
        sibling = _named_agent("beta", 4)
        widget._agents = [parent, child, grandchild, sibling]
        widget._row_entries = [
            (0, None),
            (1, None),
            (2, None),
            (BANNER_ROW, None),
            (3, None),
        ]
        widget._rail_anchor_rows = None
        anchors = widget._build_rail_anchor_map()
        assert anchors.get(1) == 0
        assert anchors.get(2) == 1
        assert 4 not in anchors


async def test_anchor_map_clamps_depth_beyond_max() -> None:
    """A depth-4 row anchors to the ancestor its clamped guides point to."""
    from sase.ace.tui.widgets._agent_list_styling import BANNER_ROW
    from sase.ace.tui.widgets._agent_list_render_rail import RAIL_MAX_DEPTH

    assert RAIL_MAX_DEPTH == 3
    app = _RailApp()
    async with app.run_test(size=(60, 20)) as pilot:
        await pilot.pause()
        widget = app.query_one(AgentList)
        rows = [
            _named_agent("a", 1),
            _named_agent("a.7", 2, tree_depth=1),
            _named_agent("a.7.5", 3, tree_depth=2),
            _named_agent("a.7.5.2", 4, tree_depth=4),
        ]
        widget._agents = rows
        widget._row_entries = [(i, None) for i in range(4)]
        widget._rail_anchor_rows = None
        anchors = widget._build_rail_anchor_map()
        assert anchors.get(3) == 2


async def test_anchor_rename_busts_child_but_unrelated_patch_keeps_cache() -> None:
    """Patching an anchor re-renders children; unrelated patches do not."""
    app = _RailApp()
    async with app.run_test(size=(60, 20)) as pilot:
        await pilot.pause()
        widget = app.query_one(AgentList)
        parent = _named_agent("alpha", 1)
        child = _named_agent(
            "alpha.cld", 2, parent_timestamp="20260425120100", tree_depth=1
        )
        other = _named_agent("other", 3)
        agents = [parent, child, other]
        widget.update_list(agents, 0, grouping_mode=BY_STATUS)
        widget.set_rail(True)
        await pilot.pause()

        child_row = widget._row_by_agent_idx[1]
        child_option = widget.get_option_at_index(child_row)
        before_cells = (widget._rail_cells_for_option(child_option) or Text("")).plain
        assert ".cld" in before_cells
        before_visual = widget._get_visual(child_option)

        other_row = widget._row_by_agent_idx[2]
        other_option = widget.get_option_at_index(other_row)
        other_before = widget._get_visual(other_option)

        # Unrelated patch leaves the child cached.
        widget._agents[2].status = "FAILED"
        assert widget.patch_agent_row(2) is True
        await pilot.pause()
        assert widget._get_visual(child_option) is before_visual

        # Renaming the anchor busts the child's cache and full name returns.
        widget._agents[0].agent_name = "beta"
        widget._agents[0].refresh_raw_presented_agent_name()
        assert widget.patch_agent_row(0) is True
        await pilot.pause()
        after_visual = widget._get_visual(child_option)
        assert after_visual is not before_visual
        after_cells = (widget._rail_cells_for_option(child_option) or Text("")).plain
        assert "alpha.cld" in after_cells
        assert other_before is not None


async def test_structural_paths_reset_anchor_map() -> None:
    """Structural paths drop the anchor map; fallback never raises."""
    app = _RailApp()
    async with app.run_test(size=(60, 20)) as pilot:
        await pilot.pause()
        widget = app.query_one(AgentList)
        widget.update_list([_agent("node-00", 0)], 0, grouping_mode=BY_STATUS)
        widget.set_rail(True)
        await pilot.pause()
        assert widget._rail_anchor_map() is not None
        widget._rail_rows_changed()
        assert widget._rail_anchor_rows is None
        widget.set_rail(False)
        widget.set_rail(True)
        assert widget._rail_anchor_rows is None
        # Fallback on unknown options never raises and traces blank cells.
        from textual.widgets.option_list import Option

        assert widget._rail_cells_for_option(Option(Text("nope"))) is None
        assert widget._get_visual(Option(Text("nope"))) is not None

"""Pilot tests for wiring the node rail into the Agents tab (rail-wiring).

``Ctrl+S`` now projects the tribe lists into rail form at a fixed width
instead of hiding them behind ``NodeSpine``: focus stays on the list, panel
titles go rail-aware, runtime ticks pause with a catch-up on expand, and the
info-row nodes chip expands the rail on click.
"""

from __future__ import annotations

from datetime import datetime

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets import AgentDetail, AgentList
from sase.ace.tui.widgets._agent_list_render_rail import NODE_RAIL_WIDTH
from sase.ace.tui.widgets.agent_info_panel import AgentInfoPanel
from sase.ace.tui.widgets.decks.layout import SidebarMode
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)


def _agent(
    name: str,
    status: str,
    minute: int,
    *,
    tribe: str = "sase",
    project: str = "/workspace/sase/rail.sase",
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=f"rail-{name}",
        project_file=project,
        status=status,
        start_time=datetime(2026, 9, 27, 10, minute, 0),
        run_start_time=datetime(2026, 9, 27, 10, minute, 0),
        raw_suffix=f"2026092710{minute:02d}00-rail-{name}",
        agent_name=f"rail.{name}",
        tribe=tribe,
        llm_provider="codex",
        model="gpt-5",
    )


def _agents() -> list[Agent]:
    return [
        _agent("asking", "QUESTION", 0),
        _agent("failed", "FAILED", 1),
        _agent("running", "RUNNING", 2),
        _agent("done", "DONE", 3),
    ]


async def _goto_agents(page: AcePage, count: int) -> AgentDetail:
    await wait_for_startup(page)
    await page.press("shift+tab")
    await page.expect_state("tab", "agents")
    await page.expect_state("agent_count", count)
    await wait_for_visual_idle(page)
    return page.app.query_one("#agent-detail-panel", AgentDetail)


def _lists(page: AcePage) -> list[AgentList]:
    container = page.app.query_one("#agent-list-container")
    return [
        widget
        for widget in container.query(AgentList).results(AgentList)
        if not getattr(widget, "_panel_retiring", False)
    ]


async def test_rail_toggle_clamps_container_and_restores_width(
    monkeypatch,
) -> None:
    """Ctrl+S clamps the list column to the rail width, then restores it."""
    patch_startup_loaders(monkeypatch, agents=_agents())
    async with AcePage(query='"visual"', patches=patches()) as page:
        detail = await _goto_agents(page, 4)
        container = page.app.query_one("#agent-list-container")
        await wait_for_visual_idle(page)
        expanded_width = container.region.width
        assert expanded_width > NODE_RAIL_WIDTH

        await page.press("ctrl+s")
        await wait_for_visual_idle(page)
        assert detail.sidebar_mode is SidebarMode.RAIL
        # The inline width still tracks the negotiated expanded width
        # underneath; max-width clamps what is rendered.
        assert int(container.styles.width.value) == expanded_width
        assert container.region.width == NODE_RAIL_WIDTH
        assert all(widget._rail_enabled for widget in _lists(page))

        await page.press("ctrl+s")
        await wait_for_visual_idle(page)
        assert detail.sidebar_mode is SidebarMode.EXPANDED
        assert container.region.width == expanded_width
        assert not any(widget._rail_enabled for widget in _lists(page))


async def test_rail_keeps_focus_and_jk_navigation(monkeypatch) -> None:
    """Focus stays on the list in rail mode and j/k moves the highlight."""
    patch_startup_loaders(monkeypatch, agents=_agents())
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _goto_agents(page, 4)
        await page.press("ctrl+s")
        await wait_for_visual_idle(page)
        focused = page.app.focused
        assert isinstance(focused, AgentList)
        before = page.app.current_idx
        await page.press("j")
        await wait_for_visual_idle(page)
        assert isinstance(page.app.focused, AgentList)
        stepped = page.app.current_idx
        assert stepped != before
        await page.press("k")
        await wait_for_visual_idle(page)
        assert isinstance(page.app.focused, AgentList)
        assert page.app.current_idx == before


async def test_rail_preserves_row_positions_and_scroll(monkeypatch) -> None:
    """Toggling the rail never moves a row vertically or the scroll offset."""
    patch_startup_loaders(monkeypatch, agents=_agents())
    # A viewport this small makes the sase panel overflow (9 options at this
    # fixture's grouping don't fit in 6 content rows), so scrolling to a
    # non-zero offset before toggling actually exercises the scroll-position
    # guarantee instead of trivially passing at offset 0.
    async with AcePage(query='"visual"', patches=patches(), size=(90, 16)) as page:
        await _goto_agents(page, 4)
        widget = _lists(page)[0]
        rows_before = [widget.get_option_at_index(i).id for i in range(4)]

        max_scroll = (
            widget.virtual_size.height - widget.scrollable_content_region.height
        )
        assert max_scroll > 0
        widget.scroll_to(y=max_scroll, animate=False)
        await wait_for_visual_idle(page)
        scroll_before = widget.scroll_offset
        assert scroll_before.y > 0
        highlighted_before = widget.highlighted
        assert highlighted_before is not None
        line_before = widget._index_to_line[highlighted_before]
        region_y_before = widget.region.y

        await page.press("ctrl+s")
        await wait_for_visual_idle(page)
        assert widget.scroll_offset == scroll_before
        rows_rail = [widget.get_option_at_index(i).id for i in range(4)]
        assert rows_rail == rows_before
        rail_ys = [widget.get_option_at_index(i) for i in range(4)]
        assert all(option is not None for option in rail_ys)
        assert widget.highlighted == highlighted_before
        assert widget._index_to_line[widget.highlighted] == line_before
        assert widget.region.y == region_y_before

        await page.press("ctrl+s")
        await wait_for_visual_idle(page)
        assert widget.scroll_offset == scroll_before
        assert [widget.get_option_at_index(i).id for i in range(4)] == rows_before
        assert widget.highlighted == highlighted_before
        assert widget._index_to_line[widget.highlighted] == line_before
        assert widget.region.y == region_y_before


async def test_split_in_rail_keeps_rail(monkeypatch) -> None:
    """Opening a deck split while railed keeps the rail projection."""
    patch_startup_loaders(monkeypatch, agents=_agents())
    async with AcePage(query='"visual"', patches=patches()) as page:
        detail = await _goto_agents(page, 4)
        await page.press("ctrl+s")
        await wait_for_visual_idle(page)
        await page.press("vertical_line")
        await wait_for_visual_idle(page)
        assert detail.sidebar_mode is SidebarMode.RAIL
        container = page.app.query_one("#agent-list-container")
        assert container.region.width == NODE_RAIL_WIDTH
        assert all(widget._rail_enabled for widget in _lists(page))


async def test_zoom_from_rail_is_flush_and_restores_rail(monkeypatch) -> None:
    """Z from the rail hides the whole column; restore brings the rail back."""
    patch_startup_loaders(monkeypatch, agents=_agents())
    async with AcePage(query='"visual"', patches=patches()) as page:
        detail = await _goto_agents(page, 4)
        await page.press("ctrl+s")
        await wait_for_visual_idle(page)
        await page.press("Z")
        await wait_for_visual_idle(page)
        assert detail.sidebar_mode is SidebarMode.HIDDEN
        container = page.app.query_one("#agent-list-container")
        assert container.display is False
        assert not any(widget._rail_enabled for widget in _lists(page))
        await page.press("Z")
        await wait_for_visual_idle(page)
        assert detail.sidebar_mode is SidebarMode.RAIL
        assert container.display is not False
        assert container.region.width == NODE_RAIL_WIDTH
        assert all(widget._rail_enabled for widget in _lists(page))


async def test_zoom_then_split_key_clears_hidden_class_and_shows_container(
    monkeypatch,
) -> None:
    """From EXPANDED, Z hides the node column; a split key ends the zoom."""
    patch_startup_loaders(monkeypatch, agents=_agents())
    async with AcePage(query='"visual"', patches=patches()) as page:
        detail = await _goto_agents(page, 4)
        assert detail.sidebar_mode is SidebarMode.EXPANDED
        content = page.app.query_one("#agents-content")
        container = page.app.query_one("#agent-list-container")

        await page.press("Z")
        await wait_for_visual_idle(page)
        assert detail.sidebar_mode is SidebarMode.HIDDEN
        assert content.has_class("-nodes-hidden")
        assert container.display is False

        await page.press("backslash")
        await wait_for_visual_idle(page)
        assert not content.has_class("-nodes-hidden")
        assert container.display is not False
        assert container.region.width > 0


async def test_panel_mounted_in_rail_starts_in_rail(monkeypatch) -> None:
    """A tribe panel first mounted while railed starts in rail mode."""
    patch_startup_loaders(monkeypatch, agents=_agents())
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _goto_agents(page, 4)
        await page.press("ctrl+s")
        await wait_for_visual_idle(page)
        before = {widget.id for widget in _lists(page)}
        page.app._agents = [
            *page.app._agents,
            _agent("newcomer", "RUNNING", 4, tribe="epic"),
        ]
        page.app._refresh_agents_display(list_changed=True)
        await wait_for_visual_idle(page)
        after = _lists(page)
        assert len(after) == len(before) + 1
        newcomers = [widget for widget in after if widget.id not in before]
        assert len(newcomers) == 1
        assert newcomers[0]._rail_enabled is True


async def test_collapsed_tribe_rail_title_shows_urgency(monkeypatch) -> None:
    """A collapsed tribe's rail title carries the urgency roll-up."""
    patch_startup_loaders(monkeypatch, agents=_agents())
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _goto_agents(page, 4)
        await page.press("ctrl+s")
        await wait_for_visual_idle(page)
        # First h takes whole-panel focus; second h collapses the tribe.
        await page.press("h")
        await page.press("h")
        await wait_for_visual_idle(page)
        assert "sase" in page.app._collapsed_panel_keys
        titles = [str(widget.border_title) for widget in _lists(page)]
        assert any("?" in title for title in titles)


async def test_sidebar_chip_click_expands_rail(monkeypatch) -> None:
    """Clicking the info-row nodes chip while railed expands the list."""
    patch_startup_loaders(monkeypatch, agents=_agents())
    async with AcePage(query='"visual"', patches=patches()) as page:
        detail = await _goto_agents(page, 4)
        await page.press("ctrl+s")
        await wait_for_visual_idle(page)
        panel = page.app.query_one("#agent-info-panel", AgentInfoPanel)
        span = panel._sidebar_chip_click_span
        assert span is not None
        # Padding is one cell, so the text-cell span shifts by one.
        await page.click("#agent-info-panel", offset=(span[0] + 2, 0))
        await wait_for_visual_idle(page)
        assert detail.sidebar_mode is SidebarMode.EXPANDED


async def test_runtime_tick_skipped_in_rail(monkeypatch) -> None:
    """Runtime patches pause in rail mode and resume on expand."""
    patch_startup_loaders(monkeypatch, agents=_agents())
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _goto_agents(page, 4)
        assert page.app._patch_agent_runtime_rows() > 0
        await page.press("ctrl+s")
        await wait_for_visual_idle(page)
        assert page.app._patch_agent_runtime_rows() == 0
        await page.press("ctrl+s")
        await wait_for_visual_idle(page)
        assert page.app._patch_agent_runtime_rows() > 0

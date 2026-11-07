"""A resize never leaves an on-screen highlighted ``AgentList`` row off screen.

Textual only clamps the scroll offset when a list resizes, so a viewport that
shrinks slides a highlighted row at its bottom edge out of view. The Agents
tab then depended on a later refresh's highlight pass to scroll it back,
which made the ``@epic`` arrival-frame invariant ("the selected row stays
inside the viewport") fail whenever the column shrank after that pass ran.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.pilot import Pilot
from textual.widgets.option_list import Option

from sase.ace.tui.widgets.agent_list import AgentList

_ROWS = 30


class _ListApp(App[None]):
    """Minimal app hosting one agent list with a fixed outer height."""

    ENABLE_COMMAND_PALETTE = False
    CSS = "#agent-list { height: 14; }"

    def compose(self) -> ComposeResult:
        yield AgentList(id="agent-list")


async def _mounted_list(pilot: Pilot) -> AgentList:
    widget = pilot.app.query_one(AgentList)
    widget.add_options([Option(f"row {idx}", id=f"row-{idx}") for idx in range(_ROWS)])
    await pilot.pause()
    return widget


async def _set_outer_height(pilot: Pilot, widget: AgentList, delta: int) -> None:
    widget.styles.height = widget.outer_size.height + delta
    await pilot.pause()


def _highlight_visible(widget: AgentList) -> bool:
    row = widget.highlighted
    top = int(widget.scroll_y)
    return row is not None and top <= row < top + widget.size.height


async def test_shrinking_viewport_keeps_bottom_edge_highlight_visible() -> None:
    async with _ListApp().run_test(size=(40, 24)) as pilot:
        widget = await _mounted_list(pilot)
        height = widget.size.height
        # Park the highlight on the bottom edge of a scrolled viewport.
        widget._set_highlighted_programmatically(height + 1)
        await pilot.pause()
        assert int(widget.scroll_y) == 2
        assert _highlight_visible(widget)

        await _set_outer_height(pilot, widget, -1)

        assert widget.size.height == height - 1
        assert _highlight_visible(widget)
        assert int(widget.scroll_y) == 3  # the least scroll that shows the row


async def test_highlight_moved_while_viewport_was_taller_stays_visible() -> None:
    """The arrival-frame race: grow, move the highlight down a row, shrink back."""
    async with _ListApp().run_test(size=(40, 24)) as pilot:
        widget = await _mounted_list(pilot)
        height = widget.size.height
        widget._set_highlighted_programmatically(height + 1)
        await pilot.pause()

        await _set_outer_height(pilot, widget, +1)
        # The taller viewport already shows the next row, so moving the
        # highlight onto it needs no scroll.
        widget._set_highlighted_programmatically(height + 2)
        assert int(widget.scroll_y) == 2

        await _set_outer_height(pilot, widget, -1)

        assert widget.size.height == height
        assert _highlight_visible(widget)
        assert int(widget.scroll_y) == 3


async def test_resize_leaves_a_highlight_scrolled_away_from_alone() -> None:
    async with _ListApp().run_test(size=(40, 24)) as pilot:
        widget = await _mounted_list(pilot)
        widget._set_highlighted_programmatically(0)
        widget.scroll_to(y=10, animate=False, immediate=True)
        await pilot.pause()
        assert not _highlight_visible(widget)

        await _set_outer_height(pilot, widget, -1)

        assert int(widget.scroll_y) == 10
        assert not _highlight_visible(widget)

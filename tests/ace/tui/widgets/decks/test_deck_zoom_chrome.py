"""Zoom chrome: DeckArea marks the zoomed panel -zoomed with context."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult

from sase.ace.tui.widgets.decks import layout as deck_layout
from sase.ace.tui.widgets.decks.area import DeckArea
from sase.ace.tui.widgets.decks.model import (
    DeckAreaState,
    DeckId,
    DeckLayout,
    DeckPanelState,
)

_ROOT = Path(__file__).resolve().parents[5]


class _AreaApp(App[None]):
    CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"

    def compose(self) -> ComposeResult:
        yield DeckArea(id="agent-deck-area")


def _split_state() -> DeckAreaState:
    """Return a LEFT_RIGHT state with distinct decks and focus right."""
    opened = deck_layout.toggle_split(
        DeckAreaState(), DeckLayout.LEFT_RIGHT, DeckPanelState(DeckId.FILES)
    )
    assert opened.layout is DeckLayout.LEFT_RIGHT
    assert opened.focused == 1
    return opened


async def test_zoomed_panel_gets_chrome_and_class() -> None:
    app = _AreaApp()
    async with app.run_test(size=(100, 30)) as pilot:
        area = app.query_one("#agent-deck-area", DeckArea)
        area.apply_state(_split_state())
        await pilot.pause()
        for index in (0, 1):
            assert not area.panel(index).has_class("-zoomed")
            assert area.panel(index).zoom_chrome is None
        zoomed = deck_layout.toggle_zoom(_split_state())
        area.apply_state(zoomed)
        await pilot.pause()
        focused = area.panel(1)
        assert focused.has_class("-zoomed")
        assert not area.panel(0).has_class("-zoomed")
        chrome = focused.zoom_chrome
        assert chrome is not None
        assert chrome.from_layout is DeckLayout.LEFT_RIGHT
        assert chrome.panel_index == 1
        assert chrome.panel_count == 2
        assert area.panel(0).zoom_chrome is None
        assert "ZOOM" in focused._border_title.plain
        assert "restore" in focused._border_subtitle.plain
        assert "2 of 2" in focused._border_subtitle.plain


async def test_zoom_chrome_cleared_on_every_restore_path() -> None:
    app = _AreaApp()
    async with app.run_test(size=(100, 30)) as pilot:
        area = app.query_one("#agent-deck-area", DeckArea)
        split = _split_state()
        zoomed = deck_layout.toggle_zoom(split)
        target = DeckPanelState(DeckId.TOOLS)
        restore_paths = [
            deck_layout.toggle_zoom(zoomed),
            deck_layout.toggle_nodes_collapsed(zoomed),
            deck_layout.exit_zoom_keeping_panels(zoomed),
            deck_layout.toggle_split(zoomed, DeckLayout.TOP_BOTTOM, target),
        ]
        for restored in restore_paths:
            assert not deck_layout.is_zoomed(restored)
            area.apply_state(zoomed)
            await pilot.pause()
            assert area.panel(1).has_class("-zoomed")
            area.apply_state(restored)
            await pilot.pause()
            for index in (0, 1):
                assert not area.panel(index).has_class("-zoomed")
                assert area.panel(index).zoom_chrome is None
            assert "ZOOM" not in area.panel(0)._border_title.plain


async def test_zoom_from_single_names_no_half() -> None:
    app = _AreaApp()
    async with app.run_test(size=(100, 30)) as pilot:
        area = app.query_one("#agent-deck-area", DeckArea)
        zoomed = deck_layout.toggle_zoom(DeckAreaState())
        area.apply_state(zoomed)
        await pilot.pause()
        panel = area.panel(0)
        assert panel.has_class("-zoomed")
        assert panel.zoom_chrome is not None
        assert panel.zoom_chrome.panel_count == 1
        assert "restore" in panel._border_subtitle.plain
        assert " of " not in panel._border_subtitle.plain

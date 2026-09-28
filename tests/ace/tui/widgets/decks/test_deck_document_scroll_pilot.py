"""Pilot regression test for FINAL/Tools deck scroll-watcher crash."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from sase.ace.tui.widgets.decks.model import DeckId
from sase.ace.tui.widgets.decks.panel import DeckPanel

_ROOT = Path(__file__).resolve().parents[5]


class _DeckPanelApp(App[None]):
    CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"

    def compose(self) -> ComposeResult:
        yield DeckPanel(0)


@pytest.mark.parametrize("deck", [DeckId.FINAL, DeckId.TOOLS, DeckId.MAIN])
async def test_document_scroll_watch_dispatch(
    deck: DeckId, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scrolling a deck must not crash and must sync the spread block cursor."""
    app = _DeckPanelApp()
    seen: list[DeckId] = []
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        panel = app.query_one(DeckPanel)

        if deck is not DeckId.MAIN:

            def _spy(target: DeckId) -> None:
                seen.append(target)

            monkeypatch.setattr(panel, "sync_document_spread_block_cursor", _spy)

        panel.set_deck(deck)
        scroll = panel.query_one(
            f"#agent-deck-panel-0-{deck.value}-scroll",
            VerticalScroll,
        )
        # An empty deck has -shown removed by set_deck, and a hidden scroll
        # clamps to max_scroll_y == 0, so force it shown before scrolling.
        scroll.add_class("-shown")
        await scroll.mount(Static("\n".join(f"row {i}" for i in range(200))))
        await pilot.pause()
        await pilot.pause()
        assert scroll.max_scroll_y > 22
        scroll.scroll_to(y=22, animate=False)
        await pilot.pause()
        await pilot.pause()
        assert int(scroll.scroll_y) == 22
        if deck is not DeckId.MAIN:
            assert deck in seen

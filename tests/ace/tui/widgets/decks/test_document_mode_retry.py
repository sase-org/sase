"""AUTO spread/paged redecision retries (sase-1kx.5.3.3.3.1)."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.text import Text

from sase.ace.tui.widgets.decks.card_part import context_card, reply_card
from sase.ace.tui.widgets.decks.main_document import MainDeckDocument
from sase.ace.tui.widgets.decks.model import DeckId, DeckView, RenderMode
from sase.ace.tui.widgets.decks.panel_spread import DeckPanelSpreadMixin


class _ModeHost(DeckPanelSpreadMixin):
    """Isolated AUTO-mode host with a controllable viewport."""

    def __init__(self) -> None:
        self._init_spread_state()
        self._viewport = (0, 0)
        self._document: MainDeckDocument | None = None
        self.scheduled: list[Any] = []

    def _spread_viewport(self, _deck: DeckId) -> tuple[int, int]:
        return self._viewport

    def view_policy(self, _deck: DeckId) -> DeckView:
        return DeckView.AUTO

    def call_after_refresh(self, callback: Any, *args: Any, **kwargs: Any) -> None:
        self.scheduled.append(callback)

    def _spread_console(self) -> tuple[Any, Any] | None:
        console = Console(width=80, height=20)
        return (console, console.options)

    def _refresh_document_mode_for_shown(self, deck: DeckId) -> None:
        document = self._document
        if document is None:
            return
        stored = self._mode_subject.get(deck)
        same = stored is not None and stored == document.subject
        new_mode = self._decide_document_mode(deck, document, same_subject=same)
        self._render_mode[deck] = new_mode
        self._mode_subject[deck] = document.subject

    def pump(self) -> None:
        queued = list(self.scheduled)
        self.scheduled.clear()
        for callback in queued:
            callback()


def _one_card() -> MainDeckDocument:
    return MainDeckDocument(
        cards=(context_card(Text("short")),),
        subject="node",
        partial=False,
        digest="one",
    )


def _tall_two_card() -> MainDeckDocument:
    reply = Text("\n".join(f"reply line {index}" for index in range(80)))
    return MainDeckDocument(
        cards=(context_card(Text("context")), reply_card(reply)),
        subject="node",
        partial=False,
        digest="two",
    )


def test_one_card_spread_then_unready_viewport_retries_to_paged() -> None:
    """A 1-card forced SPREAD must not stick after a tall 2-card layout.

    ``test_agents_decks_single_main_paged_png_snapshot`` waited 15s for
    long Reply to exceed the spread threshold while the SVG stayed
    ``MAIN spread · auto``. Viewport 0 returned the previous SPREAD
    without retrying once geometry was ready.
    """

    host = _ModeHost()
    one = _one_card()
    host._document = one
    host._viewport = (20, 80)
    first = host._decide_document_mode(DeckId.MAIN, one, same_subject=False)
    host._render_mode[DeckId.MAIN] = first
    host._mode_subject[DeckId.MAIN] = one.subject
    assert first is RenderMode.SPREAD
    assert host._deck_mode_measured is True
    assert host.scheduled == []

    two = _tall_two_card()
    host._document = two
    host._viewport = (0, 0)
    second = host._decide_document_mode(DeckId.MAIN, two, same_subject=True)
    host._render_mode[DeckId.MAIN] = second
    assert second is RenderMode.SPREAD
    assert host._deck_mode_measured is False
    assert host.scheduled

    host.pump()
    assert host._render_mode[DeckId.MAIN] is RenderMode.SPREAD
    assert host._deck_mode_measured is False
    assert host.scheduled

    host._viewport = (20, 80)
    host.pump()
    assert host._render_mode[DeckId.MAIN] is RenderMode.PAGED
    assert host._deck_mode_measured is True
    assert host.scheduled == []


def test_document_mode_retry_stops_after_cap() -> None:
    host = _ModeHost()
    two = _tall_two_card()
    host._document = two
    host._viewport = (0, 0)
    host._render_mode[DeckId.MAIN] = RenderMode.SPREAD
    host._mode_subject[DeckId.MAIN] = two.subject
    host._decide_document_mode(DeckId.MAIN, two, same_subject=True)
    pumps = 0
    while host.scheduled:
        host.pump()
        pumps += 1
        if pumps > 20:
            raise AssertionError("retry did not stop")
    assert pumps == 8
    assert host._deck_mode_retry == 8
    assert host._deck_mode_measured is False
    assert host._render_mode[DeckId.MAIN] is RenderMode.SPREAD

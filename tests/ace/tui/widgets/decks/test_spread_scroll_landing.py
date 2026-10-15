"""Spread-scroll landing and chrome-hold regressions (sase-1kx.5.3.3.3.1)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from rich.text import Text

from sase.ace.tui.widgets.decks.card_documents import DeckPanelCardDocumentsMixin
from sase.ace.tui.widgets.decks.card_part import context_card, reply_card
from sase.ace.tui.widgets.decks.document_view import CardDocumentView
from sase.ace.tui.widgets.decks.main_document import MainDeckDocument
from sase.ace.tui.widgets.decks.model import DeckId, RenderMode
from sase.ace.tui.widgets.decks.panel_chrome import DeckPanelChromeMixin
from sase.ace.tui.widgets.decks.panel_interaction import DeckPanelInteractionMixin


class _FakeScroll:
    """Scroll container that can clamp or delay applying ``scroll_to``."""

    def __init__(self) -> None:
        self.scroll_y = 0
        self.max_scroll_y = 0
        self.apply = True
        self.requested: list[int] = []
        self.immediate: list[bool] = []

    def scroll_to(self, y: int = 0, animate: bool = False, **kwargs: Any) -> None:
        self.requested.append(int(y))
        self.immediate.append(bool(kwargs.get("immediate")))
        if not self.apply:
            return
        self.scroll_y = min(int(y), int(self.max_scroll_y))


class _View(CardDocumentView):
    """Unmounted view with a controllable scroll container."""

    def __init__(self) -> None:
        super().__init__()
        self.scroll = _FakeScroll()
        self.scheduled: list[Any] = []
        self.anchors: dict[str, int | None] = {"reply": 10}

    def _scroll_container(self) -> Any:
        return self.scroll

    def call_after_refresh(self, callback: Any, *args: Any, **kwargs: Any) -> None:
        self.scheduled.append(callback)

    def spread_anchor_row(self, card_id: str) -> int | None:
        if card_id == "context":
            return 0
        return self.anchors.get(card_id)

    def pump(self) -> None:
        queued = list(self.scheduled)
        self.scheduled.clear()
        for callback in queued:
            callback()

    def pump_until_idle(self, *, limit: int = 12) -> None:
        for _ in range(limit):
            if not self.scheduled:
                return
            self.pump()
        raise AssertionError("spread scroll did not settle")


def _two_card_document() -> MainDeckDocument:
    return MainDeckDocument(
        cards=(context_card(Text("c")), reply_card(Text("r"))),
        subject="session",
        partial=False,
        digest="d1",
    )


def _ready_view() -> _View:
    view = _View()
    view._document = _two_card_document()
    view._render_mode = RenderMode.SPREAD
    view._active_card = "context"
    return view


def test_apply_spread_scroll_keeps_pending_until_range_accepts_target() -> None:
    """Early clamp plus later range growth must not drop the Reply target.

    The renamed-session CI diagnostic had pending=None, scroll_y=0,
    max_scroll_y=9, and reply anchored at row 2: the first apply cleared
    pending after a clamped scroll, then chrome derived Context.
    """

    view = _ready_view()
    view.scroll.max_scroll_y = 0
    shown = view.scroll_to_card("reply")
    assert shown == "reply"
    assert view._spread_pending_card == "reply"
    view.pump()
    assert view._spread_pending_card == "reply"
    assert view.scroll.scroll_y == 0
    assert view.scroll.requested == [10]
    view.scroll.max_scroll_y = 10
    view.pump_until_idle()
    assert view._spread_pending_card is None
    assert view.scroll.scroll_y == 10
    assert view._active_card == "reply"
    assert view.scroll.immediate[-1] is True


def test_stale_generation_does_not_override_later_navigation() -> None:
    view = _ready_view()
    view.scroll.max_scroll_y = 10
    view.scroll_to_card("reply")
    first_generation = view._spread_scroll_generation
    view.scroll_to_card("context")
    assert view._spread_pending_card == "context"
    view._apply_spread_scroll(first_generation)
    assert view._spread_pending_card == "context"
    assert view.scroll.scroll_y == 0
    view.pump_until_idle()
    assert view._spread_pending_card is None
    assert view.scroll.scroll_y == 0
    assert view._active_card == "context"


def test_missing_anchors_keep_pending_and_retry() -> None:
    view = _ready_view()
    view.anchors["reply"] = None
    view.scroll.max_scroll_y = 10
    view.scroll_to_card("reply")
    view.pump()
    assert view._spread_pending_card == "reply"
    assert view.scheduled
    view.anchors["reply"] = 10
    view.pump_until_idle()
    assert view._spread_pending_card is None
    assert view.scroll.scroll_y == 10


def test_first_card_requires_land_at_zero() -> None:
    view = _ready_view()
    view.scroll.scroll_y = 5
    view.scroll.max_scroll_y = 9
    view.scroll.apply = False
    view.scroll_to_card("context")
    view.pump()
    assert view._spread_pending_card == "context"
    assert view.scroll.scroll_y == 5
    view.scroll.apply = True
    view.pump_until_idle()
    assert view._spread_pending_card is None
    assert view.scroll.scroll_y == 0


def test_publish_section_layout_reschedules_pending() -> None:
    view = _ready_view()
    view.scroll.max_scroll_y = 0
    view.scroll_to_card("reply")
    view.pump()
    assert view._spread_pending_card == "reply"
    view.scheduled.clear()
    view._spread_retry_count = 7
    view._publish_section_layout(generation=0, width=80, anchors=())
    assert view._spread_retry_count == 0
    assert view.scheduled
    view.scroll.max_scroll_y = 10
    view.pump_until_idle()
    assert view._spread_pending_card is None
    assert view.scroll.scroll_y == 10


def test_duplicate_spread_show_reschedules_pending_card() -> None:
    view = _ready_view()
    document = view._document
    assert document is not None
    view._last_render_key = (document.digest, "spread", document.partial, "#B48EAD")
    view._spread_pending_card = "reply"
    view._active_card = "reply"
    view.scroll.max_scroll_y = 10
    shown = view._show_document_spread(document)
    assert shown == "reply"
    assert view._spread_pending_card == "reply"
    assert view.scheduled
    view.pump_until_idle()
    assert view._spread_pending_card is None
    assert view.scroll.scroll_y == 10


class _ChromePanel(DeckPanelInteractionMixin):
    """Isolated chrome holder for pending-scroll overwrite tests."""

    def __init__(self) -> None:
        self._deck = DeckId.MAIN
        self._main_active_card: str | None = "context"
        self._chrome: list[str | None] = []
        self._derived = "context"
        self._main_view = SimpleNamespace(
            _spread_pending_card="reply",
            render_mode=RenderMode.SPREAD,
        )

    @property
    def main_view(self) -> Any:
        return self._main_view

    def is_spread(self, deck: DeckId) -> bool:
        return deck is DeckId.MAIN

    def refresh_chrome(self) -> None:
        self._chrome.append(self._main_active_card)

    def _main_spread_active(self) -> str | None:
        return self._derived


def test_pending_spread_card_holds_chrome_against_scroll_derived_context() -> None:
    """Scroll-y=0 must not paint Context while Reply navigation is in flight."""

    panel = _ChromePanel()
    panel._on_main_scroll_y(0.0, 0.0)
    assert panel._main_active_card == "reply"
    assert panel._chrome == ["reply"]
    panel._derived = "context"
    panel._on_main_scroll_y(0.0, 0.0)
    assert panel._main_active_card == "reply"
    assert panel._chrome == ["reply"]
    panel.main_view._spread_pending_card = None
    panel._on_main_scroll_y(0.0, 0.0)
    assert panel._main_active_card == "context"
    assert panel._chrome == ["reply", "context"]


def test_first_land_waits_for_refresh_confirm() -> None:
    """Clear pending only after a later refresh still shows the land."""

    view = _ready_view()
    view.scroll.max_scroll_y = 10
    view.scroll_to_card("reply")
    view.pump()
    assert view._spread_pending_card == "reply"
    assert view.scroll.scroll_y == 10
    assert view._spread_land_confirmed is True
    view.pump_until_idle()
    assert view._spread_pending_card is None
    assert view.scroll.scroll_y == 10


def test_layout_reset_after_claimed_land_keeps_pending() -> None:
    """A land that layout then drops must not clear the Reply target."""

    view = _ready_view()
    view.scroll.max_scroll_y = 10
    view.scroll_to_card("reply")
    view.pump()
    assert view._spread_pending_card == "reply"
    assert view.scroll.scroll_y == 10
    view.scroll.apply = False
    view.scroll.scroll_y = 0
    view.pump()
    assert view._spread_pending_card == "reply"
    assert view.scroll.scroll_y == 0
    assert view._active_card == "reply"


class _StoreHost(DeckPanelCardDocumentsMixin):
    """Isolated store host for pending-card overwrite tests."""

    def __init__(self) -> None:
        self._main_active_card: str | None = "context"
        self._document_active_cards: dict[DeckId, str | None] = {}
        self._main_view = SimpleNamespace(_spread_pending_card="reply")

    @property
    def main_view(self) -> Any:
        return self._main_view


def test_store_document_active_holds_pending_spread_card() -> None:
    host = _StoreHost()
    host._store_document_active(DeckId.MAIN, "context")
    assert host._main_active_card == "reply"
    host.main_view._spread_pending_card = None
    host._store_document_active(DeckId.MAIN, "context")
    assert host._main_active_card == "context"


class _TabHost(DeckPanelChromeMixin):
    """Isolated chrome host for pending-tab index tests."""

    def __init__(self) -> None:
        self._deck = DeckId.MAIN
        self._main_document = _two_card_document()
        self._main_active_card: str | None = "context"
        self._main_view = SimpleNamespace(_spread_pending_card="reply")

    @property
    def main_view(self) -> Any:
        return self._main_view


def test_active_tab_index_uses_pending_spread_card() -> None:
    host = _TabHost()
    assert host._active_tab_index() == 1
    host.main_view._spread_pending_card = None
    assert host._active_tab_index() == 0

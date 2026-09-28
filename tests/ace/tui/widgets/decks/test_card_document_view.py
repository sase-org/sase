"""Deck-parameterized card-document helpers (phase card-document-view)."""

from __future__ import annotations

from rich.console import Console, Group
from rich.text import Text

from sase.ace.tui.widgets.decks import render_mode as rm
from sase.ace.tui.widgets.decks.card_documents import (
    CARD_DOCUMENT_DECKS,
    DeckPanelCardDocumentsMixin,
    is_card_document_deck,
)
from sase.ace.tui.widgets.decks.card_part import context_card, reply_card
from sase.ace.tui.widgets.decks.document_view import CardDocumentView
from sase.ace.tui.widgets.decks.main_document import (
    EMPTY_CARD_DOCUMENT,
    EMPTY_MAIN_DOCUMENT,
    CardDocument,
    MainDeckDocument,
    build_main_deck_document,
)
from sase.ace.tui.widgets.decks.main_view import MainDeckView
from sase.ace.tui.widgets.decks.model import DeckId, DeckView
from sase.ace.tui.widgets.decks.render_mode import measure_card_rows
from sase.ace.tui.widgets.decks.separators import card_separator_for
from sase.ace.tui.widgets.decks.view_policy import forced_block_mode, forced_deck_mode


def test_card_document_decks_is_main_and_final() -> None:
    assert CARD_DOCUMENT_DECKS == (DeckId.MAIN, DeckId.FINAL, DeckId.TOOLS)
    assert is_card_document_deck(DeckId.MAIN)
    assert is_card_document_deck(DeckId.TOOLS)
    assert not is_card_document_deck(DeckId.FILES)


def test_document_aliases_match_main() -> None:
    assert CardDocument is MainDeckDocument
    assert EMPTY_CARD_DOCUMENT is EMPTY_MAIN_DOCUMENT
    content = Group(context_card(Text("a")), reply_card(Text("b")))
    document = build_main_deck_document(content, subject="s", partial=False, digest="d")
    assert [card.card_id for card in document.cards] == ["context", "reply"]
    assert (document.subject, document.partial, document.digest) == ("s", False, "d")


def test_main_view_is_main_card_document_view() -> None:
    assert issubclass(MainDeckView, CardDocumentView)
    assert MainDeckView().deck is DeckId.MAIN
    assert CardDocumentView().deck is DeckId.MAIN
    assert CardDocumentView(DeckId.MAIN).deck is DeckId.MAIN


def test_card_separator_for_main_deck() -> None:
    card = reply_card(Text("x"))
    separator = card_separator_for(DeckId.MAIN, card, accent="green")
    assert separator.glyph == "\u25c6"
    assert separator.accent == "green"
    assert "Reply" in separator._rule_text(40)


def test_card_separator_defaults_to_deck_accent() -> None:
    card = context_card(Text("x"))
    separator = card_separator_for(DeckId.MAIN, card)
    assert separator.accent == "#B48EAD"


def test_measure_card_rows_matches_main_and_namespaces_cache() -> None:
    rm._measure_cache.clear()
    try:
        console = Console(width=80)
        options = console.options
        card = context_card(Text("hello"))
        kwargs = {
            "width": 80,
            "console": console,
            "options": options,
            "budget": 100,
            "cache_key_prefix": "ns-test",
        }
        measured = measure_card_rows([card], deck=DeckId.MAIN, **kwargs)  # type: ignore[arg-type]
        assert measured > 0
        assert rm._measure_cache, "expected a cached measurement entry"
        for digest, _width in rm._measure_cache:
            assert digest.startswith("main:"), digest
    finally:
        rm._measure_cache.clear()


def test_measure_card_rows_namespaces_other_decks() -> None:
    rm._measure_cache.clear()
    try:
        console = Console(width=80)
        card = context_card(Text("hello"))
        kwargs = {
            "width": 80,
            "console": console,
            "options": console.options,
            "budget": 100,
            "cache_key_prefix": "ns-test",
        }
        measure_card_rows([card], deck=DeckId.FILES, **kwargs)  # type: ignore[arg-type]
        for digest, _width in rm._measure_cache:
            assert digest.startswith("files:"), digest
    finally:
        rm._measure_cache.clear()


def test_forced_helpers_are_noops_for_auto() -> None:
    assert forced_deck_mode(DeckView.AUTO, 3) is None
    assert forced_deck_mode(DeckView.AUTO, 1) is not None
    assert forced_block_mode(DeckView.AUTO, 4) is None


class _StubHost(DeckPanelCardDocumentsMixin):
    _panel_index = 0
    _deck = DeckId.MAIN
    parent = None


def test_host_rejects_non_document_decks() -> None:
    stub = _StubHost()
    assert stub.card_document_host(DeckId.FILES) is None
    assert stub.card_document_host(DeckId.TOOLS) is None
    # Main without a mounted view also resolves to None, never raises.
    assert stub.card_document_host(DeckId.MAIN) is None


def test_document_view_rejects_unknown_deck() -> None:
    stub = _StubHost()
    try:
        stub.document_view(DeckId.TOOLS)
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError for TOOLS")
    try:
        stub.document_for(DeckId.TOOLS)
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError for TOOLS")

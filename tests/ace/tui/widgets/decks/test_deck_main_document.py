"""split_card_parts and Main document tests."""

from __future__ import annotations

from rich.console import Group
from rich.text import Text

from sase.ace.tui.widgets.decks.card_part import (
    CardPart,
    context_card,
    reply_card,
    split_card_parts,
    summary_card,
)
from sase.ace.tui.widgets.decks.main_document import (
    EMPTY_MAIN_DOCUMENT,
    build_main_deck_document,
)


def test_top_level_card_returns_singleton() -> None:
    part = context_card(Text("hi"))
    assert split_card_parts(part) == (part,)


def test_group_of_cards_in_order() -> None:
    context = context_card(Text("a"))
    reply = reply_card(Text("b"))
    assert split_card_parts(Group(context, reply)) == (context, reply)


def test_empty_card_parts_dropped() -> None:
    assert split_card_parts(context_card()) == ()
    context = context_card(Text("a"))
    empty = reply_card()
    assert split_card_parts(Group(empty, context)) == (context,)


def test_loose_renderables_join_existing_context() -> None:
    context = context_card(Text("a"))
    reply = reply_card(Text("b"))
    loose = Text("loose")
    parts = split_card_parts(Group(context, loose, reply))
    assert len(parts) == 2
    assert parts[0].card_id == "context"
    assert len(parts[0].renderables) == 2
    assert parts[1] is reply
    # Never mutates the original.
    assert len(context.renderables) == 1


def test_loose_without_context_creates_front_context() -> None:
    reply = reply_card(Text("b"))
    parts = split_card_parts(Group(Text("loose"), reply))
    assert parts[0].card_id == "context"
    assert parts[1] is reply


def test_text_and_str_become_context() -> None:
    parts = split_card_parts(Text("body"))
    assert len(parts) == 1 and parts[0].card_id == "context"
    parts = split_card_parts("body")
    assert len(parts) == 1 and parts[0].card_id == "context"


def test_empty_inputs() -> None:
    assert split_card_parts("") == ()
    assert split_card_parts(None) == ()
    assert split_card_parts(Group()) == ()


def test_build_document_subject_none_has_no_cards() -> None:
    doc = build_main_deck_document(
        Group(context_card(Text("a"))), subject=None, partial=False, digest="d"
    )
    assert doc.cards == ()
    assert doc.digest == "d"


def test_build_document_passes_through() -> None:
    content = Group(context_card(Text("a")), summary_card(Text("s")))
    doc = build_main_deck_document(
        content, subject=("agent", 1, None), partial=True, digest="abc"
    )
    assert [c.card_id for c in doc.cards] == ["context", "summary"]
    assert doc.partial is True
    assert doc.digest == "abc"
    assert doc.card_ids == ("context", "summary")
    assert doc.card("summary") is not None
    assert doc.card("missing") is None


def test_empty_document_defaults() -> None:
    assert EMPTY_MAIN_DOCUMENT.cards == ()
    assert EMPTY_MAIN_DOCUMENT.subject is None
    assert EMPTY_MAIN_DOCUMENT.partial is False
    assert EMPTY_MAIN_DOCUMENT.digest is None


def test_card_part_type() -> None:
    part = CardPart("context", "Context", Text("x"))
    assert part.card_id == "context"

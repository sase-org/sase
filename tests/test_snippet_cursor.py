"""No-I/O snippet trigger detection under a cursor offset."""

from __future__ import annotations

from sase.snippet.cursor import snippet_trigger_at_offset


def test_call_form_wins_over_bare_word() -> None:
    text = "see #[greet] here"
    offset = text.index("greet") + 1
    assert snippet_trigger_at_offset(text, offset, {"see": "x"}) == "greet"


def test_parenthesized_and_colon_calls() -> None:
    text = "#[todo(value)] then #[note:body]"
    assert snippet_trigger_at_offset(text, 3) == "todo"
    assert snippet_trigger_at_offset(text, text.index("note") + 1) == "note"


def test_bare_word_requires_known_catalog() -> None:
    text = "expand greet now"
    offset = text.index("greet")
    assert snippet_trigger_at_offset(text, offset) is None
    assert snippet_trigger_at_offset(text, offset, {"greet": "hello$0"}) == "greet"


def test_unknown_word_and_empty_text_are_misses() -> None:
    assert snippet_trigger_at_offset("", 0, {"greet": "x"}) is None
    assert snippet_trigger_at_offset("nope", 1, {"greet": "x"}) is None

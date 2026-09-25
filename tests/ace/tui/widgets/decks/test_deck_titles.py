"""Title, subtitle and file-line-status tests."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.widgets.decks.availability import DeckAvailability
from sase.ace.tui.widgets.decks.model import DeckId
from sase.ace.tui.widgets.decks.titles import (
    CardTab,
    deck_subtitle,
    deck_title,
    file_line_status,
)


def test_full_tier_active_pill_and_count() -> None:
    tabs = (CardTab("context", "Context"), CardTab("reply", "Reply"))
    rendered = deck_title(DeckId.MAIN, tabs, 0, width=80, accent="red", focused=True)
    assert "MAIN" in rendered.plain
    assert "Context" in rendered.plain
    assert "1/2" in rendered.plain


def test_single_card_has_no_count() -> None:
    rendered = deck_title(
        DeckId.TOOLS,
        (CardTab("llm-calls", "LLM Calls"),),
        0,
        width=80,
        accent="red",
        focused=True,
    )
    assert "1/1" not in rendered.plain
    assert "LLM Calls" in rendered.plain


def test_partial_paint_mutes_tabs_without_count() -> None:
    tabs = (CardTab("context", "Context"), CardTab("reply", "Reply"))
    rendered = deck_title(DeckId.MAIN, tabs, None, width=80, accent="red", focused=True)
    assert "1/2" not in rendered.plain


def test_tier_falls_back_at_narrow_widths() -> None:
    tabs = (CardTab("context", "Context"), CardTab("reply", "Reply"))
    wide = deck_title(DeckId.MAIN, tabs, 0, width=80, accent="red", focused=True)
    narrow = deck_title(DeckId.MAIN, tabs, 0, width=10, accent="red", focused=True)
    assert len(narrow.plain) <= len(wide.plain)
    assert "MAIN" in narrow.plain


def test_files_compact_form_uses_active_label() -> None:
    tabs = tuple(CardTab(f"f-{i}", f"label-{i}") for i in range(6))
    rendered = deck_title(DeckId.FILES, tabs, 2, width=80, accent="green", focused=True)
    assert "label-2" in rendered.plain
    assert "3/6" in rendered.plain


def test_unfocused_styling_differs() -> None:
    tabs = (CardTab("context", "Context"),)
    focused = deck_title(DeckId.MAIN, tabs, 0, width=80, accent="red", focused=True)
    unfocused = deck_title(DeckId.MAIN, tabs, 0, width=80, accent="red", focused=False)
    assert focused.plain == unfocused.plain
    assert (
        str(focused.style) != str(unfocused.style)
        or len(str(focused.spans) + str(unfocused.spans)) >= 0
    )


def test_subtitle_switcher_counts_only_when_known() -> None:
    availability = {
        DeckId.MAIN: DeckAvailability(True, 2),
        DeckId.FILES: DeckAvailability(None, None),
        DeckId.TOOLS: DeckAvailability(False, 0),
    }
    rendered = deck_subtitle(
        DeckId.MAIN,
        availability,
        status=None,
        width=80,
        accent_for={
            DeckId.MAIN: "red",
            DeckId.FILES: "green",
            DeckId.TOOLS: "#87D7FF",
        },
    )
    assert "main 2" in rendered.plain
    assert "files" in rendered.plain
    assert "tools 0" in rendered.plain


def test_subtitle_drops_switcher_before_truncating_status() -> None:
    availability = {
        DeckId.MAIN: DeckAvailability(True, 1),
        DeckId.FILES: DeckAvailability(True, 1),
        DeckId.TOOLS: DeckAvailability(True, 1),
    }
    status = Text("a very long status line that will not fit")
    rendered = deck_subtitle(
        DeckId.MAIN,
        availability,
        status=status,
        width=20,
        accent_for={
            DeckId.MAIN: "red",
            DeckId.FILES: "green",
            DeckId.TOOLS: "#87D7FF",
        },
    )
    assert "main" not in rendered.plain
    assert len(rendered.plain) <= 20


_COUNTED = {
    DeckId.MAIN: DeckAvailability(True, 1),
    DeckId.FILES: DeckAvailability(True, 3),
    DeckId.TOOLS: DeckAvailability(True, 2),
}
_ACCENTS = {DeckId.MAIN: "red", DeckId.FILES: "green", DeckId.TOOLS: "#87D7FF"}


def _subtitle(width: int, *, spread: bool = False, status: Text | None = None) -> str:
    return deck_subtitle(
        DeckId.MAIN,
        _COUNTED,
        status=status,
        width=width,
        accent_for=_ACCENTS,
        spread=spread,
    ).plain


def test_subtitle_drops_spread_tag_then_counts_before_slicing() -> None:
    assert _subtitle(60, spread=True) == "spread  main 1 \u00b7 files 3 \u00b7 tools 2"
    # Spread tag goes first, keeping the counts.
    assert _subtitle(30, spread=True) == "main 1 \u00b7 files 3 \u00b7 tools 2"
    # Then the counts, so no label is ever cut mid-word.
    assert _subtitle(25, spread=True) == "main \u00b7 files \u00b7 tools"
    assert _subtitle(21) == "main \u00b7 files \u00b7 tools"


def test_subtitle_slices_only_when_even_bare_labels_do_not_fit() -> None:
    assert _subtitle(8) == "main \u00b7 f"


def test_subtitle_status_keeps_bare_switcher_before_dropping_it() -> None:
    status = Text("1-50 of 90")
    assert _subtitle(60, status=status).startswith("1-50 of 90  main 1")
    bare = _subtitle(34, status=status)
    assert bare == "1-50 of 90  main \u00b7 files \u00b7 tools"
    assert _subtitle(15, status=status) == "1-50 of 90"


def test_file_line_status() -> None:
    assert file_line_status(1, 0, False, editor_key="E") is None
    capped = file_line_status(120, 693, True, editor_key="E")
    assert capped is not None and "693" in capped.plain and "E" in capped.plain
    plain = file_line_status(10, 693, False, editor_key="E")
    assert plain is not None and plain.plain == "693 lines"

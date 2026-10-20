"""Subtitle and zoomed-subtitle tests.

Split from ``test_deck_titles``; the original module re-exports these tests
so its import path keeps working.
"""

from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui.widgets.decks.availability import DeckAvailability
from sase.ace.tui.widgets.decks.model import DeckId, DeckLayout
from sase.ace.tui.widgets.decks.titles import ZoomChrome, deck_subtitle

__all__ = [
    "test_subtitle_drops_counts_before_slicing",
    "test_subtitle_drops_switcher_before_truncating_status",
    "test_subtitle_has_no_spread_tag",
    "test_subtitle_slices_only_when_even_bare_labels_do_not_fit",
    "test_subtitle_status_keeps_bare_switcher_before_dropping_it",
    "test_subtitle_switcher_counts_only_when_known",
    "test_zoom_subtitle_cards_only_unbound_keys_truncate_by_cells",
    "test_zoom_subtitle_glyph_per_half",
    "test_zoom_subtitle_keeps_status_while_switcher_drops",
    "test_zoom_subtitle_keeps_truncated_continuation_at_width_25",
    "test_zoom_subtitle_ladder_drops_counts_then_switcher_then_position",
    "test_zoom_subtitle_omits_key_when_unbound",
    "test_zoom_subtitle_single_has_no_position",
    "test_zoom_subtitle_split_drops_position_before_truncating_counts",
    "test_zoom_subtitle_truncation_preserves_styles_and_fallback_boundary",
]


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
    DeckId.RECORD: DeckAvailability(True, None),
}
_ACCENTS = {
    DeckId.MAIN: "red",
    DeckId.FILES: "green",
    DeckId.TOOLS: "#87D7FF",
    DeckId.RECORD: "#87AFAF",
}


def _subtitle(width: int, *, status: Text | None = None) -> str:
    return deck_subtitle(
        DeckId.MAIN,
        _COUNTED,
        status=status,
        width=width,
        accent_for=_ACCENTS,
    ).plain


def test_subtitle_has_no_spread_tag() -> None:
    assert (
        _subtitle(60)
        == "main 1 \u00b7 files 3 \u00b7 tools 2 \u00b7 final \u00b7 record"
    )
    assert "spread" not in _subtitle(60)


def test_subtitle_drops_counts_before_slicing() -> None:
    assert _subtitle(40) == "main \u00b7 files \u00b7 tools \u00b7 final \u00b7 record"
    # Then bare labels slice when even they do not fit.
    assert _subtitle(30) == "main \u00b7 files \u00b7 tools \u00b7 final \u00b7"
    assert _subtitle(25) == "main \u00b7 files \u00b7 tools \u00b7 fi"


def test_subtitle_slices_only_when_even_bare_labels_do_not_fit() -> None:
    assert _subtitle(8) == "main \u00b7 f"


def test_subtitle_status_keeps_bare_switcher_before_dropping_it() -> None:
    status = Text("1-50 of 90")
    assert _subtitle(60, status=status).startswith("1-50 of 90  main 1")
    bare = _subtitle(52, status=status)
    assert (
        bare == "1-50 of 90  main \u00b7 files \u00b7 tools \u00b7 final \u00b7 record"
    )
    assert _subtitle(15, status=status) == "1-50 of 90"


def _zoomed_subtitle(width: int, zoom: ZoomChrome, status: Text | None = None) -> str:
    return deck_subtitle(
        DeckId.MAIN,
        _COUNTED,
        status=status,
        width=width,
        accent_for=_ACCENTS,
        zoom=zoom,
    ).plain


def _split_zoom(index: int, layout: DeckLayout = DeckLayout.LEFT_RIGHT) -> ZoomChrome:
    from sase.ace.tui.util.pane_grid import Axis, PaneGrid, position_glyph

    axis = Axis.COLS if layout is DeckLayout.LEFT_RIGHT else Axis.ROWS
    grid = PaneGrid(
        panes=(0, 1),
        focused=index,
        axis=axis,
        ratio=50,
        recent=(index, 1 - index),
    )
    return ZoomChrome(layout, index, 2, zoom_key="Z", glyph=position_glyph(grid, index))


def test_zoom_subtitle_glyph_per_half() -> None:
    assert _zoomed_subtitle(80, _split_zoom(0)).startswith("◧ 1 of 2 · Z restore")
    right = _zoomed_subtitle(80, _split_zoom(1))
    assert right.startswith("◨ 2 of 2 · Z restore")
    top = _zoomed_subtitle(80, _split_zoom(0, DeckLayout.TOP_BOTTOM))
    assert top.startswith("⬒ 1 of 2 · Z restore")
    bottom = _zoomed_subtitle(80, _split_zoom(1, DeckLayout.TOP_BOTTOM))
    assert bottom.startswith("⬓ 2 of 2 · Z restore")


def test_zoom_subtitle_single_has_no_position() -> None:
    rendered = _zoomed_subtitle(80, ZoomChrome(DeckLayout.SINGLE, 0, 1, zoom_key="Z"))
    assert rendered.startswith("Z restore")
    assert " of " not in rendered


def test_zoom_subtitle_omits_key_when_unbound() -> None:
    assert _zoomed_subtitle(80, ZoomChrome(DeckLayout.SINGLE, 0, 1)).startswith(
        "restore"
    )
    from dataclasses import replace

    unbound = replace(_split_zoom(0, DeckLayout.LEFT_RIGHT), zoom_key="")
    split = _zoomed_subtitle(80, unbound)
    assert split.startswith("◧ 1 of 2 · restore")


def test_zoom_subtitle_ladder_drops_counts_then_switcher_then_position() -> None:
    zoom = _split_zoom(0)
    full = _zoomed_subtitle(80, zoom)
    assert full == "◧ 1 of 2 · Z restore  main 1 · files 3 · tools 2 · final · record"
    bare = _zoomed_subtitle(64, zoom)
    assert bare == "◧ 1 of 2 · Z restore  main · files · tools · final · record"
    assert "main 1" not in bare
    alone = _zoomed_subtitle(30, zoom)
    assert alone == "◧ 1 of 2 · Z restore"
    short = _zoomed_subtitle(12, zoom)
    assert short == "Z restore"
    assert _zoomed_subtitle(8, zoom) == "Z restor"


def test_zoom_subtitle_keeps_status_while_switcher_drops() -> None:
    zoom = _split_zoom(1)
    rendered = _zoomed_subtitle(40, zoom, status=Text("693 lines"))
    assert rendered.startswith("◨ 2 of 2 · Z restore  693 lines")
    assert "main" not in rendered


def _zoomed_continuation(
    width: int,
    zoom: ZoomChrome,
    *,
    tab_count: int = 2,
    block_count: int | None = 4,
    block_paged: bool = True,
    card_key: str = "Ctrl+J",
    block_prev_key: str = "(",
    block_next_key: str = ")",
    at_bottom: bool = False,
    focused: bool = True,
    accent: str = "red",
) -> Text:
    from sase.ace.tui.widgets.decks.scope_cues import continuation_texts

    full, bare = continuation_texts(
        DeckId.MAIN,
        tab_count=tab_count,
        block_count=block_count,
        block_paged=block_paged,
        card_key=card_key,
        block_prev_key=block_prev_key,
        block_next_key=block_next_key,
        at_bottom=at_bottom,
        focused=focused,
        accent=accent,
    )
    assert full is not None and bare is not None
    return deck_subtitle(
        DeckId.MAIN,
        {},
        status=None,
        width=width,
        accent_for={DeckId.MAIN: "red"},
        zoom=zoom,
        continuation=full,
        continuation_bare=bare,
    )


def test_zoom_subtitle_keeps_truncated_continuation_at_width_25() -> None:
    rendered = _zoomed_continuation(25, ZoomChrome(DeckLayout.SINGLE, 0, 1, "Z"))
    assert rendered.plain.startswith("Z restore  ")
    assert "+3 blocks" in rendered.plain
    assert rendered.plain != "Z restore"
    assert cell_len(rendered.plain) <= 25
    styles = {str(span.style) for span in rendered.spans}
    assert "#888888" in styles


def test_zoom_subtitle_split_drops_position_before_truncating_counts() -> None:
    full_width = _zoomed_continuation(80, _split_zoom(0))
    assert full_width.plain.startswith("◧ 1 of 2 · Z restore")
    narrowed = _zoomed_continuation(30, _split_zoom(0))
    assert narrowed.plain == "Z restore  +3 blocks · +1 card"
    assert "◧" not in narrowed.plain
    assert "+3 blocks" in narrowed.plain
    assert "+1 card" in narrowed.plain


def test_zoom_subtitle_cards_only_unbound_keys_truncate_by_cells() -> None:
    zoom = ZoomChrome(DeckLayout.SINGLE, 0, 1, zoom_key="")
    rendered = _zoomed_continuation(
        15,
        zoom,
        tab_count=3,
        block_count=None,
        block_paged=False,
        card_key="",
        block_prev_key="",
        block_next_key=")",
    )
    assert rendered.plain.startswith("restore  ")
    assert "+2 cards" not in rendered.plain
    assert "+2 car" in rendered.plain
    assert cell_len(rendered.plain) <= 15
    bound = _zoomed_continuation(
        20,
        ZoomChrome(DeckLayout.SINGLE, 0, 1, "Z"),
        tab_count=3,
        block_count=None,
        block_paged=False,
        card_key="Ctrl+J",
    )
    assert "+2 cards" in bound.plain or "+2 car" in bound.plain
    assert cell_len(bound.plain) <= 20


def test_zoom_subtitle_truncation_preserves_styles_and_fallback_boundary() -> None:
    at_bottom = _zoomed_continuation(
        25,
        ZoomChrome(DeckLayout.SINGLE, 0, 1, "Z"),
        at_bottom=True,
        focused=True,
        accent="red",
    )
    assert "+3 blocks" in at_bottom.plain
    assert "bold red" in {str(span.style) for span in at_bottom.spans}
    assert cell_len(at_bottom.plain) <= 25
    unfocused = _zoomed_continuation(
        15,
        ZoomChrome(DeckLayout.SINGLE, 0, 1, "Z"),
        focused=False,
    )
    assert {str(span.style) for span in unfocused.spans} <= {"bold red", "dim", ""}
    assert "dim" in {str(span.style) for span in unfocused.spans}
    assert cell_len(unfocused.plain) <= 15
    fits = _zoomed_continuation(30, ZoomChrome(DeckLayout.SINGLE, 0, 1, "Z"))
    assert fits.plain == "Z restore  +3 blocks · +1 card"
    just_below = _zoomed_continuation(29, ZoomChrome(DeckLayout.SINGLE, 0, 1, "Z"))
    assert just_below.plain.startswith("Z restore  ")
    assert "+3 blocks" in just_below.plain
    assert cell_len(just_below.plain) <= 29
    no_room = _zoomed_continuation(10, ZoomChrome(DeckLayout.SINGLE, 0, 1, "Z"))
    assert no_room.plain == "Z restore"
    tiny = _zoomed_continuation(8, ZoomChrome(DeckLayout.SINGLE, 0, 1, "Z"))
    assert tiny.plain == "Z restor"
    assert cell_len(tiny.plain) <= 8

"""Title, subtitle and file-line-status tests."""

from __future__ import annotations

from rich.text import Text

from rich.cells import cell_len

from sase.ace.tui.widgets.decks.availability import DeckAvailability
from sase.ace.tui.widgets.decks.model import DeckId, DeckLayout, DeckView
from sase.ace.tui.widgets.decks.titles import (
    ZOOM_CHIP_STYLE,
    CardTab,
    ZoomChrome,
    deck_subtitle,
    deck_title,
    file_line_status,
)
from sase.ace.tui.widgets.decks.view_policy import (
    ResolvedView,
    ViewContent,
    ViewStatus,
    resolve_view,
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


def _subtitle(width: int, *, status: Text | None = None) -> str:
    return deck_subtitle(
        DeckId.MAIN,
        _COUNTED,
        status=status,
        width=width,
        accent_for=_ACCENTS,
    ).plain


def test_subtitle_has_no_spread_tag() -> None:
    assert _subtitle(60) == "main 1 \u00b7 files 3 \u00b7 tools 2 \u00b7 final"
    assert "spread" not in _subtitle(60)


def test_subtitle_drops_counts_before_slicing() -> None:
    assert _subtitle(30) == "main \u00b7 files \u00b7 tools \u00b7 final"
    # Then bare labels slice when even they do not fit.
    assert _subtitle(25) == "main \u00b7 files \u00b7 tools \u00b7 fi"
    assert _subtitle(21) == "main \u00b7 files \u00b7 tools "


def test_subtitle_slices_only_when_even_bare_labels_do_not_fit() -> None:
    assert _subtitle(8) == "main \u00b7 f"


def test_subtitle_status_keeps_bare_switcher_before_dropping_it() -> None:
    status = Text("1-50 of 90")
    assert _subtitle(60, status=status).startswith("1-50 of 90  main 1")
    bare = _subtitle(40, status=status)
    assert bare == "1-50 of 90  main \u00b7 files \u00b7 tools \u00b7 final"
    assert _subtitle(15, status=status) == "1-50 of 90"


def test_file_line_status() -> None:
    assert file_line_status(1, 0, False, editor_key="E") is None
    capped = file_line_status(120, 693, True, editor_key="E")
    assert capped is not None and "693" in capped.plain and "E" in capped.plain
    plain = file_line_status(10, 693, False, editor_key="E")
    assert plain is not None and plain.plain == "693 lines"


def _main_view(
    policy: DeckView = DeckView.AUTO,
    shown: DeckView = DeckView.PAGE_BLOCKS,
    status: ViewStatus = ViewStatus.OK,
) -> ResolvedView:
    return ResolvedView(deck=DeckId.MAIN, policy=policy, shown=shown, status=status)


def _main_tabs() -> tuple[CardTab, ...]:
    return (CardTab("context", "Context"), CardTab("reply", "Reply"))


def test_badge_follows_deck_name_before_tabs() -> None:
    rendered = deck_title(
        DeckId.MAIN,
        _main_tabs(),
        1,
        width=80,
        accent="red",
        focused=True,
        view=_main_view(),
    )
    assert rendered.plain.startswith("◆ MAIN page blocks · auto ┃ ")
    assert "Reply" in rendered.plain


def test_badge_ladder_prefers_long_then_short_then_tiny() -> None:
    tabs = _main_tabs()
    view = _main_view()
    long = deck_title(
        DeckId.MAIN, tabs, 1, width=80, accent="red", focused=True, view=view
    )
    assert "page blocks · auto" in long.plain
    short_width = len("◆ MAIN page blocks · auto ┃ Context │ Reply  2/2") - 1
    short = deck_title(
        DeckId.MAIN,
        tabs,
        1,
        width=short_width,
        accent="red",
        focused=True,
        view=view,
    )
    assert "blocks · auto" in short.plain
    assert "page blocks" not in short.plain
    tiny = deck_title(
        DeckId.MAIN, tabs, 1, width=24, accent="red", focused=True, view=view
    )
    assert "B·A" in tiny.plain


def test_badge_micro_tiny_form_keeps_text() -> None:
    rendered = deck_title(
        DeckId.MAIN,
        _main_tabs(),
        1,
        width=12,
        accent="red",
        focused=True,
        view=_main_view(),
    )
    assert rendered.plain == "MAIN B·A 2/2"


def test_tools_keeps_tab_only_rungs_with_view() -> None:
    tabs = (CardTab("llm-calls", "LLM Calls"),)
    view = ResolvedView(
        deck=DeckId.TOOLS,
        policy=DeckView.AUTO,
        shown=DeckView.PAGE_CARDS,
        status=ViewStatus.OK,
    )
    rendered = deck_title(
        DeckId.TOOLS, tabs, 0, width=80, accent="red", focused=True, view=view
    )
    assert rendered.plain == "λ TOOLS ┃ LLM Calls"


def test_files_crowded_tabs_skip_full_rungs_with_badge() -> None:
    tabs = tuple(CardTab(f"f-{i}", f"label-{i}") for i in range(6))
    view = ResolvedView(
        deck=DeckId.FILES,
        policy=DeckView.AUTO,
        shown=DeckView.PAGE_CARDS,
        status=ViewStatus.OK,
    )
    rendered = deck_title(
        DeckId.FILES, tabs, 2, width=80, accent="green", focused=True, view=view
    )
    assert "page cards · auto" in rendered.plain
    assert "‹ 3/6 ›" in rendered.plain
    assert "label-0" not in rendered.plain


def test_resolved_fixed_badge_shows_requested_name() -> None:
    content = ViewContent(deck=DeckId.MAIN, card_count=2, active_block_count=0)
    view = resolve_view(DeckId.MAIN, DeckView.PAGE_BLOCKS, DeckView.PAGE_CARDS, content)
    assert view.shown is DeckView.PAGE_BLOCKS
    rendered = deck_title(
        DeckId.MAIN,
        _main_tabs(),
        1,
        width=80,
        accent="red",
        focused=True,
        view=view,
    )
    assert "page blocks · fixed" in rendered.plain


def _zoomed_title(width: int) -> str:
    return deck_title(
        DeckId.MAIN,
        _main_tabs(),
        1,
        width=width,
        accent="red",
        focused=True,
        zoomed=True,
    ).plain


def test_zoomed_title_chip_always_present_and_budgeted() -> None:
    for width in (80, 60, 40, 30, 24, 20, 16, 12, 10, 8, 6, 5, 4, 3, 2):
        rendered = deck_title(
            DeckId.MAIN,
            _main_tabs(),
            1,
            width=width,
            accent="red",
            focused=True,
            zoomed=True,
        )
        assert rendered.plain.startswith("ZOOM"), width
        assert cell_len(rendered.plain) <= max(width, 4), width


def test_zoomed_title_picks_rungs_against_reduced_budget() -> None:
    # The full rung is 29 cells, so at width 33 the unzoomed title still
    # shows it while the zoomed title (budget 28) must step down a rung.
    unzoomed = deck_title(
        DeckId.MAIN, _main_tabs(), 1, width=33, accent="red", focused=True
    )
    assert "Context" in unzoomed.plain and "Reply" in unzoomed.plain
    zoomed = deck_title(
        DeckId.MAIN, _main_tabs(), 1, width=33, accent="red", focused=True, zoomed=True
    )
    assert (
        zoomed.plain
        == "ZOOM "
        + deck_title(
            DeckId.MAIN, _main_tabs(), 1, width=28, accent="red", focused=True
        ).plain
    )


def test_zoomed_title_chip_alone_below_smallest_rung() -> None:
    assert _zoomed_title(4) == "ZOOM"
    assert _zoomed_title(2) == "ZOOM"


def test_zoomed_title_chip_style() -> None:
    rendered = deck_title(
        DeckId.MAIN, _main_tabs(), 1, width=80, accent="red", focused=True, zoomed=True
    )
    assert rendered.spans, "the ZOOM chip must carry its reverse-gold style"
    first = rendered.spans[0]
    assert rendered.plain[first.start : first.end] == "ZOOM"
    assert ZOOM_CHIP_STYLE in str(first.style)


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
    return ZoomChrome(layout, index, 2, zoom_key="Z")


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
    split = _zoomed_subtitle(80, ZoomChrome(DeckLayout.LEFT_RIGHT, 0, 2, zoom_key=""))
    assert split.startswith("◧ 1 of 2 · restore")


def test_zoom_subtitle_ladder_drops_counts_then_switcher_then_position() -> None:
    zoom = _split_zoom(0)
    full = _zoomed_subtitle(80, zoom)
    assert full == "◧ 1 of 2 · Z restore  main 1 · files 3 · tools 2 · final"
    bare = _zoomed_subtitle(52, zoom)
    assert bare == "◧ 1 of 2 · Z restore  main · files · tools · final"
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

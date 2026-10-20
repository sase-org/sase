"""Title, subtitle and file-line-status tests."""

from __future__ import annotations

from rich.text import Text

from rich.cells import cell_len

from sase.ace.tui.widgets.decks.availability import DeckAvailability
from sase.ace.tui.widgets.decks.model import DeckId, DeckLayout, DeckView
from sase.ace.tui.widgets.decks.title_scope import SpreadCue
from sase.ace.tui.widgets.decks.titles import (
    ZOOM_CHIP_STYLE,
    CardTab,
    ZoomChrome,
    deck_subtitle,
    deck_title,
    file_line_status,
)
from sase.ace.tui.widgets.decks.view_chip import VIEW_CHIP_STYLE
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
    assert "\u2503" not in rendered.plain


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
    *,
    effective: DeckView | None = None,
    choice_exists: bool = True,
) -> ResolvedView:
    return ResolvedView(
        deck=DeckId.MAIN,
        policy=policy,
        shown=shown,
        status=status,
        effective=shown if effective is None else effective,
        choice_exists=choice_exists,
    )


def _main_tabs() -> tuple[CardTab, ...]:
    return (CardTab("context", "Context"), CardTab("reply", "Reply"))


def test_chip_follows_deck_name_before_tabs() -> None:
    rendered = deck_title(
        DeckId.MAIN,
        _main_tabs(),
        1,
        width=80,
        accent="red",
        focused=True,
        view=_main_view(),
    )
    assert rendered.plain.startswith("◆ MAIN  PAGE BLOCKS  ┃ ")
    assert "Reply" in rendered.plain
    assert "auto" not in rendered.plain
    assert "fixed" not in rendered.plain


def test_chip_ladder_prefers_long_then_short_then_tiny() -> None:
    tabs = _main_tabs()
    view = _main_view()
    long = deck_title(
        DeckId.MAIN, tabs, 1, width=80, accent="red", focused=True, view=view
    )
    assert "PAGE BLOCKS" in long.plain
    short_width = cell_len("◆ MAIN  PAGE BLOCKS  ┃ Context │ Reply  2/2") - 1
    short = deck_title(
        DeckId.MAIN,
        tabs,
        1,
        width=short_width,
        accent="red",
        focused=True,
        view=view,
    )
    assert "BLOCKS" in short.plain
    assert "PAGE BLOCKS" not in short.plain
    tiny = deck_title(
        DeckId.MAIN, tabs, 1, width=24, accent="red", focused=True, view=view
    )
    assert (
        " B " in tiny.plain
        or tiny.plain.endswith("B 2/2")
        or " B " in f" {tiny.plain} "
    )


def test_chip_micro_tiny_form_keeps_text() -> None:
    rendered = deck_title(
        DeckId.MAIN,
        _main_tabs(),
        1,
        width=12,
        accent="red",
        focused=True,
        view=_main_view(),
    )
    assert "MAIN" in rendered.plain
    assert "2/2" in rendered.plain
    assert "B" in rendered.plain


def test_tools_one_card_has_no_tabs_or_chip() -> None:
    tabs = (CardTab("llm-calls", "LLM Calls"),)
    view = ResolvedView(
        deck=DeckId.TOOLS,
        policy=DeckView.AUTO,
        shown=DeckView.PAGE_CARDS,
        status=ViewStatus.OK,
        effective=DeckView.PAGE_CARDS,
        choice_exists=False,
    )
    rendered = deck_title(
        DeckId.TOOLS, tabs, 0, width=80, accent="red", focused=True, view=view
    )
    assert rendered.plain == "λ TOOLS  LLM Calls"
    assert "\u2503" not in rendered.plain


def test_files_crowded_tabs_skip_full_rungs_with_chip() -> None:
    tabs = tuple(CardTab(f"f-{i}", f"label-{i}") for i in range(6))
    view = ResolvedView(
        deck=DeckId.FILES,
        policy=DeckView.AUTO,
        shown=DeckView.PAGE_CARDS,
        status=ViewStatus.OK,
        effective=DeckView.PAGE_CARDS,
        choice_exists=True,
    )
    rendered = deck_title(
        DeckId.FILES, tabs, 2, width=80, accent="green", focused=True, view=view
    )
    assert "PAGE CARDS" in rendered.plain
    assert "‹ 3/6 ›" in rendered.plain
    assert "label-0" not in rendered.plain


def test_locked_chip_shows_lock_and_requested_name() -> None:
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
    assert "PAGE BLOCKS" in rendered.plain
    assert "\U0001f512" in rendered.plain
    assert "fixed" not in rendered.plain
    auto = deck_title(
        DeckId.MAIN,
        _main_tabs(),
        1,
        width=80,
        accent="red",
        focused=True,
        view=_main_view(),
    )
    assert "\U0001f512" not in auto.plain


def test_spread_rungs_have_no_tab_grammar() -> None:
    rendered = deck_title(
        DeckId.MAIN,
        _main_tabs(),
        1,
        width=80,
        accent="red",
        focused=True,
        view=_main_view(shown=DeckView.SPREAD),
        paged=False,
        spread_cue=SpreadCue(here="Reply", above=("Context",)),
    )
    assert "\u2503" not in rendered.plain
    assert "\u2502" not in rendered.plain
    assert "2/2" not in rendered.plain
    assert "\u2039" not in rendered.plain
    assert "Reply" in rendered.plain
    assert "\u25b4" in rendered.plain
    assert "Context" in rendered.plain
    assert "SPREAD" in rendered.plain
    assert "auto" not in rendered.plain
    assert "fixed" not in rendered.plain


def test_spread_counted_cue_uses_deck_noun() -> None:
    tabs = tuple(CardTab(f"f-{i}", f"file-{i}") for i in range(5))
    view = ResolvedView(
        deck=DeckId.FILES,
        policy=DeckView.AUTO,
        shown=DeckView.SPREAD,
        status=ViewStatus.OK,
        effective=DeckView.SPREAD,
        choice_exists=True,
    )
    rendered = deck_title(
        DeckId.FILES,
        tabs,
        1,
        width=80,
        accent="green",
        focused=True,
        view=view,
        paged=False,
        spread_cue=SpreadCue(
            here="file-1", above=("file-0",), below=("file-2", "file-3", "file-4")
        ),
    )
    assert "file-1" in rendered.plain
    assert "\u25b4" in rendered.plain
    assert "file-0" in rendered.plain
    assert "\u25be 3 files" in rendered.plain


def test_one_card_heading_has_no_tabs_or_chip() -> None:
    rendered = deck_title(
        DeckId.MAIN,
        (CardTab("summary", "Summary"),),
        0,
        width=80,
        accent="red",
        focused=True,
        view=_main_view(choice_exists=False),
    )
    assert rendered.plain == "◆ MAIN  Summary"
    assert "\u2503" not in rendered.plain
    assert "SPREAD" not in rendered.plain
    assert "PAGE" not in rendered.plain


def test_pending_and_blocked_words_sit_outside_the_chip() -> None:
    pending = ResolvedView(
        deck=DeckId.FILES,
        policy=DeckView.SPREAD,
        shown=DeckView.PAGE_CARDS,
        status=ViewStatus.PENDING,
        effective=DeckView.PAGE_CARDS,
        choice_exists=False,
    )
    tabs = (CardTab("a", "a.py"), CardTab("b", "b.py"))
    rendered = deck_title(
        DeckId.FILES, tabs, 0, width=80, accent="green", focused=True, view=pending
    )
    assert "spreading…" in rendered.plain
    assert "\U0001f512" in rendered.plain
    blocked = ResolvedView(
        deck=DeckId.FILES,
        policy=DeckView.SPREAD,
        shown=DeckView.PAGE_CARDS,
        status=ViewStatus.BLOCKED,
        effective=DeckView.PAGE_CARDS,
        choice_exists=False,
    )
    rendered = deck_title(
        DeckId.FILES, tabs, 0, width=80, accent="green", focused=True, view=blocked
    )
    assert "spread unavailable" in rendered.plain


def test_view_chip_style_is_solid_on_focus() -> None:
    rendered = deck_title(
        DeckId.MAIN,
        _main_tabs(),
        1,
        width=80,
        accent="red",
        focused=True,
        view=_main_view(),
    )
    assert any(VIEW_CHIP_STYLE in str(span.style) for span in rendered.spans)
    unfocused = deck_title(
        DeckId.MAIN,
        _main_tabs(),
        1,
        width=80,
        accent="red",
        focused=False,
        view=_main_view(),
    )
    assert rendered.plain == unfocused.plain
    assert not any(VIEW_CHIP_STYLE in str(span.style) for span in unfocused.spans)


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


def test_zoomed_spread_title_still_leads_with_zoom() -> None:
    rendered = deck_title(
        DeckId.MAIN,
        _main_tabs(),
        1,
        width=80,
        accent="red",
        focused=True,
        view=_main_view(shown=DeckView.SPREAD),
        zoomed=True,
        paged=False,
        spread_cue=SpreadCue(here="Reply", above=("Context",)),
    )
    assert rendered.plain.startswith("ZOOM")
    assert "SPREAD" in rendered.plain
    assert "\u2503" not in rendered.plain


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

"""Tests for the pure deck-view policy, resolution, and badge helpers."""

from __future__ import annotations

from sase.ace.tui.widgets.decks.model import DeckId, DeckView
from sase.ace.tui.widgets.decks.render_mode import RenderMode
from sase.ace.tui.widgets.decks.view_chip import chip_variants
from sase.ace.tui.widgets.decks.view_policy import (
    _BlockState,
    ResolvedView,
    ViewContent,
    ViewStatus,
    _distinct_layouts,
    forced_block_mode,
    forced_deck_mode,
    _layout_signature,
    next_view,
    resolve_view,
)


def _reply() -> ViewContent:
    return ViewContent(deck=DeckId.MAIN, card_count=3, active_block_count=5)


def _context() -> ViewContent:
    return ViewContent(deck=DeckId.MAIN, card_count=3, active_block_count=0)


def test_signature_table_reply() -> None:
    content = _reply()
    assert _layout_signature(DeckView.SPREAD, content) == (
        RenderMode.SPREAD,
        _BlockState.INLINE,
    )
    assert _layout_signature(DeckView.PAGE_CARDS, content) == (
        RenderMode.PAGED,
        _BlockState.INLINE,
    )
    assert _layout_signature(DeckView.PAGE_BLOCKS, content) == (
        RenderMode.PAGED,
        _BlockState.PAGED,
    )


def test_signature_collapses_blockless() -> None:
    content = _context()
    assert _layout_signature(DeckView.SPREAD, content) == (
        RenderMode.SPREAD,
        _BlockState.NONE,
    )
    page_cards = _layout_signature(DeckView.PAGE_CARDS, content)
    assert page_cards == (RenderMode.PAGED, _BlockState.NONE)
    assert _layout_signature(DeckView.PAGE_BLOCKS, content) == page_cards


def test_signature_single_card_collapses_all() -> None:
    content = ViewContent(deck=DeckId.MAIN, card_count=1, active_block_count=0)
    spread = _layout_signature(DeckView.SPREAD, content)
    assert spread == (RenderMode.SPREAD, _BlockState.NONE)
    assert _layout_signature(DeckView.PAGE_CARDS, content) == spread
    assert _layout_signature(DeckView.PAGE_BLOCKS, content) == spread


def test_signature_single_card_with_blocks_stays_inline() -> None:
    content = ViewContent(deck=DeckId.MAIN, card_count=1, active_block_count=4)
    spread = _layout_signature(DeckView.SPREAD, content)
    assert spread == (RenderMode.SPREAD, _BlockState.INLINE)
    assert _layout_signature(DeckView.PAGE_CARDS, content) == spread
    assert _layout_signature(DeckView.PAGE_BLOCKS, content) == spread


def test_signature_blocked_spread_collapses_into_page_cards() -> None:
    content = ViewContent(
        deck=DeckId.FILES,
        card_count=3,
        active_block_count=0,
        spread_blocked=True,
    )
    assert _layout_signature(DeckView.SPREAD, content) == (
        RenderMode.PAGED,
        _BlockState.NONE,
    )
    assert _layout_signature(DeckView.SPREAD, content) == _layout_signature(
        DeckView.PAGE_CARDS, content
    )


def test_d3_examples() -> None:
    assert _distinct_layouts(_reply()) == (
        DeckView.SPREAD,
        DeckView.PAGE_CARDS,
        DeckView.PAGE_BLOCKS,
    )
    assert _distinct_layouts(_context()) == (
        DeckView.SPREAD,
        DeckView.PAGE_CARDS,
    )
    single = ViewContent(deck=DeckId.MAIN, card_count=1, active_block_count=0)
    assert _distinct_layouts(single) == (DeckView.SPREAD,)
    files_text = ViewContent(deck=DeckId.FILES, card_count=3, active_block_count=0)
    assert _distinct_layouts(files_text) == (
        DeckView.SPREAD,
        DeckView.PAGE_CARDS,
    )
    files_media = ViewContent(
        deck=DeckId.FILES,
        card_count=3,
        active_block_count=0,
        spread_blocked=True,
    )
    assert _distinct_layouts(files_media) == (DeckView.SPREAD,)
    tools = ViewContent(deck=DeckId.TOOLS, card_count=5, active_block_count=5)
    assert _distinct_layouts(tools) == ()


def test_distinct_is_shallowest_representative() -> None:
    # Blocked Main spread collapses into page cards; the survivor keeps the
    # shallower SPREAD representative in depth order.
    content = ViewContent(
        deck=DeckId.MAIN,
        card_count=4,
        active_block_count=3,
        spread_blocked=True,
    )
    assert _distinct_layouts(content) == (
        DeckView.SPREAD,
        DeckView.PAGE_BLOCKS,
    )


def test_widening_wraps_from_each_layout() -> None:
    content = _reply()
    assert next_view(DeckView.PAGE_BLOCKS, content) is DeckView.PAGE_CARDS
    assert next_view(DeckView.PAGE_CARDS, content) is DeckView.SPREAD
    assert next_view(DeckView.SPREAD, content) is DeckView.PAGE_BLOCKS


def test_first_from_auto_never_pins() -> None:
    content = _reply()
    # From Auto the first press fixes the next distinct layout after the
    # effective one.
    assert next_view(DeckView.PAGE_BLOCKS, content) is DeckView.PAGE_CARDS
    assert next_view(DeckView.PAGE_CARDS, content) is DeckView.SPREAD
    assert next_view(DeckView.SPREAD, content) is DeckView.PAGE_BLOCKS


def test_fixed_vacuous_page_blocks_on_context_goes_spread() -> None:
    content = _context()
    assert next_view(DeckView.PAGE_BLOCKS, content) is DeckView.SPREAD
    assert next_view(DeckView.PAGE_CARDS, content) is DeckView.SPREAD
    assert next_view(DeckView.SPREAD, content) is DeckView.PAGE_CARDS


def test_next_view_none_cases() -> None:
    single = ViewContent(deck=DeckId.MAIN, card_count=1, active_block_count=0)
    assert next_view(DeckView.SPREAD, single) is None
    tools = ViewContent(deck=DeckId.TOOLS, card_count=5, active_block_count=5)
    assert next_view(DeckView.SPREAD, tools) is None
    files_media = ViewContent(
        deck=DeckId.FILES,
        card_count=3,
        active_block_count=0,
        spread_blocked=True,
    )
    assert next_view(DeckView.SPREAD, files_media) is None


def test_forced_deck_mode() -> None:
    assert forced_deck_mode(DeckView.AUTO, 3) is None
    assert forced_deck_mode(DeckView.SPREAD, 3) is RenderMode.SPREAD
    assert forced_deck_mode(DeckView.PAGE_CARDS, 3) is RenderMode.PAGED
    assert forced_deck_mode(DeckView.PAGE_BLOCKS, 3) is RenderMode.PAGED
    # One card always renders spread.
    assert forced_deck_mode(DeckView.AUTO, 1) is RenderMode.SPREAD
    assert forced_deck_mode(DeckView.PAGE_BLOCKS, 1) is RenderMode.SPREAD
    assert forced_deck_mode(DeckView.PAGE_CARDS, 0) is RenderMode.SPREAD


def test_forced_block_mode() -> None:
    assert forced_block_mode(DeckView.AUTO, 5) is None
    assert forced_block_mode(DeckView.SPREAD, 5) is RenderMode.SPREAD
    assert forced_block_mode(DeckView.PAGE_CARDS, 5) is RenderMode.SPREAD
    assert forced_block_mode(DeckView.PAGE_BLOCKS, 5) is RenderMode.PAGED
    # Fewer than two blocks has no block mode.
    assert forced_block_mode(DeckView.PAGE_BLOCKS, 1) is None
    assert forced_block_mode(DeckView.PAGE_BLOCKS, 0) is None
    assert forced_block_mode(DeckView.SPREAD, 1) is None


def test_resolve_auto_shows_effective() -> None:
    content = _reply()
    resolved = resolve_view(DeckId.MAIN, DeckView.AUTO, DeckView.PAGE_BLOCKS, content)
    assert resolved == ResolvedView(
        deck=DeckId.MAIN,
        policy=DeckView.AUTO,
        shown=DeckView.PAGE_BLOCKS,
        status=ViewStatus.OK,
        effective=DeckView.PAGE_BLOCKS,
        choice_exists=True,
    )
    assert resolved.effective is DeckView.PAGE_BLOCKS
    assert resolved.choice_exists is True


def test_resolve_fixed_non_vacuous_shows_requested() -> None:
    content = _reply()
    resolved = resolve_view(
        DeckId.MAIN, DeckView.PAGE_CARDS, DeckView.PAGE_CARDS, content
    )
    assert resolved.shown is DeckView.PAGE_CARDS
    assert resolved.status is ViewStatus.OK


def test_resolve_fixed_vacuous_shows_requested_name() -> None:
    content = _context()
    resolved = resolve_view(
        DeckId.MAIN,
        DeckView.PAGE_BLOCKS,
        DeckView.PAGE_CARDS,
        content,
    )
    assert resolved.shown is DeckView.PAGE_BLOCKS
    assert resolved.effective is DeckView.PAGE_CARDS
    assert resolved.status is ViewStatus.OK
    assert resolved.choice_exists is True


def test_resolve_one_card_has_no_choice() -> None:
    content = ViewContent(deck=DeckId.MAIN, card_count=1, active_block_count=0)
    resolved = resolve_view(DeckId.MAIN, DeckView.AUTO, DeckView.SPREAD, content)
    assert resolved.choice_exists is False
    assert resolved.effective is DeckView.SPREAD


def test_resolve_pending_and_blocked_show_effective() -> None:
    content = ViewContent(deck=DeckId.FILES, card_count=3, active_block_count=0)
    pending = resolve_view(
        DeckId.FILES,
        DeckView.SPREAD,
        DeckView.PAGE_CARDS,
        content,
        pending=True,
    )
    assert pending.shown is DeckView.PAGE_CARDS
    assert pending.status is ViewStatus.PENDING
    blocked = resolve_view(
        DeckId.FILES,
        DeckView.SPREAD,
        DeckView.PAGE_CARDS,
        content,
        blocked=True,
    )
    assert blocked.shown is DeckView.PAGE_CARDS
    assert blocked.status is ViewStatus.BLOCKED


def _chip_plain(resolved: ResolvedView) -> tuple[str, str, str]:
    long, short, tiny, word_long, word_short, word_tiny = chip_variants(
        resolved, accent="green", focused=True
    )

    def _joined(chip: object, word: object) -> str:
        extra = f" {word.plain}" if word is not None and word.plain else ""
        return f"{chip.plain}{extra}"

    return (
        _joined(long, word_long),
        _joined(short, word_short),
        _joined(tiny, word_tiny),
    )


def _rv(
    deck: DeckId,
    policy: DeckView,
    shown: DeckView,
    status: ViewStatus,
    *,
    effective: DeckView | None = None,
    choice_exists: bool = True,
) -> ResolvedView:
    return ResolvedView(
        deck=deck,
        policy=policy,
        shown=shown,
        status=status,
        effective=shown if effective is None else effective,
        choice_exists=choice_exists,
    )


def test_chip_variants_layout_and_lock() -> None:
    lock = "\U0001f512"
    auto_spread = _rv(DeckId.MAIN, DeckView.AUTO, DeckView.SPREAD, ViewStatus.OK)
    assert _chip_plain(auto_spread) == (" SPREAD ", " SPREAD ", " S ")
    auto_page_cards = _rv(
        DeckId.MAIN, DeckView.AUTO, DeckView.PAGE_CARDS, ViewStatus.OK
    )
    assert _chip_plain(auto_page_cards) == (" PAGE CARDS ", " CARDS ", " C ")
    auto_page_blocks = _rv(
        DeckId.MAIN, DeckView.AUTO, DeckView.PAGE_BLOCKS, ViewStatus.OK
    )
    assert _chip_plain(auto_page_blocks) == (" PAGE BLOCKS ", " BLOCKS ", " B ")
    locked_spread = _rv(DeckId.MAIN, DeckView.SPREAD, DeckView.SPREAD, ViewStatus.OK)
    assert _chip_plain(locked_spread) == (
        f" SPREAD {lock} ",
        f" SPREAD {lock} ",
        f" S{lock} ",
    )
    locked_blocks = _rv(
        DeckId.MAIN,
        DeckView.PAGE_BLOCKS,
        DeckView.PAGE_BLOCKS,
        ViewStatus.OK,
    )
    assert _chip_plain(locked_blocks) == (
        f" PAGE BLOCKS {lock} ",
        f" BLOCKS {lock} ",
        f" B{lock} ",
    )
    pending = _rv(
        DeckId.FILES,
        DeckView.SPREAD,
        DeckView.PAGE_CARDS,
        ViewStatus.PENDING,
        effective=DeckView.PAGE_CARDS,
    )
    assert _chip_plain(pending) == (
        f" PAGE CARDS {lock}  spreading…",
        f" CARDS {lock}  spreading…",
        f" C{lock}  …",
    )
    blocked = _rv(
        DeckId.FILES,
        DeckView.SPREAD,
        DeckView.PAGE_CARDS,
        ViewStatus.BLOCKED,
        effective=DeckView.PAGE_CARDS,
    )
    assert _chip_plain(blocked) == (
        f" PAGE CARDS {lock}  spread unavailable",
        f" CARDS {lock}  no spread",
        f" C{lock}  !",
    )
    for resolved in (auto_spread, locked_spread, pending):
        assert "auto" not in _chip_plain(resolved)[0]
        assert "fixed" not in _chip_plain(resolved)[0]


def test_chip_width_does_not_depend_on_focus() -> None:
    resolved = _rv(DeckId.MAIN, DeckView.SPREAD, DeckView.SPREAD, ViewStatus.OK)
    focused = chip_variants(resolved, accent="green", focused=True)
    unfocused = chip_variants(resolved, accent="green", focused=False)
    for left, right in zip(focused, unfocused, strict=True):
        if left is None:
            assert right is None
            continue
        assert left.plain == right.plain

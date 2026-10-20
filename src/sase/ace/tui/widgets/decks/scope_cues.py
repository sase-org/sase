"""Viewport-precise spread cues and paged continuation cues (pure helpers)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from rich.text import Text

if TYPE_CHECKING:
    from .model import DeckId
    from .title_scope import SpreadCue

_MUTED = "#888888"
_SUBTITLE_SEPARATOR = "#888888"


def _card_ends_from_anchors(
    ordered_ids: Sequence[str],
    anchor_by_id: Mapping[str, int],
    total_excluding_reserve: int,
) -> dict[str, int | None]:
    """Return ``card_id -> end row`` for ordered spread cards.

    Every card except the last ends where the next card's anchor starts.
    The last card ends at ``total_excluding_reserve``. Missing next anchors
    yield ``None`` so callers stay conservative (keep the cue).
    """
    ordered = tuple(ordered_ids)
    ends: dict[str, int | None] = {}
    for index, card_id in enumerate(ordered):
        if index + 1 < len(ordered):
            nxt = ordered[index + 1]
            try:
                ends[card_id] = int(anchor_by_id[nxt])
            except Exception:
                ends[card_id] = None
        else:
            ends[card_id] = int(total_excluding_reserve)
    return ends


def _viewport_partition(
    ordered_ids: Sequence[str],
    here_id: str | None,
    anchor_by_id: Mapping[str, int] | None,
    ends_by_id: Mapping[str, int | None] | None,
    *,
    scroll_y: int,
    viewport_height: int,
    max_scroll_y: int,
) -> tuple[tuple[str, ...], tuple[str, ...], bool]:
    """Partition ordered ids into viewport-aware ``(above, below, all_in_view)``.

    ``here_id`` is the scroll-spy active card. Every card before it is
    fully above the viewport, so ``above`` lists all of them. Cards after
    it are listed only when not fully in view
    (``card end > scroll_y + viewport height``). ``all_in_view`` is true
    when no card lies off-screen in either direction. Unknown ends stay
    conservative (kept in ``below``). ``max_scroll_y`` only documents the
    scroll range; filtering against the cached ends already covers the
    no-scroll-range case.
    """
    ordered = tuple(ordered_ids)
    if here_id is None or here_id not in ordered:
        # Anchors not usable: caller falls back to the structural cue.
        return ((), (), False)
    try:
        here_index = ordered.index(here_id)
    except ValueError:
        return ((), (), False)
    above = tuple(ordered[:here_index])
    viewport_bottom = int(scroll_y) + int(viewport_height)
    below: list[str] = []
    for card_id in ordered[here_index + 1 :]:
        end: int | None = None
        if ends_by_id is not None:
            try:
                end = ends_by_id.get(card_id)
            except Exception:
                end = None
        if end is None:
            below.append(card_id)
            continue
        try:
            if int(end) > viewport_bottom:
                below.append(card_id)
        except Exception:
            below.append(card_id)
    below_tuple = tuple(below)
    return (above, below_tuple, not above and not below_tuple)


def resolve_viewport_spread(
    ordered_ids: Sequence[str],
    here_id: str | None,
    anchor_rows: tuple[tuple[str, int], ...] | None,
    *,
    scroll_y: int,
    viewport_height: int,
    max_scroll_y: int,
    reserve: int = 0,
) -> tuple[tuple[str, ...], tuple[str, ...], bool, bool]:
    """Return ``(above_ids, below_ids, all_in_view, anchors_ready)``.

    ``anchor_rows`` is the cached ``card_anchor_rows(width=...)`` result
    (``None`` when layout has not published yet). The first card's anchor
    is implicitly row 0. The trailing layout reserve (from
    ``scroll_to_card()``) is excluded from the last card's end via
    ``total - reserve``; without a reserve the raw total is used and the
    cue stays conservative.
    """
    ordered = tuple(ordered_ids)
    if not ordered:
        return ((), (), False, False)
    if anchor_rows is None:
        return ((), (), False, False)
    try:
        anchor_by_id: dict[str, int] = {cid: int(row) for cid, row in anchor_rows}
    except Exception:
        return ((), (), False, False)
    if ordered[0] not in anchor_by_id:
        anchor_by_id[ordered[0]] = 0
    try:
        total = int(max_scroll_y) + int(viewport_height)
    except Exception:
        return ((), (), False, False)
    try:
        reserve_int = max(0, int(reserve))
    except Exception:
        reserve_int = 0
    total_excluding_reserve = max(0, total - reserve_int)
    try:
        viewport_int = int(viewport_height)
    except Exception:
        viewport_int = 0
    if here_id not in ordered:
        return ((), (), False, False)
    here_index = ordered.index(here_id)
    structural_above = tuple(ordered[:here_index])
    structural_below = tuple(ordered[here_index + 1 :])
    try:
        ends = _card_ends_from_anchors(ordered, anchor_by_id, total_excluding_reserve)
    except Exception:
        ends = {}
    _above, below, _all_in_view = _viewport_partition(
        ordered,
        here_id,
        anchor_by_id,
        ends,
        scroll_y=int(scroll_y),
        viewport_height=int(viewport_height),
        max_scroll_y=int(max_scroll_y),
    )
    # All in view only when no card lies off-screen in either direction and
    # the real content (excluding the trailing scroll_to_card reserve, which
    # inflates max_scroll_y) fits the viewport. The True case keeps the
    # structural lists so the scope key stays stable.
    if (
        not structural_above
        and not below
        and viewport_int > 0
        and (total_excluding_reserve <= viewport_int)
    ):
        return (structural_above, structural_below, True, True)
    return (structural_above, below, False, True)


def _block_noun(count: int) -> str:
    return "block" if count == 1 else "blocks"


def continuation_texts(
    deck: DeckId,
    *,
    tab_count: int,
    block_count: int | None,
    block_paged: bool,
    card_key: str = "",
    block_prev_key: str = "",
    block_next_key: str = "",
    at_bottom: bool = False,
    focused: bool = True,
    accent: str = "",
) -> tuple[Text | None, Text | None]:
    """Return the paged ``(full, counts-only)`` continuation cue.

    Counts only what is not on this page: ``cards - 1`` and, in page
    blocks, ``blocks - 1``. ``card_key`` is the ``next_deck_card`` display
    (empty when unbound); ``block_prev_key``/``block_next_key`` are the
    ``prev/next_card_block`` displays (empty when unbound). An unbound key
    drops its segment. The resting style is muted counts with the key in
    the deck accent; at the bottom the whole cue turns bold accent on the
    focused panel; unfocused panels are dim.
    """
    try:
        tabs = int(tab_count)
    except Exception:
        tabs = 0
    card_remaining = max(0, tabs - 1) if tabs >= 2 else 0
    blocks_remaining = 0
    if bool(block_paged):
        try:
            blocks = int(block_count) if block_count is not None else 0
        except Exception:
            blocks = 0
        if blocks >= 2:
            blocks_remaining = blocks - 1
    if card_remaining <= 0 and blocks_remaining <= 0:
        return (None, None)
    accent_clean = str(accent or "").strip()
    key_style = f"bold {accent_clean}".strip() if accent_clean else "bold"
    if not focused:
        count_style = "dim"
        sep_style = "dim"
        key_style = "dim"
    elif bool(at_bottom):
        at_bottom_style = f"bold {accent_clean}".strip() if accent_clean else "bold"
        count_style = at_bottom_style
        sep_style = at_bottom_style
        key_style = at_bottom_style
    else:
        count_style = _MUTED
        sep_style = _SUBTITLE_SEPARATOR
    card_key_clean = str(card_key or "").strip()
    prev_clean = str(block_prev_key or "").strip()
    next_clean = str(block_next_key or "").strip()
    if prev_clean and next_clean:
        block_key_segment = f"{prev_clean}/{next_clean}"
    else:
        block_key_segment = prev_clean or next_clean
    # Full cue: counts plus key segments.
    full = Text()
    full_parts: list[tuple[str, str]] = []
    if blocks_remaining > 0:
        full_parts.append(
            (f"+{blocks_remaining} {_block_noun(blocks_remaining)}", count_style)
        )
        if block_key_segment:
            full_parts.append((block_key_segment, key_style))
    if card_remaining > 0:
        if deck is not None and getattr(deck, "name", "") == "FILES":
            noun = "file" if card_remaining == 1 else "files"
        else:
            noun = "card" if card_remaining == 1 else "cards"
        full_parts.append((f"+{card_remaining} {noun}", count_style))
        if card_key_clean:
            full_parts.append((card_key_clean, key_style))
    for index, (segment, style) in enumerate(full_parts):
        if index > 0:
            full.append(" \u00b7 ", style=sep_style)
        full.append(segment, style=style)
    # Counts-only cue: drop every key segment.
    bare = Text()
    bare_parts: list[tuple[str, str]] = []
    if blocks_remaining > 0:
        bare_parts.append(
            (f"+{blocks_remaining} {_block_noun(blocks_remaining)}", count_style)
        )
    if card_remaining > 0:
        if deck is not None and getattr(deck, "name", "") == "FILES":
            noun = "file" if card_remaining == 1 else "files"
        else:
            noun = "card" if card_remaining == 1 else "cards"
        bare_parts.append((f"+{card_remaining} {noun}", count_style))
    for index, (segment, style) in enumerate(bare_parts):
        if index > 0:
            bare.append(" \u00b7 ", style=sep_style)
        bare.append(segment, style=style)
    if not full.plain or not bare.plain:
        return (None, None)
    return (full, bare)


def viewport_spread_cue(
    ordered_ids: Sequence[str],
    id_to_title: Mapping[str, str],
    here_id: str | None,
    above_ids: Sequence[str],
    below_ids: Sequence[str],
    *,
    all_in_view: bool,
) -> SpreadCue | None:
    """Build the viewport-precise ``SpreadCue`` from id partitions."""
    from .title_scope import SpreadCue

    ordered = tuple(ordered_ids)
    if not ordered or here_id is None or here_id not in ordered:
        return None

    def _title(card_id: str) -> str:
        try:
            title = id_to_title.get(card_id, card_id)
        except Exception:
            title = card_id
        return str(title)

    return SpreadCue(
        here=_title(here_id),
        above=tuple(_title(card_id) for card_id in above_ids),
        below=tuple(_title(card_id) for card_id in below_ids),
        all_in_view=bool(all_in_view),
        total=len(ordered),
    )


__all__ = [
    "continuation_texts",
    "resolve_viewport_spread",
    "viewport_spread_cue",
]

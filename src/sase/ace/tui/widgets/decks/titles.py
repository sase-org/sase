"""Pure deck title and subtitle helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui.util.pane_grid import Axis, PaneGrid, position_glyph

from .model import DeckId, DeckLayout
from .spec import DECK_SPECS, active_deck_cycle

from .view_policy import ResolvedView

DECK_GLYPHS: dict[DeckId, str] = {s.deck_id: s.glyph for s in DECK_SPECS}

DECK_NAMES: dict[DeckId, str] = {s.deck_id: s.name for s in DECK_SPECS}

# Dead table, kept for compatibility; derived from the spec registry.
DECK_ACCENTS: dict[DeckId, str] = {s.deck_id: s.fallback_accent for s in DECK_SPECS}

DECK_PICKER_KEYS: dict[DeckId, str] = {s.deck_id: s.picker_key for s in DECK_SPECS}

DECK_BLURBS: dict[DeckId, str] = {s.deck_id: s.blurb for s in DECK_SPECS}

DECK_COUNT_NOUNS: dict[DeckId, tuple[str, str]] = {
    s.deck_id: s.count_noun for s in DECK_SPECS
}

DECK_PICKER_RESERVED_KEYS = frozenset({"j", "k", "q", "p"})

_MUTED = "#888888"
_SEPARATOR = "#444444"

ZOOM_CHIP_TEXT = "ZOOM"
ZOOM_CHIP_STYLE = "bold #1a1a1a on #FFD700"
ZOOM_CHIP_WIDTH = 5  # "ZOOM" plus one trailing space.

_ZOOM_HALF_AXIS: dict[DeckLayout, Axis] = {
    DeckLayout.LEFT_RIGHT: Axis.COLS,
    DeckLayout.TOP_BOTTOM: Axis.ROWS,
}


def _zoom_half_glyph(from_layout: DeckLayout, panel_index: int) -> str:
    """Return the one-cell position glyph for a zoomed two-pane half."""
    axis = _ZOOM_HALF_AXIS.get(from_layout)
    if axis is None or panel_index not in (0, 1):
        return ""
    grid = PaneGrid(
        panes=(0, 1),
        focused=panel_index,
        axis=axis,
        ratio=50,
        recent=(panel_index, 1 - panel_index),
    )
    return position_glyph(grid, panel_index)


@dataclass(frozen=True)
class ZoomChrome:
    """Context for the zoom restore hint on the zoomed deck panel.

    ``from_layout`` and ``panel_count`` come from the zoom snapshot, so a
    split zoom names its half (``1 of 2``) while a single-deck zoom reads
    just ``Z restore``. ``zoom_key`` is the configured ``zoom_panel`` key
    display, resolved live by the chrome mixin; empty means unbound, and
    the key segment is then omitted.
    """

    from_layout: DeckLayout
    panel_index: int
    panel_count: int
    zoom_key: str = ""
    glyph: str = ""


@dataclass(frozen=True)
class CardTab:
    """One tab in a deck title strip."""

    card_id: str
    title: str


def _plain_width(text: Text) -> int:
    return cell_len(text.plain)


def _append_name(
    text: Text,
    deck: DeckId,
    *,
    accent: str,
    focused: bool,
    badge: Text | None,
) -> None:
    """Append ``glyph NAME`` plus the optional view badge after it."""
    glyph = DECK_GLYPHS[deck]
    name = DECK_NAMES[deck]
    if focused:
        text.append(f"{glyph} {name} ", style=f"bold {accent}")
    else:
        text.append(f"{glyph} {name} ", style="dim")
    if badge is not None:
        text.append_text(badge)
        text.append(" ", style="")


def _build_full(
    deck: DeckId,
    tabs: Sequence[CardTab],
    active_index: int | None,
    *,
    accent: str,
    focused: bool,
    badge: Text | None = None,
) -> Text:
    text = Text()
    _append_name(text, deck, accent=accent, focused=focused, badge=badge)
    text.append("\u2503", style=_SEPARATOR)
    text.append(" ", style="")
    for i, tab in enumerate(tabs):
        if i > 0:
            text.append(" \u2502 ", style=_SEPARATOR)
        if active_index is not None and i == active_index:
            if focused:
                text.append(tab.title, style=f"reverse bold {accent}")
            else:
                text.append(tab.title, style="dim")
        else:
            text.append(tab.title, style=_MUTED)
    if active_index is not None and len(tabs) > 1:
        text.append(f"  {active_index + 1}/{len(tabs)}", style=_MUTED)
    return text


def _build_compact(
    deck: DeckId,
    tabs: Sequence[CardTab],
    active_index: int | None,
    *,
    accent: str,
    focused: bool,
    badge: Text | None = None,
) -> Text:
    text = Text()
    _append_name(text, deck, accent=accent, focused=focused, badge=badge)
    text.append("\u2503", style=_SEPARATOR)
    text.append(" ", style="")
    if active_index is not None and 0 <= active_index < len(tabs):
        if len(tabs) > 1:
            text.append(f"\u2039 {active_index + 1}/{len(tabs)} \u203a ", style=_MUTED)
        text.append(
            tabs[active_index].title, style=f"bold {accent}" if focused else "dim"
        )
    elif tabs:
        text.append(tabs[0].title, style=_MUTED)
    return text


def _build_micro(
    deck: DeckId,
    tabs: Sequence[CardTab],
    active_index: int | None,
    *,
    accent: str,
    focused: bool,
    badge: Text | None = None,
) -> Text:
    del accent
    del focused
    text = Text()
    text.append(DECK_NAMES[deck], style=_MUTED)
    if badge is not None:
        text.append(" ", style="")
        text.append_text(badge)
    if active_index is not None and len(tabs) > 1:
        text.append(f" {active_index + 1}/{len(tabs)}", style=_MUTED)
    return text


def _skips_full_tier(deck: DeckId, tab_count: int) -> bool:
    """Return whether ``deck`` skips the full tab rungs when crowded.

    Files and FINAL decks with more than 4 tabs skip the full rungs;
    FINAL has no title badge, so it shares Files' compact-only rungs.
    """
    return deck in (DeckId.FILES, DeckId.FINAL) and tab_count > 4


def _badge_variants(
    deck: DeckId, view: ResolvedView | None, *, accent: str, focused: bool
) -> tuple[Text | None, Text | None, Text | None]:
    """Return the (long, short, tiny) badge, or Nones when deck has no badge."""
    if view is None:
        return (None, None, None)
    if deck is DeckId.MAIN or deck is DeckId.FILES:
        from .view_badge import badge_variants

        long, short, tiny = badge_variants(view, accent=accent, focused=focused)
        return (long, short, tiny)
    return (None, None, None)


def _with_zoom_chip(rung: Text) -> Text:
    """Return ``rung`` led by the reverse-gold ZOOM chip plus a space."""
    chip = Text()
    chip.append(ZOOM_CHIP_TEXT, style=ZOOM_CHIP_STYLE)
    chip.append(" ", style="")
    chip.append_text(rung)
    return chip


def deck_title(
    deck: DeckId,
    tabs: Sequence[CardTab],
    active_index: int | None,
    *,
    width: int,
    accent: str,
    focused: bool,
    view: ResolvedView | None = None,
    zoomed: bool = False,
) -> Text:
    """Render a deck title tab strip, picking the widest fitting tier.

    ``view`` adds the effective-view badge after the deck name for Main
    and Files decks; every other deck (and ``None``) keeps the tab-only
    rungs. The first rung that fits the chrome budget wins: full tabs +
    long badge, full tabs + short badge, compact tabs + long badge,
    compact tabs + short badge, compact tabs + tiny badge, micro + tiny
    badge, then micro alone.

    When ``zoomed``, every rung is led by the reverse-gold ZOOM chip and
    rungs are picked against ``width`` minus the chip; the chip is never
    dropped, so below the smallest rung the chip alone remains.
    """
    tabs = tuple(tabs)
    long_badge, short_badge, tiny_badge = _badge_variants(
        deck, view, accent=accent, focused=focused
    )
    has_badge = long_badge is not None
    # Files and FINAL list full-tier tabs only when there are 4 or fewer;
    # FINAL has no badge, so it shares Files' compact-only rungs.
    use_compact_full = _skips_full_tier(deck, len(tabs))
    candidates: list[tuple[str, Text]]
    if use_compact_full:
        candidates = [
            (
                "compact",
                _build_compact(
                    deck, tabs, active_index, accent=accent, focused=focused
                ),
            ),
            (
                "micro",
                _build_micro(deck, tabs, active_index, accent=accent, focused=focused),
            ),
        ]
    else:
        candidates = [
            (
                "full",
                _build_full(deck, tabs, active_index, accent=accent, focused=focused),
            ),
            (
                "compact",
                _build_compact(
                    deck, tabs, active_index, accent=accent, focused=focused
                ),
            ),
            (
                "micro",
                _build_micro(deck, tabs, active_index, accent=accent, focused=focused),
            ),
        ]
    if has_badge:
        assert long_badge is not None and short_badge is not None
        assert tiny_badge is not None
        if use_compact_full:
            candidates = [
                (
                    "compact-long",
                    _build_compact(
                        deck,
                        tabs,
                        active_index,
                        accent=accent,
                        focused=focused,
                        badge=long_badge,
                    ),
                ),
                (
                    "compact-short",
                    _build_compact(
                        deck,
                        tabs,
                        active_index,
                        accent=accent,
                        focused=focused,
                        badge=short_badge,
                    ),
                ),
                (
                    "compact-tiny",
                    _build_compact(
                        deck,
                        tabs,
                        active_index,
                        accent=accent,
                        focused=focused,
                        badge=tiny_badge,
                    ),
                ),
                (
                    "micro-tiny",
                    _build_micro(
                        deck,
                        tabs,
                        active_index,
                        accent=accent,
                        focused=focused,
                        badge=tiny_badge,
                    ),
                ),
                candidates[1],
            ]
        else:
            candidates = [
                (
                    "full-long",
                    _build_full(
                        deck,
                        tabs,
                        active_index,
                        accent=accent,
                        focused=focused,
                        badge=long_badge,
                    ),
                ),
                (
                    "full-short",
                    _build_full(
                        deck,
                        tabs,
                        active_index,
                        accent=accent,
                        focused=focused,
                        badge=short_badge,
                    ),
                ),
                (
                    "compact-long",
                    _build_compact(
                        deck,
                        tabs,
                        active_index,
                        accent=accent,
                        focused=focused,
                        badge=long_badge,
                    ),
                ),
                (
                    "compact-short",
                    _build_compact(
                        deck,
                        tabs,
                        active_index,
                        accent=accent,
                        focused=focused,
                        badge=short_badge,
                    ),
                ),
                (
                    "compact-tiny",
                    _build_compact(
                        deck,
                        tabs,
                        active_index,
                        accent=accent,
                        focused=focused,
                        badge=tiny_badge,
                    ),
                ),
                (
                    "micro-tiny",
                    _build_micro(
                        deck,
                        tabs,
                        active_index,
                        accent=accent,
                        focused=focused,
                        badge=tiny_badge,
                    ),
                ),
                candidates[2],
            ]
    if not zoomed:
        if width <= 0:
            return candidates[0][1]
        for _tier, rendered in candidates:
            if _plain_width(rendered) <= width:
                return rendered
        return candidates[-1][1]
    if width <= 0:
        return _with_zoom_chip(candidates[0][1])
    budget = width - ZOOM_CHIP_WIDTH
    for _tier, rendered in candidates:
        if _plain_width(rendered) <= budget:
            return _with_zoom_chip(rendered)
    chip_only = Text(ZOOM_CHIP_TEXT, style=ZOOM_CHIP_STYLE)
    return chip_only


def final_switcher_segment(status: str | None, glyph: str | None) -> Text:
    """Return the styled ``final <glyph>`` switcher segment (plan §3.6).

    The glyph renders in its status color so a landing failure shows in
    the border while reading Main or Files; unknown states stay dim.
    """
    from sase.finalizers.view_vocabulary import FINAL_GLYPH, STATE_STYLES

    mark = glyph or FINAL_GLYPH
    style = STATE_STYLES.get(status or "")
    color = style.color if style is not None else "dim"
    if color == "dim":
        return Text(f"final {mark}", style="dim")
    return Text(f"final {mark}", style=f"bold {color}")


def _build_switcher(
    parts: Sequence[tuple[str | Text, str | Text, str]], *, counts: bool
) -> Text:
    """Join the ``(label, counted label, style)`` deck switcher entries.

    A label may already be a styled ``Text`` segment (the FINAL status
    segment); styled segments keep their own style in both tiers.
    """
    switcher = Text()
    for i, (label, counted, style) in enumerate(parts):
        if i > 0:
            switcher.append(" \u00b7 ", style=_MUTED)
        segment = counted if counts else label
        if isinstance(segment, Text):
            switcher.append_text(segment)
        else:
            switcher.append(segment, style=style)
    return switcher


def _zoom_restore_text(zoom: ZoomChrome, *, accent: str, short: bool) -> Text:
    """Render the zoom restore lead: position plus the restore hint.

    From a split the full form names the zoomed half (``◧ 1 of 2``); from
    a single deck, and for the short form, only the restore hint remains.
    The configured key leads in bold accent and is omitted when unbound.
    """
    restore = Text()
    if not short and zoom.from_layout is not DeckLayout.SINGLE:
        glyph = zoom.glyph or _zoom_half_glyph(zoom.from_layout, zoom.panel_index)
        if glyph:
            restore.append(
                f"{glyph} {zoom.panel_index + 1} of {zoom.panel_count} ", style="dim"
            )
            restore.append("· ", style=_MUTED)
        else:
            restore.append(
                f"{zoom.panel_index + 1} of {zoom.panel_count} ", style="dim"
            )
            restore.append("· ", style=_MUTED)
    if zoom.zoom_key:
        restore.append(zoom.zoom_key, style=f"bold {accent}".strip())
        restore.append(" restore", style="dim")
    else:
        restore.append("restore", style="dim")
    return restore


def deck_subtitle(
    active: DeckId,
    availability: Mapping[DeckId, object],
    *,
    status: Text | None,
    width: int,
    accent_for: Mapping[DeckId, str],
    status_segments: Mapping[DeckId, Text] | None = None,
    zoom: ZoomChrome | None = None,
) -> Text:
    """Render the deck switcher with an optional leading status.

    The title badge now names the effective view, so the old ``spread``
    tag is gone. Tiers, widest first: status and counted switcher; then
    drop the switcher counts; then drop the switcher; and only then
    truncate. ``status_segments`` carries pre-styled switcher entries
    (the FINAL ``final <glyph>`` segment); they replace the count in both
    tiers.

    When ``zoom`` is set, the restore hint leads instead: the switcher
    counts drop first, then the switcher, then the half position (leaving
    the restore hint alone), and only then truncate.
    """
    from .availability import DeckAvailability

    parts: list[tuple[str | Text, str | Text, str]] = []
    for deck in active_deck_cycle():
        label = deck.value
        segment = status_segments.get(deck) if status_segments else None
        if isinstance(segment, Text):
            parts.append((segment, segment, ""))
            continue
        avail = availability.get(deck)
        count: int | None = None
        has_content: bool | None = None
        if isinstance(avail, DeckAvailability):
            has_content = avail.has_content
            count = avail.count
        if deck is active:
            style = f"bold {accent_for.get(deck, '')}".strip()
        elif has_content is False:
            style = "dim"
        else:
            style = ""
        display = label
        if isinstance(avail, DeckAvailability) and avail.count is not None:
            display = f"{label} {count}"
        parts.append((label, display, style))
    switcher = _build_switcher(parts, counts=True)
    bare_switcher = _build_switcher(parts, counts=False)

    def _joined(*pieces: Text | None) -> Text:
        joined = Text()
        for piece in (p for p in pieces if p is not None):
            if joined.plain:
                joined.append("  ", style="")
            joined.append_text(piece)
        return joined

    # Candidates in preference order; the first that fits the budget wins.
    if zoom is None:
        candidates = [
            _joined(status, switcher),
            _joined(status, bare_switcher),
        ]
        if width <= 0:
            return candidates[0]
        for candidate in candidates:
            if _plain_width(candidate) <= width:
                return candidate
        if status is not None:
            # Drop the switcher entirely, then truncate the status.
            if _plain_width(status) <= width:
                return _joined(status)
            return Text(status.plain[: max(0, width)], style="")
        return Text(bare_switcher.plain[: max(0, width)], style="")
    accent = str(accent_for.get(active, "") or "")
    restore_full = _zoom_restore_text(zoom, accent=accent, short=False)
    restore_short = _zoom_restore_text(zoom, accent=accent, short=True)
    zoomed_candidates = [
        _joined(restore_full, status, switcher),
        _joined(restore_full, status, bare_switcher),
        _joined(restore_full, status),
        _joined(restore_short, status),
        _joined(restore_short),
    ]
    if width <= 0:
        return zoomed_candidates[0]
    for candidate in zoomed_candidates:
        if _plain_width(candidate) <= width:
            return candidate
    return Text(restore_short.plain[: max(0, width)], style="")


def file_line_status(
    visible: int, total: int, capped: bool, *, editor_key: str
) -> Text | None:
    """Render the Files line-count status, or None when there are no lines."""
    if total == 0:
        return None
    if capped:
        return Text(
            f"1-{visible} of {total} lines \u00b7 {editor_key} editor", style=""
        )
    return Text(f"{total} lines", style="")

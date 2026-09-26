"""One-row block rail timeline for cards with navigable blocks.

The rail is a pure tiered renderer (:func:`block_rail_text`) plus a
pre-composed :class:`BlockRail` widget docked under the Main deck panel's
top border. Entries run chronologically left to right from each block's
:class:`BlockMeta` (roster number, glyph, label, status), the active entry
renders as an accent pill, unseen arrivals carry a dot, and the widest tier
adds a key hint at the right edge.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from rich.cells import cell_len
from rich.text import Text
from textual.events import Click, Resize
from textual.message import Message
from textual.widgets import Static

from sase.agent.status_buckets import AGENT_STATUS_BUCKET_GLYPHS

from .card_block import BlockMeta

_RAIL_SEPARATOR = " ─ "
_SEPARATOR_STYLE = "#444444"
_NUMBER_STYLE = "dim"
_LABEL_STYLE = "#888888"
_MUTED_STYLE = "#888888"
_ARRIVAL_GLYPH = "●"
_ARRIVAL_STYLE = "#5FD7FF"
_PILL_CAP_LEFT = "▐"
_PILL_CAP_RIGHT = "▌"
#: Left/right padding in the ``.deck-block-rail`` CSS rule. Click offsets
#: and panel width budgets must stay in sync with it.
RAIL_HORIZONTAL_PADDING = 2
#: Windowed tiers try these neighbor counts, widest first.
_WINDOW_NEIGHBORS = (3, 2, 1)

BlockRailTier = Literal["full-hint", "full", "windowed", "compact", "micro"]


@dataclass(frozen=True, slots=True)
class BlockRailEntry:
    """One rail entry: a block id plus its roster-derived display facts."""

    block_id: str
    meta: BlockMeta


def _status_glyph(bucket: str) -> str:
    """Return the roster status glyph for ``bucket``."""
    try:
        return AGENT_STATUS_BUCKET_GLYPHS.get(bucket, "•")
    except Exception:
        return "•"


def _status_style(bucket: str) -> str:
    """Return the roster status color for ``bucket``."""
    try:
        from ..prompt_panel._member_roster import member_status_style
    except Exception:
        return "bold #FFFFFF"
    try:
        return str(member_status_style(bucket))
    except Exception:
        return "bold #FFFFFF"


def _dim(style: str) -> str:
    """Return ``style`` dimmed for an unfocused panel."""
    if "dim" in style.split():
        return style
    return f"dim {style}" if style else "dim"


def _entry_inner(entry: BlockRailEntry) -> list[tuple[str, str]]:
    """Return ``(fragment, style)`` pairs for one full entry's inner text."""
    meta = entry.meta
    fragments = [(meta.number, _NUMBER_STYLE)]
    if meta.glyph:
        fragments.append((f" {meta.glyph}", meta.accent))
    fragments.append((f" {meta.label}", _LABEL_STYLE))
    fragments.append(
        (f" {_status_glyph(meta.status_bucket)}", _status_style(meta.status_bucket))
    )
    return fragments


def _truncate_middle(label: str, budget: int) -> str:
    """Truncate ``label`` with a middle ellipsis to ``budget`` cells."""
    if cell_len(label) <= budget:
        return label
    if budget <= 1:
        return "…"
    target = budget - 1
    head_target = int(target * 0.4)
    tail_target = target - head_target
    head = ""
    width = 0
    for char in label:
        char_width = cell_len(char)
        if width + char_width > head_target:
            break
        head += char
        width += char_width
    tail = ""
    width = 0
    for char in reversed(label):
        char_width = cell_len(char)
        if width + char_width > tail_target:
            break
        tail = char + tail
        width += char_width
    return f"{head}…{tail}"


class _RailBuilder:
    """Assemble one rail tier, tracking per-entry click ranges in cells."""

    def __init__(self, *, accent: str, focused: bool) -> None:
        self._text = Text()
        self._ranges: dict[str, tuple[int, int]] = {}
        self._column = 0
        self._accent = accent
        self._focused = focused

    def _style(self, style: str) -> str:
        return style if self._focused else _dim(style)

    def append(self, fragment: str, style: str | None = None) -> None:
        """Append ``fragment`` without recording a click range."""
        self._text.append(fragment, style=style or "")
        self._column += cell_len(fragment)

    def append_separator(self) -> None:
        """Append the ``─`` joiner between entries."""
        self.append(_RAIL_SEPARATOR, self._style(_SEPARATOR_STYLE))

    def append_entry(
        self,
        entry: BlockRailEntry,
        *,
        active: bool,
        arrived: bool,
        compact: bool = False,
    ) -> None:
        """Append one entry, recording its cell range for click-to-select."""
        if arrived:
            self.append(_ARRIVAL_GLYPH, _ARRIVAL_STYLE)
        start = self._column
        if active:
            pill = f"reverse bold {self._accent}" if self._focused else "reverse dim"
            cap = self._accent if self._focused else "dim"
            self.append(_PILL_CAP_LEFT, cap)
            for fragment, _style in _entry_inner(entry):
                self.append(fragment, pill)
            self.append(_PILL_CAP_RIGHT, cap)
        elif compact:
            meta = entry.meta
            self.append(meta.number, self._style(_NUMBER_STYLE))
            self.append(
                _status_glyph(meta.status_bucket),
                self._style(_status_style(meta.status_bucket)),
            )
        else:
            for fragment, style in _entry_inner(entry):
                self.append(fragment, self._style(style))
        self._ranges[entry.block_id] = (start, self._column)

    def append_overflow(
        self, *, older: bool, count: int, compact: bool, dotted: bool
    ) -> None:
        """Append one windowing overflow indicator (no click range)."""
        if compact:
            label = f"‹{count}" if older else f"{count}›"
        elif older:
            label = f"‹{count} older"
        else:
            label = f"{count} newer›"
        if dotted:
            self.append(_ARRIVAL_GLYPH, _ARRIVAL_STYLE)
        self.append(label, self._style(_MUTED_STYLE))

    def append_key_hint(self, prev: str, next_key: str) -> None:
        """Append the ``[ older · newer ]`` key hint."""
        key_style = f"bold {self._accent}"
        if not self._focused:
            key_style = _dim(key_style)
        self.append(prev, key_style)
        self.append(" older · newer ", self._style(_MUTED_STYLE))
        self.append(next_key, key_style)

    def width(self) -> int:
        """Return the assembled cell width."""
        return self._column

    def build(self) -> tuple[Text, dict[str, tuple[int, int]]]:
        """Return the assembled text and click ranges."""
        return self._text, dict(self._ranges)


def _resolve_active_index(
    entries: Sequence[BlockRailEntry], active_id: str | None
) -> int:
    for index, entry in enumerate(entries):
        if entry.block_id == active_id:
            return index
    return len(entries) - 1


def _window_bounds(active: int, neighbor_count: int, total: int) -> tuple[int, int]:
    """Return the ``[start, end)`` window of visible entries."""
    return max(0, active - neighbor_count), min(total, active + neighbor_count + 1)


def _hidden_arrived(
    entries: Sequence[BlockRailEntry],
    arrived_ids: Sequence[str] | set[str],
    start: int,
    end: int,
    *,
    side: str,
) -> bool:
    """Return whether a windowed-out side hides any arrived entries."""
    arrived = set(arrived_ids)
    if side == "older":
        hidden = [entry.block_id for entry in entries[:start]]
    else:
        hidden = [entry.block_id for entry in entries[end:]]
    return any(block_id in arrived for block_id in hidden)


def _windowed_entries(
    builder: _RailBuilder,
    ordered: tuple[BlockRailEntry, ...],
    active: int,
    arrived: set[str],
    neighbors: int,
    *,
    compact: bool,
) -> None:
    """Append one windowed tier: overflow, entries, overflow."""
    start, end = _window_bounds(active, neighbors, len(ordered))
    needs_separator = False
    if start > 0:
        builder.append_overflow(
            older=True,
            count=start,
            compact=compact,
            dotted=_hidden_arrived(ordered, arrived, start, end, side="older"),
        )
        needs_separator = True
    for index in range(start, end):
        if needs_separator:
            builder.append_separator()
        needs_separator = True
        builder.append_entry(
            ordered[index],
            active=index == active,
            arrived=ordered[index].block_id in arrived,
            compact=compact and index != active,
        )
    if end < len(ordered):
        builder.append_separator()
        builder.append_overflow(
            older=False,
            count=len(ordered) - end,
            compact=compact,
            dotted=_hidden_arrived(ordered, arrived, start, end, side="newer"),
        )


def render_block_rail(
    entries: Sequence[BlockRailEntry],
    *,
    active_id: str | None,
    arrived_ids: Sequence[str] | set[str] = (),
    width: int,
    accent: str,
    focused: bool = True,
    key_hint: tuple[str, str] | None = None,
) -> tuple[Text, dict[str, tuple[int, int]], BlockRailTier | None]:
    """Render the rail at the widest tier that fits ``width`` cells.

    Returns ``(text, ranges, tier)`` where ``ranges`` maps visible block
    ids to ``(start, end)`` cell offsets for click-to-select and ``tier``
    is None only when there is nothing to render. ``cell_len(text.plain)``
    never exceeds ``max(0, width)``.
    """
    width = max(0, int(width))
    ordered = tuple(entries)
    if not ordered or width <= 0:
        return Text(""), {}, None
    active = _resolve_active_index(ordered, active_id)
    arrived = set(arrived_ids)

    def attempt(build: Any) -> tuple[Text, dict[str, tuple[int, int]]] | None:
        builder: _RailBuilder = _RailBuilder(accent=accent, focused=focused)
        build(builder)
        text, ranges = builder.build()
        if cell_len(text.plain) <= width:
            return text, ranges
        return None

    def full_entries(builder: _RailBuilder, *, compact: bool = False) -> None:
        for index, entry in enumerate(ordered):
            if index > 0:
                builder.append_separator()
            builder.append_entry(
                entry,
                active=index == active,
                arrived=entry.block_id in arrived,
                compact=compact and index != active,
            )

    # Tier 1: full entries plus the right-aligned key hint.
    if key_hint is not None:

        def with_hint(builder: _RailBuilder) -> None:
            full_entries(builder)
            hint = Text()
            hint.append(key_hint[0], style="")
            hint.append(" older · newer ", style="")
            hint.append(key_hint[1], style="")
            gap = width - builder.width() - cell_len(hint.plain)
            if gap < 2:
                # Force a miss so the tier ladder falls through.
                builder.append(" " * (width + 1))
                return
            builder.append(" " * gap)
            builder.append_key_hint(key_hint[0], key_hint[1])

        hit = attempt(with_hint)
        if hit is not None:
            return hit[0], hit[1], "full-hint"

    # Tier 2: full entries.
    hit = attempt(full_entries)
    if hit is not None:
        return hit[0], hit[1], "full"

    # Tier 3: windowed full entries with overflow counts.
    for neighbors in _WINDOW_NEIGHBORS:

        def windowed(builder: _RailBuilder, _k: int = neighbors) -> None:
            _windowed_entries(builder, ordered, active, arrived, _k, compact=False)

        hit = attempt(windowed)
        if hit is not None:
            return hit[0], hit[1], "windowed"

    # Tier 4: windowed with compact neighbors and bare counts.
    for neighbors in _WINDOW_NEIGHBORS:

        def compacted(builder: _RailBuilder, _k: int = neighbors) -> None:
            _windowed_entries(builder, ordered, active, arrived, _k, compact=True)

        hit = attempt(compacted)
        if hit is not None:
            return hit[0], hit[1], "compact"

    # Tier 5: micro — the active pill plus bare counts, ellipsizing the
    # active label as a last resort.
    active_entry = ordered[active]
    label_budget = cell_len(active_entry.meta.label)
    while True:

        def micro(builder: _RailBuilder, _budget: int = label_budget) -> None:
            label = _truncate_middle(active_entry.meta.label, _budget)
            shown = BlockRailEntry(
                active_entry.block_id,
                BlockMeta(
                    number=active_entry.meta.number,
                    label=label,
                    glyph=active_entry.meta.glyph,
                    accent=active_entry.meta.accent,
                    status_bucket=active_entry.meta.status_bucket,
                    kind=active_entry.meta.kind,
                ),
            )
            if active > 0:
                builder.append_overflow(
                    older=True,
                    count=active,
                    compact=True,
                    dotted=_hidden_arrived(
                        ordered, arrived, active, active + 1, side="older"
                    ),
                )
                builder.append_separator()
            builder.append_entry(shown, active=True, arrived=False)
            if active + 1 < len(ordered):
                builder.append_separator()
                builder.append_overflow(
                    older=False,
                    count=len(ordered) - active - 1,
                    compact=True,
                    dotted=_hidden_arrived(
                        ordered, arrived, active, active + 1, side="newer"
                    ),
                )

        hit = attempt(micro)
        if hit is not None:
            return hit[0], hit[1], "micro"
        if label_budget <= 1:
            break
        label_budget -= 1

    # Ultimate clamp: never overflow, even at absurd widths.
    builder = _RailBuilder(accent=accent, focused=focused)
    builder.append_entry(active_entry, active=True, arrived=False)
    text, ranges = builder.build()
    plain = text.plain
    while plain and cell_len(plain) > width:
        plain = plain[:-1]
    fallback = Text(plain or "…")
    if cell_len(fallback.plain) > width:
        fallback = Text("")
    return fallback, {}, "micro"


def block_rail_text(
    entries: Sequence[BlockRailEntry],
    *,
    active_id: str | None,
    arrived_ids: Sequence[str] | set[str] = (),
    width: int,
    accent: str,
    focused: bool = True,
    key_hint: tuple[str, str] | None = None,
) -> Text:
    """Render the one-row block rail, never wider than ``width`` cells.

    The widest fitting tier wins: full entries plus key hint, full
    entries, windowed neighbors with overflow counts, compact neighbors
    with bare counts, then the micro pill with an ellipsized label.
    """
    text, _, _ = render_block_rail(
        entries,
        active_id=active_id,
        arrived_ids=arrived_ids,
        width=width,
        accent=accent,
        focused=focused,
        key_hint=key_hint,
    )
    return text


class BlockRail(Static):
    """Pre-composed one-row block rail docked above the Main scroll."""

    class BlockRailSelected(Message):
        """A click on a rail entry asked to select a block."""

        def __init__(self, block_id: str) -> None:
            """Initialize the selection request."""
            super().__init__()
            self.block_id = block_id

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the rail with empty content."""
        super().__init__(Text(""), **kwargs)
        self.can_focus = False
        self._entries: tuple[BlockRailEntry, ...] = ()
        self._active_id: str | None = None
        self._arrived_ids: tuple[str, ...] = ()
        self._accent = ""
        self._panel_focused = True
        self._key_hint: tuple[str, str] | None = None
        self._width = 0
        self._ranges: dict[str, tuple[int, int]] = {}

    def set_rail(
        self,
        entries: Sequence[BlockRailEntry],
        *,
        active_id: str | None,
        arrived_ids: Sequence[str] | set[str] = (),
        accent: str,
        focused: bool = True,
        key_hint: tuple[str, str] | None = None,
        width: int,
    ) -> None:
        """Store the rail state and render it for ``width`` cells."""
        self._entries = tuple(entries)
        self._active_id = active_id
        self._arrived_ids = tuple(arrived_ids)
        self._accent = accent
        self._panel_focused = bool(focused)
        self._key_hint = key_hint
        self._width = max(0, int(width))
        self._render_stored()

    def clear(self) -> None:
        """Empty the rail content and click ranges."""
        self._entries = ()
        self._active_id = None
        self._arrived_ids = ()
        self._ranges = {}
        try:
            self.update(Text(""))
        except Exception:
            pass

    def on_mount(self) -> None:
        """Recolor the rail live when the app theme changes."""
        try:
            self.app.theme_changed_signal.subscribe(  # type: ignore[attr-defined]
                self, self._on_app_theme_changed
            )
        except Exception:
            pass

    def _on_app_theme_changed(self, _theme: object) -> None:
        try:
            self._render_stored()
        except Exception:
            pass

    def on_resize(self, event: Resize) -> None:
        """Re-render the stored rail state for the new width."""
        try:
            width = max(0, int(event.size.width) - 2 * RAIL_HORIZONTAL_PADDING)
        except Exception:
            return
        if width <= 0:
            return
        self._width = width
        try:
            self._render_stored()
        except Exception:
            pass

    def _render_stored(self) -> None:
        """Render the stored entries for the stored width."""
        if not self._entries or self._width <= 0:
            return
        try:
            text, ranges, _tier = render_block_rail(
                self._entries,
                active_id=self._active_id,
                arrived_ids=self._arrived_ids,
                width=self._width,
                accent=self._accent,
                focused=self._panel_focused,
                key_hint=self._key_hint,
            )
        except Exception:
            return
        self._ranges = ranges
        try:
            self.update(text)
        except Exception:
            pass

    def block_id_at(self, x: int) -> str | None:
        """Return the block id under widget cell offset ``x``, if any."""
        adjusted = x - RAIL_HORIZONTAL_PADDING
        for block_id, (start, end) in self._ranges.items():
            if start <= adjusted < end:
                return block_id
        return None

    def on_click(self, event: Click) -> None:
        """Select the clicked block without stealing widget focus."""
        try:
            block_id = self.block_id_at(int(event.x))
        except Exception:
            return
        if block_id is None:
            return
        try:
            self.post_message(self.BlockRailSelected(block_id))
        except Exception:
            return
        try:
            event.stop()
        except Exception:
            pass


__all__ = [
    "RAIL_HORIZONTAL_PADDING",
    "BlockRail",
    "BlockRailEntry",
    "BlockRailTier",
    "block_rail_text",
    "render_block_rail",
]

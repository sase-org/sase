"""Pure card-block cursor and block-mode decision helpers.

A session Reply card is split into one card block per concrete sase shell.
Each deck panel keeps one :class:`BlockCursor` per card for the current
subject; the cursor names the active block, whether the panel follows the
newest block, and which block ids the reader has already seen (for arrival
dots). Everything here is pure: no Textual imports, no widget state.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .model import RenderMode
from .render_mode import decide_render_mode


@dataclass(frozen=True, slots=True)
class BlockCursor:
    """One panel's block state for one card."""

    block_id: str
    following: bool
    known_ids: frozenset[str]


def land_cursor(ids: Sequence[str]) -> BlockCursor | None:
    """Return a cursor on the newest block, following, with all ids known."""
    ordered = list(ids)
    if not ordered:
        return None
    return BlockCursor(
        block_id=ordered[-1],
        following=True,
        known_ids=frozenset(ordered),
    )


def reconcile_cursor(
    ids: Sequence[str],
    cursor: BlockCursor | None,
    *,
    new_subject: bool,
) -> BlockCursor | None:
    """Reconcile ``cursor`` with the current block ids.

    Lands on the newest block when the subject changed, there is no
    cursor yet, the cursor follows the newest block, or its block id
    vanished. Otherwise the cursor is returned unchanged, so a reader
    parked on history is never yanked out of it.
    """
    ordered = list(ids)
    if not ordered:
        return None
    if (
        new_subject
        or cursor is None
        or cursor.following
        or cursor.block_id not in set(ordered)
    ):
        return land_cursor(ordered)
    return cursor


def step_cursor(
    ids: Sequence[str],
    cursor: BlockCursor | None,
    direction: int,
) -> BlockCursor | None:
    """Step the cursor one block in ``direction`` (wraps).

    The step target becomes the active block, ``following`` tracks
    whether it is the newest, and every id becomes known (navigation
    clears arrival dots).
    """
    ordered = list(ids)
    if not ordered:
        return cursor
    active = cursor.block_id if cursor is not None else None
    target = cycle_block_id(ordered, active, direction)
    if target is None:
        return cursor
    return BlockCursor(
        block_id=target,
        following=(target == ordered[-1]),
        known_ids=frozenset(ordered),
    )


def select_cursor(ids: Sequence[str], block_id: str | None) -> BlockCursor | None:
    """Select ``block_id`` directly (rail clicks, scroll derivation).

    Returns ``None`` when there are no blocks or ``block_id`` is not one
    of them, so an unknown selection (including a ``None`` spread
    derivation from above the first header) selects nothing.
    """
    ordered = list(ids)
    if not ordered:
        return None
    if block_id is None or block_id not in set(ordered):
        return None
    return BlockCursor(
        block_id=block_id,
        following=(block_id == ordered[-1]),
        known_ids=frozenset(ordered),
    )


def arrived_ids(ids: Sequence[str], cursor: BlockCursor | None) -> tuple[str, ...]:
    """Return ids the reader has not seen yet, in chronological order.

    Empty while following: a follower lands on every new block, so
    nothing is ever unannounced.
    """
    ordered = list(ids)
    if cursor is None:
        return tuple(ordered)
    if cursor.following:
        return ()
    known = cursor.known_ids
    return tuple(block_id for block_id in ordered if block_id not in known)


def cycle_block_id(
    ids: Sequence[str], active: str | None, direction: int
) -> str | None:
    """Return the next block id after ``active`` for ``direction`` (wraps).

    An unknown (or ``None``) anchor steps from the far end: ``direction >
    0`` returns the oldest block and ``direction < 0`` the newest, so a
    ``[`` keypress above the first header reaches the newest block and
    ``]`` reaches the oldest.
    """
    ordered = list(ids)
    if not ordered:
        return None
    if active is not None and active in set(ordered):
        index = ordered.index(active)
        return ordered[(index + direction) % len(ordered)]
    if direction < 0:
        return ordered[-1]
    return ordered[0]


def derive_spread_block(
    anchor_rows: Mapping[str, int] | Sequence[tuple[str, int]],
    *,
    scroll_y: float,
    at_real_bottom: bool,
) -> str | None:
    """Derive the active block from the scroll position.

    At the real bottom the newest block is active; otherwise the last
    block whose header row is at or above ``scroll_y``; otherwise (above
    the first header) there is none.
    """
    if isinstance(anchor_rows, Mapping):
        pairs = list(anchor_rows.items())
    else:
        pairs = list(anchor_rows)
    if not pairs:
        return None
    if at_real_bottom:
        return pairs[-1][0]
    current: str | None = None
    for block_id, row in pairs:
        if row <= scroll_y:
            current = block_id
        else:
            break
    return current


def decide_block_mode(
    *,
    block_count: int,
    card_rows: int | None,
    viewport_rows: int,
    block_spread_max_screens: float,
    previous: RenderMode | None,
    same_card: bool,
) -> RenderMode:
    """Decide block-spread versus block-paged for a card shown alone.

    A thin call to :func:`decide_render_mode` over blocks instead of
    cards: fewer than two blocks always spreads, ``0`` screens always
    pages, an unmeasured card keeps ``previous`` for the same card, and
    the deck-level hysteresis band is shared.
    """
    if block_count < 2:
        return RenderMode.SPREAD
    return decide_render_mode(
        card_count=block_count,
        has_solo_card=False,
        total_rows=card_rows,
        viewport_rows=viewport_rows,
        spread_max_screens=block_spread_max_screens,
        previous=previous,
        same_subject=same_card,
    )


__all__ = [
    "BlockCursor",
    "arrived_ids",
    "cycle_block_id",
    "decide_block_mode",
    "derive_spread_block",
    "land_cursor",
    "reconcile_cursor",
    "select_cursor",
    "step_cursor",
]

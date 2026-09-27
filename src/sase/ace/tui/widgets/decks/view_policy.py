"""Pure deck-view policy resolution, cycling, and equivalence.

No Textual imports: this module implements design D2/D3 of the deck-views
plan from content measurements alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .model import DeckId, DeckView, RenderMode


class BlockState(StrEnum):
    """Block paging state for the active card."""

    NONE = "none"
    INLINE = "inline"
    PAGED = "paged"


@dataclass(frozen=True)
class ViewContent:
    """Content facts that determine view equivalence."""

    deck: DeckId
    card_count: int
    active_block_count: int
    spread_blocked: bool = False


class ViewStatus(StrEnum):
    """Badge status segment for a resolved view."""

    OK = "ok"
    PENDING = "pending"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class ResolvedView:
    """Effective view plus policy for badge rendering."""

    deck: DeckId
    policy: DeckView
    shown: DeckView
    status: ViewStatus


# Shallowest first: spread < page cards < page blocks.
_LAYOUT_DEPTH: tuple[DeckView, ...] = (
    DeckView.SPREAD,
    DeckView.PAGE_CARDS,
    DeckView.PAGE_BLOCKS,
)


def layout_signature(
    layout: DeckView, content: ViewContent
) -> tuple[RenderMode, BlockState]:
    """Return the ``(deck_mode, block_state)`` signature for ``layout``."""
    if layout is DeckView.AUTO:
        raise ValueError("AUTO has no layout signature")
    if content.card_count <= 1:
        deck_mode = RenderMode.SPREAD
    elif layout is DeckView.SPREAD and not content.spread_blocked:
        deck_mode = RenderMode.SPREAD
    else:
        deck_mode = RenderMode.PAGED
    if content.active_block_count < 2:
        block_state = BlockState.NONE
    elif deck_mode is RenderMode.SPREAD:
        block_state = BlockState.INLINE
    elif layout is DeckView.PAGE_BLOCKS:
        block_state = BlockState.PAGED
    else:
        block_state = BlockState.INLINE
    return (deck_mode, block_state)


def forced_deck_mode(policy: DeckView, card_count: int) -> RenderMode | None:
    """Return the forced deck mode, or ``None`` to decide automatically."""
    if card_count <= 1:
        return RenderMode.SPREAD
    if policy is DeckView.AUTO:
        return None
    if policy is DeckView.SPREAD:
        return RenderMode.SPREAD
    return RenderMode.PAGED


def forced_block_mode(policy: DeckView, block_count: int) -> RenderMode | None:
    """Return the forced block mode, or ``None`` to decide automatically."""
    if policy is DeckView.AUTO:
        return None
    if block_count < 2:
        return None
    if policy is DeckView.PAGE_BLOCKS:
        return RenderMode.PAGED
    return RenderMode.SPREAD


def distinct_layouts(content: ViewContent) -> tuple[DeckView, ...]:
    """Return distinct layouts in depth order (shallowest first).

    Each signature class is represented by its shallowest member. Files
    never offers ``PAGE_BLOCKS``; Tools and FINAL offer nothing.
    """
    if content.deck is DeckId.TOOLS or content.deck is DeckId.FINAL:
        return ()
    if content.deck is DeckId.FILES:
        candidates: tuple[DeckView, ...] = (DeckView.SPREAD, DeckView.PAGE_CARDS)
    else:
        candidates = _LAYOUT_DEPTH
    seen: set[tuple[RenderMode, BlockState]] = set()
    distinct: list[DeckView] = []
    for layout in candidates:
        signature = layout_signature(layout, content)
        if signature not in seen:
            seen.add(signature)
            distinct.append(layout)
    return tuple(distinct)


def next_view(current_layout: DeckView, content: ViewContent) -> DeckView | None:
    """Return the next fixed view widening from ``current_layout``.

    Walks the distinct layouts in widening order
    (``page blocks -> page cards -> spread -> page blocks``), starting from
    the distinct class that contains ``current_layout``. Returns ``None``
    when fewer than two distinct layouts exist.
    """
    distinct = distinct_layouts(content)
    if len(distinct) < 2:
        return None
    try:
        signature = layout_signature(current_layout, content)
    except ValueError:
        return None
    start: int | None = None
    for index, representative in enumerate(distinct):
        if layout_signature(representative, content) == signature:
            start = index
            break
    if start is None:
        return None
    return distinct[(start - 1) % len(distinct)]


def resolve_view(
    deck: DeckId,
    policy: DeckView,
    effective_layout: DeckView,
    content: ViewContent,
    *,
    pending: bool = False,
    blocked: bool = False,
) -> ResolvedView:
    """Resolve the badge view per the D5 label rule.

    Pending (Files probe in flight) and blocked (Files media) show the
    effective layout with a status segment. Otherwise a fixed policy whose
    requested layout shares the effective signature (a vacuous request)
    shows the requested name so the badge stays stable across cards.
    """
    if blocked:
        return ResolvedView(
            deck=deck,
            policy=policy,
            shown=effective_layout,
            status=ViewStatus.BLOCKED,
        )
    if pending:
        return ResolvedView(
            deck=deck,
            policy=policy,
            shown=effective_layout,
            status=ViewStatus.PENDING,
        )
    if policy is DeckView.AUTO:
        return ResolvedView(
            deck=deck,
            policy=policy,
            shown=effective_layout,
            status=ViewStatus.OK,
        )
    try:
        requested_signature = layout_signature(policy, content)
        effective_signature = layout_signature(effective_layout, content)
    except ValueError:
        return ResolvedView(
            deck=deck,
            policy=policy,
            shown=effective_layout,
            status=ViewStatus.OK,
        )
    if requested_signature == effective_signature:
        shown: DeckView = policy
    else:
        shown = effective_layout
    return ResolvedView(deck=deck, policy=policy, shown=shown, status=ViewStatus.OK)


__all__ = [
    "BlockState",
    "ResolvedView",
    "ViewContent",
    "ViewStatus",
    "distinct_layouts",
    "forced_block_mode",
    "forced_deck_mode",
    "layout_signature",
    "next_view",
    "resolve_view",
]

"""Deferred Main view bodies: badge-first P transitions (D10).

The synchronous prefix of a user-initiated Main view change flips the badge
(``_render_mode`` + ``refresh_chrome``) and returns. The reply strips for the
destination body are built off the UI thread with ``asyncio.to_thread`` on a
private ``rich.console.Console``. The UI thread then applies the prebuilt
strips (generation-guarded) so the Rich walk never runs on the event loop
and the stall watchdog stays quiet.

Prebuilt bodies are keyed by ``(digest, width)`` for full paints only.
Pixels, anchor rows, and scroll positions match the synchronous path because
the same renderable, width, and full-strip anchor walk are used; Textual's
post-render link walk still runs on the UI thread over the returned strips.
"""

from __future__ import annotations

from collections import OrderedDict
from itertools import islice
from typing import Any

from rich.console import Console, Group
from rich.segment import Segment
from textual.strip import Strip

_PREBUILT_MAX_ENTRIES = 8
_prebuilt_bodies: OrderedDict[
    tuple[str, int], tuple[tuple[Strip, ...], int, tuple[Any, ...]]
] = OrderedDict()


def store_prebuilt(
    digest: str | None,
    width: int,
    strips: tuple[Strip, ...],
    height: int,
    anchors: tuple[Any, ...],
) -> None:
    """Store a full-document prebuilt body, capped at 8 entries."""
    if digest is None or width <= 0:
        return
    key = (digest, int(width))
    _prebuilt_bodies[key] = (strips, int(height), anchors)
    _prebuilt_bodies.move_to_end(key)
    if len(_prebuilt_bodies) > _PREBUILT_MAX_ENTRIES:
        _prebuilt_bodies.popitem(last=False)


def get_prebuilt(
    digest: str | None, width: int
) -> tuple[tuple[Strip, ...], int, tuple[Any, ...]] | None:
    """Return the prebuilt body for ``(digest, width)``, if present."""
    if digest is None or width <= 0:
        return None
    key = (digest, int(width))
    entry = _prebuilt_bodies.get(key)
    if entry is None:
        return None
    _prebuilt_bodies.move_to_end(key)
    return entry


def build_prebuilt_offthread(
    renderable: Any, width: int
) -> tuple[tuple[Strip, ...], int, tuple[Any, ...]]:
    """Render ``renderable`` to full strips/height/anchors off the loop.

    Uses a private console and never touches widgets, the app console, or
    shared caches. Callers store the result with :func:`store_prebuilt` on
    the UI thread.
    """
    from sase.ace.tui.widgets.prompt_panel._section_navigation import (
        _segment_section_identity,
    )

    render_width = max(1, int(width))
    console = Console(width=render_width, highlight=False)
    segments = console.render(renderable, console.options.update_width(render_width))
    strips = [
        Strip(line)
        for line in Segment.split_and_crop_lines(
            segments, render_width, include_new_lines=False, pad=False
        )
    ]
    anchors: list[Any] = []
    seen: set[str] = set()
    for row, strip in enumerate(strips):
        for segment in strip:
            resolved = _segment_section_identity(segment)
            if resolved is None:
                continue
            identity, role = resolved
            if identity not in seen:
                seen.add(identity)
                # Anchor type is PromptPanelSectionAnchor; keep Any here to
                # avoid importing widget types off-thread.
                from sase.ace.tui.widgets.prompt_panel._section_navigation import (
                    PromptPanelSectionAnchor,
                )

                anchors.append(PromptPanelSectionAnchor(identity, row, role))
    return (tuple(strips), len(strips), tuple(anchors))


def build_destination_renderable(
    document: Any,
    *,
    spread: bool,
    target_card_id: str | None,
    anchor_block_id: str | None,
    want_paged_blocks: bool,
    spread_accent: str = "",
) -> tuple[Any, str | None]:
    """Build the destination Group and digest without touching widgets."""
    digest = getattr(document, "digest", None)
    if spread:
        from .separators import card_separator_for
        from .model import DeckId

        parts: list[Any] = []
        try:
            cards = list(document.cards)
        except Exception:
            cards = []
        for index, card in enumerate(cards):
            if index > 0:
                try:
                    parts.append(
                        card_separator_for(DeckId.MAIN, card, accent=spread_accent)
                    )
                except Exception:
                    pass
            try:
                parts.extend(list(card.renderables))
            except Exception:
                pass
        spread_digest = None if digest is None else f"{digest}:spread"
        return (Group(*parts), spread_digest)
    card = None
    if target_card_id is not None:
        try:
            card = document.card(target_card_id)
        except Exception:
            card = None
    if card is None:
        return (Group(), None if digest is None else f"{digest}:{target_card_id}")
    if want_paged_blocks and anchor_block_id is not None:
        try:
            page = card.block_page(anchor_block_id)
        except Exception:
            page = None
        if page is not None:
            page_digest = (
                None if digest is None else f"{digest}:{card.card_id}:{anchor_block_id}"
            )
            return (Group(*page), page_digest)
    try:
        renderables = list(card.renderables)
    except Exception:
        renderables = []
    try:
        block_ids = tuple(getattr(card, "block_ids", ()) or ())
    except Exception:
        block_ids = ()
    if not want_paged_blocks and len(block_ids) >= 2 and digest is not None:
        card_digest: str | None = f"{digest}:{card.card_id}:spread"
    else:
        card_digest = None if digest is None else f"{digest}:{card.card_id}"
    return (Group(*renderables), card_digest)


__all__ = [
    "build_destination_renderable",
    "build_prebuilt_offthread",
    "get_prebuilt",
    "store_prebuilt",
]

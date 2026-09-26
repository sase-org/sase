"""Ordered card parts for Agents metadata-panel documents.

Every Agents metadata-panel builder emits its document as ordered card
parts: ``context``, ``reply`` (titled "Reply" or "Output") or ``summary``.
Tree walkers understand the card wrapper, while
:func:`flatten_card_document` projects the card structure back to the
legacy shape for display.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import cast

from rich.console import Console, ConsoleOptions, Group, RenderableType
from rich.measure import Measurement
from rich.segment import Segment
from rich.text import Text

from .card_block import (
    CardBlock,
    is_block_spread_only,
    log_invalid_card_structure,
    partition_card_children,
)

CONTEXT_CARD_ID = "context"
REPLY_CARD_ID = "reply"
SUMMARY_CARD_ID = "summary"

CONTEXT_CARD_TITLE = "Context"
REPLY_CARD_TITLE = "Reply"
OUTPUT_CARD_TITLE = "Output"
SUMMARY_CARD_TITLE = "Summary"


class CardPart:
    """One named card inside a metadata-panel document."""

    __slots__ = ("blocks", "card_id", "preamble", "renderables", "title")

    __sase_card_part__ = True

    def __init__(self, card_id: str, title: str, *renderables: RenderableType) -> None:
        self.card_id = card_id
        self.title = title
        self.renderables: tuple[RenderableType, ...] = tuple(renderables)
        preamble, blocks, error = partition_card_children(self.renderables)
        if error is not None:
            log_invalid_card_structure(card_id, error)
            preamble, blocks = tuple(self.renderables), ()
        self.preamble: tuple[RenderableType, ...] = cast(
            "tuple[RenderableType, ...]", preamble
        )
        self.blocks: tuple[CardBlock, ...] = blocks

    @property
    def block_ids(self) -> tuple[str, ...]:
        """Return the ordered block ids of this card."""
        return tuple(block.block_id for block in self.blocks)

    @property
    def newest_block_id(self) -> str | None:
        """Return the last (newest) block id, or None when block-less."""
        if not self.blocks:
            return None
        return self.blocks[-1].block_id

    @property
    def has_block_navigation(self) -> bool:
        """Return whether this card has navigable (2+) blocks."""
        return len(self.blocks) >= 2

    def block(self, block_id: str) -> CardBlock | None:
        """Return the block with ``block_id``, or None when absent."""
        for block in self.blocks:
            if block.block_id == block_id:
                return block
        return None

    def block_page(self, block_id: str) -> tuple[RenderableType, ...]:
        """Return the renderables for one block-paged page.

        The page is the card preamble minus ``BlockSpreadOnly`` chrome —
        shown only above the newest block's page — followed by the block's
        own renderables.
        """
        target = self.block(block_id)
        if target is None:
            return ()
        page: list[RenderableType] = []
        if block_id == self.newest_block_id:
            page.extend(
                child for child in self.preamble if not is_block_spread_only(child)
            )
        page.extend(target.renderables)
        return tuple(page)

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> object:
        return Group(*self.renderables).__rich_console__(console, options)

    def __rich_measure__(
        self, console: Console, options: ConsoleOptions
    ) -> Measurement:
        return Group(*self.renderables).__rich_measure__(console, options)

    def __repr__(self) -> str:
        return (
            f"CardPart(card_id={self.card_id!r}, title={self.title!r}, "
            f"renderables={self.renderables!r})"
        )


def _make_card(card_id: str, title: str, renderables: tuple[object, ...]) -> CardPart:
    return CardPart(card_id, title, *renderables)  # type: ignore[arg-type]


def context_card(*renderables: RenderableType) -> CardPart:
    """Build the Context card holding header and prompt sections."""
    return _make_card(CONTEXT_CARD_ID, CONTEXT_CARD_TITLE, renderables)


def reply_card(*renderables: RenderableType) -> CardPart:
    """Build the Reply card holding reply sections."""
    return _make_card(REPLY_CARD_ID, REPLY_CARD_TITLE, renderables)


def output_card(*renderables: RenderableType) -> CardPart:
    """Build the Output card holding step output sections."""
    return _make_card(REPLY_CARD_ID, OUTPUT_CARD_TITLE, renderables)


def summary_card(*renderables: RenderableType) -> CardPart:
    """Build the Summary card holding a whole clan or tribe document."""
    return _make_card(SUMMARY_CARD_ID, SUMMARY_CARD_TITLE, renderables)


def card_document(*parts: CardPart | None) -> Group:
    """Assemble card parts into a document, dropping empty parts."""
    kept: list[CardPart] = []
    for part in parts:
        if part is None:
            continue
        if not part.renderables:
            continue
        kept.append(part)
    return Group(*kept)  # type: ignore[arg-type]


def _is_card_part(node: object) -> bool:
    return bool(getattr(node, "__sase_card_part__", False))


def split_card_parts(content: object) -> tuple[CardPart, ...]:
    """Split a Main document into its card parts."""
    if content is None:
        return ()
    if isinstance(content, str) and content == "":
        return ()
    if _is_card_part(content):
        part = content
        assert isinstance(part, CardPart)
        if not part.renderables:
            return ()
        return (part,)
    if isinstance(content, Group):
        children = list(content.renderables)
        if not children:
            return ()
        cards: list[CardPart] = []
        loose: list[object] = []
        for child in children:
            if _is_card_part(child):
                assert isinstance(child, CardPart)
                if child.renderables:
                    cards.append(child)
            else:
                loose.append(child)
        if not cards and not loose:
            return ()
        if not cards:
            kept = tuple(r for r in loose if not _is_empty_renderable(r))
            if not kept:
                return ()
            return (context_card(*kept),)  # type: ignore[arg-type]
        if not loose:
            return tuple(cards)
        # Merge loose renderables into the context card.
        context_index = next(
            (i for i, c in enumerate(cards) if c.card_id == CONTEXT_CARD_ID), None
        )
        if context_index is not None:
            existing = cards[context_index]
            # Loose renderables join the preamble so trailing blocks stay
            # contiguous; appending them after blocks would invalidate the
            # card's block structure.
            merged = CardPart(
                existing.card_id,
                existing.title,
                *(*existing.preamble, *loose, *existing.blocks),  # type: ignore[arg-type]
            )
            cards = [*cards[:context_index], merged, *cards[context_index + 1 :]]
        else:
            cards = [context_card(*loose), *cards]  # type: ignore[arg-type]
        return tuple(c for c in cards if c.renderables)
    return (context_card(content),)  # type: ignore[arg-type]


def _is_empty_renderable(node: object) -> bool:
    if node is None:
        return True
    if isinstance(node, str) and node == "":
        return True
    return False


def _flatten_container_children(children: Iterable[object]) -> list[object]:
    """Recursively unwrap card containers back to the legacy flat shape."""
    from .card_block import is_card_container

    flattened: list[object] = []
    for child in children:
        if is_card_container(child):
            flattened.extend(
                _flatten_container_children(getattr(child, "renderables", ()))
            )
        else:
            flattened.append(child)
    return flattened


def flatten_card_document(content: object) -> object:
    """Project a card-structured document back to its legacy shape."""
    from .card_block import is_card_container

    if is_card_container(content):
        children = _flatten_container_children(getattr(content, "renderables", ()))
        if len(children) == 1:
            return children[0]
        return Group(*children)  # type: ignore[arg-type]
    if isinstance(content, Group):
        has_card = any(is_card_container(child) for child in content.renderables)
        if not has_card:
            return content
        flattened: list[object] = []
        for child in content.renderables:
            if is_card_container(child):
                flattened.extend(
                    _flatten_container_children(getattr(child, "renderables", ()))
                )
            else:
                flattened.append(child)
        if len(flattened) == 1:
            return flattened[0]
        return Group(*flattened)  # type: ignore[arg-type]
    return content


__all__ = [
    "CONTEXT_CARD_ID",
    "CONTEXT_CARD_TITLE",
    "OUTPUT_CARD_TITLE",
    "REPLY_CARD_ID",
    "REPLY_CARD_TITLE",
    "SUMMARY_CARD_ID",
    "SUMMARY_CARD_TITLE",
    "CardPart",
    "card_document",
    "context_card",
    "flatten_card_document",
    "output_card",
    "reply_card",
    "split_card_parts",
    "summary_card",
]

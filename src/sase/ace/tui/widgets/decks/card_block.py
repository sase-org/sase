"""Card blocks: an optional third level inside Agents deck cards.

A card holds zero blocks or one or more trailing, contiguous, non-nesting
blocks. The session Reply card will get one block per concrete sase shell;
until a builder emits blocks there is no visual change because both wrappers
are transparent Rich containers.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from rich.console import Console, ConsoleOptions, Group, RenderableType
from rich.measure import Measurement

if TYPE_CHECKING:
    from ...models.agent import AgentType

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BlockMeta:
    """Rail and display facts for one card block."""

    number: str
    label: str
    glyph: str
    accent: str
    status_bucket: str
    kind: str


class CardBlock:
    """One titled, stably identified unit inside a card."""

    __slots__ = ("block_id", "meta", "renderables", "title")

    __sase_card_block__ = True

    def __init__(
        self,
        block_id: str,
        title: str,
        *renderables: RenderableType,
        meta: BlockMeta,
    ) -> None:
        self.block_id = block_id
        self.title = title
        self.renderables: tuple[RenderableType, ...] = tuple(renderables)
        self.meta = meta

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> object:
        return Group(*self.renderables).__rich_console__(console, options)

    def __rich_measure__(
        self, console: Console, options: ConsoleOptions
    ) -> Measurement:
        return Group(*self.renderables).__rich_measure__(console, options)

    def __repr__(self) -> str:
        return (
            f"CardBlock(block_id={self.block_id!r}, title={self.title!r}, "
            f"renderables=<{len(self.renderables)} items>, meta={self.meta!r})"
        )


class BlockSpreadOnly:
    """Card-level chrome that block-paged pages drop."""

    __slots__ = ("renderables",)

    __sase_block_spread_only__ = True

    def __init__(self, *renderables: RenderableType) -> None:
        self.renderables: tuple[RenderableType, ...] = tuple(renderables)

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> object:
        return Group(*self.renderables).__rich_console__(console, options)

    def __rich_measure__(
        self, console: Console, options: ConsoleOptions
    ) -> Measurement:
        return Group(*self.renderables).__rich_measure__(console, options)

    def __repr__(self) -> str:
        return f"BlockSpreadOnly(renderables=<{len(self.renderables)} items>)"


def is_card_container(node: object) -> bool:
    """Return whether walkers descend into ``node`` as a card container."""
    return bool(
        getattr(node, "__sase_card_part__", False)
        or getattr(node, "__sase_card_block__", False)
        or getattr(node, "__sase_block_spread_only__", False)
    )


def _is_card_block(node: object) -> bool:
    """Return whether ``node`` is a :class:`CardBlock`."""
    return bool(getattr(node, "__sase_card_block__", False))


def is_block_spread_only(node: object) -> bool:
    """Return whether ``node`` is a :class:`BlockSpreadOnly` wrapper."""
    return bool(getattr(node, "__sase_block_spread_only__", False))


def card_block_id(identity: tuple[AgentType, str, str | None]) -> str:
    """Return a stable block id string from an ``Agent.identity`` tuple."""
    agent_type, name, suffix = identity
    return f"{agent_type.value}|{name}|{suffix or ''}"


def partition_card_children(
    children: Iterable[object],
) -> tuple[tuple[object, ...], tuple[CardBlock, ...], str | None]:
    """Split card children into ``(preamble, blocks, error)``.

    Blocks are trailing and contiguous. ``error`` describes the first
    structural violation (a non-block child after the first block, or an
    empty or duplicate block id), or is ``None`` when valid. A card with no
    blocks is valid with an empty block tuple.
    """
    preamble: list[object] = []
    blocks: list[CardBlock] = []
    seen: set[str] = set()
    in_blocks = False
    for child in tuple(children):
        if _is_card_block(child):
            assert isinstance(child, CardBlock)
            if not child.block_id:
                return tuple(preamble), (), "empty block id"
            if child.block_id in seen:
                return tuple(preamble), (), f"duplicate block id {child.block_id!r}"
            seen.add(child.block_id)
            in_blocks = True
            blocks.append(child)
        elif in_blocks:
            return tuple(preamble), (), "non-block child after first block"
        else:
            preamble.append(child)
    return tuple(preamble), tuple(blocks), None


def log_invalid_card_structure(card_id: str, error: str) -> None:
    """Log a warning that a card's block structure fell back to block-less."""
    logger.warning(
        "card %r has invalid block structure (%s); treating as block-less",
        card_id,
        error,
    )


__all__ = [
    "BlockMeta",
    "BlockSpreadOnly",
    "CardBlock",
    "card_block_id",
    "is_block_spread_only",
    "is_card_container",
    "log_invalid_card_structure",
    "partition_card_children",
]

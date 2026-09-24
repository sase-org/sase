"""Ordered card parts for Agents metadata-panel documents.

Every Agents metadata-panel builder emits its document as ordered card
parts: ``context``, ``reply`` (titled "Reply" or "Output") or ``summary``.
Tree walkers understand the card wrapper, while
:func:`flatten_card_document` projects the card structure back to the
legacy shape for display.
"""

from __future__ import annotations

from rich.console import Console, ConsoleOptions, Group, RenderableType
from rich.measure import Measurement
from rich.segment import Segment

CONTEXT_CARD_ID = "context"
REPLY_CARD_ID = "reply"
SUMMARY_CARD_ID = "summary"

CONTEXT_CARD_TITLE = "Context"
REPLY_CARD_TITLE = "Reply"
OUTPUT_CARD_TITLE = "Output"
SUMMARY_CARD_TITLE = "Summary"


class CardPart:
    """One named card inside a metadata-panel document."""

    __slots__ = ("card_id", "renderables", "title")

    __sase_card_part__ = True

    def __init__(self, card_id: str, title: str, *renderables: RenderableType) -> None:
        self.card_id = card_id
        self.title = title
        self.renderables: tuple[RenderableType, ...] = tuple(renderables)

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


def flatten_card_document(content: object) -> object:
    """Project a card-structured document back to its legacy shape."""
    if _is_card_part(content):
        children: list[object] = list(getattr(content, "renderables", ()))
        if len(children) == 1:
            return children[0]
        return Group(*children)  # type: ignore[arg-type]
    if isinstance(content, Group):
        has_card = any(_is_card_part(child) for child in content.renderables)
        if not has_card:
            return content
        flattened: list[object] = []
        for child in content.renderables:
            if _is_card_part(child):
                flattened.extend(getattr(child, "renderables", ()))
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
    "summary_card",
]

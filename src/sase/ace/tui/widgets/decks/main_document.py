"""Main deck document built from the hidden prompt-panel source."""

from __future__ import annotations

from dataclasses import dataclass

from .card_part import CardPart, split_card_parts


@dataclass(frozen=True)
class MainDeckDocument:
    """Card-partitioned Main deck document."""

    cards: tuple[CardPart, ...] = ()
    subject: object | None = None
    partial: bool = False
    digest: str | None = None

    @property
    def card_ids(self) -> tuple[str, ...]:
        """Return the ordered card ids."""
        return tuple(card.card_id for card in self.cards)

    def card(self, card_id: str) -> CardPart | None:
        """Return the card with ``card_id``, or None."""
        for card in self.cards:
            if card.card_id == card_id:
                return card
        return None


EMPTY_MAIN_DOCUMENT = MainDeckDocument(
    cards=(), subject=None, partial=False, digest=None
)


def build_main_deck_document(
    content: object,
    *,
    subject: object | None,
    partial: bool,
    digest: str | None,
) -> MainDeckDocument:
    """Build a Main deck document from prompt-panel content."""
    if subject is None:
        return MainDeckDocument(cards=(), subject=None, partial=partial, digest=digest)
    return MainDeckDocument(
        cards=split_card_parts(content),
        subject=subject,
        partial=partial,
        digest=digest,
    )

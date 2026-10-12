"""Record deck document builder (epic sase-1jm.4.2, ``shell``).

Assembles exactly four cards in fixed order — Lifecycle, Provenance,
Relations, Links — paged like FINAL and defaulting to Lifecycle, with
Ctrl+J/K cycling through the panel's card cycle.
"""

from __future__ import annotations

from ..card_part import CardPart
from ..main_document import MainDeckDocument
from ..model import RenderMode
from .facts import FactsExtras
from .facts import lifecycle_card, provenance_card
from .model import RecordSubject
from .relations import RelationsExtras
from .relations import links_card, relations_card

#: Card id of the Lifecycle card (the default card).
RECORD_LIFECYCLE_CARD_ID = "lifecycle"

#: Card id of the Provenance card.
RECORD_PROVENANCE_CARD_ID = "provenance"

#: Card id of the Relations card.
RECORD_RELATIONS_CARD_ID = "relations"

#: Card id of the Links card.
RECORD_LINKS_CARD_ID = "links"

#: Record card ids in fixed order.
RECORD_CARD_IDS: tuple[str, ...] = (
    RECORD_LIFECYCLE_CARD_ID,
    RECORD_PROVENANCE_CARD_ID,
    RECORD_RELATIONS_CARD_ID,
    RECORD_LINKS_CARD_ID,
)

#: Record card titles in fixed order.
RECORD_CARD_TITLES: tuple[str, ...] = (
    "Lifecycle",
    "Provenance",
    "Relations",
    "Links",
)


def record_default_card(
    card_ids: tuple[str, ...] | list[str],
    preferred: str | None,
) -> str | None:
    """Return the default Record card: sticky preference, else Lifecycle."""
    ids = tuple(card_ids)
    if not ids:
        return None
    if preferred is not None and preferred in ids:
        return preferred
    if RECORD_LIFECYCLE_CARD_ID in ids:
        return RECORD_LIFECYCLE_CARD_ID
    return ids[0]


def decide_record_mode(card_count: int) -> RenderMode:
    """Return the Record spread/paged mode for ``card_count``.

    The deck stays automatic (no view policy): a lone card spreads,
    every larger document pages.
    """
    if card_count <= 1:
        return RenderMode.SPREAD
    return RenderMode.PAGED


def build_record_document(
    subject: RecordSubject | None,
    facts: FactsExtras | None,
    relations: RelationsExtras | None,
) -> MainDeckDocument:
    """Build a Record deck document with exactly four cards in order."""
    if subject is None:
        return MainDeckDocument(cards=(), subject=None, partial=False)
    facts_extras = facts if facts is not None else FactsExtras()
    relations_extras = relations if relations is not None else RelationsExtras()
    cards: tuple[CardPart, ...] = (
        lifecycle_card(subject, facts_extras),
        provenance_card(subject, facts_extras),
        relations_card(subject, relations_extras),
        links_card(subject, relations_extras),
    )
    return MainDeckDocument(cards=cards, subject=subject, partial=False)


__all__ = [
    "RECORD_CARD_IDS",
    "RECORD_CARD_TITLES",
    "RECORD_LIFECYCLE_CARD_ID",
    "RECORD_LINKS_CARD_ID",
    "RECORD_PROVENANCE_CARD_ID",
    "RECORD_RELATIONS_CARD_ID",
    "build_record_document",
    "decide_record_mode",
    "record_default_card",
]

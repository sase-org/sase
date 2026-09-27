"""FINAL deck document builder (epic sase-1b2, ``final-deck-shell``).

Assembles the ``overview`` plus ``instance:<id>`` cards from the typed
node view. Instance card bodies render through
:mod:`sase.ace.tui.widgets.decks.final.instance_card` (generic,
provider-neutral) plus the additive
:mod:`sase.ace.tui.widgets.decks.final.enrichers`; the Overview body
belongs to ``final-overview-card``.
"""

from __future__ import annotations

from typing import Any

from sase.finalizers.view_vocabulary import instance_style

from ..main_document import MainDeckDocument
from ..model import RenderMode
from .enrichers import instance_enrichments
from .instance_card import build_instance_card_renderables
from .overview_card import render_overview_lines

#: Card id of the run-level Overview card (plan D3).
FINAL_OVERVIEW_CARD_ID = "overview"

#: Tab title of the Overview card (plan D3).
FINAL_OVERVIEW_TITLE = "Overview"


def final_instance_card_id(instance_id: str) -> str:
    """Return the card id for one selected instance (plan D3)."""
    return f"instance:{instance_id}"


def final_instance_tab_title(instance_id: str, status: str | None) -> str:
    """Return the tab title for one instance card (``<id> <glyph>``)."""
    return f"{instance_id} {instance_style(status).glyph}"


def final_default_card(
    card_ids: tuple[str, ...] | list[str],
    preferred: str | None,
    *,
    attention_instance_id: str | None,
    run_level_trouble: bool,
) -> str | None:
    """Return the default FINAL card (plan §3.6).

    In order: the panel's sticky FINAL preference when that card exists
    for this node, else the attention instance, else ``overview`` when
    the run is in trouble, else the first instance card.
    """
    ids = tuple(card_ids)
    if not ids:
        return None
    if preferred is not None and preferred in ids:
        return preferred
    if attention_instance_id is not None:
        attention = final_instance_card_id(attention_instance_id)
        if attention in ids:
            return attention
    if run_level_trouble and FINAL_OVERVIEW_CARD_ID in ids:
        return FINAL_OVERVIEW_CARD_ID
    for card_id in ids:
        if card_id != FINAL_OVERVIEW_CARD_ID:
            return card_id
    return ids[0]


def decide_final_mode(card_count: int) -> RenderMode:
    """Return the FINAL spread/paged mode for ``card_count``.

    The deck stays automatic (no view policy): a lone card spreads, every
    larger document pages. Block modes stay off until ``final-run-blocks``
    adds one CardBlock per run.
    """
    if card_count <= 1:
        return RenderMode.SPREAD
    return RenderMode.PAGED


def build_final_deck_document(
    node_view: Any,
    *,
    subject: object | None,
    digest: str | None,
) -> MainDeckDocument:
    """Build a FINAL deck document from the typed node view."""
    from ..card_part import CardPart

    if subject is None or node_view is None:
        return MainDeckDocument(cards=(), subject=None, partial=False, digest=digest)
    instances = list(getattr(node_view, "instances", ()) or ())
    overview = CardPart(
        FINAL_OVERVIEW_CARD_ID,
        FINAL_OVERVIEW_TITLE,
        *render_overview_lines(node_view),
    )
    cards: list[CardPart] = [overview]
    runs = list(getattr(node_view, "runs", ()) or ())
    for item in instances:
        instance_id = str(getattr(item, "instance_id", ""))
        status = getattr(item, "status", None)
        provider_ref = getattr(item, "provider_ref", None)
        body = build_instance_card_renderables(item, runs)
        extra = instance_enrichments(
            str(provider_ref) if provider_ref else None, item, runs
        )
        cards.append(
            CardPart(
                final_instance_card_id(instance_id),
                final_instance_tab_title(instance_id, status),
                *body,
                *extra,
            )
        )
    return MainDeckDocument(
        cards=tuple(cards), subject=subject, partial=False, digest=digest
    )


__all__ = [
    "FINAL_OVERVIEW_CARD_ID",
    "FINAL_OVERVIEW_TITLE",
    "build_final_deck_document",
    "decide_final_mode",
    "final_default_card",
    "final_instance_card_id",
    "final_instance_tab_title",
]

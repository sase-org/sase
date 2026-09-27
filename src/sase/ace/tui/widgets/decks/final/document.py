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

from rich.text import Text

from sase.finalizers.view_vocabulary import instance_style

from ..card_block import CardBlock
from ..main_document import MainDeckDocument
from ..model import RenderMode
from .enrichers import instance_enrichments
from .instance_card import (
    INSTANCE_EXPORT_HINT,
    build_instance_card_renderables,
    build_instance_preamble_lines,
    build_instance_run_lines,
)
from .overview_card import (
    OVERVIEW_FOOTER,
    render_overview_ledger_lines,
    render_overview_lines,
    render_overview_preamble,
    render_overview_run_lines,
)
from .run_blocks import (
    final_block_runs,
    run_block_header,
    run_block_meta,
    run_instance_ran,
)

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


def _final_run_block(run: Any, body: Any) -> CardBlock:
    """Wrap one run's card body lines in a stably identified block."""
    meta = run_block_meta(run)
    run_id = str(getattr(run, "run_id", "") or "")
    lines = [run_block_header(run), *body]
    return CardBlock(run_id, meta.label, *lines, meta=meta)


def _overview_block_runs(node_view: Any) -> list[Any]:
    """Return the Overview card's block runs (plan §4.17)."""
    return final_block_runs(list(getattr(node_view, "runs", ()) or ()))


def _instance_block_pairs(item: Any, block_runs: list[Any]) -> list[tuple[Any, Any]]:
    """Return ``(run, run_item)`` pairs where this instance ran.

    Runs where the instance never ran (not-triggered, skipped) earn no
    block on this card; they appear only in the Overview ledger line.
    """
    instance_id = str(getattr(item, "instance_id", "") or "")
    pairs: list[tuple[Any, Any]] = []
    for run in block_runs:
        for run_item in getattr(run, "instances", ()) or ():
            if str(getattr(run_item, "instance_id", "") or "") != instance_id:
                continue
            if run_instance_ran(run_item):
                pairs.append((run, run_item))
    return pairs


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
    runs = list(getattr(node_view, "runs", ()) or ())
    block_runs = _overview_block_runs(node_view)
    if len(block_runs) < 2:
        return _build_flat_final_document(node_view, instances, runs, subject, digest)

    overview = CardPart(
        FINAL_OVERVIEW_CARD_ID,
        FINAL_OVERVIEW_TITLE,
        *render_overview_preamble(node_view),
        *render_overview_ledger_lines(node_view),
        Text(OVERVIEW_FOOTER, style="dim"),
        *[  # type: ignore[arg-type]
            _final_run_block(run, render_overview_run_lines(run)) for run in block_runs
        ],
    )
    cards: list[CardPart] = [overview]
    for item in instances:
        instance_id = str(getattr(item, "instance_id", ""))
        status = getattr(item, "status", None)
        provider_ref = getattr(item, "provider_ref", None)
        extra = instance_enrichments(
            str(provider_ref) if provider_ref else None, item, runs
        )
        pairs = _instance_block_pairs(item, block_runs)
        if not pairs:
            body = build_instance_card_renderables(item, runs)
            cards.append(
                CardPart(
                    final_instance_card_id(instance_id),
                    final_instance_tab_title(instance_id, status),
                    *body,
                    *extra,
                )
            )
            continue
        cards.append(
            CardPart(
                final_instance_card_id(instance_id),
                final_instance_tab_title(instance_id, status),
                *build_instance_preamble_lines(item, runs),
                *extra,
                Text(INSTANCE_EXPORT_HINT, style="dim"),
                *[  # type: ignore[arg-type]
                    _final_run_block(
                        run,
                        build_instance_run_lines(run_item, instance_id=instance_id),
                    )
                    for run, run_item in pairs
                ],
            )
        )
    return MainDeckDocument(
        cards=tuple(cards), subject=subject, partial=False, digest=digest
    )


def _build_flat_final_document(
    node_view: Any,
    instances: list[Any],
    runs: list[Any],
    subject: object | None,
    digest: str | None,
) -> MainDeckDocument:
    """Build a block-less FINAL deck document (fewer than two block runs)."""
    from ..card_part import CardPart

    overview = CardPart(
        FINAL_OVERVIEW_CARD_ID,
        FINAL_OVERVIEW_TITLE,
        *render_overview_lines(node_view),
    )
    cards: list[CardPart] = [overview]
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

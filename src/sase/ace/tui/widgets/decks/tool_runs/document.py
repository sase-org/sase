"""``⚒ Runs`` card document for the Tools deck (epic sase-1bt).

The document holds exactly one card, ``runs``, with one
:class:`CardBlock` per run. Exactly one run gives a block-less document
with no rail, as FINAL does. ``tools-deck-cards`` carries the outcome
line only; the full block anatomy arrives with ``runs-card-anatomy``.
"""

from __future__ import annotations

from typing import Any

from rich.text import Text

from sase.ace.tui.tool_runs.deck import (
    TOOLS_RUNS_CARD_ID,
    TOOLS_RUNS_TAB_TITLE,
    tool_run_block_header_text,
    tool_run_block_meta,
    tool_run_outcome_line,
    tools_truncated_line,
)

from ..card_block import CardBlock
from ..main_document import MainDeckDocument


def build_tool_runs_blocks(runs: Any) -> list[CardBlock]:
    """Return one :class:`CardBlock` per run, oldest first (outcome only)."""
    ordered = list(runs or ())
    blocks: list[CardBlock] = []
    for index, brief in enumerate(ordered):
        run_id = str(getattr(brief, "run_id", "") or f"run-{index}")
        meta = tool_run_block_meta(index, brief)
        header = tool_run_block_header_text(index, brief)
        blocks.append(CardBlock(run_id, meta.label, header, meta=meta))
    return blocks


def build_tool_runs_document(
    runs: Any,
    *,
    subject: object | None,
    digest: str | None,
    total_runs: int | None = None,
    truncated: bool = False,
) -> MainDeckDocument:
    """Build the ``⚒ Runs`` card document from node-summary runs.

    ``runs`` are :class:`ToolRunBrief` rows, oldest first. A ``None``
    subject (or no runs) yields an empty document. ``truncated`` adds a
    dim ``+N older runs`` preamble line so the card never pretends the
    list is complete.
    """
    from ..card_part import CardPart as _CardPart

    ordered = list(runs or ())
    if subject is None or not ordered:
        return MainDeckDocument(cards=(), subject=None, partial=False, digest=digest)
    try:
        total = int(total_runs) if total_runs is not None else len(ordered)
    except (TypeError, ValueError):
        total = len(ordered)
    hidden = max(0, total - len(ordered))
    preamble: list[Any] = []
    if truncated or hidden > 0:
        preamble.append(Text(tools_truncated_line(hidden), style="dim"))
    if len(ordered) < 2:
        lines = [tool_run_outcome_line(brief) for brief in ordered]
        card = _CardPart(TOOLS_RUNS_CARD_ID, TOOLS_RUNS_TAB_TITLE, *preamble, *lines)
        return MainDeckDocument(
            cards=(card,), subject=subject, partial=False, digest=digest
        )
    blocks = build_tool_runs_blocks(ordered)
    children: list[Any] = [*preamble, *blocks]
    card = _CardPart(TOOLS_RUNS_CARD_ID, TOOLS_RUNS_TAB_TITLE, *children)
    return MainDeckDocument(
        cards=(card,), subject=subject, partial=False, digest=digest
    )


__all__ = ["build_tool_runs_document"]

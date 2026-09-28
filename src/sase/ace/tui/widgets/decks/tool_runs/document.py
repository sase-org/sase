"""``⚒ Runs`` card document for the Tools deck (epic sase-1bt).

The document holds exactly one card, ``runs``, with one
:class:`CardBlock` per run. Exactly one run gives a block-less document
with no rail, as FINAL does. ``runs-card-anatomy`` renders each
block's full anatomy (outcome, context, waterfall, triage items, child
runs, log tail) through the pure :mod:`sase.ace.tui.tool_runs.blocks`
renderer the Admin Center Tools pane reuses.
"""

from __future__ import annotations

from typing import Any

from rich.text import Text

from sase.ace.tui.tool_runs.blocks import render_tool_run_block
from sase.ace.tui.tool_runs.deck import (
    DEFAULT_TOOL_RUNS_DETAIL_LEVEL,
    TOOLS_RUNS_CARD_ID,
    TOOLS_RUNS_TAB_TITLE,
    ToolRunsDetailLevel,
    coerce_tool_runs_detail_level,
    tool_run_block_header_text,
    tool_run_block_meta,
    tools_truncated_line,
)

from ..card_block import CardBlock
from ..main_document import MainDeckDocument


def _loaded_for(loaded: Any, run_id: str) -> tuple[Any | None, Any | None]:
    """Split one *loaded* entry into ``(detail, tail)`` (never raises)."""

    if loaded is None:
        return (None, None)
    try:
        return (loaded.detail, loaded.tail)
    except AttributeError:
        pass
    if hasattr(loaded, "stages") or hasattr(loaded, "found"):
        return (loaded, None)
    return (None, None)


def build_tool_runs_blocks(
    runs: Any,
    *,
    details: Any | None = None,
    level: ToolRunsDetailLevel | int = DEFAULT_TOOL_RUNS_DETAIL_LEVEL,
    width: int = 100,
    now_ms: int | None = None,
    now_s: float | None = None,
    silent_after_s: int = 60,
    hint_numbers: Any | None = None,
) -> list[CardBlock]:
    """Return one :class:`CardBlock` per run, oldest first (full anatomy)."""
    resolved_level = coerce_tool_runs_detail_level(level)
    ordered = list(runs or ())
    blocks: list[CardBlock] = []
    for index, brief in enumerate(ordered):
        run_id = str(getattr(brief, "run_id", "") or f"run-{index}")
        meta = tool_run_block_meta(index, brief)
        loaded = None
        if details is not None:
            try:
                loaded = details.get(run_id)
            except AttributeError:
                loaded = None
        detail, tail = _loaded_for(loaded, run_id)
        header = tool_run_block_header_text(
            index, brief, detail, now_s=now_s, silent_after_s=silent_after_s
        )
        body = render_tool_run_block(
            brief,
            detail,
            level=resolved_level,
            width=width,
            now_ms=now_ms,
            now_s=now_s,
            silent_after_s=silent_after_s,
            tail=tail,
            include_outcome=False,
            hint_numbers=hint_numbers,
        )
        blocks.append(CardBlock(run_id, meta.label, header, body, meta=meta))
    return blocks


def build_tool_runs_document(
    runs: Any,
    *,
    subject: object | None,
    digest: str | None,
    total_runs: int | None = None,
    truncated: bool = False,
    details: Any | None = None,
    level: ToolRunsDetailLevel | int = DEFAULT_TOOL_RUNS_DETAIL_LEVEL,
    width: int = 100,
    now_ms: int | None = None,
    now_s: float | None = None,
    silent_after_s: int = 60,
    hint_numbers: Any | None = None,
) -> MainDeckDocument:
    """Build the ``⚒ Runs`` card document from node-summary runs.

    ``runs`` are :class:`ToolRunBrief` rows, oldest first. A ``None``
    subject (or no runs) yields an empty document. ``truncated`` adds a
    dim ``+N older runs`` preamble line so the card never pretends the
    list is complete. ``details`` maps run ids to loaded
    (:class:`LoadedToolRunDetail`) entries; runs without one render
    brief-only with honest absence.
    """
    from ..card_part import CardPart as _CardPart

    resolved_level = coerce_tool_runs_detail_level(level)
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

    def _block_lines(brief: Any) -> Text:
        run_id = str(getattr(brief, "run_id", "") or "")
        loaded = None
        if details is not None:
            try:
                loaded = details.get(run_id)
            except AttributeError:
                loaded = None
        detail, tail = _loaded_for(loaded, run_id)
        return render_tool_run_block(
            brief,
            detail,
            level=resolved_level,
            width=width,
            now_ms=now_ms,
            now_s=now_s,
            silent_after_s=silent_after_s,
            tail=tail,
            hint_numbers=hint_numbers,
        )

    if len(ordered) < 2:
        lines = [_block_lines(brief) for brief in ordered]
        card = _CardPart(TOOLS_RUNS_CARD_ID, TOOLS_RUNS_TAB_TITLE, *preamble, *lines)
        return MainDeckDocument(
            cards=(card,), subject=subject, partial=False, digest=digest
        )
    blocks = build_tool_runs_blocks(
        ordered,
        details=details,
        level=resolved_level,
        width=width,
        now_ms=now_ms,
        now_s=now_s,
        silent_after_s=silent_after_s,
        hint_numbers=hint_numbers,
    )
    children: list[Any] = [*preamble, *blocks]
    card = _CardPart(TOOLS_RUNS_CARD_ID, TOOLS_RUNS_TAB_TITLE, *children)
    return MainDeckDocument(
        cards=(card,), subject=subject, partial=False, digest=digest
    )


__all__ = ["build_tool_runs_blocks", "build_tool_runs_document"]

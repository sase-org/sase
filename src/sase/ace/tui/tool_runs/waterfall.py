"""Stage waterfall rows for the ``⚒ Runs`` card (epic sase-1bt).

Pure functions of in-memory detail stages plus ``now``: nothing stats,
opens SQLite, or reads a log. The Admin Center Tools pane imports the
same renderer (plan §4.7 step 3).
"""

from __future__ import annotations

from typing import Any

from rich.text import Text

from sase.tool.render import format_duration_ms

#: Panel widths below this drop the Gantt bars and keep the table.
WATERFALL_NARROW_WIDTH = 70

#: Eighth-block cells for sub-cell bar precision (1/8 .. 8/8).
_EIGHTHS = ("▏", "▎", "▍", "▌", "▋", "▊", "▉", "█")

_PASS_STYLE = "dim #5FD75F"
_FAIL_STYLE = "#FF5F5F"
_RUNNING_STYLE = "bold #FFAF5F"
_PENDING_STYLE = "dim"


def _stage_kind(stage: Any, *, is_live: bool) -> str:
    """Return one of ``pass``, ``fail``, ``running``, or ``pending``."""

    exit_code = getattr(stage, "exit_code", None)
    started = getattr(stage, "started_ms", None)
    finished = getattr(stage, "finished_ms", None)
    incomplete = bool(getattr(stage, "incomplete", False))
    if finished is not None or (
        exit_code is not None and not incomplete and started is not None
    ):
        if exit_code is not None and exit_code != 0:
            return "fail"
        return "pass"
    if started is not None or (is_live and incomplete):
        return "running"
    return "pending"


def _stage_counts_text(stage: Any) -> str:
    """Return the right-aligned per-stage triage counts (``2 NEW``)."""

    counts = getattr(stage, "counts", None)
    if counts is None:
        return ""
    parts: list[str] = []
    new = int(getattr(counts, "new", 0) or 0)
    known = int(getattr(counts, "known", 0) or 0)
    flaky = int(getattr(counts, "flaky", 0) or 0)
    unknown = int(getattr(counts, "unknown", 0) or 0)
    if new:
        parts.append(f"{new} NEW")
    if unknown:
        parts.append(f"{unknown} UNKNOWN")
    if known:
        parts.append(f"{known} KNOWN")
    if flaky:
        parts.append(f"{flaky} FLAKY")
    return " · ".join(parts)


def _bar_text(offset_cells: float, length_cells: float) -> str:
    """Return a Gantt bar with eighth-block precision (≥ one cell)."""

    length_cells = max(1.0, length_cells)
    offset_eighths = max(0, int(round(offset_cells * 8)))
    length_eighths = max(8, int(round(length_cells * 8)))
    leading_full, leading_part = divmod(offset_eighths, 8)
    bar_full, bar_part = divmod(length_eighths, 8)
    bar = " " * leading_full
    if leading_part:
        bar += _EIGHTHS[leading_part - 1]
    bar += "█" * bar_full
    if bar_part:
        bar += _EIGHTHS[bar_part - 1]
    return bar


def _span_ms(
    stages: tuple[Any, ...] | list[Any],
    *,
    now_ms: int | None,
) -> tuple[int, int]:
    """Return the ``(run_start_ms, run_end_ms)`` span covering *stages*."""

    starts = [
        int(stage.started_ms or 0)
        for stage in stages
        if getattr(stage, "started_ms", None) is not None
    ]
    ends: list[int] = []
    for stage in stages:
        finished = getattr(stage, "finished_ms", None)
        if finished is not None:
            ends.append(int(finished))
        else:
            started = getattr(stage, "started_ms", None)
            elapsed = getattr(stage, "elapsed_ms", None)
            if started is not None and elapsed is not None:
                ends.append(int(started) + int(elapsed))
    if now_ms is not None:
        ends.append(int(now_ms))
    if not starts:
        return (0, 0)
    start = min(starts)
    end = max(ends) if ends else start
    return (start, max(end, start + 1))


def waterfall_rows(
    stages: tuple[Any, ...] | list[Any],
    expected_stages: tuple[Any, ...] | list[Any] | None = None,
    *,
    width: int = 100,
    is_live: bool = False,
    now_ms: int | None = None,
) -> Text:
    """Return the stage waterfall table for one run block.

    One row per stage: glyph, description, duration, and a Gantt bar
    whose offset is proportional to the stage start within the run and
    whose length is proportional to elapsed. Expected stages the run
    has not started render as pending (live) or not-reached (settled)
    rows. Below :data:`WATERFALL_NARROW_WIDTH` cells the bars drop and
    the table stays.
    """

    rows = list(stages or ())
    expected = list(expected_stages or ())
    text = Text()
    if not rows and not expected:
        return text
    show_bars = width >= WATERFALL_NARROW_WIDTH
    run_start, run_end = _span_ms(rows, now_ms=now_ms)
    span = max(1, run_end - run_start)
    seen = {str(getattr(stage, "description", "") or "") for stage in rows}
    pending = [
        stage
        for stage in expected
        if str(getattr(stage, "description", "") or "") not in seen
    ]
    desc_width = 0
    for stage in (*rows, *pending):
        desc_width = max(desc_width, len(str(getattr(stage, "description", "") or "")))
    desc_width = min(max(desc_width, 8), 28)
    bar_width = max(8, min(24, width - desc_width - 24)) if show_bars else 0
    for stage in rows:
        _append_stage_row(
            text,
            stage,
            kind=_stage_kind(stage, is_live=is_live),
            desc_width=desc_width,
            bar_width=bar_width,
            run_start=run_start,
            span_ms=span,
            now_ms=now_ms,
            show_bars=show_bars,
        )
    for stage in pending:
        _append_expected_row(
            text,
            stage,
            desc_width=desc_width,
            is_live=is_live,
        )
    return text


def _append_stage_row(
    text: Text,
    stage: Any,
    *,
    kind: str,
    desc_width: int,
    bar_width: int,
    run_start: int,
    span_ms: int,
    now_ms: int | None,
    show_bars: bool,
) -> None:
    """Append one actual-stage row to *text*."""

    desc = str(getattr(stage, "description", "") or "")
    elapsed = getattr(stage, "elapsed_ms", None)
    if elapsed is None:
        started = getattr(stage, "started_ms", None)
        finished = getattr(stage, "finished_ms", None)
        if started is not None and finished is not None:
            elapsed = int(finished) - int(started)
        elif started is not None and now_ms is not None:
            elapsed = max(0, int(now_ms) - int(started))
    duration = format_duration_ms(int(elapsed)) if elapsed is not None else ""
    counts = _stage_counts_text(stage)
    if kind == "fail":
        glyph, style = "✗", _FAIL_STYLE
    elif kind == "running":
        glyph, style = "▶", _RUNNING_STYLE
    elif kind == "pending":
        glyph, style = "·", _PENDING_STYLE
    else:
        glyph, style = "✓", _PASS_STYLE
    line = Text()
    line.append(f"  {glyph} ", style=style)
    line.append(desc.ljust(desc_width), style="" if kind != "pending" else "dim")
    if duration:
        line.append(f"  {duration:>7}", style="dim")
    if show_bars and kind in ("pass", "fail", "running"):
        started = getattr(stage, "started_ms", None)
        offset = (
            max(0.0, (int(started) - run_start) / span_ms) * bar_width
            if started is not None
            else 0.0
        )
        length = (
            max(0.0, int(elapsed or 0) / span_ms) * bar_width
            if elapsed is not None
            else 1.0
        )
        bar = _bar_text(offset, length)
        suffix = "…" if kind == "running" else ""
        line.append(f"  {bar}{suffix}", style=style)
    if counts:
        line.append(
            f"  {counts}",
            style="dim" if kind == "pass" else _FAIL_STYLE if kind == "fail" else "",
        )
    line.append("\n")
    text.append_text(line)


def _append_expected_row(
    text: Text,
    stage: Any,
    *,
    desc_width: int,
    is_live: bool,
) -> None:
    """Append one pending/not-reached expected-stage row to *text*."""

    desc = str(getattr(stage, "description", "") or "")
    elapsed = getattr(stage, "elapsed_ms", None)
    line = Text()
    if is_live:
        line.append("  · ", style=_PENDING_STYLE)
        line.append(desc.ljust(desc_width), style="dim")
        if elapsed is not None:
            line.append(f"  typ {format_duration_ms(int(elapsed))}", style="dim")
        else:
            line.append("  pending", style="dim")
    else:
        line.append("  – ", style="dim")
        line.append(desc.ljust(desc_width), style="dim")
        line.append("  not reached", style="dim")
    line.append("\n")
    text.append_text(line)


__all__ = ["WATERFALL_NARROW_WIDTH", "waterfall_rows"]

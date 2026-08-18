"""Pure rendering helpers for the Alias History model-usage strip.

No Textual imports beyond :mod:`rich.text` — the modal paints a cached
:class:`~sase.llm_provider.alias_history_usage.AliasHistoryUsageSummary`.
"""

from __future__ import annotations

import math

from rich.text import Text

from sase.ace.tui.model_alias_styles import provider_model_text
from sase.ace.tui.provider_styles import provider_bar_style
from sase.llm_provider.alias_history_usage import (
    AliasHistoryModelUsage,
    AliasHistoryUsageSummary,
)

_LABEL_STYLE = "bold #87D7FF"
_FAILED_STYLE = "bold #D75F5F"
_RUNNING_STYLE = "bold #5FD7FF"
_TRACK_STYLE = "dim"
_MIXED_EFFORT_STYLE = "dim"
_TAG_STYLE = "dim"
_UNRECORDED_STYLE = "dim italic"
_LOADING_STYLE = "dim italic"

_BAR_WIDTH = 26
_BADGE_CAP = 38
_PARTIALS = ("", "▏", "▎", "▍", "▌", "▋", "▊", "▉")
_MAX_MODEL_ROWS = 4
_OVERFLOW_THRESHOLD = 4


def alias_history_usage_text(
    summary: AliasHistoryUsageSummary | None, *, error: str | None = None
) -> Text:
    """Render the usage strip for *summary*, or a single-line loading/error state."""
    if summary is None:
        message = error or "Model usage · loading…"
        if error and not error.startswith("Model usage"):
            message = f"Model usage · {error}"
        return Text(message, style=_LOADING_STYLE)
    if summary.counted_runs == 0:
        return Text("Model usage · no runs in this window", style=_LOADING_STYLE)
    text = Text(no_wrap=False)
    text.append_text(_header_text(summary))
    shown, overflow = _visible_rows(summary.rows)
    badge_width = _badge_column_width(shown)
    for row in shown:
        text.append("\n")
        text.append_text(
            _row_text(row, badge_width=badge_width, pool_known=summary.pool_total > 0)
        )
    if overflow:
        text.append("\n")
        text.append_text(
            _overflow_text(
                overflow, badge_width=badge_width, summary=summary, shown=shown
            )
        )
    return text


def _header_text(summary: AliasHistoryUsageSummary) -> Text:
    text = Text(no_wrap=False)
    text.append("Model usage", style=_LABEL_STYLE)
    text.append(" · ", style="dim")
    noun = "run" if summary.counted_runs == 1 else "runs"
    text.append(f"{summary.counted_runs} {noun}", style="dim")
    if summary.duplicate_runs:
        text.append(" · ", style="dim")
        text.append("(deduped)", style="dim")
    if summary.pool_total > 1:
        text.append(" · ", style="dim")
        text.append(
            f"{summary.pool_used} of {summary.pool_total} members used",
            style="dim",
        )
    return text


def _visible_rows(
    rows: tuple[AliasHistoryModelUsage, ...],
) -> tuple[tuple[AliasHistoryModelUsage, ...], tuple[AliasHistoryModelUsage, ...]]:
    if len(rows) > _OVERFLOW_THRESHOLD:
        return rows[: _MAX_MODEL_ROWS - 1], rows[_MAX_MODEL_ROWS - 1 :]
    return rows, ()


def _badge_column_width(rows: tuple[AliasHistoryModelUsage, ...]) -> int:
    widest = 0
    for row in rows:
        widest = max(widest, _badge_text(row).cell_len)
    return min(widest, _BADGE_CAP)


def _badge_text(row: AliasHistoryModelUsage) -> Text:
    if row.is_unrecorded:
        return Text("unrecorded", style=_UNRECORDED_STYLE)
    if row.effort_is_mixed:
        text = provider_model_text(row.provider, row.model, "")
        text.append(" @ ", style=_MIXED_EFFORT_STYLE)
        text.append("mixed", style=_MIXED_EFFORT_STYLE)
        return text
    return provider_model_text(row.provider, row.model, row.effort or "")


def _row_text(
    row: AliasHistoryModelUsage, *, badge_width: int, pool_known: bool
) -> Text:
    text = Text(no_wrap=True)
    text.append("  ")
    badge = _badge_text(row)
    badge.truncate(badge_width, overflow="ellipsis", pad=True)
    text.append_text(badge)
    text.append("  ")
    text.append_text(_bar_text(row.share, provider=row.provider))
    text.append("  ")
    text.append(f"{row.count:>4}")
    text.append("  ")
    text.append(f"{row.share_percent:>3}%")
    if row.failed:
        text.append("  ")
        text.append(f"✗{row.failed}", style=_FAILED_STYLE)
    if row.running:
        text.append("  ")
        text.append(f"▶{row.running}", style=_RUNNING_STYLE)
    tag = _row_tag(row, pool_known=pool_known)
    if tag:
        text.append("  ")
        text.append(tag, style=_TAG_STYLE)
    return text


def _row_tag(row: AliasHistoryModelUsage, *, pool_known: bool) -> str | None:
    if row.count == 0:
        return "unused"
    if pool_known and not row.in_pool and not row.is_unrecorded:
        return "off-pool"
    return None


def _bar_text(share: float, *, provider: str | None, dim: bool = False) -> Text:
    eighths = math.floor(share * _BAR_WIDTH * 8)
    if share > 0 and eighths < 1:
        eighths = 1
    eighths = min(_BAR_WIDTH * 8, max(0, eighths))
    full, remainder = divmod(eighths, 8)
    glyphs = "█" * full
    if remainder:
        glyphs += _PARTIALS[remainder]
    glyphs = glyphs[:_BAR_WIDTH]
    track = "░" * (_BAR_WIDTH - len(glyphs))
    text = Text(no_wrap=True)
    fill_style = _TRACK_STYLE if dim else provider_bar_style(provider)
    if glyphs:
        text.append(glyphs, style=fill_style)
    if track:
        text.append(track, style=_TRACK_STYLE)
    return text


def _overflow_text(
    overflow: tuple[AliasHistoryModelUsage, ...],
    *,
    badge_width: int,
    summary: AliasHistoryUsageSummary,
    shown: tuple[AliasHistoryModelUsage, ...],
) -> Text:
    count = sum(row.count for row in overflow)
    remaining_percent = 100 - sum(row.share_percent for row in shown)
    share = (count / summary.counted_runs) if summary.counted_runs else 0.0
    text = Text(no_wrap=True)
    text.append("  ")
    label = Text(f"+{len(overflow)} more", style="dim")
    label.truncate(badge_width, overflow="ellipsis", pad=True)
    text.append_text(label)
    text.append("  ")
    text.append_text(_bar_text(share, provider=None, dim=True))
    text.append("  ")
    text.append(f"{count:>4}", style="dim")
    text.append("  ")
    text.append(f"{remaining_percent:>3}%", style="dim")
    return text


__all__ = ["alias_history_usage_text"]

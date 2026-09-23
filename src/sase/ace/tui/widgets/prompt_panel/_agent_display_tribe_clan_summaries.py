"""Fold-aware CLAN SUMMARIES section for tribe detail documents.

The curated clan-intent map: one uniform headline per clan summary at a
glance, with deeper fold levels revealing ledes, previews, and full bodies.
All strings and style spans arrive precomputed from the worker-side digest,
so this renderer only appends text and replays spans. It never parses markup
or touches the filesystem.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping

from rich.text import Text

from ...models._agent_clan_sections import ClanAgentIdentity
from ...models.fold_state import FoldLevel
from .._agent_list_styling import _CLAN_IDENTITY_COLOR
from ._agent_display_tribe_common import (
    BODY_STYLE,
    SECTIONS,
    TRIAGE_LIMIT,
    TRIBE_IDENTITY_COLOR,
    append_fold_heading,
    effective_level,
)
from ._agent_tribe_aggregation import TribeSectionSnapshot
from ._agent_tribe_clan_summaries import ClanSummaryLineSpan, TribeClanSummaryEntry
from ._helpers import append_fold_anchor

CLAN_SUMMARIES_GLANCE_LIMIT = TRIAGE_LIMIT
CLAN_SUMMARIES_LIST_LIMIT = 24
CLAN_SUMMARIES_PREVIEW_LINES = 16
CLAN_SUMMARIES_BODY_SAFETY_LINES = 500
CLAN_SUMMARY_ENTRY_ANCHOR_PREFIX = "tribe:clan-summary:"

_CLAN_LABEL_STYLE = f"bold {_CLAN_IDENTITY_COLOR}"
_KICKER_STYLE = "bold #AF87FF"
_GUTTER_STYLE = "#875FAF"
_SIZE_STYLE = "dim"


def append_clan_summaries(
    text: Text,
    section_snapshot: TribeSectionSnapshot | None,
    *,
    level: FoldLevel,
    overrides: Mapping[str, FoldLevel],
    unit_numbers: Mapping[ClanAgentIdentity, str],
    present_units: Collection[ClanAgentIdentity],
) -> None:
    """Append the CLAN SUMMARIES section after the TRIBE MEMBERS roster."""
    digest_snapshot = (
        section_snapshot.clan_summaries if section_snapshot is not None else None
    )
    entries = (
        tuple(
            entry
            for entry in digest_snapshot.entries
            if entry.unit_identity in present_units
        )
        if digest_snapshot is not None
        else ()
    )
    if not entries:
        return
    append_fold_heading(
        text,
        title="CLAN SUMMARIES",
        section_id=SECTIONS.clan_summaries,
        level=level,
        count=len(entries),
    )
    if level is FoldLevel.EXHAUSTIVE:
        shown = entries
        tail: str | None = None
        dim_tail = False
    else:
        limit = (
            CLAN_SUMMARIES_GLANCE_LIMIT
            if level is FoldLevel.COLLAPSED
            else CLAN_SUMMARIES_LIST_LIMIT
        )
        shown = entries[:limit]
        hidden = len(entries) - len(shown)
        tail = f"  +{hidden} more" if hidden > 0 else None
        dim_tail = level is FoldLevel.COLLAPSED
    for index, entry in enumerate(shown):
        entry_level = effective_level(
            f"{CLAN_SUMMARY_ENTRY_ANCHOR_PREFIX}{entry.entry_key}",
            level,
            overrides,
        )
        _append_clan_summary_entry(
            text,
            entry,
            level=entry_level,
            number=unit_numbers.get(entry.unit_identity),
        )
        if entry_level in (FoldLevel.FULLY_EXPANDED, FoldLevel.EXHAUSTIVE):
            if index < len(shown) - 1:
                text.append("\n")
    if tail is not None:
        text.append(tail + "\n", style="dim" if dim_tail else "")


def _append_clan_summary_entry(
    text: Text,
    entry: TribeClanSummaryEntry,
    *,
    level: FoldLevel,
    number: str | None,
) -> None:
    """Append one independently foldable clan summary entry and its body."""
    digest = entry.digest
    line = Text()
    if number is None:
        line.append("•", style="dim")
    else:
        line.append(f" {number} ", style=f"bold black on {TRIBE_IDENTITY_COLOR}")
    line.append(" ")
    line.append(entry.unit_label, style=_CLAN_LABEL_STYLE)
    if digest.kicker:
        line.append("  ")
        line.append(digest.kicker, style=_KICKER_STYLE)
    line.append("  ")
    line.append(digest.headline, style=BODY_STYLE)
    if len(digest.lines) > 1:
        line.append(" · ", style="dim")
        line.append(f"{len(digest.lines)} lines", style=_SIZE_STYLE)
    append_fold_anchor(
        text,
        line,
        section_id=f"{CLAN_SUMMARY_ENTRY_ANCHOR_PREFIX}{entry.entry_key}",
    )
    if level is FoldLevel.EXPANDED:
        _append_gutter_range(
            text,
            entry,
            start=digest.lede_start,
            count=digest.lede_count,
        )
    elif level is FoldLevel.FULLY_EXPANDED:
        hidden = len(digest.lines) - CLAN_SUMMARIES_PREVIEW_LINES
        _append_gutter_range(
            text,
            entry,
            start=0,
            count=min(len(digest.lines), CLAN_SUMMARIES_PREVIEW_LINES),
        )
        if hidden > 0:
            text.append(f"  ▎ … +{hidden} more lines\n", style="dim italic")
    elif level is FoldLevel.EXHAUSTIVE:
        hidden = len(digest.lines) - CLAN_SUMMARIES_BODY_SAFETY_LINES
        _append_gutter_range(
            text,
            entry,
            start=0,
            count=min(len(digest.lines), CLAN_SUMMARIES_BODY_SAFETY_LINES),
        )
        if hidden > 0:
            text.append(f"  ▎ … +{hidden} more lines\n", style="dim italic")
            if number is None:
                text.append(
                    "  ▎ open the clan panel for the rest\n", style="dim italic"
                )
            else:
                text.append(
                    f"  ▎ press {number} to open the clan panel for the rest\n",
                    style="dim italic",
                )


def _append_gutter_range(
    text: Text,
    entry: TribeClanSummaryEntry,
    *,
    start: int,
    count: int,
) -> None:
    """Append authored body lines behind the clan gutter with styles replayed."""
    digest = entry.digest
    for offset in range(count):
        index = start + offset
        if index < 0 or index >= len(digest.lines):
            continue
        spans = digest.line_spans[index] if index < len(digest.line_spans) else ()
        text.append("  ▎ ", style=_GUTTER_STYLE)
        text.append_text(_styled_line(digest.lines[index], spans))
        text.append("\n")


def _styled_line(
    content: str,
    spans: tuple[ClanSummaryLineSpan, ...],
) -> Text:
    """Return *content* with precomputed spans replayed over the base style."""
    styled = Text(content, style=BODY_STYLE)
    for span_style, start, end in spans:
        if 0 <= start < len(content):
            styled.stylize(span_style, start, min(end, len(content)))
    return styled


__all__ = [
    "CLAN_SUMMARIES_BODY_SAFETY_LINES",
    "CLAN_SUMMARIES_GLANCE_LIMIT",
    "CLAN_SUMMARIES_LIST_LIMIT",
    "CLAN_SUMMARIES_PREVIEW_LINES",
    "CLAN_SUMMARY_ENTRY_ANCHOR_PREFIX",
    "append_clan_summaries",
]

"""Cached RESULT-card and report rendering for one axe chop run."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import PurePath
from typing import Any

from rich.text import Text

from sase.axe.chop_report_render import render_chop_report, render_section_rule
from sase.axe.state import ChopRunEntry

from ._axe_dashboard_render import chop_status_label

_LABEL_STYLE = "bold #87D7FF"
_VALUE_STYLE = "#00D7AF"
_ERROR_STYLE = "bold #FF5F5F"
_CARD_REPORT_CACHE_MAX = 128
_ROSTER_LIMIT = 12

_card_report_cache: dict[tuple[str, str, str, str, str | None, int], Text] = {}


def _render_chop_result_card(entry: ChopRunEntry, *, width: int | None = None) -> Text:
    """Build the universal RESULT card from persisted run metadata."""
    text = render_section_rule("RESULT", width=width)
    text.append("\n  ")
    status_label, status_style = chop_status_label(entry.status)
    text.append(status_label, style=status_style)

    if entry.proposals:
        text.append("    ")
        text.append(_count_label(len(entry.proposals), "proposal"), style=_VALUE_STYLE)
    if entry.launches:
        text.append("    ")
        text.append(_count_label(len(entry.launches), "launch"), style=_VALUE_STYLE)
    if entry.dry_run:
        text.append("    dry run", style="bold #FFAF5F")
    if entry.source != "scheduled":
        text.append(f"    {entry.source}", style="#D7AF87")
    text.append("\n")

    result = entry.result if isinstance(entry.result, Mapping) else {}
    _append_field(text, "summary", result.get("summary"))
    _append_field(text, "reason", result.get("reason") or entry.reason)
    counters = result.get("counters")
    if isinstance(counters, Mapping) and counters:
        _append_counters(text, counters, width=width)
    _append_roster(text, entry.launches, entry.proposals)
    evidence = result.get("evidence")
    if isinstance(evidence, Sequence) and not isinstance(evidence, (str, bytes)):
        paths = [PurePath(str(item)).name for item in evidence]
        if paths:
            _append_field(text, "evidence", ", ".join(paths))
    _append_field(text, "error", entry.error, value_style=_ERROR_STYLE)
    _append_field(text, "traceback", entry.traceback, value_style="#FF5F5F")

    if text.plain.endswith("\n"):
        text.rstrip()
    return text


def render_cached_chop_card_and_report(
    lumberjack_name: str,
    chop_name: str,
    entry: ChopRunEntry,
    *,
    width: int | None = None,
) -> Text:
    """Return the cached card plus optional authored report for one run."""
    width_bucket = int(width) if width is not None and width > 0 else 0
    key = (
        lumberjack_name,
        chop_name,
        entry.run_id,
        entry.status,
        entry.finished_at,
        width_bucket,
    )
    cached = _card_report_cache.get(key)
    if cached is not None:
        return cached.copy()

    rendered = _render_chop_result_card(entry, width=width)
    result = entry.result if isinstance(entry.result, Mapping) else {}
    report = result.get("report")
    if isinstance(report, Mapping):
        report_text = render_chop_report(report, width=width)
        if report_text:
            rendered.append("\n\n")
            rendered.append_text(report_text)

    _card_report_cache[key] = rendered
    while len(_card_report_cache) > _CARD_REPORT_CACHE_MAX:
        _card_report_cache.pop(next(iter(_card_report_cache)))
    return rendered.copy()


def _append_field(
    text: Text,
    label: str,
    value: object,
    *,
    value_style: str = "",
) -> None:
    if not isinstance(value, str) or not value:
        return
    text.append("\n  ")
    text.append(f"{label:<10}", style=_LABEL_STYLE)
    text.append(value, style=value_style)


def _append_counters(
    text: Text, counters: Mapping[object, object], *, width: int | None
) -> None:
    prefix = "  counters  "
    line_length = len(prefix)
    text.append("\n")
    text.append(prefix, style=_LABEL_STYLE)
    for index, (name, value) in enumerate(counters.items()):
        chip = f"{name} {value}"
        separator = "    " if index else ""
        if (
            width is not None
            and width > 0
            and line_length + len(separator + chip) > width
        ):
            text.append("\n            ")
            line_length = 12
            separator = ""
        text.append(separator)
        text.append(str(name), style="#D7AF87")
        text.append(" ")
        text.append(str(value), style=_VALUE_STYLE)
        line_length += len(separator + chip)


def _append_roster(
    text: Text,
    launches: Sequence[Mapping[str, Any]],
    proposals: Sequence[Mapping[str, Any]],
) -> None:
    records: list[tuple[str, Mapping[str, Any], str]] = [
        ("launches", item, "launched") for item in launches if isinstance(item, Mapping)
    ]
    records.extend(
        ("proposals", item, _proposal_outcome(item))
        for item in proposals
        if isinstance(item, Mapping)
    )
    for label, item, outcome in records[:_ROSTER_LIMIT]:
        name = str(item.get("agent_name") or item.get("id") or "unnamed")
        clan = item.get("clan")
        display = f"{name} · {clan}" if isinstance(clan, str) and clan else name
        text.append("\n  ")
        text.append(f"{label:<10}", style=_LABEL_STYLE)
        text.append(display, style="#D7AF87")
        text.append(
            f"    {_outcome_glyph(outcome)} {outcome}", style=_outcome_style(outcome)
        )
    remaining = len(records) - _ROSTER_LIMIT
    if remaining > 0:
        text.append(f"\n            …and {remaining} more", style="dim #A8A8A8")


def _proposal_outcome(item: Mapping[str, Any]) -> str:
    return str(item.get("outcome") or item.get("validation") or "proposed")


def _outcome_glyph(outcome: str) -> str:
    lowered = outcome.lower()
    if lowered in {"launched", "valid", "accepted"}:
        return "↗" if lowered == "launched" else "✓"
    if any(token in lowered for token in ("fail", "error", "collision")):
        return "▲"
    if any(token in lowered for token in ("skip", "duplicate")):
        return "↷"
    return "•"


def _outcome_style(outcome: str) -> str:
    lowered = outcome.lower()
    if lowered in {"launched", "valid", "accepted"}:
        return "#5FD75F"
    if any(token in lowered for token in ("fail", "error", "collision")):
        return _ERROR_STYLE
    if any(token in lowered for token in ("skip", "duplicate")):
        return "#FFAF5F"
    return "#87D7FF"


def _count_label(count: int, singular: str) -> str:
    return f"{count} {singular if count == 1 else singular + 's'}"


__all__ = ["render_cached_chop_card_and_report"]

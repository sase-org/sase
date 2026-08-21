"""Summary-line presentation for ``sase flag list`` output."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from rich.text import Text

from sase.bead.flag_due import FlagRemovalState
from sase.bead_flag_presentation import FLAG_DUE_GLYPH, FLAG_DUE_STYLES
from sase.feature_flags.cli_render import enabled_text, kind_text
from sase.feature_flags.cli_views import FlagView
from sase.feature_flags.models import FlagKind

_GROUP_SEPARATOR = " · "
_COUNT_SEPARATOR = "  "
_OVERRIDDEN_STYLE = "bold"
_KIND_ORDER: tuple[FlagKind, ...] = ("beta", "sunset")
_DUE_ORDER: tuple[FlagRemovalState, ...] = ("live", "soon", "due")


@dataclass(frozen=True)
class FlagListSummary:
    """Counted inventory of the flag views that were rendered."""

    total: int
    by_kind: Mapping[FlagKind, int]
    enabled: int
    disabled: int
    overridden: int
    by_due: Mapping[FlagRemovalState, int]


def summarize_flag_views(views: Sequence[FlagView]) -> FlagListSummary:
    """Count kinds, effective values, overrides, and due states from *views*."""
    kind_counts: Counter[FlagKind] = Counter()
    due_counts: Counter[FlagRemovalState] = Counter()
    enabled = 0
    disabled = 0
    overridden = 0
    for view in views:
        kind_counts[view.definition.kind] += 1
        if view.decision.enabled:
            enabled += 1
        else:
            disabled += 1
        if view.decision.overridden:
            overridden += 1
        if view.due_state is not None:
            due_counts[view.due_state] += 1
    return FlagListSummary(
        total=len(views),
        by_kind={kind: kind_counts[kind] for kind in _KIND_ORDER},
        enabled=enabled,
        disabled=disabled,
        overridden=overridden,
        by_due={state: due_counts[state] for state in _DUE_ORDER},
    )


def flag_list_summary_line(summary: FlagListSummary) -> Text:
    """Return the compact statistics footer for *summary*.

    The builder may return ``0 flags``; the CLI empty state does not print it.
    """
    folded_kind = _folded_kind(summary)
    folded_enabled = _folded_enabled(summary)
    groups = [_summary_head(summary, folded_kind, folded_enabled)]
    if folded_kind is None and (kind_group := _kind_group(summary)):
        groups.append(kind_group)
    if folded_enabled is None and (enabled_group := _enabled_group(summary)):
        groups.append(enabled_group)
    if overridden_group := _overridden_group(summary):
        groups.append(overridden_group)
    if urgency_group := _urgency_group(summary):
        groups.append(urgency_group)
    return _join(groups, _GROUP_SEPARATOR)


def _folded_kind(summary: FlagListSummary) -> FlagKind | None:
    kinds = [kind for kind in _KIND_ORDER if summary.by_kind[kind] > 0]
    return kinds[0] if len(kinds) == 1 else None


def _folded_enabled(summary: FlagListSummary) -> bool | None:
    has_on = summary.enabled > 0
    has_off = summary.disabled > 0
    if has_on and not has_off:
        return True
    if has_off and not has_on:
        return False
    return None


def _summary_head(
    summary: FlagListSummary,
    folded_kind: FlagKind | None,
    folded_enabled: bool | None,
) -> Text:
    head = Text(str(summary.total))
    if folded_enabled is not None:
        head.append(" ")
        head.append_text(enabled_text(folded_enabled))
    if folded_kind is not None:
        head.append(" ")
        head.append_text(kind_text(folded_kind))
    noun = "flag" if summary.total == 1 else "flags"
    head.append(f" {noun}")
    return head


def _kind_group(summary: FlagListSummary) -> Text | None:
    entries: list[Text] = []
    for kind in _KIND_ORDER:
        count = summary.by_kind[kind]
        if count == 0:
            continue
        entry = Text(str(count))
        entry.append(" ")
        entry.append_text(kind_text(kind))
        entries.append(entry)
    return _join(entries, _COUNT_SEPARATOR) if entries else None


def _enabled_group(summary: FlagListSummary) -> Text | None:
    entries: list[Text] = []
    for enabled, count in ((True, summary.enabled), (False, summary.disabled)):
        if count == 0:
            continue
        entry = Text(str(count))
        entry.append(" ")
        entry.append_text(enabled_text(enabled))
        entries.append(entry)
    return _join(entries, _COUNT_SEPARATOR) if entries else None


def _overridden_group(summary: FlagListSummary) -> Text | None:
    if summary.overridden == 0:
        return None
    return Text(f"{summary.overridden} overridden", style=_OVERRIDDEN_STYLE)


def _urgency_group(summary: FlagListSummary) -> Text | None:
    entries: list[Text] = []
    for state in _DUE_ORDER:
        if state == "live":
            continue
        count = summary.by_due[state]
        if count == 0:
            continue
        entry = Text()
        entry.append(FLAG_DUE_GLYPH, style=FLAG_DUE_STYLES[state].rich)
        entry.append(f" {count} {state}")
        entries.append(entry)
    return _join(entries, _COUNT_SEPARATOR) if entries else None


def _join(parts: Sequence[Text], separator: str) -> Text:
    line = Text()
    for index, part in enumerate(parts):
        if index:
            line.append(separator)
        line.append_text(part)
    return line


__all__ = [
    "FlagListSummary",
    "flag_list_summary_line",
    "summarize_flag_views",
]

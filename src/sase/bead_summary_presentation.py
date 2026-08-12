"""Summary-line presentation for ``sase bead list`` output."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, cast

from sase.ansi_style import ansi_sgr, apply_ansi
from sase.bead_status_presentation import (
    BeadStatusValue,
    bead_status_display_order,
    bead_status_presentation,
)
from sase.bead_type_presentation import (
    BEAD_TYPE_VALUES,
    BeadTypeValue,
    bead_type_presentation,
)

BEAD_TYPE_NOUNS: dict[BeadTypeValue, tuple[str, str]] = {
    "plan": ("plan", "plans"),
    "phase": ("phase", "phases"),
    "task": ("task", "tasks"),
}

BEAD_STATUS_ADJECTIVES: dict[BeadStatusValue, str] = {
    "open": "open",
    "claimed": "claimed",
    "ready": "ready",
    "snoozed": "snoozed",
    "in_progress": "in-progress",
    "closed": "closed",
}

_GROUP_SEPARATOR = " · "
_COUNT_SEPARATOR = "  "
_HIDDEN_HINT = " (--limit 0 shows all)"


class BeadSummaryRow(Protocol):
    @property
    def issue_type(self) -> object: ...

    @property
    def status(self) -> object: ...


@dataclass(frozen=True)
class BeadListSummary:
    shown: int
    matched: int
    by_type: Mapping[BeadTypeValue, int]
    by_status: Mapping[BeadStatusValue, int]

    @property
    def hidden(self) -> int:
        return max(0, self.matched - self.shown)


def summarize_bead_rows(
    rows: Iterable[BeadSummaryRow], *, matched: int
) -> BeadListSummary:
    type_counts: Counter[BeadTypeValue] = Counter()
    status_counts: Counter[BeadStatusValue] = Counter()
    shown = 0
    for row in rows:
        type_counts[_normalize_bead_type_value(row.issue_type)] += 1
        status_counts[_normalize_bead_status_value(row.status)] += 1
        shown += 1

    return BeadListSummary(
        shown=shown,
        matched=matched,
        by_type={value: type_counts[value] for value in BEAD_TYPE_VALUES},
        by_status={
            value: status_counts[value] for value in bead_status_display_order()
        },
    )


def bead_list_summary_line(
    summary: BeadListSummary, *, use_color: bool, implicit_limit: bool
) -> str:
    type_values = _nonzero_type_values(summary)
    status_values = _nonzero_status_values(summary)
    type_folded = len(type_values) == 1
    status_folded = len(status_values) == 1

    groups = [
        _summary_head(
            summary,
            folded_type=type_values[0] if type_folded else None,
            folded_status=status_values[0] if status_folded else None,
            use_color=use_color,
        )
    ]
    if not type_folded and (type_group := _type_group(summary, use_color=use_color)):
        groups.append(type_group)
    if not status_folded and (
        status_group := _status_group(summary, use_color=use_color)
    ):
        groups.append(status_group)
    if summary.hidden:
        groups.append(
            _hidden_clause(
                summary.hidden, use_color=use_color, implicit_limit=implicit_limit
            )
        )
    return _GROUP_SEPARATOR.join(groups)


def _normalize_bead_type_value(value: object) -> BeadTypeValue:
    bead_type_presentation(value)
    candidate = value.value if isinstance(value, Enum) else value
    return cast(BeadTypeValue, candidate)


def _normalize_bead_status_value(value: object) -> BeadStatusValue:
    bead_status_presentation(value)
    candidate = value.value if isinstance(value, Enum) else value
    return cast(BeadStatusValue, candidate)


def _nonzero_type_values(summary: BeadListSummary) -> list[BeadTypeValue]:
    return [value for value in BEAD_TYPE_VALUES if summary.by_type[value] > 0]


def _nonzero_status_values(summary: BeadListSummary) -> list[BeadStatusValue]:
    return [
        value for value in bead_status_display_order() if summary.by_status[value] > 0
    ]


def _summary_head(
    summary: BeadListSummary,
    *,
    folded_type: BeadTypeValue | None,
    folded_status: BeadStatusValue | None,
    use_color: bool,
) -> str:
    parts = [str(summary.shown)]
    if folded_status is not None:
        adjective = BEAD_STATUS_ADJECTIVES[folded_status]
        parts.append(
            apply_ansi(
                adjective,
                bead_status_presentation(folded_status).cli_style,
                enabled=use_color,
            )
        )
    if folded_type is not None:
        singular, plural = BEAD_TYPE_NOUNS[folded_type]
        noun = singular if summary.shown == 1 else plural
        parts.append(
            apply_ansi(
                noun,
                bead_type_presentation(folded_type).cli_style,
                enabled=use_color,
            )
        )
    else:
        parts.append("bead" if summary.shown == 1 else "beads")
    return " ".join(parts)


def _type_group(summary: BeadListSummary, *, use_color: bool) -> str:
    entries = []
    for value in BEAD_TYPE_VALUES:
        count = summary.by_type[value]
        if count == 0:
            continue
        presentation = bead_type_presentation(value)
        glyph = apply_ansi(
            presentation.glyph, presentation.cli_style, enabled=use_color
        )
        entries.append(f"{glyph} {count}")
    return _COUNT_SEPARATOR.join(entries)


def _status_group(summary: BeadListSummary, *, use_color: bool) -> str:
    entries = []
    for value in bead_status_display_order():
        count = summary.by_status[value]
        if count == 0:
            continue
        presentation = bead_status_presentation(value)
        glyph = apply_ansi(
            presentation.glyph, presentation.cli_style, enabled=use_color
        )
        entries.append(f"{glyph} {count}")
    return _COUNT_SEPARATOR.join(entries)


def _hidden_clause(hidden: int, *, use_color: bool, implicit_limit: bool) -> str:
    hint = _HIDDEN_HINT if implicit_limit else ""
    return apply_ansi(
        f"{hidden} hidden{hint}",
        ansi_sgr(dim=True),
        enabled=use_color,
    )


__all__ = [
    "BEAD_STATUS_ADJECTIVES",
    "BEAD_TYPE_NOUNS",
    "BeadListSummary",
    "BeadSummaryRow",
    "bead_list_summary_line",
    "summarize_bead_rows",
]

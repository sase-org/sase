"""Shared types for the tools panel widget."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum

from sase.ace.tui.tools import ToolCallEntry


class ToolDetailLevel(IntEnum):
    """Progressive disclosure levels for the tools timeline."""

    COMPACT = 0
    EXPANDED = 1
    FULL = 2


_DETAIL_LEVEL_LABELS: dict[ToolDetailLevel, str] = {
    ToolDetailLevel.COMPACT: "compact",
    ToolDetailLevel.EXPANDED: "expanded",
    ToolDetailLevel.FULL: "full",
}


@dataclass(frozen=True)
class ToolTimelineRow:
    entry: ToolCallEntry
    source_label: str | None = None
    palette_index: int = 0


@dataclass(frozen=True)
class ToolsPanelFetchResult:
    entries: tuple[ToolCallEntry, ...] | None
    rows: tuple[ToolTimelineRow, ...] | None
    fetch_time: datetime


def coerce_detail_level(level: ToolDetailLevel | int) -> ToolDetailLevel:
    value = max(
        ToolDetailLevel.COMPACT,
        min(ToolDetailLevel.FULL, int(level)),
    )
    return ToolDetailLevel(value)


def detail_level_label(level: ToolDetailLevel | int) -> str:
    return _DETAIL_LEVEL_LABELS[coerce_detail_level(level)]

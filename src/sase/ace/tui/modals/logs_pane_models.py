"""Data models shared by the Admin Center Logs pane modules."""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text

from ..logs import LogSource


@dataclass(frozen=True)
class LogPaneLoadResult:
    sources: list[LogSource]
    options: list[tuple[str, Text]]
    active_count: int
    selected_index: int
    detail: Text
    focus_line: int | None = None
    focus_found: bool | None = None


__all__ = ["LogPaneLoadResult"]

"""Foreground ToolRun executor request and context models."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sase.tool.argv import ResolvedToolArgv


@dataclass(frozen=True)
class ToolRunCliRequest:
    """Parsed ``sase tool run`` controls."""

    quiet: bool
    verbose: bool
    tail_lines: int
    words: tuple[str, ...]
    hand_off: bool = False
    detach: bool = False
    tail_lines_explicit: bool = False
    keep_going: bool = False
    fail_fast: bool = False


@dataclass(frozen=True)
class RecordedRunContext:
    """Shared post-begin state for foreground and adopted runs."""

    run_id: str
    recorded: bool
    resolved: ResolvedToolArgv
    has_owner: bool
    owns_output: bool
    compact: bool
    tail_lines: int
    events_path: Path | None
    stdout_path: Path | None
    stderr_path: Path | None
    stop_recorded: Callable[[], bool] | None = None
    timeout_recorded: Callable[[], bool] | None = None
    continuation_mode: str | None = None


__all__ = ["RecordedRunContext", "ToolRunCliRequest"]
